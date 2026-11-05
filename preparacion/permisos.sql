GRANT SELECT ON ALL TABLES IN SCHEMA public TO kala_app;
GRANT INSERT, UPDATE ON public.productos,public.reglas_mayoreo,public.insumos_servicio,
 public.usuarios,public.turnos,public.movimientos_caja,public.ventas,public.detalle_venta,
 public.pagos_venta,public.conteos_inventario,public.movimientos_inventario,
 public.arqueos,public.detalle_arqueo,public.solicitudes_cancelacion,
 public.reembolsos,public.kala_operaciones TO kala_app;
GRANT INSERT ON public.auditoria TO kala_app;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO kala_app;


GRANT USAGE ON SCHEMA public TO kala_app;
GRANT SELECT,INSERT,UPDATE ON public.kala_config_integraciones,public.kala_envios,public.kala_respaldos TO kala_app;
GRANT SELECT,INSERT ON public.kala_consultas_whatsapp TO kala_app;
GRANT DELETE ON public.kala_consultas_whatsapp TO kala_app;
