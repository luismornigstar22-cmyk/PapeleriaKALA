from pathlib import Path
from datetime import datetime,timezone
from io import BytesIO
import os,re,socket,subprocess,shutil,tempfile,hashlib
from xml.sax.saxutils import escape
from .repository import BusinessError

SECRET_NAMES=('bot_token','kapso_key','wa_token','relay_token','s3_access','s3_secret','backup_key')

def data_dir():
    root=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share')))/'PapeleriaKALA'
    root.mkdir(parents=True,exist_ok=True);return root

class Vault:
    """Windows Credential Manager; no secretos en archivos de configuración ni BD."""
    def __init__(self,scope='kala_db'):
        self.service='PapeleriaKALA:'+scope
    def _backend(self):
        import keyring
        backend=keyring.get_keyring()
        if not backend.__class__.__module__.startswith(('keyring.backends.Windows','keyring.backends.macOS','keyring.backends.SecretService')):
            raise BusinessError('No hay un almacén de credenciales seguro disponible. En Windows utiliza el Administrador de credenciales.')
        return keyring
    def get(self,name):return self._backend().get_password(self.service,name) or ''
    def set(self,name,value):
        if name not in SECRET_NAMES:raise BusinessError('Secreto desconocido.')
        self._backend().set_password(self.service,name,value)


def document_pdf(title,text):
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.pagesizes import A4
    stream=BytesIO();styles=getSampleStyleSheet();story=[Paragraph(escape(title),styles['Title']),Spacer(1,12)]
    for line in text.splitlines():story.append(Paragraph(escape(line) or ' ',styles['BodyText']))
    SimpleDocTemplate(stream,pagesize=A4,rightMargin=32,leftMargin=32,topMargin=32,bottomMargin=32).build(story)
    return stream.getvalue()

def provider_error(data,token=''):
    """Accept proxy error strings and Graph objects without logging raw payloads."""
    parts=[]
    if isinstance(data,dict):
        error=data.get('error')
        if isinstance(error,dict):
            for k in ('code','message','error_user_msg'):
                if isinstance(error.get(k),(str,int)):parts.append(str(error[k]))
        elif isinstance(error,str):parts.append(error)
        for k in ('message','detail'):
            if isinstance(data.get(k),str):parts.append(data[k])
    text=' · '.join(dict.fromkeys(parts)) or 'El proveedor rechazó la solicitud sin un detalle JSON reconocido.'
    if token:text=text.replace(token,'[CLAVE OCULTA]')
    text=re.sub(r'(?i)(bearer|x-api-key|api[_ -]?key|token|secret)\s*[:=]\s*\S+',r'\1=[OCULTO]',text)
    text=re.sub(r'[A-Za-z0-9_-]{40,}','[VALOR OCULTO]',text)
    return ' '.join(text.split())[:650]

