// KALA: Kapso webhook v2 -> cola D1 -> escritorio. No almacena reportes ni API keys de Kapso.
const encoder = new TextEncoder();
const MAX_AGE = 20 * 3600;
const json = (data, status = 200) => Response.json(data, {status, headers: {'Cache-Control': 'no-store'}});
export function phone(value) {
  if (typeof value !== 'string') return '';
  const cleaned = value.replace(/[\s()+-]/g, '');
  return /^[1-9][0-9]{7,14}$/.test(cleaned) ? cleaned : '';
}
export function command(text) {
  if (typeof text !== 'string' || text.length > 200) return 'menu';
  const value = text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim().replace(/\s+/g, ' ');
  if (['menu', 'hola', 'ayuda', '1'].includes(value)) return 'menu';
  if (['ventas', 'ventas hoy', '2'].includes(value)) return 'ventas hoy';
  if (['bitacora', 'bitacora hoy', '3'].includes(value)) return 'bitacora hoy';
  if (/^bitacora hoy [1-9][0-9]{0,3}$/.test(value)) return value;
  return 'menu';
}
export async function signed(raw, signature, secret) {
  if (!/^[a-fA-F0-9]{64}$/.test(signature || '')) return false;
  const bytes = Uint8Array.from(signature.match(/../g), x => parseInt(x, 16));
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret), {name: 'HMAC', hash: 'SHA-256'}, false, ['verify']);
  return crypto.subtle.verify('HMAC', key, bytes, raw);
}
async function sameSecret(a, b) {
  const [x, y] = await Promise.all([a, b].map(s => crypto.subtle.digest('SHA-256', encoder.encode(s))));
  const aa = new Uint8Array(x), bb = new Uint8Array(y);
  let diff = 0; for (let i = 0; i < aa.length; i++) diff |= aa[i] ^ bb[i];
  return diff === 0;
}
async function limitedBody(request, limit) {
  const reader = request.body?.getReader();
  if (!reader) return new Uint8Array();
  const chunks = []; let size = 0;
  while (true) {
    const {done, value} = await reader.read(); if (done) break;
    size += value.length;
    if (size > limit) { await reader.cancel(); throw new Error('body_limit'); }
    chunks.push(value);
  }if (path === '/health' && request.method === 'GET') return json({service: 'KALA bot', version: 1});
  const all = new Uint8Array(size); let pos = 0;
  for (const part of chunks) { all.set(part, pos); pos += part.length; }
  return all;
}
export function incoming(payload, env, now) {
  const m = payload?.message;
  // Fallar cerrado: ni nombres de contacto ni username acreditan al dueño.
  if (payload?.phone_number_id !== env.PHONE_NUMBER_ID || !m || m.type !== 'text' ||
      m.kapso?.direction !== 'inbound' || m.kapso?.passive === true ||
      !phone(m.from) || phone(m.from) !== phone(env.OWNER_PHONE)) return null;
  if (typeof m.id !== 'string' || m.id.length < 1 || m.id.length > 512 ||
      typeof m.timestamp !== 'string' || !/^[0-9]{10,11}$/.test(m.timestamp)) return null;
  const ts = Number(m.timestamp);
  if (ts > now + 300 || ts < now - MAX_AGE || typeof m.text?.body !== 'string') return null;
  return {id: crypto.randomUUID(), message_id: m.id, phone_id: env.PHONE_NUMBER_ID,
    sender: phone(m.from), command: command(m.text.body), requested_at: ts, received_at: now};
}
export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    if (path === '/health' && request.method === 'GET') return json({service: 'KALA bot', version: 1});
    if (!env.DB || !phone(env.OWNER_PHONE) || !/^[0-9]+$/.test(env.PHONE_NUMBER_ID || '') ||
        (env.WEBHOOK_SECRET || '').length < 32 || (env.DESKTOP_TOKEN || '').length < 32)
      return json({error: 'Configuracion del servicio incompleta'}, 503);
    const now = Math.floor(Date.now() / 1000);
    try {
      if (path === '/webhook' && request.method === 'POST') {
        const raw = await limitedBody(request, 256 * 1024);
        if (!await signed(raw, request.headers.get('X-Webhook-Signature'), env.WEBHOOK_SECRET))
          return json({error: 'Firma invalida'}, 401);
        if (request.headers.get('X-Webhook-Event') !== 'whatsapp.message.received') return json({ok: true});
        if (request.headers.get('X-Webhook-Payload-Version') !== 'v2') return json({error: 'Configura webhook Kapso v2'}, 400);
        let body; try { body = JSON.parse(new TextDecoder().decode(raw)); } catch { return json({error: 'JSON invalido'}, 400); }
        const items = body?.batch === true ? body.data : [body];
        if (!Array.isArray(items) || items.length > 50) return json({error: 'Lote invalido'}, 400);
        const statements = items.map(p => incoming(p, env, now)).filter(Boolean).map(c =>
          env.DB.prepare('INSERT OR IGNORE INTO commands(id,message_id,phone_id,sender,command,requested_at,received_at) VALUES(?,?,?,?,?,?,?)')
            .bind(c.id, c.message_id, c.phone_id, c.sender, c.command, c.requested_at, c.received_at));
        if (statements.length) await env.DB.batch(statements);
        // ACK solo después del almacenamiento durable; eventos ajenos se ignoran sin respuesta al remitente.
        return json({ok: true});
      }
      if (!['/commands', '/ack'].includes(path)) return json({error: 'No encontrado'}, 404);
      if (!await sameSecret(request.headers.get('Authorization') || '', 'Bearer ' + env.DESKTOP_TOKEN))
        return json({error: 'No autorizado'}, 401);
      if (path === '/commands' && request.method === 'GET') {
        // Conservar IDs durante 7 días; eventos de más de 20 h jamás vuelven a admitirse.
        await env.DB.prepare('DELETE FROM commands WHERE received_at < ?').bind(now - 7 * 86400).run();
        const result = await env.DB.prepare('SELECT id,message_id,phone_id,sender,command,requested_at FROM commands WHERE acknowledged_at IS NULL AND requested_at>=? AND sender=? AND phone_id=? ORDER BY requested_at,id LIMIT 5')
          .bind(now - MAX_AGE, phone(env.OWNER_PHONE), env.PHONE_NUMBER_ID).all();
        return json({version: 1, owner: phone(env.OWNER_PHONE), phone_id: env.PHONE_NUMBER_ID, commands: result.results});
      }
      if (path === '/ack' && request.method === 'POST') {
        let body; try { body = JSON.parse(new TextDecoder().decode(await limitedBody(request, 4096))); } catch { return json({error: 'JSON invalido'}, 400); }
        if (!Array.isArray(body.ids) || body.ids.length > 5 || body.ids.some(id => typeof id !== 'string' || !/^[a-f0-9-]{36}$/.test(id)))
          return json({error: 'IDs invalidos'}, 400);
        if (body.ids.length) await env.DB.batch(body.ids.map(id => env.DB.prepare('UPDATE commands SET acknowledged_at=COALESCE(acknowledged_at,?) WHERE id=?').bind(now, id)));
        return json({ok: true});
      }
      return json({error: 'Metodo no permitido'}, 405);
    } catch (e) {
      // No registrar payloads, números o secretos en logs públicos.
      return json({error: e.message === 'body_limit' ? 'Cuerpo demasiado grande' : 'Servicio temporalmente no disponible'}, e.message === 'body_limit' ? 413 : 503);
    }
  }
};
