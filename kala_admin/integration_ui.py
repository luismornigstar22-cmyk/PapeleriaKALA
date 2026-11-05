from pathlib import Path
from datetime import datetime,timezone
import time,html,traceback
from uuid import uuid4
from PyQt6.QtCore import QTimer,QEvent,Qt,QUrl
from PyQt6.QtGui import QDesktopServices,QKeySequence,QShortcut,QTextDocument
from PyQt6.QtWidgets import (QApplication,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QDialogButtonBox,
 QLineEdit,QComboBox,QAbstractSpinBox,QTextEdit,QPlainTextEdit,QTextBrowser,QMessageBox,QFileDialog,QTabWidget,QWidget,QFormLayout,QScrollArea,QCheckBox)
from .repository import BusinessError,money
from .services import DEFAULTS,phone,status_text
from .transport import Transport,Vault,data_dir

class IntegrationUI:
    def init_integrations(self):
        from .ui import button,label,Table
        self.settings=dict(DEFAULTS);self.db_ok=None;self.integration_busy=False;self.integration_worker=None
        self.jobs_cache=[];self.backups_cache=[];self.delivered=None;self.reachable=False;self.next_backup=time.monotonic()+60;self.integration_detail='Pendiente de comprobar';self.scanner_state='Captura por código disponible'
        self.transport=Transport(self.repo);self.system_hint.setText('Preparando servicios…')
        l=self.page('system','Conexiones y equipos','Configura WhatsApp, respalda tu base y prueba el equipo antes de usarlo en mostrador.')
        self.bar(l,[('Configurar servicios',self.configure_services),('Revisar / procesar cola',self.start_services),('Respaldar ahora',lambda:self.start_backup(True)),('Clave de recuperación',self.export_recovery_key)])
        self.connection_info=label('Comprobando servicios…','muted');l.addWidget(self.connection_info)
        self.jobs_table=Table([('Documento','titulo'),('Destinatario','destino'),('Estado','estado',status_text),('Detalle','detalle')]);l.addWidget(self.jobs_table,2)
        self.bar(l,[('Ver documento seleccionado',self.view_job),('Reintentar envío seleccionado',self.retry_selected)])
        l.addWidget(label('Copias de seguridad recientes','muted'))
        self.backup_table=Table([('Fecha','creado_en'),('Estado','estado',status_text),('Archivo','archivo'),('Detalle','detalle')]);l.addWidget(self.backup_table,1)
        n=self.nav_layout
        b=button('Conexiones / equipo',lambda:self.navigate('system'));b.setCheckable(True);n.insertWidget(n.count()-2,b);self.nav_buttons['system']=b
        # Acciones coherentes en las pantallas que producen documentos.
        self.pages['dashboard'].layout().addWidget(button('Enviar reporte del periodo por WhatsApp',lambda:self.safe(self.send_dashboard)))
        self.pages['audit'].layout().addWidget(button('Enviar bitácora por WhatsApp',lambda:self.safe(lambda:self.send_table(self.audit_table,'Bitácora de operaciones'))))
        self.pages['closings'].layout().addWidget(button('Ticket del cierre · imprimir / WhatsApp',lambda:self.safe(self.closing_document)))
        self.pages['cash'].layout().addWidget(button('Comprobante de movimiento · imprimir / WhatsApp',lambda:self.safe(self.cash_document)))
        self.pages['sales'].layout().addWidget(button('Enviar ticket por WhatsApp',lambda:self.safe(lambda:self.ticket_preview(self.sales_table.selected()['id']))))
        self.pages['inventory'].layout().addWidget(label('1. Busca el artículo   →   2. Selecciónalo   →   3. Recibe mercancía o registra un conteo','muted'))
        QShortcut(QKeySequence('F12'),self).activated.connect(self.show_shortcuts)
        QApplication.instance().installEventFilter(self)
        self.service_timer=QTimer(self);self.service_timer.setInterval(30000);self.service_timer.timeout.connect(self.start_services);self.service_timer.start()
        QTimer.singleShot(500,self.start_services)
        self.render_status()

    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.KeyPress and event.key()==Qt.Key.Key_Tab and not event.modifiers() and self.isVisible() and QApplication.activeModalWidget() is None:
            focus=QApplication.focusWidget()
            if focus and (focus is self or self.isAncestorOf(focus)) and not isinstance(focus,(QLineEdit,QComboBox,QAbstractSpinBox,QTextEdit,QPlainTextEdit)):
                self.show_shortcuts();return True
        return super().eventFilter(obj,event)
    def show_shortcuts(self):
        if QApplication.activeModalWidget():return
        text='F1  Punto de venta\nF2  Caja y retiros\nF3  Catálogo\nF4  Resumen\nF5  Usuarios\nF6  Cobrar (dentro del POS)\nF7  Arqueo ciego\nF8  Mermas\nF9  Ventas y tickets\nF12  Mostrar esta guía\nTab  Guía fuera de campos; siguiente campo dentro de formularios\nShift + Tab  Campo anterior\nEnter  Buscar / escanear desde el campo correspondiente\nEsc  Cerrar un diálogo sin guardar'
        QMessageBox.information(self,'Atajos de KALA',text)
    def render_status(self):
        if not hasattr(self,'db_ok'):return
        if self.db_ok is False:
            title='ERROR DE BASE DE DATOS LOCAL';color='#a92e36';hint='Cobros bloqueados hasta recuperar la conexión. '+self.integration_detail
        elif self.db_ok is None:
            title='COMPROBANDO BASE LOCAL';color='#647779';hint='Verificando conexión y permisos.'
        elif self.integration_busy and getattr(self,'background_kind','') in ('backup','send'):
            title='SINCRONIZANDO';color='#2878ae';hint='Procesando en segundo plano. Puedes seguir trabajando.'
        elif self.delivered and self.reachable:
            title='ONLINE Y REPORTE ENVIADO';color='#9c6b0c';hint='Entrega al dueño confirmada: '+str(self.delivered['actualizado_en'])
        else:
            title='LOCAL LISTO';color='#15734e';hint='Puedes registrar ventas aunque no haya Internet.'
        self.state.setText('● '+title);self.state.setStyleSheet('font-weight:700;color:'+color+';padding:5px;');self.state.setToolTip(hint)
        mode='PAPELERÍA CONECTADA' if self.reachable else 'TRABAJO LOCAL'
        self.system_hint.setText(mode+'\nWhatsApp: '+('activo' if self.settings['wa_enabled'] else 'apagado')+'\nNube: '+('activa' if self.settings['cloud_enabled'] else 'apagada'))
        self.system_hint.setToolTip('Las ventas se guardan en esta computadora. Los envíos pendientes requieren Internet y KALA abierto.')
        self.state_details.setText(self.integration_detail[:130])
    def refresh_system(self):self.start_services()
    def run_background(self,fn,kind,callback):
        from .ui import Worker
        if self.integration_busy:return
        self.integration_busy=True;self.background_kind=kind;self.render_status();results=[]
        w=Worker(fn,self);self.integration_worker=w;w.done.connect(lambda data,error:results.append((data,error)))
        def finished():
            self.integration_busy=False;self.integration_worker=None;w.deleteLater()
            data,error=results[0] if results else (None,RuntimeError('Proceso interrumpido'))
            if error:
                import psycopg
                if isinstance(error,psycopg.Error) or (isinstance(error,BusinessError) and kind=='check'):
                    self.db_ok=False
                    self.integration_detail=('Falta ejecutar sql/02_integraciones.sql.' if isinstance(error,psycopg.errors.UndefinedTable) else 'No se pudo comprobar la base / permisos: '+type(error).__name__)
                else:self.integration_detail='Servicio pendiente: '+(str(error) if isinstance(error,BusinessError) else type(error).__name__)
                if kind=='backup':QMessageBox.warning(self,'Respaldo no confirmado',self.integration_detail)
            else:
                try:callback(data)
                except Exception as exc:self.report_ui_error(exc)
            self.render_status()
        w.finished.connect(finished);w.start()
    def start_services(self):
        if self.integration_busy or not self.isVisible():return
        kind='send' if self.settings['wa_enabled'] and any(r['estado']=='PENDIENTE' for r in self.jobs_cache) else 'check'
        def show(d):
            self.db_ok=True;self.settings=d['settings'];self.jobs_cache=d['jobs'];self.backups_cache=d['backups'];self.delivered=d['delivered'];self.reachable=d['reachable']
            self.jobs_table.fill(self.jobs_cache);self.backup_table.fill(self.backups_cache)
            pending=sum(r['estado'] in ('PENDIENTE','PROCESANDO') for r in self.jobs_cache)
            bad=sum(r['estado'] in ('ERROR','REVISION') for r in self.jobs_cache)
            self.integration_detail=f'Últimos 200 envíos: {pending} pendientes · {bad} por revisar · Lector: {self.scanner_state}'
            self.connection_info.setText(self.integration_detail+'\n'+d.get('bot_status','')+'\nAceptado: el proveedor recibió el mensaje. Entregado o leído: entrega confirmada.\nLector USB: escanea en el campo Código. Impresora: utiliza la instalada en Windows.')
            if self.settings['cloud_enabled'] and time.monotonic()>=self.next_backup:
                self.next_backup=time.monotonic()+self.settings['backup_minutes']*60;QTimer.singleShot(0,lambda:self.start_backup(False))
        self.run_background(self.transport.tick,kind,show)
    def start_backup(self,manual=False):
        if self.integration_busy:
            if manual:QMessageBox.information(self,'Servicio ocupado','Espera a que termine la revisión o el respaldo actual.')
            return
        cfg=dict(self.settings)
        if not cfg['cloud_enabled']:raise BusinessError('Activa y configura los respaldos en Configurar servicios.')
        self.next_backup=time.monotonic()+cfg['backup_minutes']*60
        def done(path):
            self.integration_detail='Copia de seguridad cifrada confirmada en la nube.'
            if manual:QMessageBox.information(self,'Resultado del respaldo',self.integration_detail+'\n'+path)
            QTimer.singleShot(0,self.start_services)
        self.run_background(lambda:self.transport.backup(cfg),'backup',done)
    def report_ui_error(self,error):
        traceback.print_exc()
        QMessageBox.warning(self,'No se pudo mostrar el documento','La aplicación continúa abierta. Si acabas de cobrar, la venta puede estar guardada: consulta Ventas / tickets antes de cobrar de nuevo.\n\n'+type(error).__name__+': '+str(error)[:300])
    def view_job(self):
        row=self.jobs_table.selected()
        self.run(lambda:self.repo.read('SELECT titulo,contenido,modo,estado FROM public.kala_envios WHERE id=%s',(row['id'],)),lambda data:self.show_document('<p>'+html.escape(data[0]['contenido']).replace('\n','<br>')+'</p>',False,0,data[0]['titulo']))
    def retry_selected(self):
        row=self.jobs_table.selected()
        if QMessageBox.question(self,'Reintentar envío','Si el resultado fue incierto, el mensaje pudo llegar. Revisa el proveedor antes de reenviar. ¿Solicitar un nuevo intento?')!=QMessageBox.StandardButton.Yes:return
        self.mutate(self.repo.retry_job,(row['id'],),self.start_services)
    def configure_services(self):
        from .ui import label,combo,check,number,field_value
        if self.busy or self.integration_busy:raise BusinessError('Espera a que termine la comprobación de servicios.')
        cfg=self.settings;d=QDialog(self);d.setWindowTitle('Configuración · KALA');d.resize(740,680);layout=QVBoxLayout(d)
        layout.addWidget(label('Conecta tu papelería','title'));layout.addWidget(label('Configura tus servicios. Las claves se guardan en el almacén seguro de Windows.','muted'))
        tabs=QTabWidget();layout.addWidget(tabs);fields={};secrets={}
        def tab(title):
            sc=QScrollArea();sc.setWidgetResizable(True);body=QWidget();form=QFormLayout(body);sc.setWidget(body);tabs.addTab(sc,title);return form
        def add(form,key,title,w):fields[key]=w;form.addRow(title,w)
        def secret(form,key,title):
            w=QLineEdit();w.setEchoMode(QLineEdit.EchoMode.Password);w.setPlaceholderText('Vacío = conservar el secreto guardado');secrets[key]=w;form.addRow(title,w)
        f=tab('WhatsApp')
        add(f,'wa_enabled','Procesar envíos',check(cfg['wa_enabled']))
        add(f,'wa_provider','Proveedor',combo([('Kapso','KAPSO'),('Meta directo','META')],cfg['wa_provider']))
        add(f,'wa_format','Formato',combo([('Texto · conversación activa','TEXT'),('PDF · plantilla aprobada en producción','TEMPLATE_PDF')],cfg['wa_format']))
        for k,t in [('owner','WhatsApp del dueño (+país)'),('phone_id','Phone Number ID'),('api_version','Versión Graph (vXX.0)'),('template','Plantilla aprobada'),('language','Idioma de plantilla')]:add(f,k,t,QLineEdit(cfg[k]))
        add(f,'owner_consent','El dueño autoriza recibir reportes',check(cfg['owner_consent']));add(f,'auto_close','Avisar automáticamente al cerrar turno',check(cfg['auto_close']))
        secret(f,'kapso_key','API key de Kapso')
        secret(f,'wa_token','Token de Meta (solo Meta directo)')
        f.addRow(label('Texto: requiere una conversación activa y admite hasta 4096 caracteres. Para enviar fuera de la ventana de atención, configura una plantilla aprobada con documento PDF y título. El proveedor puede aplicar cargos.'))
        add(f,'relay_url','URL HTTPS del receptor de confirmaciones',QLineEdit(cfg['relay_url']));secret(f,'relay_token','Token privado del receptor')
        f=tab('Bot del dueño')
        add(f,'bot_enabled','Permitir consultas del dueño por WhatsApp',check(cfg.get('bot_enabled',False)))
        add(f,'bot_url','URL HTTPS del Worker (sin /webhook)',QLineEdit(cfg.get('bot_url','')))
        secret(f,'bot_token','Token privado del escritorio (DESKTOP_TOKEN)')
        f.addRow(label('Comandos: menú, ventas hoy, bitácora hoy y bitácora hoy 2. Solo responde al WhatsApp del dueño configurado en la primera pestaña. Requiere Internet y una sesión de administrador o cajero abierta. Se revisa cada 30 segundos; los respaldos pueden retrasarlo.'))
        f=tab('Nube / respaldo')
        add(f,'cloud_enabled','Respaldos automáticos mientras KALA está abierto',check(cfg['cloud_enabled']))
        for k,t in [('s3_endpoint','Endpoint S3 de R2 (HTTPS)'),('s3_bucket','Bucket privado'),('s3_region','Región (R2: auto)'),('s3_prefix','Carpeta / prefijo'),('pg_dump','Ruta a pg_dump.exe')]:add(f,k,t,QLineEdit(cfg[k]))
        add(f,'backup_minutes','Intervalo en minutos',number(cfg['backup_minutes'],0));secret(f,'s3_access','Access key');secret(f,'s3_secret','Secret key')
        f.addRow(label('Copia completa cifrada de PostgreSQL. No es una réplica activa ni permite cobrar con la base local caída. Guarda la clave de recuperación fuera de esta computadora antes de activar los respaldos.'))
        f=tab('Equipo')
        f.addRow(label('Lector USB: configúralo para escribir el código y terminar con Enter. También puedes escribir el código o buscar por nombre.\n\nImpresora: instálala en Windows y elige el papel de 58 mm para tickets. Puedes guardar un PDF por separado.\n\nTarjeta: cobra en la terminal bancaria, verifica que el pago esté aprobado y registra su folio en KALA. KALA registra el pago; la terminal realiza el cargo.'))
        bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);bb.accepted.connect(d.accept);bb.rejected.connect(d.reject);layout.addWidget(bb)
        if not d.exec():return
        new={**cfg,**{k:field_value(w) for k,w in fields.items()},'wa_mode':'REAL','cloud_mode':'REAL','simulate_hardware':False}
        new['backup_minutes']=int(float(new['backup_minutes']))
        # Persistir los secretos solo en el almacén del sistema operativo.
        try:
            for k,w in secrets.items():
                if w.text():self.transport.vault.set(k,w.text());w.clear()
            if new['wa_enabled'] and new['wa_mode']=='REAL':
                key='kapso_key' if new['wa_provider']=='KAPSO' else 'wa_token'
                if not self.transport.vault.get(key):raise BusinessError('Falta la credencial del proveedor seleccionado.')
            if new.get('bot_enabled') and len(self.transport.vault.get('bot_token'))<32:raise BusinessError('Guarda el DESKTOP_TOKEN del Worker (mínimo 32 caracteres).')
            if new['cloud_enabled'] and new['cloud_mode']=='REAL':
                for key in ('backup_key','s3_access','s3_secret'):
                    if not self.transport.vault.get(key):raise BusinessError('Falta guardar '+key+'. Configura las credenciales y exporta la clave de recuperación.')
        except Exception as e:raise BusinessError(str(e))
        def saved():
            self.settings=new;self.scanner_state='Captura por código disponible';self.render_status();self.start_services()
        self.mutate(self.repo.save_settings,(new,),saved)
    def export_recovery_key(self):
        from cryptography.fernet import Fernet
        key=self.transport.vault.get('backup_key') or Fernet.generate_key().decode()
        path,_=QFileDialog.getSaveFileName(self,'Guardar clave FUERA de la computadora de caja','KALA_recuperacion.key','Clave (*.key)')
        if not path:return
        Path(path).write_text(key,encoding='ascii');self.transport.vault.set('backup_key',key)
        QMessageBox.information(self,'Clave de recuperación','Conserva este archivo en un USB o lugar seguro separado. Sin él no se pueden descifrar los respaldos. No lo envíes por WhatsApp.')
    def send_document(self,title,body):
        from .ui import Form,combo,check
        cfg=self.settings;fields={'recipient':('Destinatario',combo([('Dueño','OWNER'),('Cliente / otro autorizado','CLIENT')])),'phone':('WhatsApp del cliente (+país)',QLineEdit()),'consent':('El destinatario autorizó recibirlo',check(False))}
        if not cfg['wa_enabled']:raise BusinessError('Activa WhatsApp en Configurar servicios antes de enviar.')
        d=Form(self,'Enviar por WhatsApp · '+title,fields,'Confirma el número y la autorización del destinatario. El documento se guardará en la cola de envíos.')
        if not d.exec():return
        v=d.data();target=(cfg['owner'] or 'DUEÑO SIN CONFIGURAR') if v['recipient']=='OWNER' else v['phone'];consent=cfg['owner_consent'] if v['recipient']=='OWNER' else v['consent']
        def done():QMessageBox.information(self,'Documento en cola','El documento quedó en cola. Revisa su estado en Conexiones / equipo.');self.start_services()
        self.mutate(self.repo.queue_document,(title,body,target,cfg['wa_mode'],consent),done)
    def show_document(self,body,thermal=False,lines=0,title='Comprobante KALA'):
        from .ui import button,label
        d=QDialog(self);d.setWindowTitle(title);d.resize(680,700);layout=QVBoxLayout(d);layout.addWidget(label(title,'title'));view=QTextBrowser();view.setHtml(body);layout.addWidget(view,1)
        layout.addWidget(label('Puedes imprimir y enviar por WhatsApp el mismo comprobante. Cerrar esta ventana no cancela la operación.','muted'))
        text=view.toPlainText();actions=QHBoxLayout();actions.addWidget(button('Imprimir',lambda:self.safe(lambda:self.print_html(body,thermal,lines))));actions.addWidget(button('Guardar PDF',lambda:self.safe(lambda:self.save_pdf(body,thermal,lines))))
        # Encolar después de cerrar la vista evita diálogos modales superpuestos.
        def send():d.accept();QTimer.singleShot(0,lambda:self.safe(lambda:self.send_document(title,text)))
        actions.addWidget(button('Enviar por WhatsApp',send));actions.addWidget(button('Cerrar',d.reject));layout.addLayout(actions);d.exec()
    def table_text(self,table,title):
        if not table.rows:raise BusinessError('No hay registros para enviar.')
        lines=['PAPELERÍA KALA',title,'Generado: '+datetime.now().strftime('%d/%m/%Y %H:%M'),' | '.join(c[0] for c in table.columns)]
        for i in range(table.rowCount()):lines.append(' | '.join(table.item(i,j).text() for j in range(table.columnCount())))
        return '\n'.join(lines)
    def send_table(self,table,title):self.send_document(title,self.table_text(table,title))
    def send_dashboard(self):
        a,z=self.range(self.dash_dates)
        def show(d):
            text=f'PAPELERÍA KALA\nReporte del {a} al {z}\nVentas vigentes: {money(d["ventas"])}\nGanancia estimada: {money(d["ganancia"])}\nTickets: {d["tickets"]}\nProductos con stock bajo: {len(d["bajos"])}\n\nROTACIÓN ABC\n'
            text+='\n'.join(f'{r["clase"]} · {r["nombre"]}: {r["unidades"]} unidades' for r in d['abc'])
            text+='\n\nREABASTECER\n'+'\n'.join(f'{r["nombre"]}: {r["existencia"]}, reorden {r["punto_reorden"]}' for r in d['bajos'])
            self.send_document('Reporte gerencial',text)
        self.run(lambda:self.repo.dashboard(a,z),show)
    def closing_document(self):
        row=self.closings_table.selected()
        self.run(lambda:self.repo.closing_report(row['id']),lambda text:self.show_document('<p>'+html.escape(text).replace('\n','<br>')+'</p>',True,20,'Cierre #'+str(row['id'])))
    def cash_document(self):
        row=self.cash_table.selected();text='PAPELERÍA KALA\nMOVIMIENTO #'+str(row['id'])+'\n'+'\n'.join(f'{name}: {formatter(row[key]) if formatter else row[key]}' for name,key,formatter in [('Fecha','creado_en',str),('Turno','turno_id',str),('Tipo','tipo',str),('Importe','importe_centavos',money),('Motivo','motivo',str),('Responsable','responsable',str)])
        self.show_document('<p>'+html.escape(text).replace('\n','<br>')+'</p>',True,10,'Movimiento #'+str(row['id']))
