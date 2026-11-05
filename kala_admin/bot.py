import re
import time
from uuid import UUID, uuid4
from urllib.parse import urlsplit
from psycopg.types.json import Jsonb
from .repository import BusinessError, money

MENU = ('PAPELERÍA KALA · Consultas del dueño\n'
        '1. menú\n2. ventas hoy\n3. bitácora hoy\n\n'
        'Más registros: bitácora hoy 2 (cambia el número de página).\n'
        'Consultas disponibles mientras KALA está abierto con sesión de administrador o cajero e Internet.\n'
        'Fecha de referencia: la del mensaje, zona Ciudad de México.')
MAX_AGE = 20 * 3600

def valid_url(value):
    u = urlsplit(value)
    return u.scheme == 'https' and bool(u.hostname) and not u.username and not u.password and not u.query and not u.fragment and u.path in ('', '/')

def canonical_phone(value):
    clean = re.sub(r'[\s()+-]', '', str(value))
    return clean if re.fullmatch(r'[1-9][0-9]{7,14}', clean) else ''

def enabled(cfg):
    return (cfg.get('bot_enabled') is True and cfg.get('wa_enabled') is True and
            cfg.get('wa_mode') == 'REAL' and cfg.get('wa_provider') == 'KAPSO' and
            cfg.get('owner_consent') is True and bool(canonical_phone(cfg.get('owner', ''))))

def safe_line(value, limit):
    text = ' '.join(str(value or '').split())
    # Una descripción de bitácora puede contener texto introducido por empleados.
    text = re.sub(r'(?i)(bearer|token|api[_ -]?key|secret|password|contraseña)\s*[:=]\s*\S+', r'\1=[OCULTO]', text)
    return text[:limit] + ('… [resumen]' if len(text) > limit else '')

