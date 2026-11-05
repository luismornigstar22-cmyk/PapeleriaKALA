import sys
import secrets
from pathlib import Path

try:
    import psycopg
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRectF
    from PyQt6.QtGui import QPainter, QPixmap, QShortcut, QKeySequence
    from PyQt6.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
        QPushButton, QFrame, QStackedWidget, QDialog, QFormLayout,
        QDialogButtonBox, QSpinBox, QMessageBox, QCheckBox,
    )
except ImportError:
    print('Faltan dependencias. Ejecuta: python -m pip install PyQt6 "psycopg[binary]" argon2-cffi')
    sys.exit(1)


STYLE = """
QWidget { font-family: 'Segoe UI'; font-size: 14px; color: #343831; }
QWidget#window { background-color: #f8e8d6; }
QFrame#card { background: #fffcf3; border: 1px solid #d7cab7; border-radius: 22px; }
QLabel#brand { font-size: 40px; font-weight: 800; color: #4d736d; }
QLabel#subtitle { color: #726e65; }
QLabel#title { font-size: 24px; font-weight: 700; }
QLabel#status { color: #a43b34; }
QLineEdit, QSpinBox { background: #fffef9; border: 1px solid #b7b7a4;
    border-radius: 10px; padding: 10px; min-height: 22px; }
QLineEdit:focus, QSpinBox:focus { border: 2px solid #557d75; }
QPushButton { background: #557d75; color: white; border: none;
    border-radius: 10px; padding: 12px 18px; font-weight: 600; }
QPushButton:hover { background: #41665e; }
QPushButton:disabled { background: #a7b4ac; }
QPushButton#secondary { background: #eee6d8; color: #41483f; }
"""


class ConnectionDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('Conexión local de KALA')
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        intro = QLabel('Configura la conexión para esta ejecución.\nLa contraseña no se guarda en archivos.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        form.addRow('Servidor:', QLabel('localhost'))
        form.addRow('Base de datos:', QLabel('kala_db'))
        form.addRow('Cuenta PostgreSQL:', QLabel('kala_app'))
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(5432)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow('Puerto:', self.port)
        form.addRow('Contraseña de kala_app:', self.password)
        layout.addLayout(form)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Usar conexión')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Cancelar')
        self.buttons.accepted.connect(self.validate)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.password.setFocus()

    def validate(self):
        if not self.password.text():
            QMessageBox.information(self, 'Contraseña necesaria', 'Introduce la contraseña de kala_app.')
            return
        self.accept()


class LoginWorker(QThread):
    result = pyqtSignal(object, str)

    def __init__(self, config, username, password, parent):
        super().__init__(parent)
        self.config = dict(config)
        self.username = username
        self.password = password

    def run(self):
        try:
            with psycopg.connect(
                **self.config, connect_timeout=5,
                application_name='kala_login_grafico',
                options='-c statement_timeout=5000',
            ) as conn:
                conn.read_only = True
                row = conn.execute(
                    'SELECT id, nombre, password_hash, rol, activo '
                    'FROM public.usuarios WHERE lower(usuario) = lower(%s)',
                    (self.username,),
                ).fetchone()
            hasher = PasswordHasher()
            hashed = row[2] if row else hasher.hash(secrets.token_urlsafe(32))
            try:
                valid = hasher.verify(hashed, self.password)
            except VerifyMismatchError:
                valid = False
            if row and valid and row[4] and row[3] in ('ADMINISTRADOR', 'CAJERO'):
                self.result.emit({'id': row[0], 'nombre': row[1], 'rol': row[3]}, '')
            else:
                self.result.emit(None, 'Usuario o contraseña incorrectos, o cuenta no habilitada.')
        except psycopg.errors.InsufficientPrivilege:
            self.result.emit(None, 'La cuenta kala_app no tiene los permisos de lectura necesarios.')
        except psycopg.OperationalError:
            self.result.emit(None, 'No fue posible conectar. Revisa PostgreSQL y la configuración de conexión.')
        except (VerificationError, InvalidHashError):
            self.result.emit(None, 'No se pudo verificar la contraseña almacenada. Revisa la cuenta.')
        except psycopg.Error as exc:
            self.result.emit(None, f'Error de base de datos. Código: {exc.sqlstate or "no disponible"}.')
        except Exception:
            self.result.emit(None, 'No fue posible completar el acceso. Revisa las dependencias instaladas.')
        finally:
            self.password = ''
            self.config.clear()


