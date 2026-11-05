from pathlib import Path
from argparse import ArgumentParser
from cryptography.fernet import Fernet,InvalidToken
p=ArgumentParser(description='Descifrar una copia KALA. No modifica PostgreSQL.')
p.add_argument('respaldo');p.add_argument('clave');p.add_argument('salida');a=p.parse_args()
try:
    data=Fernet(Path(a.clave).read_bytes().strip()).decrypt(Path(a.respaldo).read_bytes())
    if not data.startswith(b'PGDMP'):raise ValueError('El contenido no es un respaldo PostgreSQL custom.')
    with Path(a.salida).open('xb') as f:f.write(data)
    print('Archivo descifrado:',a.salida)
    print('Restaura primero en una base NUEVA de prueba usando pgAdmin / pg_restore. No sobrescribas kala_db sin validar.')
except (OSError,InvalidToken,ValueError) as e:
    print('No se pudo descifrar:',type(e).__name__)
    raise SystemExit(1)
