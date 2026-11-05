import re
import sys
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from argon2 import PasswordHasher
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (QApplication,QWidget,QVBoxLayout,QFormLayout,QLabel,QLineEdit,QSpinBox,QPushButton,QMessageBox)
ROOT=Path(__file__).resolve().parent

class SetupError(Exception):pass

def validate(v):
    if not 1<=v['port']<=65535:raise SetupError('Puerto inválido.')
    if not v['postgres']:raise SetupError('Escribe la contraseña de postgres.')
    if not 1<=len(v['name'].strip())<=120:raise SetupError('Escribe el nombre del dueño (hasta 120 caracteres).')
    if not re.fullmatch(r'[a-z0-9_.-]{3,50}',v['user']):raise SetupError('Usuario: 3 a 50 letras minúsculas, números, punto, guion o guion bajo.')
    for key in ('app','admin'):
        if not 12<=len(v[key])<=128 or not v[key].strip():raise SetupError('Las contraseñas nuevas deben tener entre 12 y 128 caracteres.')
        if v[key]!=v[key+'_again']:raise SetupError('No coinciden las contraseñas repetidas.')
    if v['app']==v['admin'] or v['app']==v['postgres'] or v['admin']==v['postgres']:raise SetupError('Utiliza contraseñas distintas para postgres, conexión local y administrador de KALA.')

def schema_text():
    # pg_dump añade dos metacomandos exclusivos de psql. No son SQL del servidor.
    text=(ROOT/'kala_estructura.sql').read_text(encoding='utf-8-sig')
    text='\n'.join(line for line in text.splitlines() if not re.match(r'^\\(?:un)?restrict\s',line))
    if any(line.startswith('\\') for line in text.splitlines()):raise SetupError('La estructura contiene un comando de consola no admitido.')
    return text

def initialize(c,v):
    with c.transaction():
        c.execute('SET LOCAL ROLE kala_owner')
        c.execute(schema_text(),prepare=False)
        c.execute((ROOT/'permisos.sql').read_text(),prepare=False)
        # Restablece el search_path vacío que usa pg_dump para su restauración.
        c.execute("SET LOCAL search_path=public,pg_catalog")
        cfg=dict(wa_enabled=False,wa_mode='REAL',wa_provider='KAPSO',wa_format='TEXT',
          bot_enabled=False,cloud_enabled=False,cloud_mode='REAL',simulate_hardware=False,
          owner_consent=False,auto_close=True,operacion_real_version=1,s3_region='auto',backup_minutes=60)
        c.execute('INSERT INTO public.kala_config_integraciones(id,datos) VALUES(1,%s)',(Jsonb(cfg),))
        c.execute("INSERT INTO public.cajas(nombre,descripcion) VALUES('Caja principal','Mostrador')")
        uid=c.execute("INSERT INTO public.usuarios(nombre,usuario,password_hash,rol) VALUES(%s,%s,%s,'ADMINISTRADOR') RETURNING id",
          (v['name'].strip(),v['user'],PasswordHasher().hash(v['admin']))).fetchone()[0]
        c.execute("INSERT INTO public.auditoria(usuario_id,origen,accion,entidad,registro_id,descripcion) VALUES(NULL,'SISTEMA','CREAR_ADMIN_INICIAL','usuarios',%s,'Preparación de base nueva del negocio.')",(uid,))
        assert c.execute('SELECT count(*) FROM public.ventas').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM public.productos').fetchone()[0]==0

def provision(v):
    validate(v)
    cfg=dict(host='localhost',port=v['port'],user='postgres',password=v['postgres'],connect_timeout=5,
             options='-c statement_timeout=120000 -c lock_timeout=5000')
    with psycopg.connect(**cfg,dbname='postgres',autocommit=True) as guard:
        if guard.info.server_version<180000:raise SetupError('Instala PostgreSQL 18 o posterior antes de continuar.')
        if not guard.execute('SELECT pg_try_advisory_lock(724002)').fetchone()[0]:raise SetupError('Ya hay otra preparación en curso.')
        if guard.execute("SELECT 1 FROM pg_database WHERE datname='kala_db'").fetchone():
            raise SetupError('Ya existe kala_db. No se modificó. Esta herramienta es solo para una PC nueva; abre KALA si ya estaba configurada.')
        if guard.execute("SELECT 1 FROM pg_roles WHERE rolname IN ('kala_owner','kala_app')").fetchone():
            raise SetupError('Ya existen cuentas de KALA en PostgreSQL. No se modificaron. Requiere revisión de la instalación anterior.')
        with guard.transaction():
            guard.execute('CREATE ROLE kala_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION')
            guard.execute(sql.SQL('CREATE ROLE kala_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}').format(sql.Literal(v['app'])))
        guard.execute("CREATE DATABASE kala_db OWNER kala_owner TEMPLATE template0 ENCODING 'UTF8'")
        with psycopg.connect(**cfg,dbname='kala_db') as c:initialize(c,v)
    # Verificación con la misma cuenta que usa el programa, no como superusuario.
    with psycopg.connect(host='localhost',port=v['port'],dbname='kala_db',user='kala_app',password=v['app'],connect_timeout=5) as c:
        if c.execute('SELECT count(*) FROM public.usuarios').fetchone()[0]!=1:raise SetupError('No se pudo comprobar la cuenta inicial.')

