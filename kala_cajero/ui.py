import time
from PyQt6.QtCore import QTimer, pyqtSignal, Qt, QEvent
from PyQt6.QtGui import QKeySequence, QShortcut, QPainter, QColor
from PyQt6.QtWidgets import (QApplication,QMainWindow,QVBoxLayout,QHBoxLayout,QFrame,QStackedWidget,
                            QLineEdit,QMessageBox,QComboBox,QAbstractSpinBox,QTextEdit,QPlainTextEdit)
from kala_admin.ui import AdminWindow, Background, STYLE, Table, Form, label, button, combo, check
from kala_admin.integration_ui import IntegrationUI
from kala_admin.repository import BusinessError, money
from kala_admin.services import DEFAULTS,status_text
from .repository import CashierRepository
from .automatic import AutomaticServices


class CashierBackground(Background):
    def paintEvent(self,event):
        super().paintEvent(event)
        # La imagen compartida contiene insignias de administrador en la cabecera.
        painter=QPainter(self)
        painter.fillRect(0,0,self.width(),72,QColor('#fffcf3'))


class CashierWindow(QMainWindow):
    logged_out = pyqtSignal()

    # Compartir únicamente componentes operativos. No hereda AdminWindow ni sus menús.
    run = AdminWindow.run
    safe = AdminWindow.safe
    mutate = AdminWindow.mutate
    page = AdminWindow.page
    bar = AdminWindow.bar
    dates = AdminWindow.dates
    range = AdminWindow.range
    set_turns = AdminWindow.set_turns
    open_turn_form = AdminWindow.open_turn_form
    build_pos = AdminWindow.build_pos
    scan = AdminWindow.scan
    add_product = AdminWindow.add_product
    requote = AdminWindow.requote
    remove_item = AdminWindow.remove_item
    empty_cart = AdminWindow.empty_cart
    pay_form = AdminWindow.pay_form
    ticket_preview = AdminWindow.ticket_preview
    build_count = AdminWindow.build_count
    count_total = AdminWindow.count_total
    refresh_count = AdminWindow.refresh_count
    save_pdf = AdminWindow.save_pdf
    print_html = AdminWindow.print_html
    render_document = staticmethod(AdminWindow.render_document)
    render_status = IntegrationUI.render_status
    run_background = IntegrationUI.run_background
    report_ui_error = IntegrationUI.report_ui_error
    show_document = IntegrationUI.show_document

    def __init__(self,config,user,repo=None,services=None):
        super().__init__()
        self.user=dict(user);self.repo=repo or CashierRepository(config,user)
        self._services=services or AutomaticServices(config,user)
        self.worker=None;self.busy=False;self.integration_worker=None;self.integration_busy=False
        self.cart={};self.quote_rows=[];self.own_turn=None;self.turn_rows=[];self.products_rows=[]
        self.pages={};self.nav_buttons={};self.settings=dict(DEFAULTS)
        self.db_ok=None;self.delivered=None;self.reachable=False;self.jobs_cache=[]
        self.integration_detail='Comprobando la base local…';self.scanner_state='Captura por código disponible'
        self.next_backup=time.monotonic()+60;self._closing=False;self._settings_ready=False
        self.setWindowTitle('Papelería KALA · Caja');self.resize(1280,800);self.setMinimumSize(1080,720)
        self.setStyleSheet(STYLE)
        root=CashierBackground();self.setCentralWidget(root);outer=QVBoxLayout(root);outer.setContentsMargins(22,18,22,18)
        top=QHBoxLayout();top.addWidget(label('KALA · Mostrador','title'));top.addStretch()
        top.addWidget(label(user['nombre']+' · Cajero'));top.addWidget(button('Cerrar sesión',self.logout));outer.addLayout(top)
        outer.addSpacing(24);row=QHBoxLayout();row.setSpacing(18);outer.addLayout(row,1)
        nav=QFrame();nav.setObjectName('nav');nav.setFixedWidth(200);n=QVBoxLayout(nav);n.setContentsMargins(14,20,14,18)
        n.addWidget(label('MI JORNADA'));n.addSpacing(15);row.addWidget(nav)
        self.stack=QStackedWidget();row.addWidget(self.stack,1)
        for key,title,shortcut in [('cash','Mi turno','F2'),('pos','Punto de venta','F1'),('sales','Mis tickets','F9'),('count','Cerrar turno','F7')]:
            b=button(title+'  '+shortcut,lambda k=key:self.navigate(k));b.setCheckable(True);n.addWidget(b);self.nav_buttons[key]=b
            s=QShortcut(QKeySequence(shortcut),self);s.activated.connect(lambda k=key:self.navigate(k) if not QApplication.activeModalWidget() else None)
        n.addStretch();self.system_hint=label('');n.addWidget(self.system_hint)
        self.state=label('','muted');self.state_details=label('','muted')
        status=QHBoxLayout();status.addWidget(self.state);status.addWidget(self.state_details,1)
        status.addWidget(button('Atajos · Tab / F12',self.show_shortcuts));outer.addLayout(status)
        self.build_cash();self.build_pos();self.build_sales();self.build_count()
        self.product_pick.setEditable(True);self.product_pick.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.product_pick.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.product_pick.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.product_pick.setToolTip('Escribe parte del nombre y selecciona una coincidencia.')
        QShortcut(QKeySequence('F12'),self).activated.connect(self.show_shortcuts)
        QApplication.instance().installEventFilter(self)
        self.service_timer=QTimer(self);self.service_timer.setInterval(30000)
        self.service_timer.timeout.connect(self.start_services);self.service_timer.start()
        QTimer.singleShot(500,self.start_services)
        self.navigate('cash');self.render_status()

    def navigate(self,key):
        if self.busy or self._closing:return
        if key not in self.pages:
            self.safe(lambda: self._denied());return
        self.stack.setCurrentWidget(self.pages[key]);self.current=key
        for k,b in self.nav_buttons.items():b.setChecked(k==key)
        self.safe(getattr(self,'refresh_'+key))

    @staticmethod
    def _denied():
        raise BusinessError('Esta función corresponde al administrador.')

    def build_cash(self):
        l=self.page('cash','Mi turno','1. Abre tu caja   ·   2. Registra tus ventas   ·   3. Cuenta el efectivo y cierra')
        self.turn_label=label('Consultando tu turno…','metric');l.addWidget(self.turn_label)
        l.addWidget(label('El fondo inicial es el dinero físico con el que empiezas. Si la caja está ocupada, solicita al administrador revisar el turno anterior.','muted'))
        self.bar(l,[('Actualizar',self.refresh_cash),('Abrir mi turno',self.open_turn_form),('Ir a vender · F1',lambda:self.navigate('pos'))])
        l.addWidget(label('Tus envíos recientes','title'))
        self.jobs_table=Table([('Documento','titulo'),('Estado','estado',status_text),('Fecha','creado_en')]);l.addWidget(self.jobs_table)
        l.addWidget(label('Por enviar: está en cola. Aceptado: lo recibió el proveedor. Entregado o leído: entrega confirmada. Si aparece un error, pide al administrador revisarlo antes de reenviar.','muted'))
        self.bar(l,[('Actualizar envíos',self.start_services),('Contar y cerrar · F7',lambda:self.navigate('count'))])

    def refresh_cash(self):
        def show(data):
            self.set_turns(data[0]);self.settings.update(data[2]);self._settings_ready=True
            self.turn_label.setText('Turno #'+str(self.own_turn['id'])+' · '+self.own_turn['caja'] if self.own_turn else 'Listo para abrir tu turno')
            self.jobs_table.fill(data[1])
        self.run(lambda:(self.repo.turns(),self.repo.jobs(),self.repo.ticket_settings()),show)

    def refresh_pos(self):
        def show(data):
            self.products_rows=data[0];self.set_turns(data[1]);self.settings.update(data[2]);self._settings_ready=True
            self.product_pick.clear()
            for p in self.products_rows:
                self.product_pick.addItem(p['nombre']+' · '+money(p['precio_venta_centavos']),p['id'])
            while self.services_bar.count():
                item=self.services_bar.takeAt(0)
                if item.widget():item.widget().deleteLater()
            self.services_bar.addStretch()
            self.pos_turn.setText('Turno #'+str(self.own_turn['id'])+' abierto' if self.own_turn else 'Primero abre tu turno en Mi turno · F2.')
            self.barcode.setFocus()
            if self.cart:self.requote()
        self.run(lambda:(self.repo.products(),self.repo.turns(),self.repo.ticket_settings()),show)

    def add_selected(self):
        # Un texto parcial no debe agregar silenciosamente el artículo seleccionado antes.
        text=self.product_pick.currentText();idx=self.product_pick.findText(text)
        if idx<0:raise BusinessError('Selecciona una coincidencia de la lista antes de agregar.')
        pid=self.product_pick.itemData(idx)
        if pid is None:raise BusinessError('No hay productos disponibles. Pide al administrador revisar el catálogo.')
        self.add_product(pid)

    def build_sales(self):
        l=self.page('sales','Mis tickets','Consulta únicamente tus ventas. Para cancelaciones o devoluciones, solicita al administrador.')
        self.sales_dates=self.dates(l,self.refresh_sales)
        self.bar(l,[('Ver ticket · imprimir / WhatsApp',lambda:self.ticket_preview(self.sales_table.selected()['id']))])
        self.sales_table=Table([('Ticket','id'),('Fecha','cobrado_en'),('Turno','turno_id'),('Estado','estado'),('Pago','metodo'),('Total','total_centavos',money)])
        l.addWidget(self.sales_table)

    def refresh_sales(self):
        a,z=self.range(self.sales_dates)
        def show(data):
            self.sales_table.fill(data[0]);self.settings.update(data[1]);self._settings_ready=True
        self.run(lambda:(self.repo.sales(a,z),self.repo.ticket_settings()),show)

    def send_document(self,title,body):
        # El cuerpo de la vista nunca se usa como autoridad: se reconstruye desde el ticket propio.
        import re
        match=re.fullmatch(r'Ticket #([0-9]+)',title)
        if not match:raise BusinessError('Solo se permite enviar un ticket propio.')
        vid=int(match[1])
        fields={'recipient':('Enviar a',combo([('Cliente','CLIENT'),('Dueño','OWNER')])),
                'phone':('WhatsApp del cliente (+país)',QLineEdit()),
                'consent':('El cliente autoriza recibir el ticket',check(False))}
        d=Form(self,'Enviar ticket #'+str(vid),fields,'El número del dueño y el servicio se configuran desde administración. El envío queda registrado.')
        if not d.exec():return
        v=d.data()
        def done():
            QMessageBox.information(self,'Ticket guardado en cola','Consulta el estado en Mi turno. Si no hay Internet se enviará cuando regrese la conexión y KALA esté abierto.')
            self.start_services()
        self.mutate(self.repo.queue_ticket,(vid,v['recipient'],v['phone'],v['consent']),done)

    def close_form(self):
        if not self.own_turn:raise BusinessError('No tienes un turno abierto.')
        if self.cart:raise BusinessError('Cobra o vacía el carrito antes de cerrar el turno.')
        if QMessageBox.question(self,'Cerrar mi turno','¿Terminaste de contar? El conteo quedará guardado y no podrá editarse.')!=QMessageBox.StandardButton.Yes:return
        tid=self.own_turn['id'];values=[(k,v,w.value()) for k,v,w in self.denoms]
        def done():
            for k,v,w in self.denoms:w.setValue(0)
            self.count_note.clear();self.refresh_count()
            QMessageBox.information(self,'Turno cerrado','Tu conteo quedó registrado. Si el aviso automático está activado, el resumen quedó en cola para el dueño. Consulta su estado en Mi turno.')
            QTimer.singleShot(300,self.start_services)
        self.mutate(self.repo.close_turn,(tid,values,self.count_note.text()),done)

    def start_services(self):
        if self._closing or self.integration_busy or not self.isVisible():return
        kind='send' if any(j['estado']=='PENDIENTE' for j in self.jobs_cache) else 'check'
        def show(d):
            self.db_ok=True;self.settings.update(d['settings']);self._settings_ready=True
            self.jobs_cache=d['jobs'];self.jobs_table.fill(self.jobs_cache)
            self.delivered=d['delivered'];self.reachable=d['reachable']
            pending=sum(j['estado'] in ('PENDIENTE','PROCESANDO') for j in self.jobs_cache)
            self.integration_detail=d.get('notice') or f'Tus envíos: {pending} pendientes · Lector: {self.scanner_state}'
            if self.settings['cloud_enabled'] and time.monotonic()>=self.next_backup:
                self.next_backup=time.monotonic()+self.settings['backup_minutes']*60
                QTimer.singleShot(0,self._backup)
        self.run_background(self._services.tick,kind,show)

    def _backup(self):
        if self._closing or self.integration_busy or not self.isVisible():return
        def done(result):
            self.integration_detail='Copia de seguridad confirmada' if result else 'Respaldo desactivado'
        self.run_background(self._services.backup,'backup',done)

    def eventFilter(self,obj,event):
        if (event.type()==QEvent.Type.KeyPress and event.key()==Qt.Key.Key_Tab
                and not event.modifiers() and self.isVisible() and QApplication.activeModalWidget() is None):
            focus=QApplication.focusWidget()
            if (focus and (focus is self or self.isAncestorOf(focus))
                    and not isinstance(focus,(QLineEdit,QComboBox,QAbstractSpinBox,QTextEdit,QPlainTextEdit))):
                self.show_shortcuts();return True
        return super().eventFilter(obj,event)

    def show_shortcuts(self):
        if QApplication.activeModalWidget():return
        QMessageBox.information(self,'Atajos del cajero','F1 · Punto de venta\nF2 · Mi turno\nF6 · Cobrar dentro del punto de venta\nF7 · Arqueo y cierre\nF9 · Mis tickets\nF12 · Esta guía\nTab · Siguiente campo en formularios; guía fuera de campos\nShift + Tab · Campo anterior\nEnter · Escanear código\nEsc · Cerrar diálogo')

    def logout(self):
        if self.busy or self.integration_busy:
            QMessageBox.information(self,'Proceso en curso','Espera a que termine el proceso antes de salir.');return
        if self.cart and QMessageBox.question(self,'Carrito pendiente','¿Descartar el carrito sin cobrar y cerrar sesión?')!=QMessageBox.StandardButton.Yes:return
        if self.own_turn and QMessageBox.question(self,'Turno abierto','Cerrar sesión no cierra el turno. ¿Salir y retomarlo después?')!=QMessageBox.StandardButton.Yes:return
        self._closing=True;self.service_timer.stop();self.logged_out.emit();self.close()

    def closeEvent(self,event):
        if self.busy or self.integration_busy:
            QMessageBox.information(self,'Proceso en curso','Espera a que termine el proceso actual.');event.ignore();return
        if not self._closing:
            if (self.cart or self.own_turn) and QMessageBox.question(self,'Salir de caja','El turno seguirá abierto y el carrito sin cobrar se descartará. ¿Volver al inicio de sesión?')!=QMessageBox.StandardButton.Yes:
                event.ignore();return
            self._closing=True;self.logged_out.emit()
        self.service_timer.stop();QApplication.instance().removeEventFilter(self);event.accept()
