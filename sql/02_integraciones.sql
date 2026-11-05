-- Ejecutar COMPLETO en kala_db, como postgres, después de 01_habilitar_admin.sql.
BEGIN;
DO $$ BEGIN
 IF current_database()<>'kala_db' THEN RAISE EXCEPTION 'Selecciona kala_db'; END IF;
 IF to_regclass('public.kala_operaciones') IS NULL THEN RAISE EXCEPTION 'Ejecuta primero 01_habilitar_admin.sql'; END IF;
END $$;
SET LOCAL ROLE kala_owner;
CREATE TABLE IF NOT EXISTS public.kala_config_integraciones (
 id integer PRIMARY KEY CHECK(id=1), datos jsonb NOT NULL DEFAULT '{}'::jsonb,
 actualizado_en timestamptz NOT NULL DEFAULT now()
);
INSERT INTO public.kala_config_integraciones(id) VALUES(1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS public.kala_envios (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), dedupe text UNIQUE,
 usuario_id bigint NOT NULL REFERENCES public.usuarios(id), titulo text NOT NULL,
 destino text NOT NULL, contenido text NOT NULL,
 modo text NOT NULL CHECK(modo IN ('SIMULACION','REAL')),
 estado text NOT NULL DEFAULT 'PENDIENTE' CHECK(estado IN ('PENDIENTE','PROCESANDO','SIMULADO','ACEPTADO','ENTREGADO','LEIDO','ERROR','REVISION','CANCELADO')),
 mensaje_id text UNIQUE, consulta_en timestamptz, intentos integer NOT NULL DEFAULT 0,
 detalle text NOT NULL DEFAULT '', creado_en timestamptz NOT NULL DEFAULT now(),
 actualizado_en timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS kala_envios_pendientes ON public.kala_envios(estado,creado_en);
CREATE TABLE IF NOT EXISTS public.kala_respaldos (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), estado text NOT NULL,
 archivo text NOT NULL DEFAULT '', detalle text NOT NULL DEFAULT '',
 creado_en timestamptz NOT NULL DEFAULT now()
);
-- El aviso se guarda en la MISMA transacción del cierre. Si no hay Internet,
-- permanece pendiente. El trigger también cubre cierres de futuros cajeros.
CREATE OR REPLACE FUNCTION public.kala_encolar_cierre() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE cfg jsonb; empleado text; rol_empleado text; caja text;
 ventas bigint; efectivo bigint; tarjeta bigint; canceladas bigint; simuladas bigint; arqueo record; texto text;
BEGIN
 IF NEW.estado='CERRADO' AND OLD.estado IS DISTINCT FROM NEW.estado THEN
  SELECT datos INTO cfg FROM public.kala_config_integraciones WHERE id=1;
  IF COALESCE((cfg->>'auto_close')::boolean,true) THEN
   SELECT u.nombre,u.rol,c.nombre INTO empleado,rol_empleado,caja FROM public.usuarios u,public.cajas c WHERE u.id=NEW.usuario_id AND c.id=NEW.caja_id;
   SELECT COALESCE(sum(total_centavos) FILTER (WHERE estado='COBRADA'),0),count(*) FILTER (WHERE estado='CANCELADA') INTO ventas,canceladas FROM public.ventas WHERE turno_id=NEW.id;
   SELECT COALESCE(sum(p.importe_centavos) FILTER (WHERE p.metodo='EFECTIVO'),0),COALESCE(sum(p.importe_centavos) FILTER (WHERE p.metodo='TARJETA'),0) INTO efectivo,tarjeta FROM public.pagos_venta p JOIN public.ventas v ON v.id=p.venta_id WHERE v.turno_id=NEW.id AND v.cobrado_en IS NOT NULL;
   SELECT * INTO arqueo FROM public.arqueos WHERE turno_id=NEW.id;
   SELECT count(*) INTO simuladas FROM public.pagos_venta p JOIN public.ventas v ON v.id=p.venta_id WHERE v.turno_id=NEW.id AND p.metodo='TARJETA' AND p.referencia_terminal LIKE 'SIM-%';
   texto=format(E'PAPELERÍA KALA\nCIERRE DE TURNO #%s\n%s (%s) terminó su turno.\nCaja: %s\nApertura: %s\nCierre: %s\nVentas vigentes: $%s\nCobros originales efectivo: $%s\nCobros originales tarjeta: $%s\nTickets cancelados: %s\nEfectivo esperado (incluye movimientos y reembolsos): $%s\nContado: $%s\nDiferencia: $%s\nObservaciones: %s',NEW.id,empleado,rol_empleado,caja,NEW.abierto_en,NEW.cerrado_en,round(ventas/100.0,2),round(efectivo/100.0,2),round(tarjeta/100.0,2),canceladas,round(arqueo.efectivo_esperado_centavos/100.0,2),round(arqueo.efectivo_contado_centavos/100.0,2),round(arqueo.diferencia_centavos/100.0,2),COALESCE(NEW.observaciones,''));
   texto=texto||E'\nPagos de tarjeta con terminal simulada (sin cobro bancario): '||simuladas;
   INSERT INTO public.kala_envios(dedupe,usuario_id,titulo,destino,contenido,modo)
   VALUES('cierre:'||NEW.id,NEW.usuario_id,'Cierre de turno '||NEW.id,COALESCE(NULLIF(cfg->>'owner',''),'DUEÑO SIN CONFIGURAR'),texto,COALESCE(cfg->>'wa_mode','SIMULACION')) ON CONFLICT(dedupe) DO NOTHING;
  END IF;
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS kala_aviso_cierre ON public.turnos;
CREATE TRIGGER kala_aviso_cierre AFTER UPDATE OF estado ON public.turnos FOR EACH ROW EXECUTE FUNCTION public.kala_encolar_cierre();
GRANT SELECT,INSERT,UPDATE ON public.kala_config_integraciones,public.kala_envios,public.kala_respaldos TO kala_app;
COMMIT;
