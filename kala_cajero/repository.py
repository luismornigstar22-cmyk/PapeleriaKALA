from contextlib import contextmanager
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from kala_admin.repository import Repository, BusinessError, money
from kala_admin.services import DEFAULTS, phone, production_settings


class CashierRepository:
    def __init__(self, config, user):
        self.config = dict(config)
        self.user_id = int(user['id'])

    @contextmanager
    def connection(self, write=False):
        with psycopg.connect(**self.config, row_factory=dict_row, connect_timeout=5,
                             options='-c statement_timeout=15000 -c lock_timeout=5000',
                             application_name='KALA_cajero_local') as c:
            c.execute("SET LOCAL TIME ZONE 'America/Mexico_City'")
            if write:
                c.execute('SELECT pg_advisory_xact_lock(724001)')
            u = c.execute('SELECT id,rol,activo FROM public.usuarios WHERE id=%s', (self.user_id,)).fetchone()
            if not u or not u['activo'] or u['rol'] != 'CAJERO':
                raise BusinessError('La cuenta ya no tiene acceso de cajero activo. Cierra sesión.')
            yield c

    # Reutilizar transacciones probadas sin habilitar el repositorio administrativo.
    mutate = Repository.mutate
    audit = Repository.audit
    open_turn = Repository.open_turn
    charge = Repository.charge
    close_turn = Repository.close_turn
    _quote = Repository._quote
    stock_move = Repository.stock_move
    expected_cash = Repository.expected_cash

    def require_turn(self, c, tid, own=True):
        return Repository.require_turn(self, c, tid, own=True)

    def health(self):
        with self.connection() as c:
            if c.execute('SHOW transaction_read_only').fetchone()['transaction_read_only'] == 'on':
                raise BusinessError('La base local está en modo de solo lectura.')
        return True

    def products(self, search=''):
        with self.connection() as c:
            return c.execute('''SELECT id,codigo,codigo_barras,nombre,tipo,unidad,
                precio_venta_centavos,existencia,controla_stock,activo FROM public.productos
                WHERE activo AND (nombre ILIKE %s OR codigo ILIKE %s OR codigo_barras ILIKE %s)
                ORDER BY nombre''', tuple('%'+search+'%' for _ in range(3))).fetchall()

    def quote(self, items):
        with self.connection() as c:
            rows = self._quote(c, items)
            return [{k:v for k,v in r.items() if k not in ('costo','materials')} for r in rows]

    def boxes(self):
        with self.connection() as c:
            return c.execute('''SELECT c.id,c.nombre FROM public.cajas c WHERE c.activo
                AND NOT EXISTS(SELECT 1 FROM public.turnos t WHERE t.caja_id=c.id AND t.estado='ABIERTO')
                ORDER BY c.id''').fetchall()

    def turns(self):
        with self.connection() as c:
            return c.execute('''SELECT t.id,t.usuario_id,t.caja_id,t.estado,t.abierto_en,
                u.nombre AS cajero,c.nombre AS caja FROM public.turnos t
                JOIN public.usuarios u ON u.id=t.usuario_id JOIN public.cajas c ON c.id=t.caja_id
                WHERE t.usuario_id=%s AND t.estado='ABIERTO' ORDER BY t.id''', (self.user_id,)).fetchall()

    def sales(self, start, end):
        with self.connection() as c:
            return c.execute('''SELECT v.id,v.cobrado_en,v.estado,v.total_centavos,v.turno_id,u.nombre AS cajero,
                (SELECT string_agg(p.metodo,' + ' ORDER BY p.metodo) FROM public.pagos_venta p WHERE p.venta_id=v.id) AS metodo
                FROM public.ventas v JOIN public.turnos t ON t.id=v.turno_id
                JOIN public.usuarios u ON u.id=t.usuario_id
                WHERE t.usuario_id=%s AND v.cobrado_en::date BETWEEN %s AND %s
                ORDER BY v.id DESC''', (self.user_id,start,end)).fetchall()

    def _ticket(self, c, vid):
        v = c.execute('''SELECT v.id,v.cobrado_en,v.estado,v.total_centavos,v.turno_id,u.nombre AS cajero
            FROM public.ventas v JOIN public.turnos t ON t.id=v.turno_id
            JOIN public.usuarios u ON u.id=t.usuario_id WHERE v.id=%s AND t.usuario_id=%s''',
            (vid,self.user_id)).fetchone()
        if not v:
            raise BusinessError('Ticket no disponible: solo puedes consultar tus propias ventas.')
        return dict(venta=v, detalle=c.execute('''SELECT nombre_producto,codigo_producto,unidad,cantidad,
            precio_unitario_centavos,subtotal_centavos,aplica_mayoreo FROM public.detalle_venta
            WHERE venta_id=%s ORDER BY id''', (vid,)).fetchall(),
            pagos=c.execute('''SELECT metodo,importe_centavos,recibido_centavos,cambio_centavos,referencia_terminal
            FROM public.pagos_venta WHERE venta_id=%s ORDER BY id''', (vid,)).fetchall())

    def ticket(self, vid):
        with self.connection() as c:
            return self._ticket(c,vid)

    def ticket_settings(self):
        with self.connection() as c:
            row = c.execute('SELECT datos FROM public.kala_config_integraciones WHERE id=1').fetchone()
            cfg = production_settings(row['datos'] if row else {})
            return {k:cfg[k] for k in ('wa_enabled','wa_mode','wa_format','simulate_hardware')}

    def queue_ticket(self, vid, recipient, target='', consent=False, request_id=None):
        if recipient not in ('OWNER','CLIENT'):
            raise BusinessError('Destinatario inválido.')
        def work(c):
            # Documento, autorización y canal se resuelven dentro de la transacción.
            d = self._ticket(c,vid)
            row = c.execute('SELECT datos FROM public.kala_config_integraciones WHERE id=1').fetchone()
            cfg = production_settings(row['datos'] if row else {})
            if not cfg['wa_enabled']:
                raise BusinessError('WhatsApp está desactivado. Solicita al administrador que lo configure.')
            destination = cfg['owner'] if recipient == 'OWNER' else target
            allowed = cfg['owner_consent'] if recipient == 'OWNER' else consent
            if not allowed:
                raise BusinessError('Se necesita autorización del destinatario para enviar el ticket.')
            destination = phone(destination)
            v = d['venta']
            lines = ['PAPELERÍA KALA',f'Ticket #{vid}',str(v['cobrado_en']),v['cajero'],v['estado']]
            for r in d['detalle']:
                lines.append(f'{r["nombre_producto"]}\n{r["cantidad"]} × {money(r["precio_unitario_centavos"])} = {money(r["subtotal_centavos"])}')
            lines.append('Total: '+money(v['total_centavos']))
            for p in d['pagos']:
                lines.append(p['metodo']+': '+money(p['importe_centavos']))
                if p['metodo']=='EFECTIVO': lines.append('Cambio: '+money(p['cambio_centavos']))
                if p['referencia_terminal']:
                    lines.append('Referencia: '+p['referencia_terminal'])
                    if p['referencia_terminal'].startswith('SIM-'):
                        lines.append('TERMINAL SIMULADA · Sin cobro bancario real')
            lines.append('Comprobante de compra · No es factura fiscal.')
            jid = str(uuid4())
            c.execute('''INSERT INTO public.kala_envios(id,dedupe,usuario_id,titulo,destino,contenido,modo)
                VALUES(%s,%s,%s,%s,%s,%s,%s)''',
                (jid,'ticket-cajero:'+jid,self.user_id,f'Ticket #{vid}',destination,'\n'.join(lines),cfg['wa_mode']))
            self.audit(c,'ENCOLAR_TICKET','ventas',vid,'Ticket propio para destinatario autorizado.')
            return {'id':jid}
        return self.mutate('TICKET_CAJERO',work,request_id)

    def jobs(self):
        # No mostrar respuestas del bot (bitácora / reportes generales) al empleado.
        with self.connection() as c:
            return c.execute('''SELECT titulo,estado,creado_en FROM public.kala_envios
                WHERE usuario_id=%s AND modo='REAL' AND (dedupe LIKE 'ticket-cajero:%%' OR dedupe LIKE 'cierre:%%')
                ORDER BY creado_en DESC LIMIT 30''', (self.user_id,)).fetchall()
