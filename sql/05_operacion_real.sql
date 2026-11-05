-- Ejecutar completo como postgres, conectado a kala_db. Requiere migraciones 01 a 04.
BEGIN;
DO $$ BEGIN
 IF current_database()<>'kala_db' THEN RAISE EXCEPTION 'Selecciona kala_db'; END IF;
 IF to_regclass('public.kala_consultas_whatsapp') IS NULL THEN RAISE EXCEPTION 'Falta la migración 04 del bot'; END IF;
END $$;
SET LOCAL ROLE kala_owner;
UPDATE public.kala_config_integraciones SET datos=datos||jsonb_build_object(
 'simulate_hardware',false,'wa_mode','REAL','cloud_mode','REAL',
 'wa_enabled',CASE WHEN datos->>'wa_mode'='REAL' THEN COALESCE((datos->>'wa_enabled')::boolean,false) ELSE false END,
 'bot_enabled',CASE WHEN datos->>'wa_mode'='REAL' THEN COALESCE((datos->>'bot_enabled')::boolean,false) ELSE false END,
 'cloud_enabled',CASE WHEN datos->>'cloud_mode'='REAL' THEN COALESCE((datos->>'cloud_enabled')::boolean,false) ELSE false END,
 'operacion_real_version',1),actualizado_en=now() WHERE id=1;
CREATE OR REPLACE FUNCTION public.kala_encolar_cierre() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE cfg jsonb; empleado text; rol_empleado text; caja text;
 ventas bigint; efectivo bigint; tarjeta bigint; canceladas bigint; simuladas bigint; arqueo record; texto text;
BEGIN
 IF NEW.estado='CERRADO' AND OLD.estado IS DISTINCT FROM NEW.estado THEN
  SELECT datos INTO cfg FROM public.kala_config_integraciones WHERE id=1;
  IF COALESCE((cfg->>'auto_close')::boolean,false) AND COALESCE((cfg->>'wa_enabled')::boolean,false) AND COALESCE((cfg->>'owner_consent')::boolean,false) AND cfg->>'wa_mode'='REAL' AND cfg->>'owner' ~ '^[1-9][0-9]{7,14}$' THEN
   SELECT u.nombre,u.rol,c.nombre INTO empleado,rol_empleado,caja FROM public.usuarios u,public.cajas c WHERE u.id=NEW.usuario_id AND c.id=NEW.caja_id;
   SELECT COALESCE(sum(total_centavos) FILTER (WHERE estado='COBRADA'),0),count(*) FILTER (WHERE estado='CANCELADA') INTO ventas,canceladas FROM public.ventas WHERE turno_id=NEW.id;
   SELECT COALESCE(sum(p.importe_centavos) FILTER (WHERE p.metodo='EFECTIVO'),0),COALESCE(sum(p.importe_centavos) FILTER (WHERE p.metodo='TARJETA'),0) INTO efectivo,tarjeta FROM public.pagos_venta p JOIN public.ventas v ON v.id=p.venta_id WHERE v.turno_id=NEW.id AND v.cobrado_en IS NOT NULL;
   SELECT * INTO arqueo FROM public.arqueos WHERE turno_id=NEW.id;
   SELECT count(*) INTO simuladas FROM public.pagos_venta p JOIN public.ventas v ON v.id=p.venta_id WHERE v.turno_id=NEW.id AND p.metodo='TARJETA' AND p.referencia_terminal LIKE 'SIM-%';
   texto=format(E'PAPELERÍA KALA\nCIERRE DE TURNO #%s\n%s (%s) terminó su turno.\nCaja: %s\nApertura: %s\nCierre: %s\nVentas vigentes: $%s\nCobros originales efectivo: $%s\nCobros originales tarjeta: $%s\nTickets cancelados: %s\nEfectivo esperado (incluye movimientos y reembolsos): $%s\nContado: $%s\nDiferencia: $%s\nObservaciones: %s',NEW.id,empleado,rol_empleado,caja,NEW.abierto_en,NEW.cerrado_en,round(ventas/100.0,2),round(efectivo/100.0,2),round(tarjeta/100.0,2),canceladas,round(arqueo.efectivo_esperado_centavos/100.0,2),round(arqueo.efectivo_contado_centavos/100.0,2),round(arqueo.diferencia_centavos/100.0,2),COALESCE(NEW.observaciones,''));
   IF simuladas>0 THEN texto=texto||E'\nPagos históricos de prueba sin cobro bancario: '||simuladas; END IF;
   INSERT INTO public.kala_envios(dedupe,usuario_id,titulo,destino,contenido,modo)
   VALUES('cierre:'||NEW.id,NEW.usuario_id,'Cierre de turno '||NEW.id,COALESCE(NULLIF(cfg->>'owner',''),'DUEÑO SIN CONFIGURAR'),texto,'REAL') ON CONFLICT(dedupe) DO NOTHING;
  END IF;
 END IF;
 RETURN NEW;
END $$;
COMMIT;
