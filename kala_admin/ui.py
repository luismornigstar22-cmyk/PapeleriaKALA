from pathlib import Path
from decimal import Decimal
from uuid import uuid4
import html
import traceback
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate, QSizeF, QTimer
from PyQt6.QtGui import QPixmap, QPainter, QColor, QShortcut, QKeySequence, QTextDocument, QPageSize
from PyQt6.QtWidgets import (QApplication,QMainWindow,QWidget,QFrame,QLabel,QPushButton,QVBoxLayout,QHBoxLayout,
 QGridLayout,QStackedWidget,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QLineEdit,QComboBox,
 QDoubleSpinBox,QSpinBox,QCheckBox,QDialog,QDialogButtonBox,QFormLayout,QMessageBox,QDateEdit,QFileDialog,QScrollArea,QInputDialog)
from PyQt6.QtPrintSupport import QPrinter,QPrintPreviewDialog,QPrinterInfo
from .repository import BusinessError, money
from .services import ExtendedRepository as Repository
from .integration_ui import IntegrationUI

STYLE='''
QWidget {font-family: 'Segoe UI'; font-size: 13px; color: #263d46;}
QFrame#nav {background: #123e43; border-radius: 18px;}
QFrame#nav QLabel {color: #cee5db; background: transparent;}
QFrame#nav QPushButton {text-align: left; background: transparent; color: #dfeee7; border:0; padding:8px; border-radius:9px; font-size:12px;}
QFrame#nav QPushButton:checked {background: #e6b351; color:#17383a; font-weight:700;}
QFrame#nav QPushButton:hover {background:#286064; color:white;}
QFrame#card,QWidget#page {background: rgba(255,253,248,244); border:1px solid #e1e4da; border-radius:16px;}
QLabel {background:transparent;} QLabel#title {font-size:25px; font-weight:700; color:#174a4b;}
QLabel#muted {color:#61736e;} QLabel#warning {color:#885218;background:#fff0c9;padding:10px;border-radius:8px;} QLabel#metric {font-size:27px; font-weight:700; color:#195f53;}
QPushButton {background:#1c645c; color:white; padding:10px 15px; border:0; border-radius:8px; font-weight:600;}
QPushButton:hover {background:#287e70;} QPushButton:focus {border:2px solid #dfad45;} QPushButton:pressed {background:#113f3d;} QPushButton:disabled {background:#bcc9c2; color:#eff4ee;}
QLineEdit,QComboBox,QDoubleSpinBox,QSpinBox,QDateEdit {background:white; border:1px solid #cbd7ce; border-radius:7px; padding:8px; min-height:20px;}
QLineEdit:focus,QDoubleSpinBox:focus {border:2px solid #c79535;}
QTableWidget {background:white; alternate-background-color:#f4f7f1; border:1px solid #dce4d9; border-radius:9px; gridline-color:#edf0e9; selection-background-color:#d3e8dd; selection-color:#154841;}
QHeaderView::section {background:#eaf0e8; color:#36574e; padding:10px; border:0; border-bottom:1px solid #d9e1d7; font-weight:600;}
QDialog {background:#fafaf3;} QToolTip {background:#fff5d5;color:#253a49;}
QScrollArea {border:0; background:transparent;} QTabWidget::pane {border:1px solid #d8e3d9;border-radius:8px;} QTabBar::tab {background:#e4ece1;padding:10px 20px;} QTabBar::tab:selected {background:#e9b64f;color:#153c3d;font-weight:700;} QTableWidget::item:hover {background:#eaf3dc;} QTableWidget::item:selected {background:#cce5d8;color:#123c3d;} QCheckBox {spacing:8px;}
'''

class Worker(QThread):
    done=pyqtSignal(object,object)
    def __init__(self,fn,parent): super().__init__(parent); self.fn=fn
    def run(self):
        try: self.done.emit(self.fn(),None)
        except Exception as e: self.done.emit(None,e)

class Background(QWidget):
    def __init__(self):
        super().__init__(); self.pix=QPixmap(str(Path(__file__).resolve().parent.parent/'assets'/'fondo_admin.png'))
    def paintEvent(self,event):
        p=QPainter(self); p.fillRect(self.rect(),QColor('#f5f1df'))
        if not self.pix.isNull(): p.drawPixmap(self.rect(),self.pix)


def label(text,obj=None):
    w=QLabel(text)
    if obj: w.setObjectName(obj)
    w.setWordWrap(True); return w

def button(text,fn):
    b=QPushButton(text);b.clicked.connect(lambda checked=False:fn());return b

def number(value=0,decimals=2):
    w=QDoubleSpinBox();w.setDecimals(decimals);w.setRange(0,999999999);w.setValue(float(value or 0));return w

def combo(options,selected=None):
    w=QComboBox()
    for text,data in options:w.addItem(str(text),data)
    i=w.findData(selected)
    if i>=0:w.setCurrentIndex(i)
    return w

def field_value(w):
    if isinstance(w,QLineEdit):return w.text()
    if isinstance(w,QComboBox):return w.currentData()
    if isinstance(w,QCheckBox):return w.isChecked()
    if isinstance(w,(QDoubleSpinBox,QSpinBox)):return str(w.value())

def check(checked=True):
    w=QCheckBox();w.setChecked(checked);return w

class Form(QDialog):
    def __init__(self,parent,title,fields,help_text=''):
        super().__init__(parent);self.setWindowTitle(title);self.resize(520,400);self.fields=fields
        layout=QVBoxLayout(self);layout.addWidget(label(title,'title'))
        if help_text:layout.addWidget(label(help_text,'muted'))
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();form=QFormLayout(body)
        for key,(caption,w) in fields.items():form.addRow(caption,w)
        scroll.setWidget(body);layout.addWidget(scroll)
        bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setText('Guardar')
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText('Cancelar')
        bb.accepted.connect(self.accept);bb.rejected.connect(self.reject);layout.addWidget(bb)
    def data(self):return {k:field_value(w) for k,(_,w) in self.fields.items()}

