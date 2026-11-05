import getpass
import re
import sys
import warnings

try:
    import psycopg
    from argon2 import PasswordHasher
    from argon2.exceptions import Argon2Error
except ImportError:
    print('Faltan dependencias. Ejecuta: python -m pip install "psycopg[binary]" argon2-cffi')
    sys.exit(1)


def main():
    warnings.simplefilter('error', getpass.GetPassWarning)
    print('KALA - Creacion del primer administrador')
    print('No se modifican cuentas existentes ni se guardan contrasenas en archivos.')
    nombre = input('Nombre completo: ').strip()
    usuario = input('Usuario para entrar a KALA (ejemplo: admin): ').strip().lower()
    if not nombre or len(nombre) > 120:
        raise ValueError('El nombre debe tener entre 1 y 120 caracteres.')
    if not re.fullmatch(r'[a-z0-9_.-]{3,50}', usuario):
        raise ValueError('El usuario debe tener 3 a 50 letras sin acentos, numeros, punto, guion o guion bajo.')

    clave = getpass.getpass('Nueva contrasena del administrador de KALA (minimo 12 caracteres): ')
    if len(clave) < 12 or len(clave) > 128 or not clave.strip():
        raise ValueError('Usa una contrasena de 12 a 128 caracteres, no solo espacios.')
    if clave != getpass.getpass('Repite la nueva contrasena de KALA: '):
        raise ValueError('Las contrasenas no coinciden. No se creo ninguna cuenta.')
    ph = PasswordHasher()
    password_hash = ph.hash(clave)
    ph.verify(password_hash, clave)
    del clave

    puerto = input('Puerto PostgreSQL [5432]: ').strip() or '5432'
    if not puerto.isdigit() or not 1 <= int(puerto) <= 65535:
        raise ValueError('Puerto no valido.')
    clave_pg = getpass.getpass('Contrasena de postgres (la de la instalacion, NO la de kala_app): ')
    conexion = psycopg.connect(
        host='localhost', port=int(puerto), dbname='kala_db',
        user='postgres', password=clave_pg, connect_timeout=5,
        application_name='kala_creacion_admin',
    )
    del clave_pg
    with conexion as conn:
        conn.execute("SET LOCAL lock_timeout = '5s'")
        conn.execute("SET LOCAL statement_timeout = '15s'")
        conn.execute('SET LOCAL ROLE kala_owner')
        # ALTAS DE USUARIOSXD
        conn.execute('LOCK TABLE public.usuarios IN EXCLUSIVE MODE')
        if conn.execute(
            "SELECT 1 FROM public.usuarios WHERE rol = 'ADMINISTRADOR' LIMIT 1"
        ).fetchone():
            raise ValueError('Ya existe un administrador. No se modifico ninguna cuenta.')
        if conn.execute(
            'SELECT 1 FROM public.usuarios WHERE lower(usuario) = lower(%s)',
            (usuario,),
        ).fetchone():
            raise ValueError('Ese usuario ya existe. No se modifico ninguna cuenta.')

        admin_id = conn.execute(
            "INSERT INTO public.usuarios (nombre, usuario, password_hash, rol) "
            "VALUES (%s, %s, %s, 'ADMINISTRADOR') RETURNING id",
            (nombre, usuario, password_hash),
        ).fetchone()[0]
        conn.execute(
            'INSERT INTO public.auditoria '
            '(usuario_id, origen, accion, entidad, registro_id, descripcion) '
            "VALUES (NULL, 'SISTEMA', 'CREAR_ADMIN_INICIAL', 'usuarios', %s, %s)",
            (admin_id, 'Creacion inicial del administrador mediante herramienta local.'),
        )
    print(f'Administrador creado correctamente. Usuario: {usuario} | ID: {admin_id}')
    print('Contrasena protegida con Argon2id. Alta registrada en auditoria.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print('\nOperacion interrumpida. Verifica usuarios antes de volver a ejecutar.')
        sys.exit(1)
    except getpass.GetPassWarning:
        print('No se puede ocultar la contrasena en esta consola. Ejecuta el archivo desde CMD.')
        sys.exit(1)
    except ValueError as exc:
        print(f'No se completo el alta: {exc}')
        sys.exit(1)
    except psycopg.OperationalError:
        print('Error de conexion o transaccion. Revisa PostgreSQL, puerto y contrasena de postgres.')
        print('Si hubo una desconexion al guardar, consulta usuarios antes de reintentar.')
        sys.exit(1)
    except psycopg.Error as exc:
        print(f'Error de base de datos. Codigo SQLSTATE: {exc.sqlstate or "no disponible"}.')
        print('Comprueba que existen las 19 tablas y el rol kala_owner.')
        sys.exit(1)
    except Argon2Error:
        print('No se pudo proteger o verificar la contrasena. No se completo el alta.')
        sys.exit(1)
