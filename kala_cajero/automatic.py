from kala_admin.repository import Repository
from kala_admin.services import ExtendedRepository
import psycopg
from kala_admin.bot import BotRepositoryMixin
from kala_admin.transport import Transport
from .repository import CashierRepository


class _AutomaticRepository(BotRepositoryMixin):
    __init__ = CashierRepository.__init__
    connection = CashierRepository.connection
    health = CashierRepository.health
    read = Repository.read
    audit = Repository.audit
    settings = ExtendedRepository.settings
    claim_job = ExtendedRepository.claim_job
    job_state = ExtendedRepository.job_state
    backup_record = ExtendedRepository.backup_record
    pending_receipts = ExtendedRepository.pending_receipts
    touch_receipt = ExtendedRepository.touch_receipt

    def jobs(self):
        return []  # Transport necesita estos campos; la ventana no recibe documentos privados.

    def backup_history(self):
        return []

    def delivered_owner(self, owner):
        result = ExtendedRepository.delivered_owner(self,owner)
        return {'actualizado_en':result['actualizado_en']} if result else None


class AutomaticServices:
    def __init__(self, config, user, vault=None):
        self._transport = Transport(_AutomaticRepository(config,user),vault)
        self._cashier = CashierRepository(config,user)

    def tick(self):
        notice=''
        self._transport.repo.health()
        try:
            d = self._transport.tick()
        except psycopg.Error:
            raise
        except Exception:
            # Una credencial externa ausente no significa que PostgreSQL esté caído.
            d = dict(settings=self._transport.repo.settings(),delivered=None,reachable=False)
            notice='Servicios pendientes · solicita revisión al administrador. Puedes seguir vendiendo.'
        # No entregar endpoints, números, tokens, contenidos ni bitácora a la UI.
        cfg = d['settings']
        visible = {k:cfg[k] for k in ('wa_enabled','wa_mode','wa_format','simulate_hardware',
                   'cloud_enabled','cloud_mode','backup_minutes')}
        return dict(settings=visible,jobs=self._cashier.jobs(),delivered=d['delivered'],
                    reachable=d['reachable'],notice=notice)

    def backup(self):
        repo = self._transport.repo
        repo.health()
        cfg = repo.settings()
        if not cfg['cloud_enabled']:
            return False
        self._transport.backup(cfg)
        return True
