from uuid import uuid4
import re
from .repository import Repository, BusinessError, money
from psycopg.types.json import Jsonb
from .bot import BotRepositoryMixin, valid_url
DEFAULTS=dict(wa_enabled=False,wa_mode='REAL',owner='',owner_consent=False,auto_close=True,
 wa_provider='META',wa_format='TEMPLATE_PDF',phone_id='',api_version='',template='',language='es_MX',relay_url='',
 bot_enabled=False,bot_url='',simulate_hardware=False,cloud_enabled=False,cloud_mode='REAL',
 s3_endpoint='',s3_bucket='',s3_region='us-east-1',s3_prefix='kala',pg_dump='',backup_minutes=60)

def phone(value):
    clean=re.sub(r'[\s()+-]','',str(value))
    if not re.fullmatch(r'[1-9][0-9]{7,14}',clean):raise BusinessError('Escribe el teléfono con código de país, por ejemplo +52 seguido de los 10 dígitos.')
    return clean

def production_settings(stored):
    cfg={**DEFAULTS,**stored}
    if cfg['wa_mode']!='REAL':cfg['wa_enabled']=False;cfg['bot_enabled']=False
    if cfg['cloud_mode']!='REAL':cfg['cloud_enabled']=False
    cfg.update(wa_mode='REAL',cloud_mode='REAL',simulate_hardware=False)
    return cfg

def status_text(value):
    return {'PENDIENTE':'Por enviar','PROCESANDO':'Enviando','ACEPTADO':'Aceptado por el proveedor','ENTREGADO':'Entregado','LEIDO':'Leído','ERROR':'Error: revisar','REVISION':'Confirmar antes de reenviar','CANCELADO':'Cancelado','NUBE_CONFIRMADA':'Guardado en la nube','LOCAL_PENDIENTE_NUBE':'Copia local; falta subir a la nube'}.get(value,str(value or ''))

