from getpass import getpass
import sys
import psycopg
from kala_admin.schema import missing_columns

def main():
    print('KALA · Verificación de PostgreSQL local (solo lectura)')
    port=input('Puerto [5432]: ').strip() or '5432'
    password=getpass('Contraseña PostgreSQL de kala_app: ')
    try:
        with psycopg.connect(host='localhost',port=port,dbname='kala_db',user='kala_app',password=password,connect_timeout=5) as c:
            c.execute('SET TRANSACTION READ ONLY')
            missing=missing_columns(c)
            if missing:
                print('Faltan columnas esperadas. NO ejecutes cambios para inventarlas; comparte este listado para adaptar el código:')
                print('\n'.join(missing));return 1
            if not c.execute("SELECT to_regclass('public.kala_operaciones')").fetchone()[0]:
                print('Esquema original compatible. Falta ejecutar sql/01_habilitar_admin.sql en pgAdmin.');return 1
            nuevos=['kala_config_integraciones','kala_envios','kala_respaldos']
            faltantes=[t for t in nuevos if not c.execute('SELECT to_regclass(%s)',('public.'+t,)).fetchone()[0]]
            if faltantes:
                print('Falta la actualización v2. Abre y ejecuta sql/02_integraciones.sql en pgAdmin como postgres.');return 1
            rows=c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('productos','usuarios','ventas','movimientos_inventario','kala_operaciones','kala_config_integraciones','kala_envios','kala_respaldos') AND NOT (has_table_privilege(current_user, 'public.'||tablename, 'SELECT') AND has_table_privilege(current_user, 'public.'||tablename, 'INSERT') AND has_table_privilege(current_user, 'public.'||tablename, 'UPDATE'))").fetchall()
            if rows:print('Faltan permisos:',rows);return 1
            print('Columnas y permisos básicos correctos. Inicia con: python iniciar_kala.py')
            print('Haz una venta de prueba, revisa existencias y realiza un cierre antes de usarlo en mostrador.');return 0
    except psycopg.Error as e:
        print('No se pudo verificar. Comprueba PostgreSQL, puerto, contraseña y permisos. Tipo:',type(e).__name__);return 1
if __name__=='__main__':sys.exit(main())
