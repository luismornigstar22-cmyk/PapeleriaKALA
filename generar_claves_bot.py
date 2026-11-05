import secrets
print('Guarda estas dos claves distintas en tu gestor de contraseñas. No las envíes al chat.')
print('WEBHOOK_SECRET=' + secrets.token_urlsafe(32))
print('DESKTOP_TOKEN=' + secrets.token_urlsafe(32))
print('Se generaron localmente; este script no las guarda ni las envía por Internet.')