class Transport:
    def __init__(self,repo,vault=None):self.repo=repo;self.vault=vault or Vault(repo.config.get('dbname','kala_db'))
    def network_reachable(self,cfg=None):
        try:
            with socket.create_connection(('api.kapso.ai' if (cfg or {}).get('wa_provider')=='KAPSO' else 'graph.facebook.com',443),timeout=2):return True
        except OSError:return False
    def send(self,job,cfg):
        import requests
        if job.get('modo')!='REAL':raise BusinessError('Un envío histórico de prueba no puede enviarse como real.')
        jid=job['id'];submitted=False
        snapshot=job.get('canal')
        if not snapshot:
            self.repo.job_state(jid,'ERROR','Envío antiguo sin canal identificado. Genera un nuevo envío desde el documento.');return
        cfg={**cfg,**snapshot}
        try:
            if 'bot_requested_at' in snapshot:
                from .bot import enabled, canonical_phone, MAX_AGE
                current=self.repo.settings()
                age=datetime.now(timezone.utc).timestamp()-int(snapshot['bot_requested_at'])
                if (not enabled(current) or canonical_phone(current['owner'])!=job['destino'] or
                    snapshot.get('bot_owner')!=job['destino'] or current.get('phone_id')!=snapshot.get('phone_id')):
                    raise BusinessError('Consulta bloqueada: cambió el dueño, canal o autorización del bot.')
                if age>MAX_AGE or age < -300:
                    raise BusinessError('Consulta expirada. El dueño debe escribir de nuevo por WhatsApp.')
            token=self.vault.get('kapso_key' if cfg.get('wa_provider')=='KAPSO' else 'wa_token')
            if not token:raise BusinessError('Falta el token de WhatsApp en Configuración.')
            if not re.fullmatch(r'v\d+\.\d+',cfg['api_version']) or not cfg['phone_id'].isdigit():raise BusinessError('Configura la versión Graph y Phone Number ID.')
            if not re.fullmatch(r'[1-9]\d{7,14}',job['destino']):raise BusinessError('Destino inválido; configura el teléfono del dueño.')
            host='https://api.kapso.ai/meta/whatsapp' if cfg.get('wa_provider')=='KAPSO' else 'https://graph.facebook.com'
            base=f'{host}/{cfg["api_version"]}/{cfg["phone_id"]}'
            headers={'X-API-Key':token} if cfg.get('wa_provider')=='KAPSO' else {'Authorization':'Bearer '+token}
            if cfg.get('wa_format')=='TEXT':
                body=job['titulo']+'\n\n'+job['contenido']
                if len(body.encode('utf-16-le'))//2>4096:
                    raise BusinessError('Reporte demasiado largo para texto (4096 caracteres). Reduce el periodo o utiliza PDF con plantilla en producción. No se envió una versión recortada.')
                payload={'messaging_product':'whatsapp','to':job['destino'],'type':'text','text':{'preview_url':False,'body':body}}
            else:
                pdf=document_pdf(job['titulo'],job['contenido'])
                # Subir un archivo no envía un mensaje; un fallo aquí se puede reintentar.
                r=requests.post(base+'/media',headers=headers,data={'messaging_product':'whatsapp','type':'application/pdf'},files={'file':('KALA.pdf',pdf,'application/pdf')},timeout=(5,45),allow_redirects=False)
                if r.status_code!=200:
                    self.repo.job_state(jid,'ERROR','El proveedor rechazó el archivo: HTTP '+str(r.status_code)+'. Revisa credenciales y permisos.');return
                media_id=r.json()['id']
                payload={'messaging_product':'whatsapp','to':job['destino'],'type':'template','template':{
                    'name':cfg['template'],'language':{'code':cfg['language']},'components':[
                    {'type':'header','parameters':[{'type':'document','document':{'id':media_id,'filename':'KALA.pdf'}}]},
                    {'type':'body','parameters':[{'type':'text','text':job['titulo']}]}]}}
            submitted=True
            r=requests.post(base+'/messages',headers=headers,json=payload,timeout=(5,30),allow_redirects=False)
            try:
                data=r.json()
            except ValueError:
                data=None
            if r.status_code in (200,201):
                messages=data.get('messages') if isinstance(data,dict) else None
                mid=(messages[0].get('id') if isinstance(messages,list) and messages and isinstance(messages[0],dict) else None)
                if isinstance(mid,str) and mid.strip():
                    self.repo.job_state(jid,'ACEPTADO','El proveedor aceptó el mensaje. Entrega aún no confirmada.',mid)
                else:
                    self.repo.job_state(jid,'REVISION',f'HTTP {r.status_code}: respuesta de éxito sin ID de mensaje reconocido. Revisa Inbox antes de reenviar.')
            elif 400<=r.status_code<500:
                detail=provider_error(data,token)
                hint=(' Comprueba que la sesión sandbox del destinatario esté activa y pertenezca al mismo proyecto e ID.' if r.status_code==403 else
                      ' Revisa la API key del proyecto.' if r.status_code==401 else
                      ' Revisa la versión API y Phone Number ID.' if r.status_code==404 else '')
                self.repo.job_state(jid,'ERROR',f'HTTP {r.status_code}: '+detail+hint)
            else:
                self.repo.job_state(jid,'REVISION',f'HTTP {r.status_code}: resultado incierto. Revisa el proveedor antes de reenviar.')
        except BusinessError as e:self.repo.job_state(jid,'ERROR',str(e))
        except Exception as e:
            # No guardar excepciones HTTP completas: pueden contener credenciales.
            self.repo.job_state(jid,'REVISION' if submitted else 'ERROR',('Resultado incierto; revisa el proveedor antes de reenviar. ' if submitted else 'No se envió el mensaje. ')+'Tipo: '+type(e).__name__)
    def receipts(self,cfg):
        if cfg.get('wa_provider')=='KAPSO':
            return self.kapso_receipts(cfg)
        if not cfg.get('relay_url'):return
        import requests
        token=self.vault.get('relay_token')
        if not token:return
        for row in self.repo.pending_receipts():
            self.repo.touch_receipt(row['id'])
            try:
                r=requests.get(cfg['relay_url'].rstrip('/')+'/status',params={'message_id':row['mensaje_id']},headers={'Authorization':'Bearer '+token},timeout=(3,5),allow_redirects=False)
                if r.status_code!=200:continue
                d=r.json()
                if d.get('message_id')!=row['mensaje_id'] or d.get('recipient')!=row['destino']:continue
                state={'delivered':'ENTREGADO','read':'LEIDO','failed':'ERROR'}.get(d.get('status'))
                if state:self.repo.job_state(row['id'],state,'Confirmación del webhook de Meta: '+d['status'])
            except requests.RequestException:return
    def kapso_receipts(self,cfg):
        """Kapso SDK 0.4: GET /phone/messages/id, status in kapso extension."""
        import requests
        from urllib.parse import quote
        token=self.vault.get('kapso_key')
        if not token:return
        for row in self.repo.pending_receipts():
            channel=row.get('canal') or {}
            if channel.get('wa_provider')!='KAPSO':continue
            version,pid=channel.get('api_version',''),channel.get('phone_id','')
            if not re.fullmatch(r'v\d+\.\d+',version) or not pid.isdigit():continue
            self.repo.touch_receipt(row['id'])
            try:
                mid=quote(row['mensaje_id'],safe='')
                r=requests.get(f'https://api.kapso.ai/meta/whatsapp/{version}/{pid}/messages/{mid}',
                    headers={'X-API-Key':token},params={'fields':'kapso(status,direction)'},timeout=(3,5),allow_redirects=False)
                if r.status_code!=200:continue
                data=r.json();message=data.get('data',data)
                if not isinstance(message,dict) or message.get('id')!=row['mensaje_id']:continue
                recipient=re.sub(r'[ +()-]','',str(message.get('to','')))
                if recipient!=row['destino']:continue
                extra=message.get('kapso') or {}
                if extra.get('direction') not in (None,'outbound'):continue
                status=extra.get('status')
                state={'delivered':'ENTREGADO','read':'LEIDO','failed':'ERROR'}.get(status)
                if state:self.repo.job_state(row['id'],state,'Estado confirmado por Kapso: '+status)
            except (requests.RequestException,ValueError,TypeError,AttributeError):continue

    def tick(self):
        self.repo.health();cfg=self.repo.settings();reachable=False;bot_status='Bot del dueño desactivado.'
        if cfg['wa_enabled'] and cfg['wa_mode']=='REAL':
            import psycopg
            try:
                reachable=self.network_reachable(cfg)
                if reachable:
                    from .bot import OwnerBot
                    bot_status=OwnerBot(self.repo,self.vault).poll(cfg)
                    job=self.repo.claim_job('REAL')
                    if job:self.send(job,cfg)
                    self.receipts(cfg)
            except psycopg.Error:raise
            except Exception:bot_status='Servicios pendientes: revisa la conexión y las credenciales en Configurar servicios.'
        if cfg.get('bot_enabled') and not reachable:bot_status='Bot pendiente: sin conexión con Kapso o WhatsApp desactivado.'
        return dict(bot_status=bot_status,settings=cfg,jobs=self.repo.jobs(),backups=self.repo.backup_history(),delivered=self.repo.delivered_owner(cfg['owner']),reachable=reachable)
    def backup(self,cfg):
        if not cfg['cloud_enabled'] or cfg['cloud_mode']!='REAL':raise BusinessError('Activa y configura el respaldo en la nube antes de continuar.')
        from cryptography.fernet import Fernet
        import boto3
        from botocore.config import Config
        key=self.vault.get('backup_key')
        if not key:raise BusinessError('Genera y exporta tu clave de recuperación antes del respaldo real.')
        cipher=Fernet(key.encode())
        executable=cfg.get('pg_dump') or shutil.which('pg_dump')
        if not executable:
            candidates=sorted(Path('C:/Program Files/PostgreSQL').glob('*/bin/pg_dump.exe'),reverse=True)
            executable=str(candidates[0]) if candidates else ''
        if not executable or not Path(executable).is_file():raise BusinessError('Configura la ruta a pg_dump.exe de tu versión PostgreSQL.')
        access=self.vault.get('s3_access');secret=self.vault.get('s3_secret')
        if not access or not secret:raise BusinessError('Faltan las credenciales S3.')
        self.repo.health();db=self.repo.config;directory=data_dir()/'respaldos';directory.mkdir(exist_ok=True)
        filename='kala_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+os.urandom(4).hex()+'.backup.fernet'
        path=directory/filename
        env=os.environ.copy();env['PGPASSWORD']=db.get('password','');env['PGCONNECT_TIMEOUT']='5'
        with tempfile.TemporaryDirectory(prefix='kala_backup_') as tmp:
            raw=Path(tmp)/'kala.backup'
            args=[executable,'--host',db.get('host','localhost'),'--port',str(db.get('port',5432)),'--username',db['user'],'--dbname',db['dbname'],'--format=custom','--no-owner','--no-acl','--no-password','--file',str(raw)]
            result=subprocess.run(args,env=env,capture_output=True,timeout=900,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:raise BusinessError('pg_dump no pudo crear el respaldo. Revisa versión, permisos y conexión local. No se subió ningún archivo.')
            if not raw.exists() or raw.stat().st_size<5 or raw.read_bytes()[:5]!=b'PGDMP':raise BusinessError('El respaldo no tiene un formato válido.')
            path.write_bytes(cipher.encrypt(raw.read_bytes()))
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        object_key=cfg['s3_prefix'].strip('/')+'/'+filename
        try:
            client=boto3.client('s3',endpoint_url=cfg.get('s3_endpoint') or None,region_name=cfg['s3_region'],aws_access_key_id=access,aws_secret_access_key=secret,config=Config(connect_timeout=5,read_timeout=60,retries={'max_attempts':2},request_checksum_calculation='when_required',response_checksum_validation='when_required'))
            with path.open('rb') as f:client.put_object(Bucket=cfg['s3_bucket'],Key=object_key,Body=f,ContentType='application/octet-stream',Metadata={'sha256':digest})
            head=client.head_object(Bucket=cfg['s3_bucket'],Key=object_key)
            if head['ContentLength']!=path.stat().st_size or head.get('Metadata',{}).get('sha256')!=digest:raise BusinessError('No coincide la verificación del objeto remoto.')
        except Exception:
            self.repo.backup_record('LOCAL_PENDIENTE_NUBE',str(path),'Copia cifrada local conservada; la subida no pudo confirmarse.')
            raise BusinessError('El respaldo cifrado quedó en '+str(path)+', pero la nube no confirmó la copia. Revisa el servicio y vuelve a respaldar.')
        self.repo.backup_record('NUBE_CONFIRMADA',str(path),'Objeto: '+object_key+' · SHA256: '+digest)
        return str(path)