class LoginSurface(QWidget):
    """Imagen original sin alteraciones y controles reales superpuestos."""
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        asset = Path(__file__).resolve().parent / 'assets' / 'LOGEO.png'
        self.background = QPixmap(str(asset))
        if self.background.isNull():
            raise FileNotFoundError('Falta assets/LOGEO.png. Extrae tambien la carpeta assets del ZIP.')
        self.controls = []
        self.setMinimumSize(820, 461)
        owner.username = QLineEdit(self)
        owner.username.setMaxLength(50)
        owner.username.setAccessibleName('Usuario de KALA')
        owner.username.setToolTip('Usuario de KALA')
        owner.password = QLineEdit(self)
        owner.password.setMaxLength(128)
        owner.password.setEchoMode(QLineEdit.EchoMode.Password)
        owner.password.setAccessibleName('Contraseña de KALA')
        owner.password.setToolTip('Contraseña de KALA')
        owner.login_button = QPushButton('INICIA SESION', self)
        owner.login_button.setAccessibleName('Iniciar sesión')
        owner.login_button.clicked.connect(owner.login)
        owner.status = QLabel('', self)
        owner.status.setWordWrap(True)
        owner.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        owner.status.setTextFormat(Qt.TextFormat.PlainText)
        owner.connection_button = QPushButton('F2 · Configurar conexión', self)
        owner.connection_button.clicked.connect(owner.configure)
        owner.username.returnPressed.connect(owner.password.setFocus)
        owner.password.returnPressed.connect(owner.login)
        self.controls = [
            (owner.username, (478, 371, 268, 51)),
            (owner.password, (478, 487, 268, 51)),
            (owner.login_button, (509, 580, 300, 50)),
            (owner.status, (484, 644, 330, 65)),
            (owner.connection_button, (523, 738, 270, 25)),
        ]
        self.setTabOrder(owner.username, owner.password)
        self.setTabOrder(owner.password, owner.login_button)
        self.setTabOrder(owner.login_button, owner.connection_button)

    def scale_info(self):
        scale = min(self.width() / 1366, self.height() / 768)
        return scale, (self.width() - 1366 * scale) / 2, (self.height() - 768 * scale) / 2

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.place_controls()

    def place_controls(self):
        scale, ox, oy = self.scale_info()
        for widget, (x, y, w, h) in self.controls:
            widget.setGeometry(round(ox+x*scale), round(oy+y*scale), round(w*scale), round(h*scale))
        border = max(1, round(2*scale))
        radius = round(25*scale)
        text = max(11, round(19*scale))
        field_style = f"""
+            QLineEdit {{ background: #fcf9ee; color: #111111;
+                border: {border}px solid #111111; border-radius: {radius}px;
+                padding: 0px {round(13*scale)}px; min-height: 0px;
+                font-family: Arial; font-size: {text}px; }}
+            QLineEdit:focus {{ border-color: #37636b; }}
+            QLineEdit:disabled {{ color: #777777; }}
+        """.replace('+', '')
        self.owner.username.setStyleSheet(field_style)
        self.owner.password.setStyleSheet(field_style)
        self.owner.login_button.setStyleSheet(f"""
+            QPushButton {{ background: #d9d9d9; color: #000000;
+                border: {border}px solid #393939; border-radius: {round(12*scale)}px;
+                padding: 0px; font-family: Arial; font-size: {max(11,round(20*scale))}px;
+                font-weight: bold; }}
+            QPushButton:hover {{ background: #c7d4cd; }}
+            QPushButton:focus {{ border-color: #37636b; }}
+            QPushButton:pressed {{ background: #b7c9bf; }}
+            QPushButton:disabled {{ color: #666666; }}
+        """.replace('+', ''))
        self.owner.status.setStyleSheet(f'background: transparent; color: #9d3434; font-size: {max(10,round(14*scale))}px;')
        self.owner.connection_button.setStyleSheet(f'QPushButton {{ background: transparent; color: #53645e; border: none; padding: 0px; font-size: {max(10,round(13*scale))}px; }} QPushButton:hover {{ text-decoration: underline; }}')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.white)
        scale, ox, oy = self.scale_info()
        painter.fillRect(self.rect(), self.background.toImage().pixelColor(0, 0))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(QRectF(ox, oy, 1366*scale, 768*scale), self.background, QRectF(self.background.rect()))


