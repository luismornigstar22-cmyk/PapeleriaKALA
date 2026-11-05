-- pgAdmin / kala_db / postgres. Ejecutar completo después de 03_kapso_r2.sql.
BEGIN;
DO $$ BEGIN
 IF current_database()<>'kala_db' THEN RAISE EXCEPTION 'Selecciona kala_db'; END IF;
 IF NOT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='kala_envios' AND column_name='canal') THEN
  RAISE EXCEPTION 'Aplica primero 03_kapso_r2.sql';
 END IF;
END $$;
SET LOCAL ROLE kala_owner;
CREATE TABLE IF NOT EXISTS public.kala_consultas_whatsapp (
 id uuid PRIMARY KEY,
 phone_id text NOT NULL,
 mensaje_entrada text NOT NULL,
 remitente text NOT NULL,
 comando text NOT NULL,
 solicitado_en timestamptz NOT NULL,
 procesado_en timestamptz NOT NULL DEFAULT now(),
 envio_id uuid NOT NULL REFERENCES public.kala_envios(id),
 UNIQUE(phone_id,mensaje_entrada)
);
GRANT SELECT,INSERT ON public.kala_consultas_whatsapp TO kala_app;
COMMIT;
