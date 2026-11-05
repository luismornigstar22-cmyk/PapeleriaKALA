REQUIRED={
'usuarios':'id nombre usuario password_hash rol activo',
'productos':'id codigo codigo_barras nombre tipo unidad precio_venta_centavos costo_referencia_centavos controla_stock existencia punto_reorden activo',
'reglas_mayoreo':'producto_id cantidad_minima precio_unitario_centavos activo',
'insumos_servicio':'servicio_id insumo_id cantidad_por_servicio activo',
'cajas':'id nombre activo',
 'turnos':'id caja_id usuario_id estado abierto_en cerrado_en observaciones',
'movimientos_caja':'id turno_id registrado_por tipo importe_centavos motivo referencia creado_en',
'ventas':'id turno_id estado total_centavos cobrado_en',
'detalle_venta':'id venta_id producto_id codigo_producto nombre_producto unidad cantidad precio_unitario_centavos costo_unitario_centavos aplica_mayoreo subtotal_centavos',
'pagos_venta':'id venta_id metodo importe_centavos recibido_centavos cambio_centavos referencia_terminal',
'conteos_inventario':'id producto_id contado_por existencia_sistema cantidad_contada motivo',
'movimientos_inventario':'id producto_id registrado_por tipo cantidad costo_unitario_centavos motivo detalle_venta_id conteo_id proveedor referencia creado_en',
'arqueos':'id turno_id registrado_por efectivo_contado_centavos efectivo_esperado_centavos diferencia_centavos observaciones_cajero creado_en revisado_por revisado_en observaciones_revision',
'detalle_arqueo':'arqueo_id tipo denominacion_centavos cantidad subtotal_centavos',
'solicitudes_cancelacion':'id venta_id solicitado_por motivo estado resuelto_por resuelto_en observaciones_resolucion solicitado_en',
'reembolsos':'id solicitud_id venta_id pago_id turno_id registrado_por importe_centavos referencia_terminal observaciones',
'auditoria':'id usuario_id origen accion entidad registro_id descripcion creado_en',
'cola_sincronizacion':'destino estado',
'configuracion':'clave valor'
}

def missing_columns(connection):
    rows=connection.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public'").fetchall()
    actual={}
    for row in rows:
        table,col=(row['table_name'],row['column_name']) if isinstance(row,dict) else row
        actual.setdefault(table,set()).add(col)
    return [table+'.'+col for table,cols in REQUIRED.items() for col in cols.split() if col not in actual.get(table,set())]
