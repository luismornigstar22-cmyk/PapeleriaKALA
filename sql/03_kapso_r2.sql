-- Abrir en pgAdmin, kala_db, como postgres. Ejecutar completo.
BEGIN;
DO $$ BEGIN
 IF current_database()<>'kala_db' THEN RAISE EXCEPTION 'Selecciona kala_db'; END IF;
 IF to_regclass('public.kala_envios') IS NULL THEN RAISE EXCEPTION 'Aplica primero 02_integraciones.sql'; END IF;
END $$;
SET LOCAL ROLE kala_owner;
ALTER TABLE public.kala_envios ADD COLUMN IF NOT EXISTS canal jsonb NOT NULL DEFAULT '{}'::jsonb;
-- Congelar proveedor, emisor y formato al encolar; jamás guardar claves aquí.
CREATE OR REPLACE FUNCTION public.kala_fijar_canal() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE cfg jsonb;
BEGIN
 SELECT datos INTO cfg FROM public.kala_config_integraciones WHERE id=1;
 NEW.canal=jsonb_build_object(
  'wa_provider',COALESCE(cfg->>'wa_provider','META'),
  'wa_format',COALESCE(cfg->>'wa_format','TEMPLATE_PDF'),
  'phone_id',COALESCE(cfg->>'phone_id',''),
  'api_version',COALESCE(cfg->>'api_version',''),
  'template',COALESCE(cfg->>'template',''),
  'language',COALESCE(cfg->>'language','es_MX'));
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS kala_canal_envio ON public.kala_envios;
CREATE TRIGGER kala_canal_envio BEFORE INSERT ON public.kala_envios
FOR EACH ROW EXECUTE FUNCTION public.kala_fijar_canal();
-- Los envíos reales antiguos pertenecían a la integración Meta original.
UPDATE public.kala_envios SET canal=jsonb_build_object('wa_provider','META','wa_format','TEMPLATE_PDF',
 'phone_id',COALESCE(c.datos->>'phone_id',''),'api_version',COALESCE(c.datos->>'api_version',''),
 'template',COALESCE(c.datos->>'template',''),'language',COALESCE(c.datos->>'language','es_MX'))
FROM public.kala_config_integraciones c WHERE c.id=1 AND canal='{}'::jsonb;
COMMIT;
