import sys
import traceback
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox
from kala_login import LoginWindow, STYLE
from kala_admin.ui import AdminWindow
from kala_cajero.ui import CashierWindow


class KALALogin(LoginWindow):
    def __init__(self):
        super().__init__()
        self.admin_window = None
        self.pending_user = None
        self.setWindowTitle('KALA · Inicio integrado')

    def receive_result(self, user, error):
        if not user or user.get('rol') not in ('ADMINISTRADOR', 'CAJERO'):
            super().receive_result(user, error)
            return

        self.user = user
        self.pending_user = dict(user)
        self.status.setText('Acceso correcto. Abriendo tu panel…')
        QTimer.singleShot(0, self.finish_login)

    def finish_login(self):
        if self.pending_user is None:
            return
        worker = getattr(self, 'worker', None)
        if worker is not None and worker.isRunning():
            QTimer.singleShot(25, self.finish_login)
            return
        user = self.pending_user
        self.pending_user = None
        self.open_admin(user)

    def open_admin(self, user):
        try:
            panel = AdminWindow if user['rol'] == 'ADMINISTRADOR' else CashierWindow
            window = panel(self.config, user)
            window.logged_out.connect(self.return_to_login)
            self.admin_window = window
            window.show()
            self.hide()
        except Exception as exc:
            traceback.print_exc()
            self.status.setText('El acceso fue correcto, pero no se pudo abrir el panel.')
            self.show()
            QMessageBox.critical(
                self, 'No se pudo abrir el panel',
                'El usuario fue autenticado. Falló la apertura del panel.\n\n'
                + type(exc).__name__ + ': ' + str(exc)
                + '\n\nCopia el error que aparece en la terminal para revisarlo.'
            )

    def return_to_login(self):
        self.pending_user = None
        self.logout()
        self.show()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    print('KALA: iniciador integrado corregido. Archivo:', __file__, flush=True)
    window = KALALogin()
    window.show()
    sys.exit(app.exec())
