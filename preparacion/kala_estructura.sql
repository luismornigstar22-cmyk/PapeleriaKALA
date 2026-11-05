--
-- PostgreSQL database dump
--

\restrict 9xLkwSzLGCfH0zydeKljDDCFKHkfhrIaQUQSgOTthvAMubHtuhue9CY1zvA823s

-- Dumped from database version 18.6
-- Dumped by pg_dump version 18.6

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: kala_encolar_cierre(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.kala_encolar_cierre() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'public'
    AS $_$
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
END $_$;


--
-- Name: kala_fijar_canal(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.kala_fijar_canal() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'public'
    AS $$
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


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: arqueos; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.arqueos (
    id bigint NOT NULL,
    turno_id bigint NOT NULL,
    registrado_por bigint NOT NULL,
    efectivo_contado_centavos bigint NOT NULL,
    efectivo_esperado_centavos bigint NOT NULL,
    diferencia_centavos bigint GENERATED ALWAYS AS ((efectivo_contado_centavos - efectivo_esperado_centavos)) STORED,
    observaciones_cajero text,
    creado_en timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    revisado_por bigint,
    revisado_en timestamp with time zone,
    observaciones_revision text,
    CONSTRAINT arqueos_contado_valido CHECK ((efectivo_contado_centavos >= 0)),
    CONSTRAINT arqueos_revision_coherente CHECK ((((revisado_por IS NULL) AND (revisado_en IS NULL) AND (observaciones_revision IS NULL)) OR ((revisado_por IS NOT NULL) AND (revisado_en IS NOT NULL) AND (revisado_en >= creado_en) AND (observaciones_revision IS NOT NULL) AND (btrim(observaciones_revision) <> ''::text))))
);


--
-- Name: arqueos_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.arqueos ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.arqueos_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auditoria; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auditoria (
    id bigint NOT NULL,
    usuario_id bigint,
    origen character varying(10) DEFAULT 'USUARIO'::character varying NOT NULL,
    accion character varying(80) NOT NULL,
    entidad character varying(80) NOT NULL,
    registro_id bigint,
    descripcion text NOT NULL,
    detalles jsonb DEFAULT '{}'::jsonb NOT NULL,
    creado_en timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT auditoria_detalles_validos CHECK ((jsonb_typeof(detalles) = 'object'::text)),
    CONSTRAINT auditoria_origen_valido CHECK (((((origen)::text = 'USUARIO'::text) AND (usuario_id IS NOT NULL)) OR (((origen)::text = 'SISTEMA'::text) AND (usuario_id IS NULL)))),
    CONSTRAINT auditoria_textos_validos CHECK (((btrim((accion)::text) <> ''::text) AND (btrim((entidad)::text) <> ''::text) AND (btrim(descripcion) <> ''::text)))
);


--
-- Name: auditoria_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auditoria ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.auditoria_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: cajas; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cajas (
    id bigint NOT NULL,
    nombre character varying(60) NOT NULL,
    descripcion character varying(200),
    activo boolean DEFAULT true NOT NULL,
    creado_en timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT cajas_nombre_valido CHECK ((((nombre)::text = btrim((nombre)::text)) AND ((nombre)::text <> ''::text)))
);


--
-- Name: cajas_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.cajas ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.cajas_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: cola_sincronizacion; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cola_sincronizacion (
    id bigint NOT NULL,
    evento_id uuid DEFAULT gen_random_uuid() NOT NULL,
    destino character varying(20) NOT NULL,
    tipo_evento character varying(80) NOT NULL,
    datos jsonb NOT NULL,
    estado character varying(20) DEFAULT 'PENDIENTE'::character varying NOT NULL,
    intentos integer DEFAULT 0 NOT NULL,
    max_intentos integer DEFAULT 10 NOT NULL,
    creado_en timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    proximo_intento_en timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    ultimo_intento_en timestamp with time zone,
    bloqueo_token uuid,
    bloqueado_hasta timestamp with time zone,
    completado_en timestamp with time zone,
    referencia_externa text,
    ultimo_error text,
    CONSTRAINT cola_bloqueo_coherente CHECK (((((estado)::text = 'PROCESANDO'::text) AND (bloqueo_token IS NOT NULL) AND (bloqueado_hasta IS NOT NULL)) OR (((estado)::text <> 'PROCESANDO'::text) AND (bloqueo_token IS NULL) AND (bloqueado_hasta IS NULL)))),
    CONSTRAINT cola_datos_validos CHECK ((jsonb_typeof(datos) = 'object'::text)),
    CONSTRAINT cola_destino_valido CHECK (((destino)::text = ANY ((ARRAY['NUBE'::character varying, 'WHATSAPP'::character varying])::text[]))),
    CONSTRAINT cola_error_coherente CHECK ((((estado)::text <> 'FALLIDO'::text) OR ((ultimo_error IS NOT NULL) AND (btrim(ultimo_error) <> ''::text)))),
    CONSTRAINT cola_estado_valido CHECK (((estado)::text = ANY ((ARRAY['PENDIENTE'::character varying, 'PROCESANDO'::character varying, 'COMPLETADO'::character varying, 'FALLIDO'::character varying])::text[]))),
    CONSTRAINT cola_finalizacion_coherente CHECK (((((estado)::text = 'COMPLETADO'::text) AND (completado_en IS NOT NULL) AND (completado_en >= creado_en)) OR (((estado)::text <> 'COMPLETADO'::text) AND (completado_en IS NULL)))),
    CONSTRAINT cola_intentos_validos CHECK (((intentos >= 0) AND (max_intentos > 0))),
    CONSTRAINT cola_tipo_evento_valido CHECK ((btrim((tipo_evento)::text) <> ''::text))
);


--
-- Name: cola_sincronizacion_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.cola_sincronizacion ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.cola_sincronizacion_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: configuracion; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.configuracion (
    clave character varying(100) NOT NULL,
    valor jsonb NOT NULL,
    descripcion text NOT NULL,
    actualizado_por bigint,
    actualizado_en timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT configuracion_clave_valida CHECK ((((clave)::text = btrim((clave)::text)) AND ((clave)::text <> ''::text))),
    CONSTRAINT configuracion_descripcion_valida CHECK ((btrim(descripcion) <> ''::text))
);


--
-- Name: conteos_inventario; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conteos_inventario (
    id bigint NOT NULL,
    producto_id bigint NOT NULL,
    contado_por bigint NOT NULL,
    existencia_sistema numeric(14,3) NOT NULL,
    cantidad_contada numeric(14,3) NOT NULL,
    diferencia numeric(14,3) GENERATED ALWAYS AS ((cantidad_contada - existencia_sistema)) STORED,
    motivo text NOT NULL,
    creado_en timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT conteos_cantidades_validas CHECK (((existencia_sistema >= (0)::numeric) AND (cantidad_contada >= (0)::numeric))),
    CONSTRAINT conteos_motivo_valido CHECK ((btrim(motivo) <> ''::text))
);


--
-- Name: conteos_inventario_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.conteos_inventario ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.conteos_inventario_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: detalle_arqueo; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.detalle_arqueo (
    id bigint NOT NULL,
    arqueo_id bigint NOT NULL,
    tipo character varying(10) NOT NULL,
    denominacion_centavos bigint NOT NULL,
    cantidad integer NOT NULL,
    subtotal_centavos bigint GENERATED ALWAYS AS ((denominacion_centavos * (cantidad)::bigint)) STORED,
    CONSTRAINT detalle_arqueo_cantidad_valida CHECK ((cantidad >= 0)),
    CONSTRAINT detalle_arqueo_denominacion_valida CHECK ((denominacion_centavos > 0)),
    CONSTRAINT detalle_arqueo_tipo_valido CHECK (((tipo)::text = ANY ((ARRAY['BILLETE'::character varying, 'MONEDA'::character varying])::text[])))
);


--
-- Name: detalle_arqueo_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.detalle_arqueo ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.detalle_arqueo_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: detalle_venta; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.detalle_venta (
    id bigint NOT NULL,
    venta_id bigint NOT NULL,
    producto_id bigint NOT NULL,
    codigo_producto character varying(50) NOT NULL,
    nombre_producto character varying(150) NOT NULL,
    unidad character varying(20) NOT NULL,
    cantidad numeric(14,3) NOT NULL,
    precio_unitario_centavos bigint NOT NULL,
    costo_unitario_centavos bigint NOT NULL,
    aplica_mayoreo boolean DEFAULT false NOT NULL,
    subtotal_centavos bigint GENERATED ALWAYS AS ((round((cantidad * (precio_unitario_centavos)::numeric), 0))::bigint) STORED,
    CONSTRAINT detalle_venta_cantidad_valida CHECK ((cantidad > (0)::numeric)),
    CONSTRAINT detalle_venta_datos_validos CHECK (((btrim((codigo_producto)::text) <> ''::text) AND (btrim((nombre_producto)::text) <> ''::text))),
    CONSTRAINT detalle_venta_importes_validos CHECK (((precio_unitario_centavos >= 0) AND (costo_unitario_centavos >= 0))),
    CONSTRAINT detalle_venta_unidad_valida CHECK (((unidad)::text = ANY ((ARRAY['PIEZA'::character varying, 'HOJA'::character varying, 'HORA'::character varying, 'METRO'::character varying, 'PAQUETE'::character varying])::text[])))
);


--
-- Name: detalle_venta_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.detalle_venta ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.detalle_venta_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: insumos_servicio; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.insumos_servicio (
    id bigint NOT NULL,
    servicio_id bigint NOT NULL,
    insumo_id bigint NOT NULL,
    cantidad_por_servicio numeric(14,3) NOT NULL,
    activo boolean DEFAULT true NOT NULL,
    CONSTRAINT insumos_cantidad_valida CHECK ((cantidad_por_servicio > (0)::numeric)),
    CONSTRAINT insumos_distintos CHECK ((servicio_id <> insumo_id))
);


--
-- Name: insumos_servicio_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.insumos_servicio ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.insumos_servicio_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: kala_config_integraciones; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kala_config_integraciones (
    id integer NOT NULL,
    datos jsonb DEFAULT '{}'::jsonb NOT NULL,
    actualizado_en timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT kala_config_integraciones_id_check CHECK ((id = 1))
);


--
-- Name: kala_consultas_whatsapp; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kala_consultas_whatsapp (
    id uuid NOT NULL,
    phone_id text NOT NULL,
    mensaje_entrada text NOT NULL,
    remitente text NOT NULL,
    comando text NOT NULL,
    solicitado_en timestamp with time zone NOT NULL,
    procesado_en timestamp with time zone DEFAULT now() NOT NULL,
    envio_id uuid NOT NULL
);


--
-- Name: kala_envios; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kala_envios (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    dedupe text,
    usuario_id bigint NOT NULL,
    titulo text NOT NULL,
    destino text NOT NULL,
    contenido text NOT NULL,
    modo text NOT NULL,
    estado text DEFAULT 'PENDIENTE'::text NOT NULL,
    mensaje_id text,
    consulta_en timestamp with time zone,
    intentos integer DEFAULT 0 NOT NULL,
    detalle text DEFAULT ''::text NOT NULL,
    creado_en timestamp with time zone DEFAULT now() NOT NULL,
    actualizado_en timestamp with time zone DEFAULT now() NOT NULL,
    canal jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT kala_envios_estado_check CHECK ((estado = ANY (ARRAY['PENDIENTE'::text, 'PROCESANDO'::text, 'SIMULADO'::text, 'ACEPTADO'::text, 'ENTREGADO'::text, 'LEIDO'::text, 'ERROR'::text, 'REVISION'::text, 'CANCELADO'::text]))),
    CONSTRAINT kala_envios_modo_check CHECK ((modo = ANY (ARRAY['SIMULACION'::text, 'REAL'::text])))
);


--
-- Name: kala_operaciones; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kala_operaciones (
    id uuid NOT NULL,
    usuario_id bigint NOT NULL,
    tipo character varying(40) NOT NULL,
    resultado jsonb NOT NULL,
    creado_en timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: kala_respaldos; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kala_respaldos (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    estado text NOT NULL,
    archivo text DEFAULT ''::text NOT NULL,
    detalle text DEFAULT ''::text NOT NULL,
    creado_en timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: movimientos_caja; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.movimientos_caja (
    id bigint NOT NULL,
    turno_id bigint NOT NULL,
    registrado_por bigint NOT NULL,
    tipo character varying(20) NOT NULL,
    importe_centavos bigint NOT NULL,
    motivo text NOT NULL,
    referencia character varying(100),
    creado_en timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT movimientos_caja_importe_valido CHECK (((((tipo)::text = 'FONDO_INICIAL'::text) AND (importe_centavos >= 0)) OR (((tipo)::text = ANY ((ARRAY['ENTRADA'::character varying, 'RETIRO'::character varying])::text[])) AND (importe_centavos > 0)))),
    CONSTRAINT movimientos_caja_motivo_valido CHECK ((btrim(motivo) <> ''::text)),
    CONSTRAINT movimientos_caja_tipo_valido CHECK (((tipo)::text = ANY ((ARRAY['FONDO_INICIAL'::character varying, 'ENTRADA'::character varying, 'RETIRO'::character varying])::text[])))
);


--
-- Name: movimientos_caja_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.movimientos_caja ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.movimientos_caja_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: movimientos_inventario; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.movimientos_inventario (
    id bigint NOT NULL,
    producto_id bigint NOT NULL,
    registrado_por bigint NOT NULL,
    tipo character varying(25) NOT NULL,
    cantidad numeric(14,3) NOT NULL,
    costo_unitario_centavos bigint NOT NULL,
    motivo text NOT NULL,
    proveedor character varying(150),
    referencia character varying(100),
    detalle_venta_id bigint,
    conteo_id bigint,
    creado_en timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT movimientos_inventario_costo_valido CHECK ((costo_unitario_centavos >= 0)),
    CONSTRAINT movimientos_inventario_motivo_valido CHECK ((btrim(motivo) <> ''::text)),
    CONSTRAINT movimientos_inventario_origen_valido CHECK (((((tipo)::text = ANY ((ARRAY['VENTA'::character varying, 'CONSUMO_SERVICIO'::character varying, 'DEVOLUCION_VENTA'::character varying])::text[])) AND (detalle_venta_id IS NOT NULL) AND (conteo_id IS NULL)) OR (((tipo)::text = 'AJUSTE_CONTEO'::text) AND (conteo_id IS NOT NULL) AND (detalle_venta_id IS NULL)) OR (((tipo)::text = ANY ((ARRAY['ENTRADA'::character varying, 'MERMA'::character varying, 'USO_INTERNO'::character varying])::text[])) AND (detalle_venta_id IS NULL) AND (conteo_id IS NULL)))),
    CONSTRAINT movimientos_inventario_signo_valido CHECK (((((tipo)::text = ANY ((ARRAY['ENTRADA'::character varying, 'DEVOLUCION_VENTA'::character varying])::text[])) AND (cantidad > (0)::numeric)) OR (((tipo)::text = ANY ((ARRAY['VENTA'::character varying, 'CONSUMO_SERVICIO'::character varying, 'MERMA'::character varying, 'USO_INTERNO'::character varying])::text[])) AND (cantidad < (0)::numeric)) OR (((tipo)::text = 'AJUSTE_CONTEO'::text) AND (cantidad <> (0)::numeric)))),
    CONSTRAINT movimientos_inventario_tipo_valido CHECK (((tipo)::text = ANY ((ARRAY['ENTRADA'::character varying, 'VENTA'::character varying, 'CONSUMO_SERVICIO'::character varying, 'MERMA'::character varying, 'USO_INTERNO'::character varying, 'DEVOLUCION_VENTA'::character varying, 'AJUSTE_CONTEO'::character varying])::text[])))
);


--
-- Name: movimientos_inventario_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.movimientos_inventario ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.movimientos_inventario_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: pagos_venta; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pagos_venta (
    id bigint NOT NULL,
    venta_id bigint NOT NULL,
    metodo character varying(15) NOT NULL,
    importe_centavos bigint NOT NULL,
    recibido_centavos bigint,
    cambio_centavos bigint DEFAULT 0 NOT NULL,
    referencia_terminal character varying(100),
    creado_en timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pagos_venta_datos_coherentes CHECK (((((metodo)::text = 'EFECTIVO'::text) AND (recibido_centavos IS NOT NULL) AND (recibido_centavos >= importe_centavos) AND (cambio_centavos = (recibido_centavos - importe_centavos)) AND (referencia_terminal IS NULL)) OR (((metodo)::text = 'TARJETA'::text) AND (recibido_centavos IS NULL) AND (cambio_centavos = 0) AND (referencia_terminal IS NOT NULL) AND (btrim((referencia_terminal)::text) <> ''::text)))),
    CONSTRAINT pagos_venta_importes_validos CHECK (((importe_centavos > 0) AND (cambio_centavos >= 0))),
    CONSTRAINT pagos_venta_metodo_valido CHECK (((metodo)::text = ANY ((ARRAY['EFECTIVO'::character varying, 'TARJETA'::character varying])::text[])))
);


--
-- Name: pagos_venta_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.pagos_venta ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.pagos_venta_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: productos; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.productos (
    id bigint NOT NULL,
    codigo character varying(50) NOT NULL,
    codigo_barras character varying(100),
    nombre character varying(150) NOT NULL,
    tipo character varying(20) NOT NULL,
    unidad character varying(20) DEFAULT 'PIEZA'::character varying NOT NULL,
    precio_venta_centavos bigint NOT NULL,
    costo_referencia_centavos bigint DEFAULT 0 NOT NULL,
    controla_stock boolean DEFAULT true NOT NULL,
    existencia numeric(14,3) DEFAULT 0 NOT NULL,
    punto_reorden numeric(14,3) DEFAULT 0 NOT NULL,
    activo boolean DEFAULT true NOT NULL,
    creado_en timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT productos_barras_validas CHECK (((codigo_barras IS NULL) OR (((codigo_barras)::text = btrim((codigo_barras)::text)) AND ((codigo_barras)::text <> ''::text)))),
    CONSTRAINT productos_codigo_valido CHECK ((((codigo)::text = btrim((codigo)::text)) AND ((codigo)::text <> ''::text))),
    CONSTRAINT productos_importes_validos CHECK (((precio_venta_centavos >= 0) AND (costo_referencia_centavos >= 0))),
    CONSTRAINT productos_nombre_valido CHECK ((btrim((nombre)::text) <> ''::text)),
    CONSTRAINT productos_sin_control_sin_existencias CHECK ((controla_stock OR ((existencia = (0)::numeric) AND (punto_reorden = (0)::numeric)))),
    CONSTRAINT productos_stock_valido CHECK (((existencia >= (0)::numeric) AND (punto_reorden >= (0)::numeric))),
    CONSTRAINT productos_tipo_valido CHECK (((tipo)::text = ANY ((ARRAY['PRODUCTO'::character varying, 'SERVICIO'::character varying])::text[]))),
    CONSTRAINT productos_unidad_valida CHECK (((unidad)::text = ANY ((ARRAY['PIEZA'::character varying, 'HOJA'::character varying, 'HORA'::character varying, 'METRO'::character varying, 'PAQUETE'::character varying])::text[]))),
    CONSTRAINT servicios_sin_stock_propio CHECK ((((tipo)::text <> 'SERVICIO'::text) OR (controla_stock = false)))
);


--
-- Name: productos_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.productos ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.productos_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: reembolsos; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reembolsos (
    id bigint NOT NULL,
    solicitud_id bigint NOT NULL,
    venta_id bigint NOT NULL,
    pago_id bigint NOT NULL,
    turno_id bigint NOT NULL,
    registrado_por bigint NOT NULL,
    importe_centavos bigint NOT NULL,
    referencia_terminal character varying(100),
    observaciones text,
    realizado_en timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT reembolsos_importe_valido CHECK ((importe_centavos > 0)),
    CONSTRAINT reembolsos_referencia_valida CHECK (((referencia_terminal IS NULL) OR (btrim((referencia_terminal)::text) <> ''::text)))
);


--
-- Name: reembolsos_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.reembolsos ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.reembolsos_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: reglas_mayoreo; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reglas_mayoreo (
    id bigint NOT NULL,
    producto_id bigint NOT NULL,
    cantidad_minima numeric(14,3) NOT NULL,
    precio_unitario_centavos bigint NOT NULL,
    activo boolean DEFAULT true NOT NULL,
    creado_en timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT mayoreo_cantidad_valida CHECK ((cantidad_minima > (0)::numeric)),
    CONSTRAINT mayoreo_precio_valido CHECK ((precio_unitario_centavos >= 0))
);


--
-- Name: reglas_mayoreo_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.reglas_mayoreo ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.reglas_mayoreo_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: solicitudes_cancelacion; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.solicitudes_cancelacion (
    id bigint NOT NULL,
    venta_id bigint NOT NULL,
    solicitado_por bigint NOT NULL,
    motivo text NOT NULL,
    estado character varying(15) DEFAULT 'PENDIENTE'::character varying NOT NULL,
    solicitado_en timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    resuelto_por bigint,
    resuelto_en timestamp with time zone,
    observaciones_resolucion text,
    CONSTRAINT cancelaciones_estado_valido CHECK (((estado)::text = ANY ((ARRAY['PENDIENTE'::character varying, 'APROBADA'::character varying, 'RECHAZADA'::character varying])::text[]))),
    CONSTRAINT cancelaciones_motivo_valido CHECK ((btrim(motivo) <> ''::text)),
    CONSTRAINT cancelaciones_resolucion_coherente CHECK (((((estado)::text = 'PENDIENTE'::text) AND (resuelto_por IS NULL) AND (resuelto_en IS NULL) AND (observaciones_resolucion IS NULL)) OR (((estado)::text = ANY ((ARRAY['APROBADA'::character varying, 'RECHAZADA'::character varying])::text[])) AND (resuelto_por IS NOT NULL) AND (resuelto_en IS NOT NULL) AND (resuelto_en >= solicitado_en) AND (observaciones_resolucion IS NOT NULL) AND (btrim(observaciones_resolucion) <> ''::text))))
);


--
-- Name: solicitudes_cancelacion_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.solicitudes_cancelacion ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.solicitudes_cancelacion_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: turnos; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.turnos (
    id bigint NOT NULL,
    caja_id bigint NOT NULL,
    usuario_id bigint NOT NULL,
    abierto_en timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    cerrado_en timestamp with time zone,
    estado character varying(15) DEFAULT 'ABIERTO'::character varying NOT NULL,
    observaciones text,
    CONSTRAINT turnos_cierre_coherente CHECK (((((estado)::text = 'ABIERTO'::text) AND (cerrado_en IS NULL)) OR (((estado)::text = 'CERRADO'::text) AND (cerrado_en IS NOT NULL) AND (cerrado_en >= abierto_en)))),
    CONSTRAINT turnos_estado_valido CHECK (((estado)::text = ANY ((ARRAY['ABIERTO'::character varying, 'CERRADO'::character varying])::text[])))
);


--
-- Name: turnos_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.turnos ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.turnos_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: usuarios; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usuarios (
    id bigint NOT NULL,
    nombre character varying(120) NOT NULL,
    usuario character varying(50) NOT NULL,
    password_hash text NOT NULL,
    rol character varying(20) NOT NULL,
    activo boolean DEFAULT true NOT NULL,
    creado_en timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT usuarios_hash_no_vacio CHECK ((btrim(password_hash) <> ''::text)),
    CONSTRAINT usuarios_nombre_valido CHECK ((btrim((nombre)::text) <> ''::text)),
    CONSTRAINT usuarios_rol_valido CHECK (((rol)::text = ANY ((ARRAY['ADMINISTRADOR'::character varying, 'CAJERO'::character varying])::text[]))),
    CONSTRAINT usuarios_usuario_valido CHECK ((((usuario)::text = btrim((usuario)::text)) AND ((usuario)::text <> ''::text)))
);


--
-- Name: usuarios_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.usuarios ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.usuarios_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: ventas; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ventas (
    id bigint NOT NULL,
    turno_id bigint NOT NULL,
    estado character varying(15) DEFAULT 'BORRADOR'::character varying NOT NULL,
    total_centavos bigint DEFAULT 0 NOT NULL,
    creado_en timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    cobrado_en timestamp with time zone,
    observaciones text,
    CONSTRAINT ventas_estado_cobro_coherente CHECK (((((estado)::text = 'BORRADOR'::text) AND (cobrado_en IS NULL)) OR (((estado)::text = 'COBRADA'::text) AND (cobrado_en IS NOT NULL)) OR ((estado)::text = 'CANCELADA'::text))),
    CONSTRAINT ventas_estado_valido CHECK (((estado)::text = ANY ((ARRAY['BORRADOR'::character varying, 'COBRADA'::character varying, 'CANCELADA'::character varying])::text[]))),
    CONSTRAINT ventas_fecha_cobro_valida CHECK (((cobrado_en IS NULL) OR (cobrado_en >= creado_en))),
    CONSTRAINT ventas_total_valido CHECK ((total_centavos >= 0))
);


--
-- Name: ventas_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.ventas ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.ventas_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: arqueos arqueos_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.arqueos
    ADD CONSTRAINT arqueos_pkey PRIMARY KEY (id);


--
-- Name: arqueos arqueos_turno_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.arqueos
    ADD CONSTRAINT arqueos_turno_id_key UNIQUE (turno_id);


--
-- Name: auditoria auditoria_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auditoria
    ADD CONSTRAINT auditoria_pkey PRIMARY KEY (id);


--
-- Name: cajas cajas_nombre_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cajas
    ADD CONSTRAINT cajas_nombre_key UNIQUE (nombre);


--
-- Name: cajas cajas_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cajas
    ADD CONSTRAINT cajas_pkey PRIMARY KEY (id);


--
-- Name: solicitudes_cancelacion cancelaciones_id_venta_unico; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.solicitudes_cancelacion
    ADD CONSTRAINT cancelaciones_id_venta_unico UNIQUE (id, venta_id);


--
-- Name: cola_sincronizacion cola_sincronizacion_evento_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cola_sincronizacion
    ADD CONSTRAINT cola_sincronizacion_evento_id_key UNIQUE (evento_id);


--
-- Name: cola_sincronizacion cola_sincronizacion_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cola_sincronizacion
    ADD CONSTRAINT cola_sincronizacion_pkey PRIMARY KEY (id);


--
-- Name: configuracion configuracion_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.configuracion
    ADD CONSTRAINT configuracion_pkey PRIMARY KEY (clave);


--
-- Name: conteos_inventario conteos_id_producto_unico; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conteos_inventario
    ADD CONSTRAINT conteos_id_producto_unico UNIQUE (id, producto_id);


--
-- Name: conteos_inventario conteos_inventario_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conteos_inventario
    ADD CONSTRAINT conteos_inventario_pkey PRIMARY KEY (id);


--
-- Name: detalle_arqueo detalle_arqueo_denominacion_unica; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detalle_arqueo
    ADD CONSTRAINT detalle_arqueo_denominacion_unica UNIQUE (arqueo_id, tipo, denominacion_centavos);


--
-- Name: detalle_arqueo detalle_arqueo_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detalle_arqueo
    ADD CONSTRAINT detalle_arqueo_pkey PRIMARY KEY (id);


--
-- Name: detalle_venta detalle_venta_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detalle_venta
    ADD CONSTRAINT detalle_venta_pkey PRIMARY KEY (id);


--
-- Name: detalle_venta detalle_venta_producto_unico; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detalle_venta
    ADD CONSTRAINT detalle_venta_producto_unico UNIQUE (venta_id, producto_id);


--
-- Name: insumos_servicio insumos_servicio_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insumos_servicio
    ADD CONSTRAINT insumos_servicio_pkey PRIMARY KEY (id);


--
-- Name: insumos_servicio insumos_servicio_unico; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insumos_servicio
    ADD CONSTRAINT insumos_servicio_unico UNIQUE (servicio_id, insumo_id);


--
-- Name: kala_config_integraciones kala_config_integraciones_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kala_config_integraciones
    ADD CONSTRAINT kala_config_integraciones_pkey PRIMARY KEY (id);


--
-- Name: kala_consultas_whatsapp kala_consultas_whatsapp_phone_id_mensaje_entrada_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kala_consultas_whatsapp
    ADD CONSTRAINT kala_consultas_whatsapp_phone_id_mensaje_entrada_key UNIQUE (phone_id, mensaje_entrada);


--
-- Name: kala_consultas_whatsapp kala_consultas_whatsapp_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kala_consultas_whatsapp
    ADD CONSTRAINT kala_consultas_whatsapp_pkey PRIMARY KEY (id);


--
-- Name: kala_envios kala_envios_dedupe_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kala_envios
    ADD CONSTRAINT kala_envios_dedupe_key UNIQUE (dedupe);


--
-- Name: kala_envios kala_envios_mensaje_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kala_envios
    ADD CONSTRAINT kala_envios_mensaje_id_key UNIQUE (mensaje_id);


--
-- Name: kala_envios kala_envios_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kala_envios
    ADD CONSTRAINT kala_envios_pkey PRIMARY KEY (id);


--
-- Name: kala_operaciones kala_operaciones_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kala_operaciones
    ADD CONSTRAINT kala_operaciones_pkey PRIMARY KEY (id);


--
-- Name: kala_respaldos kala_respaldos_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kala_respaldos
    ADD CONSTRAINT kala_respaldos_pkey PRIMARY KEY (id);


--
-- Name: reglas_mayoreo mayoreo_umbral_unico; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reglas_mayoreo
    ADD CONSTRAINT mayoreo_umbral_unico UNIQUE (producto_id, cantidad_minima);


--
-- Name: movimientos_caja movimientos_caja_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.movimientos_caja
    ADD CONSTRAINT movimientos_caja_pkey PRIMARY KEY (id);


--
-- Name: movimientos_inventario movimientos_inventario_conteo_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.movimientos_inventario
    ADD CONSTRAINT movimientos_inventario_conteo_id_key UNIQUE (conteo_id);


--
-- Name: movimientos_inventario movimientos_inventario_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.movimientos_inventario
    ADD CONSTRAINT movimientos_inventario_pkey PRIMARY KEY (id);


--
-- Name: pagos_venta pagos_venta_id_venta_unico; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pagos_venta
    ADD CONSTRAINT pagos_venta_id_venta_unico UNIQUE (id, venta_id);


--
-- Name: pagos_venta pagos_venta_metodo_unico; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pagos_venta
    ADD CONSTRAINT pagos_venta_metodo_unico UNIQUE (venta_id, metodo);


--
-- Name: pagos_venta pagos_venta_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pagos_venta
    ADD CONSTRAINT pagos_venta_pkey PRIMARY KEY (id);


--
-- Name: productos productos_codigo_barras_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.productos
    ADD CONSTRAINT productos_codigo_barras_key UNIQUE (codigo_barras);


--
-- Name: productos productos_codigo_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.productos
    ADD CONSTRAINT productos_codigo_key UNIQUE (codigo);


--
-- Name: productos productos_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.productos
    ADD CONSTRAINT productos_pkey PRIMARY KEY (id);


--
-- Name: reembolsos reembolsos_pago_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reembolsos
    ADD CONSTRAINT reembolsos_pago_id_key UNIQUE (pago_id);


--
-- Name: reembolsos reembolsos_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reembolsos
    ADD CONSTRAINT reembolsos_pkey PRIMARY KEY (id);


--
-- Name: reglas_mayoreo reglas_mayoreo_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reglas_mayoreo
    ADD CONSTRAINT reglas_mayoreo_pkey PRIMARY KEY (id);


--
-- Name: solicitudes_cancelacion solicitudes_cancelacion_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.solicitudes_cancelacion
    ADD CONSTRAINT solicitudes_cancelacion_pkey PRIMARY KEY (id);


--
-- Name: turnos turnos_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.turnos
    ADD CONSTRAINT turnos_pkey PRIMARY KEY (id);


--
-- Name: usuarios usuarios_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usuarios
    ADD CONSTRAINT usuarios_pkey PRIMARY KEY (id);


--
-- Name: ventas ventas_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ventas
    ADD CONSTRAINT ventas_pkey PRIMARY KEY (id);


--
-- Name: arqueos_fecha_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX arqueos_fecha_idx ON public.arqueos USING btree (creado_en);


--
-- Name: auditoria_entidad_registro_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auditoria_entidad_registro_idx ON public.auditoria USING btree (entidad, registro_id);


--
-- Name: auditoria_usuario_fecha_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auditoria_usuario_fecha_idx ON public.auditoria USING btree (usuario_id, creado_en);


--
-- Name: cancelaciones_estado_fecha_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cancelaciones_estado_fecha_idx ON public.solicitudes_cancelacion USING btree (estado, solicitado_en);


--
-- Name: cancelaciones_venta_activa_unica; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX cancelaciones_venta_activa_unica ON public.solicitudes_cancelacion USING btree (venta_id) WHERE ((estado)::text = ANY ((ARRAY['PENDIENTE'::character varying, 'APROBADA'::character varying])::text[]));


--
-- Name: cola_bloqueos_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cola_bloqueos_idx ON public.cola_sincronizacion USING btree (bloqueado_hasta) WHERE ((estado)::text = 'PROCESANDO'::text);


--
-- Name: cola_pendientes_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cola_pendientes_idx ON public.cola_sincronizacion USING btree (proximo_intento_en, id) WHERE ((estado)::text = 'PENDIENTE'::text);


--
-- Name: conteos_producto_fecha_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX conteos_producto_fecha_idx ON public.conteos_inventario USING btree (producto_id, creado_en);


--
-- Name: detalle_venta_producto_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX detalle_venta_producto_idx ON public.detalle_venta USING btree (producto_id);


--
-- Name: insumos_material_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX insumos_material_idx ON public.insumos_servicio USING btree (insumo_id);


--
-- Name: kala_envios_pendientes; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX kala_envios_pendientes ON public.kala_envios USING btree (estado, creado_en);


--
-- Name: movimientos_caja_fondo_unico; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX movimientos_caja_fondo_unico ON public.movimientos_caja USING btree (turno_id) WHERE ((tipo)::text = 'FONDO_INICIAL'::text);


--
-- Name: movimientos_caja_turno_fecha_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX movimientos_caja_turno_fecha_idx ON public.movimientos_caja USING btree (turno_id, creado_en);


--
-- Name: movimientos_inventario_detalle_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX movimientos_inventario_detalle_idx ON public.movimientos_inventario USING btree (detalle_venta_id);


--
-- Name: movimientos_inventario_producto_fecha_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX movimientos_inventario_producto_fecha_idx ON public.movimientos_inventario USING btree (producto_id, creado_en);


--
-- Name: reembolsos_solicitud_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX reembolsos_solicitud_idx ON public.reembolsos USING btree (solicitud_id, venta_id);


--
-- Name: reembolsos_turno_fecha_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX reembolsos_turno_fecha_idx ON public.reembolsos USING btree (turno_id, realizado_en);


--
-- Name: turnos_caja_abierta_unica; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX turnos_caja_abierta_unica ON public.turnos USING btree (caja_id) WHERE ((estado)::text = 'ABIERTO'::text);


--
-- Name: turnos_usuario_abierto_unico; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX turnos_usuario_abierto_unico ON public.turnos USING btree (usuario_id) WHERE ((estado)::text = 'ABIERTO'::text);


--
-- Name: turnos_usuario_fecha_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX turnos_usuario_fecha_idx ON public.turnos USING btree (usuario_id, abierto_en);


--
-- Name: usuarios_usuario_unico; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX usuarios_usuario_unico ON public.usuarios USING btree (lower((usuario)::text));


--
-- Name: ventas_turno_fecha_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ventas_turno_fecha_idx ON public.ventas USING btree (turno_id, creado_en);


--
-- Name: turnos kala_aviso_cierre; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER kala_aviso_cierre AFTER UPDATE OF estado ON public.turnos FOR EACH ROW EXECUTE FUNCTION public.kala_encolar_cierre();


--
-- Name: kala_envios kala_canal_envio; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER kala_canal_envio BEFORE INSERT ON public.kala_envios FOR EACH ROW EXECUTE FUNCTION public.kala_fijar_canal();


--
-- Name: arqueos arqueos_registrado_por_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.arqueos
    ADD CONSTRAINT arqueos_registrado_por_fkey FOREIGN KEY (registrado_por) REFERENCES public.usuarios(id) ON DELETE RESTRICT;


--
-- Name: arqueos arqueos_revisado_por_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.arqueos
    ADD CONSTRAINT arqueos_revisado_por_fkey FOREIGN KEY (revisado_por) REFERENCES public.usuarios(id) ON DELETE RESTRICT;


--
-- Name: arqueos arqueos_turno_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.arqueos
    ADD CONSTRAINT arqueos_turno_id_fkey FOREIGN KEY (turno_id) REFERENCES public.turnos(id) ON DELETE RESTRICT;


--
-- Name: auditoria auditoria_usuario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auditoria
    ADD CONSTRAINT auditoria_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES public.usuarios(id) ON DELETE RESTRICT;


--
-- Name: configuracion configuracion_actualizado_por_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.configuracion
    ADD CONSTRAINT configuracion_actualizado_por_fkey FOREIGN KEY (actualizado_por) REFERENCES public.usuarios(id) ON DELETE RESTRICT;


--
-- Name: conteos_inventario conteos_inventario_contado_por_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conteos_inventario
    ADD CONSTRAINT conteos_inventario_contado_por_fkey FOREIGN KEY (contado_por) REFERENCES public.usuarios(id) ON DELETE RESTRICT;


--
-- Name: conteos_inventario conteos_inventario_producto_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conteos_inventario
    ADD CONSTRAINT conteos_inventario_producto_id_fkey FOREIGN KEY (producto_id) REFERENCES public.productos(id) ON DELETE RESTRICT;


--
-- Name: detalle_arqueo detalle_arqueo_arqueo_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detalle_arqueo
    ADD CONSTRAINT detalle_arqueo_arqueo_id_fkey FOREIGN KEY (arqueo_id) REFERENCES public.arqueos(id) ON DELETE RESTRICT;


--
-- Name: detalle_venta detalle_venta_producto_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detalle_venta
    ADD CONSTRAINT detalle_venta_producto_id_fkey FOREIGN KEY (producto_id) REFERENCES public.productos(id) ON DELETE RESTRICT;


--
-- Name: detalle_venta detalle_venta_venta_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detalle_venta
    ADD CONSTRAINT detalle_venta_venta_id_fkey FOREIGN KEY (venta_id) REFERENCES public.ventas(id) ON DELETE RESTRICT;


--
-- Name: insumos_servicio insumos_servicio_insumo_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insumos_servicio
    ADD CONSTRAINT insumos_servicio_insumo_id_fkey FOREIGN KEY (insumo_id) REFERENCES public.productos(id) ON DELETE RESTRICT;


--
-- Name: insumos_servicio insumos_servicio_servicio_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insumos_servicio
    ADD CONSTRAINT insumos_servicio_servicio_id_fkey FOREIGN KEY (servicio_id) REFERENCES public.productos(id) ON DELETE RESTRICT;


--
-- Name: kala_consultas_whatsapp kala_consultas_whatsapp_envio_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kala_consultas_whatsapp
    ADD CONSTRAINT kala_consultas_whatsapp_envio_id_fkey FOREIGN KEY (envio_id) REFERENCES public.kala_envios(id);


--
-- Name: kala_envios kala_envios_usuario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kala_envios
    ADD CONSTRAINT kala_envios_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES public.usuarios(id);


--
-- Name: kala_operaciones kala_operaciones_usuario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kala_operaciones
    ADD CONSTRAINT kala_operaciones_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES public.usuarios(id);


--
-- Name: movimientos_caja movimientos_caja_registrado_por_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.movimientos_caja
    ADD CONSTRAINT movimientos_caja_registrado_por_fkey FOREIGN KEY (registrado_por) REFERENCES public.usuarios(id) ON DELETE RESTRICT;


--
-- Name: movimientos_caja movimientos_caja_turno_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.movimientos_caja
    ADD CONSTRAINT movimientos_caja_turno_id_fkey FOREIGN KEY (turno_id) REFERENCES public.turnos(id) ON DELETE RESTRICT;


--
-- Name: movimientos_inventario movimientos_inventario_conteo_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.movimientos_inventario
    ADD CONSTRAINT movimientos_inventario_conteo_fk FOREIGN KEY (conteo_id, producto_id) REFERENCES public.conteos_inventario(id, producto_id) ON DELETE RESTRICT;


--
-- Name: movimientos_inventario movimientos_inventario_detalle_venta_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.movimientos_inventario
    ADD CONSTRAINT movimientos_inventario_detalle_venta_id_fkey FOREIGN KEY (detalle_venta_id) REFERENCES public.detalle_venta(id) ON DELETE RESTRICT;


--
-- Name: movimientos_inventario movimientos_inventario_producto_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.movimientos_inventario
    ADD CONSTRAINT movimientos_inventario_producto_id_fkey FOREIGN KEY (producto_id) REFERENCES public.productos(id) ON DELETE RESTRICT;


--
-- Name: movimientos_inventario movimientos_inventario_registrado_por_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.movimientos_inventario
    ADD CONSTRAINT movimientos_inventario_registrado_por_fkey FOREIGN KEY (registrado_por) REFERENCES public.usuarios(id) ON DELETE RESTRICT;


--
-- Name: pagos_venta pagos_venta_venta_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pagos_venta
    ADD CONSTRAINT pagos_venta_venta_id_fkey FOREIGN KEY (venta_id) REFERENCES public.ventas(id) ON DELETE RESTRICT;


--
-- Name: reembolsos reembolsos_pago_venta_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reembolsos
    ADD CONSTRAINT reembolsos_pago_venta_fk FOREIGN KEY (pago_id, venta_id) REFERENCES public.pagos_venta(id, venta_id) ON DELETE RESTRICT;


--
-- Name: reembolsos reembolsos_registrado_por_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reembolsos
    ADD CONSTRAINT reembolsos_registrado_por_fkey FOREIGN KEY (registrado_por) REFERENCES public.usuarios(id) ON DELETE RESTRICT;


--
-- Name: reembolsos reembolsos_solicitud_venta_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reembolsos
    ADD CONSTRAINT reembolsos_solicitud_venta_fk FOREIGN KEY (solicitud_id, venta_id) REFERENCES public.solicitudes_cancelacion(id, venta_id) ON DELETE RESTRICT;


--
-- Name: reembolsos reembolsos_turno_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reembolsos
    ADD CONSTRAINT reembolsos_turno_id_fkey FOREIGN KEY (turno_id) REFERENCES public.turnos(id) ON DELETE RESTRICT;


--
-- Name: reglas_mayoreo reglas_mayoreo_producto_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reglas_mayoreo
    ADD CONSTRAINT reglas_mayoreo_producto_id_fkey FOREIGN KEY (producto_id) REFERENCES public.productos(id) ON DELETE RESTRICT;


--
-- Name: solicitudes_cancelacion solicitudes_cancelacion_resuelto_por_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.solicitudes_cancelacion
    ADD CONSTRAINT solicitudes_cancelacion_resuelto_por_fkey FOREIGN KEY (resuelto_por) REFERENCES public.usuarios(id) ON DELETE RESTRICT;


--
-- Name: solicitudes_cancelacion solicitudes_cancelacion_solicitado_por_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.solicitudes_cancelacion
    ADD CONSTRAINT solicitudes_cancelacion_solicitado_por_fkey FOREIGN KEY (solicitado_por) REFERENCES public.usuarios(id) ON DELETE RESTRICT;


--
-- Name: solicitudes_cancelacion solicitudes_cancelacion_venta_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.solicitudes_cancelacion
    ADD CONSTRAINT solicitudes_cancelacion_venta_id_fkey FOREIGN KEY (venta_id) REFERENCES public.ventas(id) ON DELETE RESTRICT;


--
-- Name: turnos turnos_caja_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.turnos
    ADD CONSTRAINT turnos_caja_id_fkey FOREIGN KEY (caja_id) REFERENCES public.cajas(id) ON DELETE RESTRICT;


--
-- Name: turnos turnos_usuario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.turnos
    ADD CONSTRAINT turnos_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES public.usuarios(id) ON DELETE RESTRICT;


--
-- Name: ventas ventas_turno_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ventas
    ADD CONSTRAINT ventas_turno_id_fkey FOREIGN KEY (turno_id) REFERENCES public.turnos(id) ON DELETE RESTRICT;


--
-- PostgreSQL database dump complete
--

\unrestrict 9xLkwSzLGCfH0zydeKljDDCFKHkfhrIaQUQSgOTthvAMubHtuhue9CY1zvA823s

