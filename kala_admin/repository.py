from contextlib import contextmanager
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from uuid import uuid4
import re
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from argon2 import PasswordHasher


class BusinessError(Exception):
    pass


def cents(value):
    try:
        n = Decimal(str(value))
        if not n.is_finite() or n < 0 or n > Decimal('999999999.99'):
            raise ValueError()
        return int((n * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except (ValueError, InvalidOperation):
        raise BusinessError('Importe no válido.')


def quantity(value, allow_zero=False):
    try:
        n = Decimal(str(value))
        if not n.is_finite() or n < 0 or (not allow_zero and n == 0) or n > Decimal('999999999.999') or n != n.quantize(Decimal('.001')):
            raise ValueError()
        return n
    except (ValueError, InvalidOperation):
        raise BusinessError('Cantidad no válida: usa hasta tres decimales.')


def money(value):
    return f'${Decimal(value or 0)/100:,.2f}'


def nonempty(text, label, limit=2000):
    text = str(text).strip()
    if not text or len(text) > limit:
        raise BusinessError(f'{label}: introduce de 1 a {limit} caracteres.')
    return text


def rounded(n):
    return int(Decimal(n).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


class Repository:
    def __init__(self, config, user):
        self.config = dict(config)
        self.user_id = int(user['id'])

    @contextmanager
    def connection(self, write=False):
        with psycopg.connect(**self.config, row_factory=dict_row, connect_timeout=5,
                             options='-c statement_timeout=15000 -c lock_timeout=5000',
                             application_name='KALA_admin_local') as c:
            c.execute("SET LOCAL TIME ZONE 'America/Mexico_City'")
            if write:
                c.execute('SELECT pg_advisory_xact_lock(724001)')
            u = c.execute('SELECT id,nombre,rol,activo FROM public.usuarios WHERE id=%s', (self.user_id,)).fetchone()
            if not u or not u['activo'] or u['rol'] != 'ADMINISTRADOR':
                raise BusinessError('La cuenta no tiene acceso de administrador activo. Cierra sesión.')
            yield c

    def read(self, sql, args=()):
        with self.connection() as c:
            return c.execute(sql, args).fetchall()

    def mutate(self, operation, callback, request_id=None):
        request_id = str(request_id or uuid4())
        with self.connection(True) as c:
            previous = c.execute('SELECT usuario_id,tipo,resultado FROM public.kala_operaciones WHERE id=%s', (request_id,)).fetchone()
            if previous:
                if previous['usuario_id'] != self.user_id or previous['tipo'] != operation:
                    raise BusinessError('Identificador de operación ya utilizado.')
                return previous['resultado']
            result = callback(c)
            c.execute('INSERT INTO public.kala_operaciones(id,usuario_id,tipo,resultado) VALUES (%s,%s,%s,%s)',
                      (request_id, self.user_id, operation, Jsonb(result)))
            return result

    def audit(self, c, action, entity, rid, description):
        c.execute('INSERT INTO public.auditoria(usuario_id,origen,accion,entidad,registro_id,descripcion) VALUES (%s,\'USUARIO\',%s,%s,%s,%s)',
                  (self.user_id, action, entity, rid, description))

    def products(self, search=''):
        return self.read('''SELECT p.*,
            (SELECT cantidad_minima FROM public.reglas_mayoreo r WHERE r.producto_id=p.id AND r.activo ORDER BY cantidad_minima LIMIT 1) AS mayoreo_desde,
            (SELECT precio_unitario_centavos FROM public.reglas_mayoreo r WHERE r.producto_id=p.id AND r.activo ORDER BY cantidad_minima LIMIT 1) AS mayoreo_precio
            FROM public.productos p WHERE p.nombre ILIKE %s OR p.codigo ILIKE %s OR p.codigo_barras ILIKE %s ORDER BY p.nombre''',
            tuple('%'+search+'%' for _ in range(3)))

    def save_product(self, data, pid=None, request_id=None):
        d = dict(data)
        d['codigo'] = nonempty(d['codigo'], 'Código', 50)
        d['nombre'] = nonempty(d['nombre'], 'Nombre', 150)
        barcode = d.get('codigo_barras','').strip() or None
        if barcode and len(barcode)>100: raise BusinessError('Código de barras demasiado largo.')
        if d['tipo'] not in ('PRODUCTO','SERVICIO'): raise BusinessError('Tipo inválido.')
        if d['unidad'] not in ('PIEZA','HOJA','HORA','METRO','PAQUETE'): raise BusinessError('Unidad inválida.')
        price, cost = cents(d['precio']), cents(d['costo'])
        stock = bool(d['controla_stock']) and d['tipo']=='PRODUCTO'
        reorder = quantity(d['punto_reorden'], True) if stock else Decimal(0)
        threshold = quantity(d['mayoreo_desde']) if d['mayoreo'] else None
        wholesale = cents(d['mayoreo_precio']) if threshold else None
        if wholesale is not None and wholesale > price: raise BusinessError('El mayoreo no puede superar el precio de menudeo.')
        def work(c):
            old = None
            if pid:
                old = c.execute('SELECT * FROM public.productos WHERE id=%s FOR UPDATE', (pid,)).fetchone()
                if not old: raise BusinessError('Producto inexistente.')
                if (old['tipo'], old['controla_stock'], old['unidad']) != (d['tipo'], stock, d['unidad']):
                    raise BusinessError('Para conservar el historial no se permite cambiar tipo, unidad o control de stock. Crea otro artículo.')
                if old['controla_stock'] and old['existencia']>0 and cost != old['costo_referencia_centavos']:
                    raise BusinessError('El costo con existencias se actualiza al recibir mercancía.')
            fields = (d['codigo'],barcode,d['nombre'],d['tipo'],d['unidad'],price,cost,stock,reorder,bool(d['activo']))
            if pid:
                c.execute('''UPDATE public.productos SET codigo=%s,codigo_barras=%s,nombre=%s,tipo=%s,unidad=%s,precio_venta_centavos=%s,
                    costo_referencia_centavos=%s,controla_stock=%s,punto_reorden=%s,activo=%s WHERE id=%s''', fields+(pid,))
                rid=pid
            else:
                rid=c.execute('''INSERT INTO public.productos(codigo,codigo_barras,nombre,tipo,unidad,precio_venta_centavos,
                    costo_referencia_centavos,controla_stock,punto_reorden,activo) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',fields).fetchone()['id']
            c.execute('UPDATE public.reglas_mayoreo SET activo=FALSE WHERE producto_id=%s',(rid,))
            if threshold:
                c.execute('''INSERT INTO public.reglas_mayoreo(producto_id,cantidad_minima,precio_unitario_centavos)
                    VALUES (%s,%s,%s) ON CONFLICT (producto_id,cantidad_minima) DO UPDATE SET precio_unitario_centavos=EXCLUDED.precio_unitario_centavos,activo=TRUE''',(rid,threshold,wholesale))
            self.audit(c,'GUARDAR_PRODUCTO','productos',rid,'Alta/edición de catálogo y regla de mayoreo.')
            return {'id':rid}
        return self.mutate('PRODUCTO',work,request_id)

    def materials(self, service_id):
        return self.read('''SELECT i.*,p.nombre FROM public.insumos_servicio i JOIN public.productos p ON p.id=i.insumo_id
            WHERE i.servicio_id=%s AND i.activo ORDER BY p.nombre''',(service_id,))

    def save_material(self, service_id, material_id, qty, active=True, request_id=None):
        qty=quantity(qty)
        def work(c):
            s=c.execute('SELECT * FROM public.productos WHERE id=%s',(service_id,)).fetchone()
            m=c.execute('SELECT * FROM public.productos WHERE id=%s',(material_id,)).fetchone()
            if not s or s['tipo']!='SERVICIO' or not m or not m['controla_stock'] or s['id']==m['id']:
                raise BusinessError('Selecciona un servicio y un material con control de stock.')
            c.execute('''INSERT INTO public.insumos_servicio(servicio_id,insumo_id,cantidad_por_servicio,activo) VALUES (%s,%s,%s,%s)
                ON CONFLICT(servicio_id,insumo_id) DO UPDATE SET cantidad_por_servicio=EXCLUDED.cantidad_por_servicio,activo=EXCLUDED.activo''',(service_id,material_id,qty,active))
            self.audit(c,'INSUMOS_SERVICIO','productos',service_id,'Cambio de materiales del servicio.')
            return {'id':service_id}
        return self.mutate('INSUMO',work,request_id)

    def stock_move(self,c,pid,delta,kind,reason,detail=None,count_id=None,cost=None,provider=None,reference=None):
        p=c.execute('SELECT * FROM public.productos WHERE id=%s FOR UPDATE',(pid,)).fetchone()
        if not p or not p['controla_stock']: raise BusinessError('El producto no controla inventario.')
        delta=Decimal(delta)
        if p['existencia']+delta<0: raise BusinessError(f'Stock insuficiente: {p["nombre"]}. Disponible: {p["existencia"]}.')
        c.execute('UPDATE public.productos SET existencia=existencia+%s WHERE id=%s',(delta,pid))
        c.execute('''INSERT INTO public.movimientos_inventario(producto_id,registrado_por,tipo,cantidad,costo_unitario_centavos,motivo,
            detalle_venta_id,conteo_id,proveedor,referencia) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (pid,self.user_id,kind,delta,cost if cost is not None else p['costo_referencia_centavos'],reason,detail,count_id,provider,reference))

    def inventory(self,pid,kind,qty,reason,cost='0',provider='',reference='',expected=None,request_id=None):
        qty=quantity(qty,kind=='CONTEO'); reason=nonempty(reason,'Motivo')
        if kind not in ('ENTRADA','CONTEO','MERMA','USO_INTERNO'): raise BusinessError('Operación inválida.')
        unitcost=cents(cost)
        def work(c):
            p=c.execute('SELECT * FROM public.productos WHERE id=%s FOR UPDATE',(pid,)).fetchone()
            if not p or not p['activo'] or not p['controla_stock']: raise BusinessError('Selecciona un producto activo con control de stock.')
            if kind=='CONTEO':
                if expected is None or p['existencia']!=Decimal(str(expected)):
                    raise BusinessError('Las existencias cambiaron desde que abriste el conteo. Actualiza y vuelve a contar.')
                cid=c.execute('''INSERT INTO public.conteos_inventario(producto_id,contado_por,existencia_sistema,cantidad_contada,motivo)
                    VALUES (%s,%s,%s,%s,%s) RETURNING id''',(pid,self.user_id,p['existencia'],qty,reason)).fetchone()['id']
                delta=qty-p['existencia']
                if delta: self.stock_move(c,pid,delta,'AJUSTE_CONTEO',reason,count_id=cid)
            elif kind=='ENTRADA':
                total=p['existencia']+qty
                avg=rounded((p['existencia']*p['costo_referencia_centavos']+qty*unitcost)/total)
                self.stock_move(c,pid,qty,kind,reason,cost=unitcost,provider=provider[:150],reference=reference[:100])
                c.execute('UPDATE public.productos SET costo_referencia_centavos=%s WHERE id=%s',(avg,pid))
            else:
                self.stock_move(c,pid,-qty,kind,reason)
            self.audit(c,kind,'productos',pid,reason)
            return {'id':pid,'stock':str(c.execute('SELECT existencia FROM public.productos WHERE id=%s',(pid,)).fetchone()['existencia'])}
        return self.mutate('INVENTARIO',work,request_id)

    def inventory_history(self):
        return self.read('''SELECT m.id,m.creado_en,p.nombre,m.tipo,m.cantidad,m.motivo,u.nombre AS responsable
            FROM public.movimientos_inventario m JOIN public.productos p ON p.id=m.producto_id
            JOIN public.usuarios u ON u.id=m.registrado_por ORDER BY m.id DESC LIMIT 500''')

    def users(self):
        return self.read('SELECT id,nombre,usuario,rol,activo FROM public.usuarios ORDER BY id')

    def save_user(self,data,uid=None,request_id=None):
        name=nonempty(data['nombre'],'Nombre',120); username=nonempty(data['usuario'],'Usuario',50).lower()
        if not re.fullmatch(r'[a-z0-9_.-]{3,50}',username): raise BusinessError('Usuario: 3–50 letras sin acentos, números, punto, guion o guion bajo.')
        role=data['rol']; active=bool(data['activo']); password=data.get('password','')
        if role not in ('ADMINISTRADOR','CAJERO'): raise BusinessError('Rol inválido.')
        if not uid and not password: raise BusinessError('Escribe la contraseña inicial.')
        if password and (len(password)<12 or len(password)>128 or not password.strip()): raise BusinessError('Contraseña: de 12 a 128 caracteres.')
        hashed=PasswordHasher().hash(password) if password else None
        def work(c):
            if uid:
                old=c.execute('SELECT * FROM public.usuarios WHERE id=%s FOR UPDATE',(uid,)).fetchone()
                if not old: raise BusinessError('Usuario inexistente.')
                if uid==self.user_id and (role!='ADMINISTRADOR' or not active): raise BusinessError('No puedes quitar tu propio acceso administrativo durante la sesión.')
                if old['rol']=='ADMINISTRADOR' and old['activo'] and (role!='ADMINISTRADOR' or not active):
                    if c.execute("SELECT count(*) AS n FROM public.usuarios WHERE rol='ADMINISTRADOR' AND activo").fetchone()['n']<=1:
                        raise BusinessError('Debe existir al menos un administrador activo.')
                if (role!=old['rol'] or not active) and c.execute("SELECT id FROM public.turnos WHERE usuario_id=%s AND estado='ABIERTO'",(uid,)).fetchone():
                    raise BusinessError('Cierra el turno del usuario antes de desactivarlo o cambiar su rol.')
                c.execute('UPDATE public.usuarios SET nombre=%s,usuario=%s,rol=%s,activo=%s WHERE id=%s',(name,username,role,active,uid))
                if hashed: c.execute('UPDATE public.usuarios SET password_hash=%s WHERE id=%s',(hashed,uid))
                rid=uid
            else:
                rid=c.execute('INSERT INTO public.usuarios(nombre,usuario,password_hash,rol,activo) VALUES (%s,%s,%s,%s,%s) RETURNING id',(name,username,hashed,role,active)).fetchone()['id']
            self.audit(c,'GUARDAR_USUARIO','usuarios',rid,'Alta/edición de usuario. No se registra su contraseña.')
            return {'id':rid}
        return self.mutate('USUARIO',work,request_id)

    def boxes(self):
        return self.read('SELECT id,nombre FROM public.cajas WHERE activo ORDER BY id')

    def turns(self):
        return self.read('''SELECT t.*,u.nombre AS cajero,c.nombre AS caja FROM public.turnos t
            JOIN public.usuarios u ON u.id=t.usuario_id JOIN public.cajas c ON c.id=t.caja_id
            WHERE t.estado='ABIERTO' ORDER BY t.id''')

    def open_turn(self,box,amount,request_id=None):
        amount=cents(amount)
        def work(c):
            if not c.execute('SELECT id FROM public.cajas WHERE id=%s AND activo',(box,)).fetchone(): raise BusinessError('Caja no disponible.')
            if c.execute("SELECT id FROM public.turnos WHERE estado='ABIERTO' AND (caja_id=%s OR usuario_id=%s)",(box,self.user_id)).fetchone(): raise BusinessError('La caja o tu usuario ya tienen un turno abierto.')
            rid=c.execute('INSERT INTO public.turnos(caja_id,usuario_id) VALUES (%s,%s) RETURNING id',(box,self.user_id)).fetchone()['id']
            c.execute("INSERT INTO public.movimientos_caja(turno_id,registrado_por,tipo,importe_centavos,motivo) VALUES (%s,%s,'FONDO_INICIAL',%s,'Fondo de apertura')",(rid,self.user_id,amount))
            self.audit(c,'ABRIR_TURNO','turnos',rid,'Apertura con fondo inicial.')
            return {'id':rid}
        return self.mutate('ABRIR_TURNO',work,request_id)

    def require_turn(self,c,tid,own=False):
        t=c.execute('SELECT * FROM public.turnos WHERE id=%s FOR UPDATE',(tid,)).fetchone()
        if not t or t['estado']!='ABIERTO': raise BusinessError('El turno está cerrado o no existe.')
        if own and t['usuario_id']!=self.user_id: raise BusinessError('Solo puedes vender o contar en tu propio turno.')
        return t

    def expected_cash(self,c,tid):
        # No se filtran ventas canceladas: sus cobros permanecen, los reembolsos
        # se descuentan del turno donde realmente se devolvió el dinero.
        base=c.execute("SELECT COALESCE(sum(CASE WHEN tipo='RETIRO' THEN -importe_centavos ELSE importe_centavos END),0) AS n FROM public.movimientos_caja WHERE turno_id=%s",(tid,)).fetchone()['n']
        payments=c.execute("SELECT COALESCE(sum(p.importe_centavos),0) AS n FROM public.pagos_venta p JOIN public.ventas v ON v.id=p.venta_id WHERE v.turno_id=%s AND v.cobrado_en IS NOT NULL AND p.metodo='EFECTIVO'",(tid,)).fetchone()['n']
        refunds=c.execute("SELECT COALESCE(sum(r.importe_centavos),0) AS n FROM public.reembolsos r JOIN public.pagos_venta p ON p.id=r.pago_id WHERE r.turno_id=%s AND p.metodo='EFECTIVO'",(tid,)).fetchone()['n']
        return int(base+payments-refunds)

    def cash_move(self,tid,kind,amount,reason,reference='',request_id=None):
        amount=cents(amount);reason=nonempty(reason,'Motivo')
        if kind not in ('ENTRADA','RETIRO') or amount<=0: raise BusinessError('Movimiento o importe inválidos.')
        def work(c):
            self.require_turn(c,tid)
            if kind=='RETIRO' and self.expected_cash(c,tid)<amount: raise BusinessError('El retiro supera el efectivo registrado en caja.')
            rid=c.execute('INSERT INTO public.movimientos_caja(turno_id,registrado_por,tipo,importe_centavos,motivo,referencia) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',(tid,self.user_id,kind,amount,reason,reference[:100])).fetchone()['id']
            self.audit(c,kind,'movimientos_caja',rid,reason)
            return {'id':rid}
        return self.mutate('CAJA',work,request_id)

    def cash_history(self):
        return self.read('''SELECT m.id,m.creado_en,m.turno_id,m.tipo,m.importe_centavos,m.motivo,m.referencia,u.nombre AS responsable
            FROM public.movimientos_caja m JOIN public.usuarios u ON u.id=m.registrado_por ORDER BY m.id DESC LIMIT 500''')

    def quote(self,items):
        with self.connection() as c: return self._quote(c,items)

    def _quote(self,c,items):
        merged={}
        for pid,qty in items:
            pid=int(pid); merged[pid]=merged.get(pid,Decimal(0))+quantity(qty)
        if not merged: raise BusinessError('El carrito está vacío.')
        rows=[]
        for pid,qty in sorted(merged.items()):
            p=c.execute('SELECT * FROM public.productos WHERE id=%s',(pid,)).fetchone()
            if not p or not p['activo']: raise BusinessError('Hay un artículo inactivo o inexistente en el carrito.')
            if p['unidad'] in ('PIEZA','HOJA','PAQUETE') and qty!=qty.to_integral_value(): raise BusinessError(f'{p["nombre"]}: utiliza cantidades enteras.')
            rule=c.execute('SELECT precio_unitario_centavos FROM public.reglas_mayoreo WHERE producto_id=%s AND activo AND cantidad_minima<=%s ORDER BY cantidad_minima DESC LIMIT 1',(pid,qty)).fetchone()
            unit=rule['precio_unitario_centavos'] if rule else p['precio_venta_centavos']
            materials=[]; cost=p['costo_referencia_centavos']
            if p['tipo']=='SERVICIO':
                materials=c.execute('''SELECT i.insumo_id,i.cantidad_por_servicio,p.costo_referencia_centavos,p.activo,p.controla_stock FROM public.insumos_servicio i
                    JOIN public.productos p ON p.id=i.insumo_id WHERE i.servicio_id=%s AND i.activo ORDER BY i.insumo_id''',(pid,)).fetchall()
                if any(not m['activo'] or not m['controla_stock'] for m in materials): raise BusinessError('Un material del servicio está inactivo o no controla stock.')
                if materials: cost=rounded(sum(m['cantidad_por_servicio']*m['costo_referencia_centavos'] for m in materials))
            rows.append(dict(id=pid,nombre=p['nombre'],codigo=p['codigo'],unidad=p['unidad'],cantidad=qty,precio=unit,costo=cost,
                             subtotal=rounded(qty*unit),mayoreo=bool(rule),stock=p['controla_stock'],materials=materials))
        return rows

    def charge(self,tid,items,cash,card,received,reference,expected_total,request_id):
        cash,card,received=cents(cash),cents(card),cents(received)
        if card>0:
            reference=nonempty(reference,'Folio de aprobación de la terminal',100)
            if reference.upper().startswith('SIM-'):raise BusinessError('Registra el folio de un pago aprobado en la terminal bancaria.')
        if received<cash: raise BusinessError('Efectivo recibido insuficiente.')
        if cash==0 and received!=0: raise BusinessError('No captures efectivo recibido en un cobro solo con tarjeta.')
        def work(c):
            self.require_turn(c,tid,True)
            rows=self._quote(c,items); total=sum(r['subtotal'] for r in rows)
            if total<=0: raise BusinessError('El total de la venta debe ser mayor que cero.')
            if total!=expected_total: raise BusinessError('Los precios cambiaron. Actualiza el carrito y vuelve a cobrar.')
            if cash+card!=total: raise BusinessError('Efectivo aplicado más tarjeta deben cubrir exactamente el total.')
            vid=c.execute("INSERT INTO public.ventas(turno_id,total_centavos) VALUES (%s,%s) RETURNING id",(tid,total)).fetchone()['id']
            for r in rows:
                did=c.execute('''INSERT INTO public.detalle_venta(venta_id,producto_id,codigo_producto,nombre_producto,unidad,cantidad,precio_unitario_centavos,costo_unitario_centavos,aplica_mayoreo)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',(vid,r['id'],r['codigo'],r['nombre'],r['unidad'],r['cantidad'],r['precio'],r['costo'],r['mayoreo'])).fetchone()['id']
                if r['stock']: self.stock_move(c,r['id'],-r['cantidad'],'VENTA',f'Venta {vid}',detail=did)
                for m in r['materials']:
                    consumed=r['cantidad']*m['cantidad_por_servicio']
                    if consumed!=consumed.quantize(Decimal('.001')): raise BusinessError('El consumo del servicio necesita más de tres decimales. Ajusta la cantidad o receta.')
                    self.stock_move(c,m['insumo_id'],-consumed,'CONSUMO_SERVICIO',f'Servicio en venta {vid}',detail=did)
            if cash:
                c.execute("INSERT INTO public.pagos_venta(venta_id,metodo,importe_centavos,recibido_centavos,cambio_centavos) VALUES (%s,'EFECTIVO',%s,%s,%s)",(vid,cash,received,received-cash))
            if card:
                c.execute("INSERT INTO public.pagos_venta(venta_id,metodo,importe_centavos,referencia_terminal) VALUES (%s,'TARJETA',%s,%s)",(vid,card,reference))
            c.execute("UPDATE public.ventas SET estado='COBRADA',cobrado_en=CURRENT_TIMESTAMP WHERE id=%s",(vid,))
            self.audit(c,'COBRAR','ventas',vid,'Venta confirmada con pagos y movimientos de inventario.')
            return {'id':vid,'total':total,'cambio':received-cash}
        return self.mutate('VENTA',work,request_id)

    def sales(self,start,end):
        return self.read('''SELECT v.id,v.cobrado_en,v.estado,v.total_centavos,v.turno_id,u.nombre AS cajero,
            (SELECT string_agg(p.metodo,' + ' ORDER BY p.metodo) FROM public.pagos_venta p WHERE p.venta_id=v.id) AS metodo
            FROM public.ventas v JOIN public.turnos t ON t.id=v.turno_id JOIN public.usuarios u ON u.id=t.usuario_id
            WHERE v.cobrado_en::date BETWEEN %s AND %s ORDER BY v.id DESC''',(start,end))

    def ticket(self,vid):
        with self.connection() as c:
            v=c.execute('''SELECT v.*,u.nombre AS cajero FROM public.ventas v JOIN public.turnos t ON t.id=v.turno_id
                JOIN public.usuarios u ON u.id=t.usuario_id WHERE v.id=%s''',(vid,)).fetchone()
            if not v: raise BusinessError('Ticket inexistente.')
            return dict(venta=v,detalle=c.execute('SELECT * FROM public.detalle_venta WHERE venta_id=%s ORDER BY id',(vid,)).fetchall(),
                        pagos=c.execute('SELECT * FROM public.pagos_venta WHERE venta_id=%s ORDER BY id',(vid,)).fetchall())

    def cancel_sale(self,vid,tid,reason,return_goods,card_reference='',request_id=None):
        reason=nonempty(reason,'Motivo de cancelación')
        def work(c):
            self.require_turn(c,tid)
            v=c.execute('SELECT * FROM public.ventas WHERE id=%s FOR UPDATE',(vid,)).fetchone()
            if not v or v['estado']!='COBRADA': raise BusinessError('Solo se pueden cancelar ventas cobradas.')
            payments=c.execute('SELECT * FROM public.pagos_venta WHERE venta_id=%s',(vid,)).fetchall()
            cash=sum(p['importe_centavos'] for p in payments if p['metodo']=='EFECTIVO')
            if self.expected_cash(c,tid)<cash: raise BusinessError('El turno no tiene efectivo suficiente para el reembolso.')
            if any(p['metodo']=='TARJETA' for p in payments): nonempty(card_reference,'Folio de devolución bancaria',100)
            request=c.execute("SELECT * FROM public.solicitudes_cancelacion WHERE venta_id=%s AND estado IN ('PENDIENTE','APROBADA')",(vid,)).fetchone()
            if request and request['estado']=='APROBADA': raise BusinessError('La venta ya tiene una cancelación aprobada; revisa su estado.')
            if request:
                sid=request['id']; c.execute("UPDATE public.solicitudes_cancelacion SET estado='APROBADA',resuelto_por=%s,resuelto_en=CURRENT_TIMESTAMP,observaciones_resolucion=%s WHERE id=%s",(self.user_id,reason,sid))
            else:
                sid=c.execute("""INSERT INTO public.solicitudes_cancelacion(venta_id,solicitado_por,motivo,estado,resuelto_por,resuelto_en,observaciones_resolucion)
                    VALUES (%s,%s,%s,'APROBADA',%s,CURRENT_TIMESTAMP,%s) RETURNING id""",(vid,self.user_id,reason,self.user_id,reason)).fetchone()['id']
            for pay in payments:
                c.execute('''INSERT INTO public.reembolsos(solicitud_id,venta_id,pago_id,turno_id,registrado_por,importe_centavos,referencia_terminal,observaciones)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',(sid,vid,pay['id'],tid,self.user_id,pay['importe_centavos'],card_reference if pay['metodo']=='TARJETA' else None,reason))
            if return_goods:
                rows=c.execute("SELECT m.* FROM public.movimientos_inventario m JOIN public.detalle_venta d ON d.id=m.detalle_venta_id WHERE d.venta_id=%s AND m.tipo='VENTA' ORDER BY m.producto_id",(vid,)).fetchall()
                for m in rows:
                    p=c.execute('SELECT existencia,costo_referencia_centavos FROM public.productos WHERE id=%s FOR UPDATE',(m['producto_id'],)).fetchone()
                    returned=-m['cantidad']
                    avg=rounded((p['existencia']*p['costo_referencia_centavos']+returned*m['costo_unitario_centavos'])/(p['existencia']+returned))
                    self.stock_move(c,m['producto_id'],returned,'DEVOLUCION_VENTA',reason,detail=m['detalle_venta_id'],cost=m['costo_unitario_centavos'])
                    c.execute('UPDATE public.productos SET costo_referencia_centavos=%s WHERE id=%s',(avg,m['producto_id']))
            c.execute("UPDATE public.ventas SET estado='CANCELADA' WHERE id=%s",(vid,))
            self.audit(c,'CANCELAR','ventas',vid,reason+' | Reintegro de productos: '+str(return_goods))
            return {'id':vid}
        return self.mutate('CANCELACION',work,request_id)

    def requests(self):
        return self.read('''SELECT s.id,s.venta_id,s.solicitado_en,s.motivo,u.nombre AS solicitante FROM public.solicitudes_cancelacion s
            JOIN public.usuarios u ON u.id=s.solicitado_por WHERE s.estado='PENDIENTE' ORDER BY s.id''')

    def reject_request(self,sid,reason,request_id=None):
        reason=nonempty(reason,'Justificación')
        def work(c):
            row=c.execute("UPDATE public.solicitudes_cancelacion SET estado='RECHAZADA',resuelto_por=%s,resuelto_en=CURRENT_TIMESTAMP,observaciones_resolucion=%s WHERE id=%s AND estado='PENDIENTE' RETURNING id",(self.user_id,reason,sid)).fetchone()
            if not row: raise BusinessError('La solicitud ya fue resuelta.')
            self.audit(c,'RECHAZAR_CANCELACION','solicitudes_cancelacion',sid,reason); return {'id':sid}
        return self.mutate('RECHAZAR',work,request_id)

    def close_turn(self,tid,denominations,note,request_id=None):
        valid=[]
        for kind,value,num in denominations:
            if kind not in ('BILLETE','MONEDA') or int(value)<=0 or int(num)<0: raise BusinessError('Denominación inválida.')
            valid.append((kind,int(value),int(num)))
        if len(set((k,v) for k,v,n in valid))!=len(valid): raise BusinessError('Denominación repetida.')
        counted=sum(v*n for k,v,n in valid)
        def work(c):
            self.require_turn(c,tid,True)
            expected=self.expected_cash(c,tid)
            aid=c.execute('''INSERT INTO public.arqueos(turno_id,registrado_por,efectivo_contado_centavos,efectivo_esperado_centavos,observaciones_cajero)
                VALUES (%s,%s,%s,%s,%s) RETURNING id''',(tid,self.user_id,counted,expected,note)).fetchone()['id']
            for kind,value,num in valid:
                c.execute('INSERT INTO public.detalle_arqueo(arqueo_id,tipo,denominacion_centavos,cantidad) VALUES (%s,%s,%s,%s)',(aid,kind,value,num))
            c.execute("UPDATE public.turnos SET estado='CERRADO',cerrado_en=CURRENT_TIMESTAMP,observaciones=%s WHERE id=%s",(note,tid))
            self.audit(c,'CERRAR_TURNO','arqueos',aid,'Conteo ciego y cierre de turno.')
            return {'id':aid}
        return self.mutate('ARQUEO',work,request_id)

    def closings(self,start,end,uid=None):
        return self.read('''SELECT a.*,u.nombre AS cajero,c.nombre AS caja FROM public.arqueos a JOIN public.turnos t ON t.id=a.turno_id
            JOIN public.usuarios u ON u.id=t.usuario_id JOIN public.cajas c ON c.id=t.caja_id
            WHERE a.creado_en::date BETWEEN %s AND %s AND (%s::bigint IS NULL OR t.usuario_id=%s) ORDER BY a.id DESC''',(start,end,uid,uid))

    def closing_detail(self,aid):
        return self.read('SELECT tipo,denominacion_centavos,cantidad,subtotal_centavos FROM public.detalle_arqueo WHERE arqueo_id=%s ORDER BY denominacion_centavos DESC',(aid,))

    def review_closing(self,aid,note,request_id=None):
        note=nonempty(note,'Nota de revisión')
        def work(c):
            a=c.execute('SELECT id FROM public.arqueos WHERE id=%s FOR UPDATE',(aid,)).fetchone()
            if not a: raise BusinessError('Arqueo inexistente.')
            c.execute('UPDATE public.arqueos SET revisado_por=%s,revisado_en=CURRENT_TIMESTAMP,observaciones_revision=%s WHERE id=%s',(self.user_id,note,aid))
            self.audit(c,'REVISAR_ARQUEO','arqueos',aid,note);return {'id':aid}
        return self.mutate('REVISION',work,request_id)

    def dashboard(self,start,end):
        with self.connection() as c:
            totals=c.execute("SELECT COALESCE(sum(total_centavos),0) AS ventas,count(*) AS tickets FROM public.ventas WHERE estado='COBRADA' AND cobrado_en::date BETWEEN %s AND %s",(start,end)).fetchone()
            profit=c.execute("SELECT COALESCE(sum(d.subtotal_centavos-round(d.cantidad*d.costo_unitario_centavos)),0) AS ganancia FROM public.detalle_venta d JOIN public.ventas v ON v.id=d.venta_id WHERE v.estado='COBRADA' AND v.cobrado_en::date BETWEEN %s AND %s",(start,end)).fetchone()['ganancia']
            low=c.execute('SELECT id,nombre,existencia,punto_reorden FROM public.productos WHERE activo AND controla_stock AND existencia<=punto_reorden ORDER BY existencia,nombre').fetchall()
            abc=c.execute("""SELECT p.id,p.nombre,COALESCE(sum(CASE WHEN v.estado='COBRADA' AND v.cobrado_en::date BETWEEN %s AND %s THEN d.cantidad ELSE 0 END),0) AS unidades
                FROM public.productos p LEFT JOIN public.detalle_venta d ON d.producto_id=p.id LEFT JOIN public.ventas v ON v.id=d.venta_id
                WHERE p.tipo='PRODUCTO' AND p.activo GROUP BY p.id,p.nombre ORDER BY unidades DESC,p.id""",(start,end)).fetchall()
            total_units=sum(r['unidades'] for r in abc); cumulative=Decimal(0)
            for r in abc:
                before=cumulative/total_units if total_units else 1
                r['clase']='C' if r['unidades']==0 else ('A' if before<Decimal('.8') else 'B' if before<Decimal('.95') else 'C')
                cumulative+=r['unidades']
            queue=c.execute('SELECT destino,estado,count(*) AS tareas FROM public.cola_sincronizacion GROUP BY destino,estado ORDER BY destino,estado').fetchall()
            return dict(ventas=int(totals['ventas']),tickets=totals['tickets'],ganancia=int(profit),bajos=low,abc=abc,cola=queue)

    def audit_history(self):
        return self.read('''SELECT a.id,a.creado_en,COALESCE(u.nombre,'Sistema') AS usuario,a.accion,a.entidad,a.registro_id,a.descripcion
            FROM public.auditoria a LEFT JOIN public.usuarios u ON u.id=a.usuario_id ORDER BY a.id DESC LIMIT 500''')