class Table(QTableWidget):
    def __init__(self,columns):
        super().__init__(0,len(columns));self.columns=columns;self.rows=[]
        self.setHorizontalHeaderLabels([c[0] for c in columns]);self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.verticalHeader().hide()
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setDefaultSectionSize(44);self.setMinimumHeight(95)
        self.empty=QLabel('Sin registros para mostrar. Agrega información o consulta otro periodo.',self.viewport())
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter);self.empty.setStyleSheet('color:#7a8981;font-size:12px;background:transparent;');self.empty.setWordWrap(True)
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'empty'):self.empty.setGeometry(self.viewport().rect())
    def fill(self,rows):
        self.clearSpans();self.setSortingEnabled(False);self.rows=rows;self.setRowCount(len(rows));self.empty.setVisible(not rows);self.empty.setGeometry(self.viewport().rect())
        for i,row in enumerate(rows):
            for j,col in enumerate(self.columns):
                val=row.get(col[1]);txt=col[2](val) if len(col)>2 else ('' if val is None else str(val))
                item=QTableWidgetItem(txt);item.setData(Qt.ItemDataRole.UserRole,i);self.setItem(i,j,item)
                if col[1]=='diferencia_centavos':item.setForeground(QColor('#b74232' if val<0 else '#947019' if val>0 else '#197453'))
        self.setSortingEnabled(True)
    def selected(self):
        if not self.rows:raise BusinessError('Todavía no hay registros. Agrega un artículo o cambia el periodo de consulta.')
        item=self.item(self.currentRow(),0)
        if not item:raise BusinessError('Selecciona una fila primero.')
        return self.rows[item.data(Qt.ItemDataRole.UserRole)]