class ExtendedRepository(BotRepositoryMixin,Repository):
    def health(self):
        with self.connection() as c:
            ro=c.execute('SHOW transaction_read_only').fetchone()['transaction_read_only']
            if ro=='on':raise BusinessError('PostgreSQL está en modo de solo lectura.')
            return True
    def settings(self):
        rows=self.read('SELECT datos FROM public.kala_config_integraciones WHERE id=1')
        return production_settings(rows[0]['datos'] if rows else {})
    def save_settings(self,values,request_id=None):
        cfg={**DEFAULTS,**{k:v for k,v in values.items() if k in DEFAULTS}}
        cfg['backup_minutes']=int(float(cfg['backup_minutes']))
        if cfg['backup_minutes']<5:raise BusinessError('El intervalo mínimo de respaldo es de 5 minutos.')
        if cfg['wa_mode']!='REAL' or cfg['cloud_mode']!='REAL':raise BusinessError('Los servicios solo admiten operación real.')
        cfg['simulate_hardware']=False
        if cfg['owner']:cfg['owner']=phone(cfg['owner'])
        if cfg['wa_mode']=='REAL' and cfg['wa_enabled']:
            if not cfg['owner'] or not cfg['owner_consent']:raise BusinessError('Configura el teléfono y la autorización del dueño.')
            if cfg['wa_provider'] not in ('META','KAPSO') or cfg['wa_format'] not in ('TEXT','TEMPLATE_PDF'):raise BusinessError('Proveedor o formato inválido.')
            if not cfg['phone_id'].isdigit() or not re.fullmatch(r'v\d+\.\d+',cfg['api_version']):raise BusinessError('Completa Phone Number ID y versión API (ejemplo v24.0).')
            if cfg['wa_format']=='TEMPLATE_PDF' and not re.fullmatch(r'[a-z0-9_]+',cfg['template']):raise BusinessError('Para PDF configura una plantilla aprobada con encabezado DOCUMENTO y una variable en el cuerpo.')
        if cfg['bot_enabled']:
            if not (cfg['wa_enabled'] and cfg['wa_mode']=='REAL' and cfg['wa_provider']=='KAPSO' and cfg['owner_consent']):raise BusinessError('El bot requiere WhatsApp real por Kapso y autorización del dueño.')
            if not valid_url(cfg['bot_url']):raise BusinessError('URL del bot: usa https://nombre.workers.dev sin /webhook, usuario ni parámetros.')
        for key in ('relay_url','s3_endpoint'):
            if cfg[key] and not cfg[key].startswith('https://'):raise BusinessError('Usa HTTPS para el servicio externo.')
        if cfg['cloud_enabled'] and cfg['cloud_mode']=='REAL' and not cfg['s3_bucket']:raise BusinessError('Falta el bucket de respaldos.')
        def work(c):
            c.execute('UPDATE public.kala_config_integraciones SET datos=%s,actualizado_en=now() WHERE id=1',(Jsonb(cfg),))
            self.audit(c,'CONFIGURAR_INTEGRACIONES','kala_config_integraciones',1,'Configuración de servicios y consentimiento. Sin secretos.')
            return {'id':1}
        return self.mutate('INTEGRACIONES',work,request_id)
    def queue_document(self,title,body,target,mode,consent,request_id=None):
        if mode!='REAL':raise BusinessError('Solo se permiten envíos reales.')
        target=phone(target)
        if not consent:raise BusinessError('Confirma que el destinatario autorizó recibir el documento.')
        if not body.strip():raise BusinessError('El documento está vacío.')
        if len(body)>250000:raise BusinessError('Reduce el reporte a menos registros.')
        rid=str(uuid4());dedupe=str(request_id or uuid4())
        def work(c):
            cfg=production_settings(c.execute('SELECT datos FROM public.kala_config_integraciones WHERE id=1').fetchone()['datos'])
            if not cfg['wa_enabled']:raise BusinessError('Activa WhatsApp en Configurar servicios antes de enviar.')
            c.execute('INSERT INTO public.kala_envios(id,dedupe,usuario_id,titulo,destino,contenido,modo) VALUES(%s,%s,%s,%s,%s,%s,%s)',(rid,'manual:'+dedupe,self.user_id,title[:100],target,body,mode))
            self.audit(c,'ENCOLAR_DOCUMENTO','kala_envios',None,title[:100]+' · '+mode)
            return {'id':rid}
        return self.mutate('ENCOLAR_DOCUMENTO',work,dedupe)
    def jobs(self):
        return self.read("SELECT id,titulo,destino,modo,estado,detalle,mensaje_id,creado_en FROM public.kala_envios WHERE modo='REAL' ORDER BY creado_en DESC LIMIT 200")
    def claim_job(self,mode):
        with self.connection(True) as c:
            # Una caída después del POST puede dejar un resultado desconocido.
            # Nunca reenviar automáticamente un mensaje con resultado incierto.
            c.execute("UPDATE public.kala_envios SET estado='REVISION',detalle='Operación interrumpida: revisa el proveedor antes de reenviar.',actualizado_en=now() WHERE estado='PROCESANDO' AND actualizado_en<now()-interval '10 minutes'")
            row=c.execute("SELECT * FROM public.kala_envios WHERE estado='PENDIENTE' AND modo=%s ORDER BY creado_en FOR UPDATE SKIP LOCKED LIMIT 1",(mode,)).fetchone()
            if row:c.execute("UPDATE public.kala_envios SET estado='PROCESANDO',intentos=intentos+1,actualizado_en=now() WHERE id=%s",(row['id'],))
            return row
    def job_state(self,jid,state,detail='',message_id=None):
        with self.connection(True) as c:
            c.execute('UPDATE public.kala_envios SET estado=%s,detalle=%s,mensaje_id=COALESCE(%s,mensaje_id),actualizado_en=now() WHERE id=%s',(state,detail[:1000],message_id,jid))
    def retry_job(self,jid,request_id=None):
        def work(c):
            r=c.execute("UPDATE public.kala_envios SET estado='PENDIENTE',mensaje_id=NULL,detalle='Reintento solicitado por administrador',actualizado_en=now() WHERE id=%s AND estado IN ('ERROR','REVISION') RETURNING id",(jid,)).fetchone()
            if not r:raise BusinessError('Solo se reintentan los estados ERROR o REVISION.')
            self.audit(c,'REINTENTAR_WHATSAPP','kala_envios',None,str(jid));return {'id':str(jid)}
        return self.mutate('REINTENTAR_WA',work,request_id)
    def backup_record(self,state,path,detail):
        with self.connection(True) as c:c.execute('INSERT INTO public.kala_respaldos(estado,archivo,detalle) VALUES(%s,%s,%s)',(state,path,detail[:1000]))
    def backup_history(self):return self.read("SELECT creado_en,estado,archivo,detalle FROM public.kala_respaldos WHERE estado<>'SIMULADO' ORDER BY creado_en DESC LIMIT 40")
    def pending_receipts(self):return self.read("SELECT id,mensaje_id,destino,canal FROM public.kala_envios WHERE modo='REAL' AND estado IN ('ACEPTADO','ENTREGADO') AND mensaje_id IS NOT NULL ORDER BY consulta_en NULLS FIRST,actualizado_en LIMIT 20")
    def touch_receipt(self,jid):
        with self.connection(True) as c:c.execute('UPDATE public.kala_envios SET consulta_en=now() WHERE id=%s',(jid,))
    def delivered_owner(self,owner):
        rows=self.read("SELECT titulo,actualizado_en,estado FROM public.kala_envios WHERE modo='REAL' AND destino=%s ORDER BY creado_en DESC LIMIT 1",(owner,))
        return rows[0] if rows and rows[0]['estado'] in ('ENTREGADO','LEIDO') else None
    def closing_report(self,aid):
        rows=self.read('''SELECT a.*,t.abierto_en,t.cerrado_en,u.nombre,u.rol,c.nombre AS caja FROM public.arqueos a JOIN public.turnos t ON t.id=a.turno_id JOIN public.usuarios u ON u.id=t.usuario_id JOIN public.cajas c ON c.id=t.caja_id WHERE a.id=%s''',(aid,))
        if not rows:raise BusinessError('Cierre inexistente.')
        a=rows[0]
        lines=['PAPELERÍA KALA',f'Cierre #{aid} · Turno #{a["turno_id"]}',a['nombre']+' · '+a['rol'],'Caja: '+a['caja'],'Apertura: '+str(a['abierto_en']),'Cierre: '+str(a['cerrado_en']),'Esperado: '+money(a['efectivo_esperado_centavos']),'Contado: '+money(a['efectivo_contado_centavos']),'Diferencia: '+money(a['diferencia_centavos']),'Observaciones: '+str(a.get('observaciones_cajero') or ''),'Revisión: '+str(a.get('observaciones_revision') or '')]
        for r in self.closing_detail(aid):lines.append(f'{r["tipo"]} {money(r["denominacion_centavos"])} × {r["cantidad"]} = {money(r["subtotal_centavos"])}')
        return '\n'.join(lines)