class Worker(QThread):
    result=pyqtSignal(str,bool)
    def __init__(self,v,parent):super().__init__(parent);self.v=v
    def run(self):
        try:
            provision(self.v)
            self.result.emit('Base nueva lista.\n\nAbre KALA y usa el puerto indicado y la contraseña de conexión local (kala_app). Después inicia sesión con el usuario y la contraseña del dueño.\n\nCrea el catálogo y los cajeros desde administración. WhatsApp y nube quedan apagados hasta configurarlos.',True)
        except SetupError as e:self.result.emit(str(e),False)
        except psycopg.OperationalError:self.result.emit('No se pudo completar la conexión. Revisa que PostgreSQL esté funcionando, el puerto y la contraseña de postgres. Si hubo una interrupción después de empezar, no borres bases ni roles: solicita revisión.',False)
        except psycopg.Error as e:self.result.emit('Preparación incompleta. Código SQLSTATE: '+str(e.sqlstate or 'no disponible')+'. La estructura se restaura en una transacción; pueden quedar la base vacía y los roles creados. No se eliminan automáticamente. Solicita revisión.',False)
        except Exception:self.result.emit('No se pudo completar la preparación. No borres ni reemplaces una base existente; solicita revisión.',False)
        finally:self.v.clear()

class Window(QWidget):
    def __init__(self):
        super().__init__();self.worker=None;self.setWindowTitle('KALA · Primera instalación');self.resize(650,620)
        self.setStyleSheet('QWidget{font-family:Segoe UI;font-size:13px;background:#faf9f2;color:#193f42;} QLineEdit,QSpinBox{background:white;padding:7px;border:1px solid #bdcec6;border-radius:5px;} QPushButton{background:#1c645c;color:white;padding:12px;border-radius:8px;}')
        l=QVBoxLayout(self);title=QLabel('Prepara la papelería del dueño');title.setStyleSheet('font-size:24px;font-weight:bold');l.addWidget(title)
        msg=QLabel('Solo para una PC nueva con PostgreSQL instalado. Se creará una base sin productos ni ventas, una caja y la cuenta del dueño. Si ya existe kala_db, se detiene sin modificarla.');msg.setWordWrap(True);l.addWidget(msg)
        f=QFormLayout();l.addLayout(f);self.fields={}
        self.port=QSpinBox();self.port.setRange(1,65535);self.port.setValue(5432);f.addRow('Puerto PostgreSQL',self.port)
        for key,title in [('postgres','Contraseña de postgres'),('app','Nueva contraseña de conexión local'),('app_again','Repite contraseña de conexión'),('name','Nombre del dueño'),('user','Usuario del dueño'),('admin','Nueva contraseña del dueño'),('admin_again','Repite contraseña del dueño')]:
            w=QLineEdit();self.fields[key]=w
            if key not in ('name','user'):w.setEchoMode(QLineEdit.EchoMode.Password)
            f.addRow(title,w)
        note=QLabel('Conserva las tres contraseñas en un lugar seguro. No se guardan en archivos. Las nuevas deben tener al menos 12 caracteres y ser distintas.');note.setWordWrap(True);l.addWidget(note)
        self.button=QPushButton('Crear base nueva');self.button.clicked.connect(self.start);l.addWidget(self.button)
        self.status=QLabel('');self.status.setWordWrap(True);l.addWidget(self.status)
    def start(self):
        v={k:w.text() for k,w in self.fields.items()};v['user']=v['user'].strip().lower();v['port']=self.port.value()
        try:validate(v)
        except SetupError as e:QMessageBox.warning(self,'Revisa los datos',str(e));return
        self.button.setEnabled(False);self.status.setText('Preparando… No cierres esta ventana.')
        self.worker=Worker(v,self);self.worker.result.connect(self.done);self.worker.finished.connect(self.finished);self.worker.start()
    def done(self,msg,ok):
        self.status.setText('Completado.' if ok else 'Preparación detenida.');self.success=ok
        if ok:
            for k,w in self.fields.items():
                if k not in ('name','user'):w.clear()
        (QMessageBox.information if ok else QMessageBox.warning)(self,'Preparación de KALA',msg)
    def finished(self):
        self.button.setEnabled(not getattr(self,'success',False));self.worker.deleteLater();self.worker=None
    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():event.ignore()
        else:event.accept()

if __name__=='__main__':
    app=QApplication(sys.argv);app.setStyle('Fusion');w=Window();w.show();sys.exit(app.exec())
