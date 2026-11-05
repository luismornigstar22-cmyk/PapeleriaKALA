import getpass
import hmac
import hashlib
import re
import sys
from urllib.parse import urlsplit
import requests


def main():
    print('Registrar receptor KALA en Kapso. Necesitas el Worker ya configurado.')
    url = input('URL del Worker, sin /webhook: ').strip().rstrip('/')
    u = urlsplit(url)
    if u.scheme != 'https' or not u.hostname or u.username or u.password or u.query or u.fragment or u.path:
        raise ValueError('Usa solamente https://nombre.workers.dev')
    pid = input('Phone Number ID de Kapso (el mismo de KALA): ').strip()
    if not re.fullmatch(r'[0-9]+', pid): raise ValueError('Phone Number ID inválido.')
    secret = getpass.getpass('WEBHOOK_SECRET guardado en Cloudflare (no se muestra): ').strip()
    if len(secret) < 32: raise ValueError('WEBHOOK_SECRET debe tener al menos 32 caracteres.')
    token = ''
    try:
        from kala_admin.transport import Vault
        token = Vault('kala_db').get('kapso_key')
    except Exception:
        pass
    if not token: token = getpass.getpass('API key de Kapso (no se muestra): ').strip()
    if not token: raise ValueError('Falta la API key de Kapso.')
    # Verifica el receptor antes de modificar Kapso.
    r = requests.get(url + '/health', timeout=(5, 10), allow_redirects=False)
    if r.status_code != 200 or r.json().get('service') != 'KALA bot':
        raise ValueError('La URL no corresponde al receptor KALA. Revisa el despliegue.')
    desktop = getpass.getpass('DESKTOP_TOKEN del Worker (no se muestra): ').strip()
    r = requests.get(url + '/commands', headers={'Authorization': 'Bearer ' + desktop}, timeout=(5, 10), allow_redirects=False)
    if r.status_code != 200 or r.json().get('phone_id') != pid:
        raise ValueError('El Worker no está listo: revisa D1, secretos, Phone Number ID y token.')
    signature = hmac.new(secret.encode(), b'{}', hashlib.sha256).hexdigest()
    r = requests.post(url + '/webhook', data=b'{}', headers={'Content-Type':'application/json', 'X-Webhook-Signature':signature, 'X-Webhook-Event':'whatsapp.message.received', 'X-Webhook-Payload-Version':'v2'}, timeout=(5,10), allow_redirects=False)
    if r.status_code != 200: raise ValueError('WEBHOOK_SECRET no coincide con Cloudflare o el receptor no está listo.')
    print('Receptor verificado. Se registrará únicamente whatsapp.message.received, formato Kapso v2.')
    # No reintentar automáticamente: un timeout podría ocurrir después de crear el webhook.
    try:
        r = requests.post(f'https://api.kapso.ai/platform/v1/whatsapp/phone_numbers/{pid}/webhooks',
            headers={'X-API-Key': token},
            json={'whatsapp_webhook': {'kind': 'kapso', 'url': url + '/webhook',
                  'events': ['whatsapp.message.received'], 'secret_key': secret, 'active': True}},
            timeout=(5, 25), allow_redirects=False)
    except requests.RequestException:
        print('Resultado incierto. Revisa en Kapso si el receptor ya existe antes de ejecutar otra vez.')
        return 2
    if r.status_code not in (200, 201):
        from kala_admin.transport import provider_error
        try: data = r.json()
        except ValueError: data = None
        detail = provider_error(data, token).replace(secret, '[OCULTO]').replace(desktop, '[OCULTO]')
        print('Kapso rechazó el registro: HTTP', r.status_code, detail)
        return 1
    print('Kapso aceptó el registro. No vuelvas a ejecutar este paso si ya está creado.')
    print('Activa el Bot del dueño en KALA y escribe menú desde el teléfono autorizado.')
    return 0

if __name__ == '__main__':
    try: sys.exit(main())
    except (ValueError, requests.RequestException) as e:
        print('No se completó el registro:', str(e) if isinstance(e, ValueError) else type(e).__name__)
        sys.exit(1)
    except KeyboardInterrupt:
        print('\nCancelado.'); sys.exit(1)