class BotRepositoryMixin:
    def process_owner_command(self, item):
        if not isinstance(item, dict): raise BusinessError('Solicitud del bot inválida.')
        try:
            request_id = str(UUID(item['id']))
            timestamp = int(item['requested_at'])
        except (KeyError, ValueError, TypeError): raise BusinessError('Solicitud del bot inválida.')
        msg = item.get('message_id'); pid = item.get('phone_id'); sender = canonical_phone(item.get('sender', ''))
        command = item.get('command', '')
        if not isinstance(msg, str) or not 1 <= len(msg) <= 512 or not isinstance(pid, str) or not pid.isdigit():
            raise BusinessError('Identidad del mensaje inválida.')
        if not isinstance(command, str) or not (command in ('menu', 'ventas hoy', 'bitacora hoy') or re.fullmatch(r'bitacora hoy [1-9][0-9]{0,3}', command)):
            raise BusinessError('Comando no permitido.')
        with self.connection(True) as c:
            # Leer permisos actuales en la misma transacción que produce la respuesta.
            cfg = c.execute('SELECT datos FROM public.kala_config_integraciones WHERE id=1').fetchone()['datos']
            if not enabled(cfg) or sender != canonical_phone(cfg.get('owner', '')) or pid != cfg.get('phone_id'):
                raise BusinessError('El remitente o canal no coincide con el dueño autorizado.')
            now = c.execute('SELECT extract(epoch FROM now())::bigint AS n').fetchone()['n']
            if timestamp > now + 300 or timestamp < now - MAX_AGE:
                raise BusinessError('La solicitud expiró. Escribe de nuevo desde WhatsApp.')
            old = c.execute('SELECT envio_id FROM public.kala_consultas_whatsapp WHERE phone_id=%s AND mensaje_entrada=%s', (pid, msg)).fetchone()
            if old: return str(old['envio_id'])
            day = c.execute('SELECT to_timestamp(%s)::date AS dia', (timestamp,)).fetchone()['dia']
            title = 'Consulta KALA'
            body = MENU
            if command == 'ventas hoy':
                title = 'Ventas · ' + day.strftime('%d/%m/%Y')
                totals = c.execute("""SELECT COALESCE(sum(total_centavos) FILTER(WHERE estado='COBRADA'),0) AS total,
                    count(*) FILTER(WHERE estado='COBRADA') AS tickets,
                    count(*) FILTER(WHERE estado='CANCELADA') AS cancelados
                    FROM public.ventas WHERE cobrado_en::date=%s""", (day,)).fetchone()
                payments = c.execute("""SELECT p.metodo, COALESCE(sum(p.importe_centavos),0) AS total
                    FROM public.pagos_venta p JOIN public.ventas v ON v.id=p.venta_id
                    WHERE v.estado='COBRADA' AND v.cobrado_en::date=%s GROUP BY p.metodo ORDER BY p.metodo""", (day,)).fetchall()
                body = ('PAPELERÍA KALA\nVentas vigentes: ' + money(totals['total']) +
                        f"\nTickets cobrados vigentes: {totals['tickets']}\nTickets cancelados de ese día: {totals['cancelados']}\n" +
                        '\n'.join(f"{p['metodo']}: {money(p['total'])}" for p in payments) +
                        '\n\nImportes MXN. No incluye fondos ni retiros de caja.\nEstado actual de las ventas del día indicado.')
            elif command.startswith('bitacora hoy'):
                page = int(command.split()[-1]) if command != 'bitacora hoy' else 1
                size = 4
                total = c.execute('SELECT count(*) AS n FROM public.auditoria WHERE creado_en::date=%s AND creado_en<=to_timestamp(%s)', (day, timestamp)).fetchone()['n']
                pages = max(1, (total + size - 1) // size)
                rows = c.execute("""SELECT a.id,to_char(a.creado_en,'HH24:MI:SS') AS hora,
                    COALESCE(u.nombre,'Sistema') AS usuario,a.accion,a.entidad,a.registro_id,a.descripcion
                    FROM public.auditoria a LEFT JOIN public.usuarios u ON u.id=a.usuario_id
                    WHERE a.creado_en::date=%s AND a.creado_en<=to_timestamp(%s)
                    ORDER BY a.creado_en,a.id LIMIT %s OFFSET %s""", (day, timestamp, size, (page - 1) * size)).fetchall()
                title = 'Bitácora · ' + day.strftime('%d/%m/%Y')
                body = f'Página {page} de {pages} · {total} registros hasta la hora de tu mensaje.\nOrden: del más antiguo al más reciente.\n'
                for r in rows:
                    body += (f"\n#{r['id']} · {r['hora']} · {safe_line(r['usuario'],60)}\n"
                             f"{safe_line(r['accion'],60)} · {safe_line(r['entidad'],40)} #{r['registro_id'] or '-'}\n"
                             f"{safe_line(r['descripcion'],220)}\n")
                if not rows: body += '\nSin registros en esta página.\n'
                if page < pages: body += f'\nSiguiente: bitácora hoy {page + 1}\n'
                body += '\nLas descripciones largas se resumen; el detalle completo está en KALA.\nEscribe menú para volver.'
            body += '\n\nGenerado: ' + c.execute("SELECT to_char(now(),'DD/MM/YYYY HH24:MI') AS hora").fetchone()['hora'] + ' · Ciudad de México'
            if len((title + '\n\n' + body).encode('utf-16-le')) // 2 > 4096:
                raise BusinessError('El reporte supera el tamaño permitido.')
            jid = str(uuid4())
            c.execute("INSERT INTO public.kala_envios(id,dedupe,usuario_id,titulo,destino,contenido,modo) VALUES(%s,%s,%s,%s,%s,%s,'REAL')",
                      (jid, 'bot:' + pid + ':' + msg, self.user_id, title, sender, body))
            # La migración 03 fija el canal. Las respuestas a consultas son texto incluso
            # si los reportes automáticos usan plantilla PDF.
            c.execute("UPDATE public.kala_envios SET canal=canal || %s WHERE id=%s",
                      (Jsonb({'wa_format': 'TEXT', 'bot_requested_at': timestamp, 'bot_owner': sender}), jid))
            c.execute('INSERT INTO public.kala_consultas_whatsapp(id,phone_id,mensaje_entrada,remitente,comando,solicitado_en,envio_id) VALUES(%s,%s,%s,%s,%s,to_timestamp(%s),%s)',
                      (request_id, pid, msg, sender, command, timestamp, jid))
            self.audit(c, 'CONSULTA_WHATSAPP_DUENO', 'kala_consultas_whatsapp', None,
                       'Consulta remota autorizada: ' + command + '. Respuesta encolada; procesada por los servicios automáticos de la sesión activa.')
            return jid

class OwnerBot:
    def __init__(self, repo, vault): self.repo, self.vault = repo, vault
    def poll(self, cfg):
        import requests
        if not enabled(cfg): return 'Bot del dueño desactivado.'
        url = cfg.get('bot_url', '').rstrip('/')
        if not valid_url(url): return 'Bot: configura la URL HTTPS del Worker (sin /webhook).'
        token = self.vault.get('bot_token')
        if len(token) < 32: return 'Bot: falta el token privado del escritorio.'
        headers = {'Authorization': 'Bearer ' + token}
        try:
            r = requests.get(url + '/commands', headers=headers, timeout=(3, 8), allow_redirects=False)
            if r.status_code != 200: return f'Bot: receptor HTTP {r.status_code}; revisa URL, token y configuración.'
            data = r.json()
            if (not isinstance(data, dict) or data.get('version') != 1 or
                canonical_phone(data.get('owner', '')) != canonical_phone(cfg['owner']) or data.get('phone_id') != cfg['phone_id']):
                return 'Bot: el dueño o Phone Number ID del Worker no coincide con KALA.'
            items = data.get('commands')
            if not isinstance(items, list) or len(items) > 5: return 'Bot: respuesta del receptor inválida.'
            ids = []
            for item in items:
                self.repo.process_owner_command(item)
                ids.append(item['id'])
            if ids:
                r = requests.post(url + '/ack', headers=headers, json={'ids': ids}, timeout=(3, 8), allow_redirects=False)
                if r.status_code != 200: return 'Bot: respuestas guardadas; confirmación al receptor pendiente. No se duplicarán.'
            return f'Bot conectado · {len(ids)} solicitudes procesadas en esta revisión.'
        except BusinessError as e: return 'Bot: ' + str(e)
        except Exception as e:
            # El fallo del bot no bloquea los cobros ni se etiqueta como caída de PostgreSQL.
            return 'Bot pendiente · ' + type(e).__name__ + '. Revisa conexión y migración 04.'