class AdminWindow(IntegrationUI,QMainWindow):
    logged_out=pyqtSignal()
    def __init__(self,config,user,repo=None):
        super().__init__();self.user=user;self.repo=repo or Repository(config,user);self.worker=None;self.busy=False
        self.cart={};self.quote_rows=[];self.own_turn=None;self.turn_rows=[];self.products_rows=[];self.pages={};self.nav_buttons={}
        self.setWindowTitle('Papelería KALA · Administración');self.resize(1366,768);self.setMinimumSize(1120,720);self.setStyleSheet(STYLE)
        root=Background();self.setCentralWidget(root);outer=QVBoxLayout(root);outer.setContentsMargins(24,18,24,18)
        header=QHBoxLayout();header.setContentsMargins(140,0,105,0);brand=label('Panel de administración','title');brand.setWordWrap(False);header.addWidget(brand);header.addStretch()
        header.addWidget(label(user['nombre']+'  ·  Administrador'));header.addWidget(button('Cerrar sesión',self.logout));outer.addLayout(header)
        outer.addSpacing(30) # deja visible la franja y la identidad del fondo original
        row=QHBoxLayout();row.setSpacing(20);outer.addLayout(row,1)
        nav=QFrame();nav.setObjectName('nav');nav.setFixedWidth(205);n=QVBoxLayout(nav);self.nav_layout=n;n.setContentsMargins(14,22,14,18)
        n.addWidget(label('MI PAPELERÍA'));n.addSpacing(14);row.addWidget(nav)
        self.stack=QStackedWidget();row.addWidget(self.stack,1)
        specs=[('dashboard','Resumen','F4'),('pos','Punto de venta','F1'),('catalog','Catálogo','F3'),('inventory','Inventario',''),('cash','Caja y retiros','F2'),('closings','Auditar cierres',''),('users','Usuarios','F5'),('count','Arqueo ciego','F7'),('waste','Mermas','F8'),('sales','Ventas / tickets','F9'),('audit','Bitácora','')]
        for key,title,shortcut in specs:
            b=button(title+('  '+shortcut if shortcut else ''),lambda k=key:self.navigate(k));b.setCheckable(True);n.addWidget(b);self.nav_buttons[key]=b
            if shortcut:
                s=QShortcut(QKeySequence(shortcut),self);s.activated.connect(lambda k=key:self.navigate(k) if not QApplication.activeModalWidget() else None)
        n.addStretch();self.system_hint=label('Servicios pendientes');n.addWidget(self.system_hint)
        self.state=label('Comprobando conexión local…','muted');self.state_details=label('','muted');status_row=QHBoxLayout();status_row.addWidget(self.state);status_row.addWidget(self.state_details,1);status_row.addWidget(button('Atajos · Tab / F12',self.show_shortcuts));outer.addLayout(status_row)
        self.build_dashboard();self.build_catalog();self.build_inventory();self.build_cash();self.build_users();self.build_closings();self.build_pos();self.build_sales();self.build_count();self.build_waste();self.build_audit()
        self.init_integrations()
        self.navigate('dashboard')

    def run(self,fn,success,mutation=False):
        if self.busy:return
        self.busy=True;self.stack.setEnabled(False);self.state_details.setText('Guardando operación…' if mutation else 'Actualizando información…')
        w=Worker(fn,self);self.worker=w;result=[]
        w.done.connect(lambda data,error:result.append((data,error)))
        def finished():
            self.busy=False;self.stack.setEnabled(True);w.deleteLater();self.worker=None
            data,error=result[0] if result else (None,RuntimeError('Operación interrumpida'))
            if error:
                self.state_details.setText('Operación no confirmada · revisa el mensaje')
                if isinstance(error,BusinessError):QMessageBox.warning(self,'Revisa los datos',str(error));return
                import psycopg
                if isinstance(error,psycopg.IntegrityError):
                    QMessageBox.warning(self,'Datos no aceptados','La base de datos rechazó un dato duplicado o incompatible. La operación se revirtió.\nDetalle: '+(getattr(error.diag,'message_primary','') or 'Restricción de integridad.'));return
                if isinstance(error,(psycopg.OperationalError,psycopg.InterfaceError)):
                    self.db_ok=False;self.integration_detail='Conexión local interrumpida';self.render_status()
                    box=QMessageBox(self);box.setWindowTitle('Conexión interrumpida');box.setText('No se pudo confirmar la respuesta de PostgreSQL. Reintentar conserva el identificador para evitar duplicados. Si sales, revisa el historial antes de repetir una venta.');box.setStandardButtons(QMessageBox.StandardButton.Retry|QMessageBox.StandardButton.Cancel)
                    if box.exec()==QMessageBox.StandardButton.Retry:self.run(fn,success,mutation)
                    return
                QMessageBox.warning(self,'No se pudo completar','Revisa la compatibilidad y permisos con verificar_instalacion.py.\n'+type(error).__name__+': '+str(error)[:450]);return
            self.state_details.setText('● Cambios guardados' if mutation else '● Información actualizada')
            self.db_ok=True
            try:success(data)
            except BusinessError as e:QMessageBox.warning(self,'KALA',str(e))
            except Exception as e:self.report_ui_error(e)
            self.render_status()
        w.finished.connect(finished);w.start()

    def safe(self,fn):
        try:fn()
        except BusinessError as e:QMessageBox.information(self,'KALA',str(e))
        except Exception as e:self.report_ui_error(e)
    def mutate(self,method,args,refresh,kwargs=None):
        if getattr(self,'db_ok',None) is False:raise BusinessError('La base local no responde. Recupera la conexión antes de registrar operaciones.')
        kw=dict(kwargs or {});kw['request_id']=str(uuid4())
        self.run(lambda:method(*args,**kw),lambda result:refresh(),True)
    def page(self,key,title,subtitle):
        page=QWidget();page.setObjectName('page');layout=QVBoxLayout(page);layout.setContentsMargins(24,18,24,18);layout.setSpacing(10)
        heading=QHBoxLayout();heading.addWidget(label(title,'title'),1)
        categories={'dashboard':'VISIÓN DEL NEGOCIO','pos':'VENTA RÁPIDA','catalog':'PRODUCTOS Y SERVICIOS','inventory':'EXISTENCIAS','cash':'EFECTIVO','closings':'REVISIÓN','users':'TU EQUIPO','count':'CIERRE DE TURNO','waste':'CONTROL DE STOCK','sales':'COMPROBANTES','audit':'TRAZABILIDAD','system':'CENTRO DE CONEXIONES'}
        tag=label(categories.get(key,'KALA'));tag.setStyleSheet('background:#fff0cc;color:#866017;border-radius:9px;padding:7px 10px;font-size:10px;font-weight:700;');heading.addWidget(tag)
        layout.addLayout(heading);layout.addWidget(label(subtitle,'muted'));self.stack.addWidget(page);self.pages[key]=page
        return layout
    def bar(self,layout,buttons):
        b=QHBoxLayout()
        for text,fn in buttons:
            action=button(text,lambda f=fn:self.safe(f))
            if text.startswith(('+','Recibir','Cobrar','Registrar y cerrar')):action.setStyleSheet('background:#e8b347;color:#203f3d;font-weight:700;')
            elif text.startswith(('Actualizar','Consultar','Buscar','Exportar','Vista')):action.setStyleSheet('background:#e8f0e6;color:#26554c;')
            b.addWidget(action)
        b.addStretch();layout.addLayout(b);return b
    def dates(self,layout,refresh):
        b=QHBoxLayout();a=QDateEdit(QDate.currentDate());z=QDateEdit(QDate.currentDate())
        for w in (a,z):w.setCalendarPopup(True);w.setDisplayFormat('dd/MM/yyyy')
        b.addWidget(label('Desde'));b.addWidget(a);b.addWidget(label('Hasta'));b.addWidget(z);b.addWidget(button('Consultar',lambda:self.safe(refresh)));b.addStretch();layout.addLayout(b);return a,z
    def range(self,pair):
        a,z=[w.date().toPyDate() for w in pair]
        if a>z:raise BusinessError('La fecha inicial no puede ser posterior a la final.')
        return a,z
    def navigate(self,key):
        if self.busy:return
        self.stack.setCurrentWidget(self.pages[key]);self.current=key
        for k,b in self.nav_buttons.items():b.setChecked(k==key)
        self.safe(getattr(self,'refresh_'+key))
    def logout(self):
        if self.busy or getattr(self,'integration_busy',False):
            QMessageBox.information(self,'Proceso en curso','Espera a que termine el proceso actual antes de salir.');return
        if self.cart and QMessageBox.question(self,'Cerrar sesión','Hay un carrito sin cobrar. ¿Descartarlo y salir?')!=QMessageBox.StandardButton.Yes:return
        self.logged_out.emit();self.close()
    def closeEvent(self,e):
        if self.busy or getattr(self,'integration_busy',False):QMessageBox.information(self,'Operación en curso','Espera a que termine la operación o el respaldo.');e.ignore()
        else:
            if hasattr(self,'service_timer'):self.service_timer.stop()
            QApplication.instance().removeEventFilter(self)
            e.accept()

    def build_dashboard(self):
        l=self.page('dashboard','Tu negocio, de un vistazo','Ventas netas vigentes del periodo. La ganancia es estimada; no incluye gastos ni impuestos.')
        self.dash_dates=self.dates(l,self.refresh_dashboard);r=QHBoxLayout();self.metrics=[]
        for title in ['Ventas','Ganancia estimada','Tickets','Stock bajo']:
            c=QFrame();c.setObjectName('card');v=QVBoxLayout(c);v.addWidget(label(title,'muted'));m=label('—','metric');v.addWidget(m);r.addWidget(c);self.metrics.append(m)
        l.addLayout(r);l.addWidget(label('Rotación ABC · unidades vendidas · A: primer 80%, B: siguiente 15%, C: resto','muted'))
        self.abc=Table([('Producto','nombre'),('Unidades','unidades'),('Clase','clase')]);l.addWidget(self.abc,2)
        self.low=Table([('Reponer','nombre'),('Existencia','existencia'),('Punto de reorden','punto_reorden')]);l.addWidget(self.low,1)
        l.addWidget(label('Envía el reporte del periodo o configura el envío automático al cerrar turno en Conexiones / equipo.','muted'))
        self.bar(l,[('Exportar ABC a Excel',lambda:self.export(self.abc,'rotacion_abc'))])
    def refresh_dashboard(self):
        a,z=self.range(self.dash_dates)
        def show(d):
            for w,t in zip(self.metrics,[money(d['ventas']),money(d['ganancia']),str(d['tickets']),str(len(d['bajos']))]):w.setText(t)
            self.abc.fill(d['abc']);self.low.fill(d['bajos'])
        self.run(lambda:self.repo.dashboard(a,z),show)

    def build_catalog(self):
        l=self.page('catalog','Catálogo y mayoreo','Busca un artículo para consultar o editar su precio. Desactivarlo evita nuevas ventas y conserva su historial.')
        self.search=QLineEdit();self.search.setPlaceholderText('Buscar nombre, código o código de barras');self.search.returnPressed.connect(self.refresh_catalog)
        l.addWidget(self.search);self.bar(l,[('Buscar',self.refresh_catalog),('+ Nuevo artículo',lambda:self.product_form()),('Editar seleccionado',lambda:self.product_form(self.catalog.selected())),('Insumos del servicio',self.material_form)])
        self.catalog=Table([('Código','codigo'),('Artículo','nombre'),('Tipo','tipo'),('Precio','precio_venta_centavos',money),('Stock','existencia'),('Mayoreo desde','mayoreo_desde'),('Activo','activo',lambda x:'Sí' if x else 'No')]);self.catalog.empty.setText('Tu catálogo empieza aquí\nPulsa + Nuevo artículo para registrar productos y servicios.');self.catalog.doubleClicked.connect(lambda _:self.safe(lambda:self.product_form(self.catalog.selected())));l.addWidget(self.catalog)
    def refresh_catalog(self):
        search=self.search.text().strip();self.run(lambda:self.repo.products(search),self.catalog.fill)
    def product_form(self,p=None):
        p=p or {};fields={
         'codigo':('Código interno',QLineEdit(p.get('codigo',''))),'codigo_barras':('Código de barras',QLineEdit(p.get('codigo_barras') or '')),
         'nombre':('Nombre',QLineEdit(p.get('nombre',''))),'tipo':('Tipo',combo([(x,x) for x in ['PRODUCTO','SERVICIO']],p.get('tipo'))),
         'unidad':('Unidad',combo([(x,x) for x in ['PIEZA','HOJA','HORA','METRO','PAQUETE']],p.get('unidad'))),
         'precio':('Precio menudeo $',number(Decimal(p.get('precio_venta_centavos',0))/100)),
         'costo':('Costo unitario $',number(Decimal(p.get('costo_referencia_centavos',0))/100)),
         'controla_stock':('Controlar stock',check(p.get('controla_stock',True))),
         'punto_reorden':('Punto de reorden',number(p.get('punto_reorden',0),3)), 'activo':('Activo',check(p.get('activo',True))),
         'mayoreo':('Activar mayoreo',check(bool(p.get('mayoreo_desde')))),
         'mayoreo_desde':('A partir de unidades',number(p.get('mayoreo_desde') or 50,3)),
         'mayoreo_precio':('Precio unitario mayoreo $',number(Decimal(p.get('mayoreo_precio') or 0)/100))}
        if p:
            for k in ['tipo','unidad','controla_stock']:fields[k][1].setEnabled(False)
            if p.get('controla_stock') and p.get('existencia',0)>0:fields['costo'][1].setEnabled(False)
        d=Form(self,'Editar artículo' if p else 'Nuevo artículo',fields,'El inventario se recibe desde Inventario. Servicios: sus materiales se configuran con «Insumos del servicio».');d.resize(560,680)
        if d.exec():self.mutate(self.repo.save_product,(d.data(),p.get('id')),self.refresh_catalog)
    def material_form(self):
        s=self.catalog.selected()
        if s['tipo']!='SERVICIO':raise BusinessError('Selecciona un servicio.')
        def show(data):
            products,mats=data
            fields={'pid':('Material',combo([(p['nombre'],p['id']) for p in products if p['controla_stock'] and p['activo']])), 'qty':('Consumo por servicio',number(1,3)), 'active':('Activo',check())}
            text='Configurados: '+('; '.join(f'{m["nombre"]}: {m["cantidad_por_servicio"]}' for m in mats) or 'ninguno')+'. Selecciona un material para agregarlo, actualizarlo o desactivarlo.'
            d=Form(self,'Insumos · '+s['nombre'],fields,text)
            if d.exec():
                v=d.data()
                if v['pid'] is None:raise BusinessError('Crea primero un producto con control de stock.')
                self.mutate(self.repo.save_material,(s['id'],v['pid'],v['qty'],v['active']),self.refresh_catalog)
        self.run(lambda:(self.repo.products(),self.repo.materials(s['id'])),show)

    def build_inventory(self):
        l=self.page('inventory','Inventario físico','Recepción de mercancía, costo promedio y conteos con motivo obligatorio.')
        self.bar(l,[('Actualizar',self.refresh_inventory),('Recibir mercancía',lambda:self.stock_form('ENTRADA',self.inventory_table.selected())),('Conteo físico',lambda:self.stock_form('CONTEO',self.inventory_table.selected())),('Exportar Excel',lambda:self.export(self.inventory_table,'inventario'))])
        self.inventory_search=QLineEdit();self.inventory_search.setPlaceholderText('Buscar producto por nombre, código o código de barras…');self.inventory_search.setClearButtonEnabled(True);self.inventory_search.textChanged.connect(self.filter_inventory);l.addWidget(self.inventory_search)
        self.inventory_table=Table([('Código','codigo'),('Producto','nombre'),('Existencia','existencia'),('Costo promedio','costo_referencia_centavos',money),('Reorden','punto_reorden')]);l.addWidget(self.inventory_table,2)
        l.addWidget(label('Últimos 500 movimientos','muted'));self.inventory_log=Table([('Fecha','creado_en'),('Producto','nombre'),('Tipo','tipo'),('Cantidad','cantidad'),('Motivo','motivo')]);l.addWidget(self.inventory_log,1)
    def refresh_inventory(self):
        def show(d):
            self.inventory_rows=[p for p in d[0] if p['controla_stock'] and p['activo']];self.filter_inventory();self.inventory_log.fill(d[1])
        self.run(lambda:(self.repo.products(),self.repo.inventory_history()),show)
    def filter_inventory(self):
        import unicodedata
        def norm(value):return ''.join(c for c in unicodedata.normalize('NFD',str(value or '').casefold()) if unicodedata.category(c)!='Mn')
        q=norm(self.inventory_search.text()).strip()
        self.inventory_table.fill([p for p in getattr(self,'inventory_rows',[]) if not q or any(q in norm(p.get(k)) for k in ('nombre','codigo','codigo_barras'))])
    def stock_form(self,kind,p,refresh=None):
        fields={'qty':('Cantidad contada' if kind=='CONTEO' else 'Cantidad',number(p['existencia'] if kind=='CONTEO' else 1,3)), 'reason':('Motivo',QLineEdit())}
        if kind=='ENTRADA':fields.update({'cost':('Costo unitario de compra $',number(Decimal(p['costo_referencia_centavos'])/100)), 'provider':('Proveedor',QLineEdit()),'reference':('Folio / referencia',QLineEdit())})
        d=Form(self,kind.replace('_',' ')+' · '+p['nombre'],fields,'Stock actual: '+str(p['existencia'])+'. La operación queda en la bitácora.')
        if d.exec():
            v=d.data();kw={'expected':str(p['existencia'])}
            for k in ['cost','provider','reference']:
                if k in v:kw[k]=v[k]
            self.mutate(self.repo.inventory,(p['id'],kind,v['qty'],v['reason']),refresh or self.refresh_inventory,kw)

    def build_users(self):
        l=self.page('users','Usuarios y permisos','Contraseñas protegidas con Argon2. Los usuarios inactivos conservan su historial.')
        self.bar(l,[('Actualizar',self.refresh_users),('+ Nuevo usuario',lambda:self.user_form()),('Editar / contraseña',lambda:self.user_form(self.users_table.selected()))])
        self.users_table=Table([('ID','id'),('Nombre','nombre'),('Usuario','usuario'),('Rol','rol'),('Activo','activo',lambda x:'Sí' if x else 'No')]);self.users_table.doubleClicked.connect(lambda _:self.safe(lambda:self.user_form(self.users_table.selected())));l.addWidget(self.users_table)
    def refresh_users(self):self.run(self.repo.users,self.users_table.fill)
    def user_form(self,u=None):
        u=u or {};pwd=QLineEdit();pwd.setEchoMode(QLineEdit.EchoMode.Password)
        d=Form(self,'Editar usuario' if u else 'Nuevo usuario',{'nombre':('Nombre',QLineEdit(u.get('nombre',''))),'usuario':('Usuario',QLineEdit(u.get('usuario',''))),'rol':('Rol',combo([(x,x) for x in ['CAJERO','ADMINISTRADOR']],u.get('rol'))),'activo':('Activo',check(u.get('activo',True))),'password':('Nueva contraseña',pwd)},'Mínimo 12 caracteres. Al editar, déjala vacía para conservar la contraseña.')
        if d.exec():self.mutate(self.repo.save_user,(d.data(),u.get('id')),self.refresh_users)

    def build_cash(self):
        l=self.page('cash','Caja y movimientos','El fondo y los retiros modifican el efectivo esperado; no cambian las ventas.')
        self.turn_label=label('Sin consultar','metric');l.addWidget(self.turn_label)
        self.bar(l,[('Actualizar',self.refresh_cash),('Abrir mi turno',self.open_turn_form),('Entrada de efectivo',lambda:self.cash_form('ENTRADA')),('Retiro de efectivo',lambda:self.cash_form('RETIRO')),('Exportar Excel',lambda:self.export(self.cash_table,'movimientos_caja'))])
        self.cash_table=Table([('Fecha','creado_en'),('Turno','turno_id'),('Tipo','tipo'),('Importe','importe_centavos',money),('Motivo','motivo'),('Responsable','responsable')]);l.addWidget(self.cash_table)
    def set_turns(self,turns):self.turn_rows=turns;self.own_turn=next((t for t in turns if t['usuario_id']==self.user['id']),None)
    def refresh_cash(self):
        def show(d):
            self.set_turns(d[0]);self.turn_label.setText('Mi turno: #'+str(self.own_turn['id'])+' · '+self.own_turn['caja'] if self.own_turn else 'No tienes un turno abierto');self.cash_table.fill(d[1])
        self.run(lambda:(self.repo.turns(),self.repo.cash_history()),show)
    def open_turn_form(self):
        def show(boxes):
            if not boxes:raise BusinessError('No hay cajas activas. Crea una caja en la base de datos antes de abrir turno.')
            d=Form(self,'Abrir turno',{'box':('Caja',combo([(b['nombre'],b['id']) for b in boxes])),'amount':('Fondo inicial $',number())})
            if d.exec():v=d.data();self.mutate(self.repo.open_turn,(v['box'],v['amount']),self.refresh_cash)
        self.run(self.repo.boxes,show)
    def cash_form(self,kind):
        if not self.turn_rows:raise BusinessError('Abre un turno primero.')
        d=Form(self,kind.title()+' de efectivo',{'tid':('Turno',combo([(f'#{t["id"]} · {t["cajero"]} · {t["caja"]}',t['id']) for t in self.turn_rows])),'amount':('Importe $',number()),'reason':('Motivo',QLineEdit()),'reference':('Referencia',QLineEdit())})
        if d.exec():v=d.data();self.mutate(self.repo.cash_move,(v['tid'],kind,v['amount'],v['reason'],v['reference']),self.refresh_cash)

    def build_closings(self):
        l=self.page('closings','Auditoría de cierres','Rojo: faltante · ámbar: sobrante · verde: caja cuadrada. El registro original no se modifica.')
        self.closing_dates=self.dates(l,self.refresh_closings);self.cashier_filter=QComboBox();self.cashier_filter.addItem('Todos los cajeros',None);l.addWidget(self.cashier_filter)
        self.bar(l,[('Consultar',self.refresh_closings),('Detalle y revisión',self.review_form),('Exportar Excel',lambda:self.export(self.closings_table,'cierres')),('Vista de impresión',lambda:self.print_table(self.closings_table,'Auditoría de cierres'))])
        self.closings_table=Table([('ID','id'),('Fecha','creado_en'),('Cajero','cajero'),('Contado','efectivo_contado_centavos',money),('Esperado','efectivo_esperado_centavos',money),('Diferencia','diferencia_centavos',money),('Revisión','observaciones_revision')]);l.addWidget(self.closings_table)
    def refresh_closings(self):
        a,z=self.range(self.closing_dates);uid=self.cashier_filter.currentData()
        def show(d):
            self.closings_table.fill(d[0]);self.cashier_filter.clear();self.cashier_filter.addItem('Todos los cajeros',None)
            for u in d[1]:self.cashier_filter.addItem(u['nombre'],u['id'])
            i=self.cashier_filter.findData(uid);self.cashier_filter.setCurrentIndex(max(i,0))
        self.run(lambda:(self.repo.closings(a,z,uid),self.repo.users()),show)
    def review_form(self):
        a=self.closings_table.selected()
        def show(rows):
            detail='\n'.join(f'{r["tipo"]} {money(r["denominacion_centavos"])} × {r["cantidad"]} = {money(r["subtotal_centavos"])}' for r in rows)
            d=Form(self,'Revisar cierre #'+str(a['id']),{'note':('Nota del administrador',QLineEdit(a.get('observaciones_revision') or ''))},detail+'\nNota del cajero: '+str(a.get('observaciones_cajero') or 'Sin nota'))
            if d.exec():self.mutate(self.repo.review_closing,(a['id'],d.data()['note']),self.refresh_closings)
        self.run(lambda:self.repo.closing_detail(a['id']),show)

    def build_pos(self):
        l=self.page('pos','Punto de venta','1. Escanea o busca un artículo.  2. Indica la cantidad y agrégalo.  3. Revisa el total y pulsa Cobrar.')
        self.pos_turn=label('','muted');l.addWidget(self.pos_turn)
        row=QHBoxLayout();self.barcode=QLineEdit();self.barcode.setPlaceholderText('Código de barras / código interno');self.barcode.returnPressed.connect(lambda:self.safe(self.scan));row.addWidget(self.barcode,2)
        self.product_pick=QComboBox();self.product_pick.setEditable(True);self.product_pick.setInsertPolicy(QComboBox.InsertPolicy.NoInsert);self.product_pick.completer().setFilterMode(Qt.MatchFlag.MatchContains);self.product_pick.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive);row.addWidget(self.product_pick,3);row.addWidget(label('Cantidad'));self.pos_qty=number(1,3);self.pos_qty.setMaximumWidth(110);row.addWidget(self.pos_qty);row.addWidget(button('Agregar',lambda:self.safe(self.add_selected)));l.addLayout(row)
        self.services_bar=QHBoxLayout();l.addLayout(self.services_bar)
        self.cart_table=Table([('Artículo','nombre'),('Cantidad','cantidad'),('Precio','precio',money),('Mayoreo','mayoreo',lambda x:'Aplicado' if x else '—'),('Importe','subtotal',money)]);self.cart_table.empty.setText('Listo para tu primera venta\nEscanea un código o selecciona un artículo y pulsa Agregar.');l.addWidget(self.cart_table)
        self.total_label=label('Total  $0.00','metric');l.addWidget(self.total_label)
        self.bar(l,[('Actualizar catálogo',self.refresh_pos),('Quitar artículo',self.remove_item),('Vaciar venta',self.empty_cart),('Cobrar · F6',self.pay_form)])
        s=QShortcut(QKeySequence('F6'),self);s.activated.connect(lambda:self.safe(self.pay_form) if self.current=='pos' and not self.busy and not QApplication.activeModalWidget() else None)
    def refresh_pos(self):
        def show(d):
            self.products_rows=[p for p in d[0] if p['activo']];self.set_turns(d[1]);self.product_pick.clear()
            for p in self.products_rows:self.product_pick.addItem(p['nombre']+' · '+money(p['precio_venta_centavos']),p['id'])
            while self.services_bar.count():
                it=self.services_bar.takeAt(0)
                if it.widget():it.widget().deleteLater()
            for p in [p for p in self.products_rows if p['tipo']=='SERVICIO'][:4]:self.services_bar.addWidget(button(p['nombre'],lambda pid=p['id']:self.safe(lambda:self.add_product(pid))))
            self.services_bar.addStretch();self.pos_turn.setText('Turno #'+str(self.own_turn['id'])+' abierto' if self.own_turn else 'Abre tu turno en Caja para cobrar.');self.barcode.setFocus()
            if self.cart:self.requote()
        self.run(lambda:(self.repo.products(),self.repo.turns()),show)
    def scan(self):
        code=self.barcode.text().strip();matches=[p for p in self.products_rows if code and code in (p['codigo'],p.get('codigo_barras'))]
        if len(matches)!=1:raise BusinessError('Código no encontrado o ambiguo. Actualiza el catálogo o selecciona el producto.')
        self.add_product(matches[0]['id']);self.barcode.clear()
    def add_selected(self):
        idx=self.product_pick.findText(self.product_pick.currentText())
        if idx<0:raise BusinessError('Selecciona una coincidencia de la lista antes de agregarla.')
        pid=self.product_pick.itemData(idx)
        if pid is None:raise BusinessError('No hay artículos disponibles. Solicita al administrador revisar el catálogo.')
        self.add_product(pid)
    def add_product(self,pid):
        qty=Decimal(str(self.pos_qty.value()))
        if qty<=0:raise BusinessError('La cantidad debe ser mayor que cero.')
        pending=dict(self.cart);pending[pid]=pending.get(pid,Decimal(0))+qty;self.requote(pending)
    def requote(self,pending=None):
        target=dict(self.cart if pending is None else pending)
        if not target:self.cart={};self.quote_rows=[];self.cart_table.fill([]);self.total_label.setText('Total  $0.00');return
        def show(rows):self.cart=target;self.quote_rows=rows;self.cart_table.fill(rows);self.total_label.setText('Total  '+money(sum(r['subtotal'] for r in rows)));self.barcode.setFocus()
        self.run(lambda:self.repo.quote(list(target.items())),show)
    def remove_item(self):
        r=self.cart_table.selected();p=dict(self.cart);p.pop(r['id'],None);self.requote(p)
    def empty_cart(self):
        if not self.cart or QMessageBox.question(self,'Vaciar carrito','¿Descartar el carrito sin cobrar?')==QMessageBox.StandardButton.Yes:self.requote({})
    def pay_form(self):
        from .payment_ui import PaymentDialog
        if self.busy:return
        if getattr(self,'db_ok',None) is False:raise BusinessError('No se puede cobrar: revisa la conexión con la base local.')
        if not self.own_turn:raise BusinessError('Primero abre tu turno en Caja o Mi turno.')
        if not self.quote_rows:raise BusinessError('Agrega al menos un artículo a la venta.')
        total=sum(r['subtotal'] for r in self.quote_rows);d=PaymentDialog(self,total)
        if not d.exec():return
        v=d.data();items=list(self.cart.items());tid=self.own_turn['id'];req=str(uuid4())
        def done(r):
            self.requote({});QMessageBox.information(self,'Venta cobrada',f'Ticket #{r["id"]}\nCambio a entregar: {money(r["cambio"])}');self.ticket_preview(r['id'])
        self.run(lambda:self.repo.charge(tid,items,v['cash'],v['card'],v['received'],v['reference'],total,req),done,True)

    def build_sales(self):
        l=self.page('sales','Historial de ventas','Consulta, reimpresión y cancelación completa con registro de reembolso.')
        self.sales_dates=self.dates(l,self.refresh_sales)
        self.bar(l,[('Ver / imprimir ticket',lambda:self.ticket_preview(self.sales_table.selected()['id'])),('Cancelar venta',lambda:self.cancel_form(self.sales_table.selected()['id'])),('Exportar Excel',lambda:self.export(self.sales_table,'ventas'))])
        self.sales_table=Table([('Ticket','id'),('Fecha','cobrado_en'),('Cajero','cajero'),('Estado','estado'),('Pago','metodo'),('Total','total_centavos',money)]);l.addWidget(self.sales_table,2)
        l.addWidget(label('Solicitudes pendientes de cancelación','muted'));self.requests_table=Table([('Solicitud','id'),('Ticket','venta_id'),('Solicitante','solicitante'),('Motivo','motivo')]);l.addWidget(self.requests_table,1)
        self.bar(l,[('Aprobar solicitud',lambda:self.cancel_form(self.requests_table.selected()['venta_id'])),('Rechazar solicitud',self.reject_form)])
    def refresh_sales(self):
        a,z=self.range(self.sales_dates)
        def show(d):self.sales_table.fill(d[0]);self.requests_table.fill(d[1]);self.set_turns(d[2])
        self.run(lambda:(self.repo.sales(a,z),self.repo.requests(),self.repo.turns()),show)
    def cancel_form(self,vid):
        if not self.turn_rows:raise BusinessError('Se necesita un turno abierto para registrar el reembolso.')
        d=Form(self,'Cancelar ticket #'+str(vid),{'tid':('Turno que reembolsa',combo([(f'#{t["id"]} · {t["cajero"]}',t['id']) for t in self.turn_rows])),'reason':('Motivo',QLineEdit()),'goods':('Productos recibidos físicamente',check(False)),'ref':('Folio devolución tarjeta',QLineEdit())},'Se cancelará el ticket completo. Devuelve el dinero por el mismo medio de pago. Marca productos recibidos solo si regresan al estante; los insumos de servicios no se recuperan. La devolución bancaria se realiza fuera de KALA.')
        if d.exec():
            v=d.data()
            if QMessageBox.question(self,'Confirmar cancelación','¿Confirmas la cancelación y el reembolso completo de este ticket?')==QMessageBox.StandardButton.Yes:self.mutate(self.repo.cancel_sale,(vid,v['tid'],v['reason'],v['goods'],v['ref']),self.refresh_sales)
    def reject_form(self):
        r=self.requests_table.selected();note,ok=QInputDialog.getText(self,'Rechazar solicitud','Justificación')
        if ok:self.mutate(self.repo.reject_request,(r['id'],note),self.refresh_sales)
    def ticket_preview(self,vid):
        def show(d):
            v=d['venta'];parts=['<h2>Papelería KALA</h2>',f'<p>Ticket #{vid}<br>{html.escape(str(v["cobrado_en"]))}<br>{html.escape(v["cajero"])}<br>{html.escape(v["estado"])}</p>','<hr>']
            for r in d['detalle']:parts.append(f'<p>{html.escape(r["nombre_producto"])}<br>{r["cantidad"]} × {money(r["precio_unitario_centavos"])} = {money(r["subtotal_centavos"])}</p>')
            parts.append('<hr><h3>Total '+money(v['total_centavos'])+'</h3>')
            for p in d['pagos']:parts.append('<p>'+p['metodo']+': '+money(p['importe_centavos'])+(' · Cambio '+money(p['cambio_centavos']) if p['metodo']=='EFECTIVO' else '')+'</p>')
            for p in d['pagos']:
                reference=p.get('referencia_terminal') or ''
                if reference:parts.append('<p>Referencia: '+html.escape(reference)+('</p><p><b>TERMINAL SIMULADA · Sin cobro bancario real</b>' if reference.startswith('SIM-') else '')+'</p>')
            parts.append('<p>Comprobante de compra · No es factura fiscal.</p>');self.show_document(''.join(parts),True,len(d['detalle']),'Ticket #'+str(vid))
        self.run(lambda:self.repo.ticket(vid),show)

    def build_count(self):
        l=self.page('count','Arqueo ciego de caja','Cuenta el dinero físico por denominación. El efectivo esperado se muestra únicamente en la auditoría después del cierre.')
        self.count_turn=label('','metric');l.addWidget(self.count_turn);self.denoms=[];grid=QGridLayout()
        for i,(kind,value) in enumerate([('BILLETE',100000),('BILLETE',50000),('BILLETE',20000),('BILLETE',10000),('BILLETE',5000),('BILLETE',2000),('MONEDA',2000),('MONEDA',1000),('MONEDA',500),('MONEDA',200),('MONEDA',100),('MONEDA',50),('MONEDA',20),('MONEDA',10)]):
            n=QSpinBox();n.setRange(0,999999);n.valueChanged.connect(self.count_total);self.denoms.append((kind,value,n));row=i%7;col=(i//7)*2;grid.addWidget(label(kind.title()+' '+money(value)),row,col);grid.addWidget(n,row,col+1)
        l.addLayout(grid);self.count_amount=label('Contado: $0.00','metric');l.addWidget(self.count_amount);self.count_note=QLineEdit();self.count_note.setPlaceholderText('Observaciones del conteo');l.addWidget(self.count_note)
        self.bar(l,[('Actualizar turno',self.refresh_count),('Registrar y cerrar mi turno',self.close_form)]);l.addStretch()
    def count_total(self):
        if hasattr(self,'count_amount'):self.count_amount.setText('Contado: '+money(sum(v*w.value() for k,v,w in self.denoms)))
    def refresh_count(self):
        def show(rows):self.set_turns(rows);self.count_turn.setText('Mi turno #'+str(self.own_turn['id']) if self.own_turn else 'No tienes un turno abierto')
        self.run(self.repo.turns,show)
    def close_form(self):
        if not self.own_turn:raise BusinessError('No tienes un turno abierto.')
        if self.cart:raise BusinessError('Cobra o vacía el carrito antes de cerrar tu turno.')
        if QMessageBox.question(self,'Cerrar turno','¿Terminaste de contar? El turno quedará cerrado y este conteo no se podrá editar.')!=QMessageBox.StandardButton.Yes:return
        tid=self.own_turn['id'];values=[(k,v,w.value()) for k,v,w in self.denoms]
        def done():
            for k,v,w in self.denoms:w.setValue(0)
            self.count_note.clear();self.refresh_count();QTimer.singleShot(300,self.start_services)
        self.mutate(self.repo.close_turn,(tid,values,self.count_note.text()),done)

    def build_waste(self):
        l=self.page('waste','Mermas y uso interno','Registra el material realmente consumido: por ejemplo, hojas y tinta de una copia fallida.')
        self.bar(l,[('Actualizar',self.refresh_waste),('Registrar merma',lambda:self.stock_form('MERMA',self.waste_table.selected(),self.refresh_waste)),('Registrar uso interno',lambda:self.stock_form('USO_INTERNO',self.waste_table.selected(),self.refresh_waste))])
        self.waste_table=Table([('Código','codigo'),('Material / producto','nombre'),('Disponible','existencia'),('Unidad','unidad')]);l.addWidget(self.waste_table)
    def refresh_waste(self):self.run(self.repo.products,lambda rows:self.waste_table.fill([p for p in rows if p['activo'] and p['controla_stock']]))
    def build_audit(self):
        l=self.page('audit','Bitácora de operaciones','Últimas 500 operaciones registradas. La interfaz no permite borrar el historial.')
        self.bar(l,[('Actualizar',self.refresh_audit),('Exportar Excel',lambda:self.export(self.audit_table,'bitacora'))])
        self.audit_table=Table([('Fecha','creado_en'),('Usuario','usuario'),('Acción','accion'),('Entidad','entidad'),('Registro','registro_id'),('Descripción','descripcion')]);l.addWidget(self.audit_table)
    def refresh_audit(self):self.run(self.repo.audit_history,self.audit_table.fill)

    def export(self,table,name):
        if not table.rows:raise BusinessError('No hay datos para exportar.')
        path,_=QFileDialog.getSaveFileName(self,'Guardar Excel',name+'.xlsx','Excel (*.xlsx)')
        if not path:return
        from openpyxl import Workbook
        from openpyxl.styles import Font,PatternFill
        wb=Workbook();ws=wb.active;ws.title='KALA'
        for j,col in enumerate(table.columns,1):ws.cell(1,j,col[0]);ws.cell(1,j).font=Font(bold=True,color='FFFFFF');ws.cell(1,j).fill=PatternFill('solid',fgColor='1C645C')
        for i in range(table.rowCount()):
            for j in range(table.columnCount()):
                c=ws.cell(i+2,j+1,table.item(i,j).text());c.data_type='s' # evita interpretar texto ingresado como fórmulas
        ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
        for col in ws.columns:ws.column_dimensions[col[0].column_letter].width=min(60,max(16,max(len(str(c.value or '')) for c in col)+2))
        try:wb.save(path)
        except OSError:raise BusinessError('No se pudo guardar. Cierra el archivo si está abierto y revisa la carpeta.')
        QMessageBox.information(self,'Exportación','Archivo guardado.')
    def print_table(self,table,title):
        head=''.join('<th>'+html.escape(c[0])+'</th>' for c in table.columns)
        rows=''.join('<tr>'+''.join('<td>'+html.escape(table.item(i,j).text())+'</td>' for j in range(table.columnCount()))+'</tr>' for i in range(table.rowCount()))
        self.show_document('<h2>Papelería KALA · '+html.escape(title)+'</h2><table border="1" cellspacing="0" cellpadding="4"><tr>'+head+'</tr>'+rows+'</table>')
    def print_html(self,body,thermal=False,lines=0):
        doc=QTextDocument();doc.setHtml('<html><body style="font-family:Arial;font-size:'+('9' if thermal else '10')+'pt">'+body+'</body></html>')
        printer=QPrinter(QPrinter.PrinterMode.HighResolution)
        if thermal:
            printer.setPageSize(QPageSize(QSizeF(58,max(130,90+lines*15)),QPageSize.Unit.Millimeter,'Ticket 58mm'))
            printer.setFullPage(True);doc.setDocumentMargin(10)
        if not QPrinterInfo.availablePrinters():raise BusinessError('No hay una impresora instalada. Conéctala y configúrala en Windows, o utiliza Guardar PDF.')
        dialog=QPrintPreviewDialog(printer,self);dialog.setWindowTitle('Imprimir comprobante · 58 mm' if thermal else 'Imprimir reporte');dialog.resize(800,700)
        def render(device):
            try:self.render_document(doc,device)
            except Exception as exc:
                dialog.reject();self.report_ui_error(exc)
        dialog.paintRequested.connect(render);dialog.exec()
    def save_pdf(self,body,thermal=False,lines=0):
        path,_=QFileDialog.getSaveFileName(self,'Guardar comprobante en PDF','KALA_ticket.pdf' if thermal else 'KALA_reporte.pdf','PDF (*.pdf)')
        if not path:return
        if not path.lower().endswith('.pdf'):path+='.pdf'
        doc=QTextDocument();doc.setHtml('<html><body style="font-family:Arial;font-size:10pt">'+body+'</body></html>')
        printer=QPrinter(QPrinter.PrinterMode.HighResolution)
        if thermal:
            printer.setPageSize(QPageSize(QSizeF(58,max(130,90+lines*15)),QPageSize.Unit.Millimeter,'Ticket 58mm'));printer.setFullPage(True);doc.setDocumentMargin(10)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat);printer.setOutputFileName(path);self.render_document(doc,printer)
        if not Path(path).is_file() or not Path(path).stat().st_size:raise BusinessError('No se pudo guardar el PDF. Revisa la carpeta elegida.')
        QMessageBox.information(self,'Comprobante guardado','Tu PDF está en:\n'+path)

    @staticmethod
    def render_document(doc,printer):
        method=getattr(doc,'print',None) or getattr(doc,'print_',None)
        if method is None:raise BusinessError('La versión de Qt no ofrece impresión de documentos.')
        method(printer)
