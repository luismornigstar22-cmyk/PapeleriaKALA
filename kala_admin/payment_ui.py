from decimal import Decimal
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QFrame,QRadioButton,QButtonGroup,QDoubleSpinBox,QLineEdit,QCheckBox,QDialogButtonBox,QFormLayout)
from .repository import cents,money

class PaymentDialog(QDialog):
    def __init__(self,parent,total):
        super().__init__(parent);self.total=int(total);self.setWindowTitle('Cobrar venta');self.setMinimumWidth(580)
        self.setStyleSheet('''QDialog{background:#f7f6f0;} QLabel#payTitle{font-size:24px;font-weight:700;color:#174a4b;}
        QFrame#payTotal{background:#174a4b;border-radius:14px;} QFrame#payTotal QLabel{color:white;background:transparent;}
        QLabel#payAmount{font-size:34px;font-weight:800;} QRadioButton{padding:12px;background:#e5ece5;border-radius:9px;font-weight:600;}
        QRadioButton:checked{background:#f3d48c;color:#163f3d;} QLabel#payChange{font-size:25px;font-weight:700;color:#17684e;}
        QLabel#payError{color:#a63e32;min-height:22px;} QPushButton{min-height:25px;padding:9px 18px;}''')
        layout=QVBoxLayout(self);layout.setContentsMargins(24,22,24,22);layout.setSpacing(14)
        title=QLabel('Cobrar venta');title.setObjectName('payTitle');layout.addWidget(title)
        box=QFrame();box.setObjectName('payTotal');tl=QVBoxLayout(box);tl.addWidget(QLabel('TOTAL A PAGAR'))
        amount=QLabel(money(total));amount.setObjectName('payAmount');tl.addWidget(amount);layout.addWidget(box)
        layout.addWidget(QLabel('1. Elige cómo paga el cliente'));self.group=QButtonGroup(self);row=QHBoxLayout();self.methods={}
        for i,(key,caption) in enumerate([('cash','Efectivo'),('card','Tarjeta'),('mixed','Combinado')]):
            b=QRadioButton(caption);self.group.addButton(b,i);self.methods[key]=b;row.addWidget(b)
        layout.addLayout(row);self.methods['cash'].setChecked(True)
        self.help=QLabel();self.help.setWordWrap(True);layout.addWidget(self.help)
        form=QFormLayout();form.setSpacing(10);layout.addLayout(form)
        self.cash_label=QLabel('Parte en efectivo');self.cash=self.amount(total/100);self.cash.setMaximum(total/100);form.addRow(self.cash_label,self.cash)
        self.card_label=QLabel('A cobrar en la terminal');self.card=QLabel();form.addRow(self.card_label,self.card)
        self.received_label=QLabel('Dinero recibido');self.received=self.amount(0);form.addRow(self.received_label,self.received)
        self.reference_label=QLabel('Folio de aprobación');self.reference=QLineEdit();self.reference.setMaxLength(100);self.reference.setPlaceholderText('Folio del comprobante de la terminal');form.addRow(self.reference_label,self.reference)
        self.approved=QCheckBox('La terminal aprobó el pago con tarjeta');layout.addWidget(self.approved)
        self.change=QLabel();self.change.setObjectName('payChange');layout.addWidget(self.change)
        self.error=QLabel();self.error.setObjectName('payError');self.error.setWordWrap(True);layout.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.confirm=buttons.button(QDialogButtonBox.StandardButton.Ok);self.confirm.setText('Confirmar cobro')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Volver a la venta');buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.group.idClicked.connect(self.change_method);self.cash.valueChanged.connect(self.cash_changed)
        self.received.valueChanged.connect(self.calculate);self.reference.textChanged.connect(self.calculate);self.approved.toggled.connect(self.calculate);self.change_method()
    @staticmethod
    def amount(value):
        w=QDoubleSpinBox();w.setDecimals(2);w.setRange(0,999999999.99);w.setPrefix('$ ');w.setValue(value);return w
    def method(self):return next(k for k,b in self.methods.items() if b.isChecked())
    def change_method(self,*args):
        m=self.method();self.cash.blockSignals(True);self.cash.setValue(self.total/100 if m=='cash' else 0 if m=='card' else (self.total//2)/100);self.cash.blockSignals(False)
        for w in (self.cash,self.cash_label):w.setVisible(m=='mixed')
        for w in (self.received,self.received_label,self.change):w.setVisible(m!='card')
        for w in (self.card,self.card_label,self.reference,self.reference_label,self.approved):w.setVisible(m!='cash')
        self.approved.setChecked(False)
        self.help.setText({'cash':'2. Escribe cuánto dinero te entregó el cliente. Devuelve el cambio indicado y confirma.','card':'2. Cobra el importe en la terminal. Cuando esté aprobado, escribe el folio y confirma aquí.','mixed':'2. Indica la parte en efectivo. Cobra el resto en la terminal y registra su aprobación.'}[m])
        self.calculate();w=self.reference if m=='card' else self.cash if m=='mixed' else self.received;w.setFocus();w.selectAll();self.adjustSize()
    def cash_changed(self,*args):self.approved.setChecked(False);self.calculate()
    def data(self):
        cash=cents(self.cash.value());card=self.total-cash;received=cents(self.received.value()) if self.method()!='card' else 0
        return dict(cash=str(Decimal(cash)/100),card=str(Decimal(card)/100),received=str(Decimal(received)/100),reference=self.reference.text().strip() if card else '')
    def calculate(self,*args):
        d=self.data();cash=cents(d['cash']);card=cents(d['card']);received=cents(d['received']);self.card.setText(money(card));self.change.setText('Cambio: '+money(max(0,received-cash)))
        error=''
        if self.method()=='mixed' and (cash<=0 or card<=0):error='Reparte el total entre efectivo y tarjeta, o elige un solo método.'
        elif received<cash:error='Faltan '+money(cash-received)+' en efectivo.'
        elif card and not d['reference']:error='Escribe el folio de aprobación de la terminal.'
        elif card and d['reference'].upper().startswith('SIM-'):error='Usa el folio de una operación aprobada en la terminal.'
        elif card and not self.approved.isChecked():error='Confirma que la terminal aprobó el pago.'
        self.error.setText(error);self.confirm.setEnabled(not error);self.valid=not error
    def accept(self):
        self.calculate()
        if self.valid:super().accept()