class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName('window')
        self.setWindowTitle('Papelería KALA · Acceso')
        self.resize(1366, 768)
        self.setMinimumSize(820, 461)
        self.config = None
        self.worker = None
        self.user = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages)
        self.surface = LoginSurface(self)
        self.pages.addWidget(self.surface)
        self.build_welcome()
        self.connection_shortcut = QShortcut(QKeySequence('F2'), self)
        self.connection_shortcut.activated.connect(self.configure)
        self.username.setFocus()

    def build_welcome(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch()
        card = QFrame()
        card.setObjectName('card')
        card.setMaximumWidth(500)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(30, 30, 30, 30)
        title = QLabel('Acceso correcto')
        title.setObjectName('title')
        inner.addWidget(title)
        self.welcome = QLabel()
        self.welcome.setTextFormat(Qt.TextFormat.PlainText)
        self.welcome.setWordWrap(True)
        inner.addWidget(self.welcome)
        note = QLabel('La conexión y tu cuenta fueron verificadas.\n\nLos módulos de ventas y administración se incorporarán en la siguiente etapa. No se ha abierto un turno de caja.')
        note.setWordWrap(True)
        inner.addWidget(note)
        logout = QPushButton('Cerrar sesión')
        logout.clicked.connect(self.logout)
        inner.addWidget(logout)
        layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()
        self.pages.addWidget(page)

    def configure(self):
        if self.worker and self.worker.isRunning():
            return False
        dialog = ConnectionDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self.config = dict(host='localhost', port=dialog.port.value(),
                           dbname='kala_db', user='kala_app', password=dialog.password.text())
        dialog.password.clear()
        self.status.setText('Configuración lista. Se comprobará al iniciar sesión.')
        return True

    def login(self):
        if self.worker and self.worker.isRunning():
            return
        if not self.username.text().strip() or not self.password.text():
            self.status.setText('Escribe tu usuario y contraseña de KALA.')
            return
        if self.config is None and not self.configure():
            return
        self.status.setText('Verificando acceso…')
        self.set_busy(True)
        self.worker = LoginWorker(self.config, self.username.text().strip(), self.password.text(), self)
        self.password.clear()
        self.worker.result.connect(self.receive_result)
        self.worker.finished.connect(lambda: self.set_busy(False))
        self.worker.start()

    def set_busy(self, busy):
        for widget in (self.login_button, self.connection_button, self.username, self.password):
            widget.setEnabled(not busy)

    def receive_result(self, user, error):
        if user is None:
            self.status.setText(error)
            self.password.setFocus()
            return
        self.user = user
        self.status.clear()
        self.welcome.setText(f'Hola, {user["nombre"]}.\nRol: {user["rol"]}\nID: {user["id"]}')
        self.pages.setCurrentIndex(1)

    def logout(self):
        if self.worker and self.worker.isRunning():
            return
        self.user = None
        self.username.clear()
        self.password.clear()
        self.status.clear()
        self.pages.setCurrentIndex(0)
        self.username.setFocus()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.status.setText('Espera a que termine la verificación antes de cerrar.')
            event.ignore()
        else:
            self.config = None
            event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    try:
        window = LoginWindow()
    except FileNotFoundError as exc:
        QMessageBox.critical(None, 'Falta la imagen del login', str(exc))
        sys.exit(1)
    window.show()
    sys.exit(app.exec())
