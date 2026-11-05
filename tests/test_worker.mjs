// Run with Miniflare installed. No live Cloudflare account / Kapso messages used.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHmac} from 'node:crypto';
const {Miniflare} = await import(process.env.MINIFLARE_MODULE || 'miniflare');
const root = new URL('../', import.meta.url);
const secret='test-webhook-secret-'+ 'x'.repeat(32), token='test-desktop-token-'+ 'y'.repeat(32);
const mf = new Miniflare({modules: true, script:readFileSync(new URL('cloudflare/worker.mjs',root),'utf8'),
  compatibilityDate:'2026-08-01',d1Databases:{DB:'kala-test'},
  bindings:{WEBHOOK_SECRET:secret,DESKTOP_TOKEN:token,PHONE_NUMBER_ID:'123',OWNER_PHONE:'525512345678'}});
try {
 const db=await mf.getD1Database('DB');
 const schema=readFileSync(new URL('cloudflare/schema.sql',root),'utf8').replace(/^--.*$/gm,'');
 for(const sql of schema.split(';').filter(x=>x.trim()))await db.prepare(sql).run();
 const now=Math.floor(Date.now()/1000);
 const event=(id='wamid.test')=>({phone_number_id:'123',message:{id,from:'525512345678',type:'text',timestamp:String(now),text:{body:'MENÚ'},kapso:{direction:'inbound'}}});
 async function webhook(body, headers={}) {
   const raw=typeof body==='string'?body:JSON.stringify(body);
   return mf.dispatchFetch('https://bot.example/webhook',{method:'POST',body:raw,headers:{'Content-Type':'application/json','X-Webhook-Event':'whatsapp.message.received','X-Webhook-Payload-Version':'v2','X-Webhook-Signature':createHmac('sha256',secret).update(raw).digest('hex'),...headers}});
 }
 const pending=()=>mf.dispatchFetch('https://bot.example/commands',{headers:{Authorization:'Bearer '+token}}).then(r=>r.json());
 assert.equal((await mf.dispatchFetch('https://bot.example/commands')).status,401);
 assert.equal((await webhook(event(),{'X-Webhook-Signature':'0'.repeat(64)})).status,401);
 assert.equal((await webhook(event(),{'X-Webhook-Payload-Version':'v1'})).status,400);
 assert.equal((await webhook(event())).status,200);
 assert.equal((await webhook(event())).status,200);
 let list=(await pending()).commands;assert.equal(list.length,1);assert.equal(list[0].command,'menu');
 for (const edit of [e=>e.message.from='525500000000',e=>e.phone_number_id='999',e=>e.message.kapso.direction='outbound',e=>e.message.timestamp=String(now-21*3600),e=>delete e.message.from,e=>e.message.kapso.passive=true]) {
   const e=event(crypto.randomUUID());edit(e);assert.equal((await webhook(e)).status,200);
 }
 assert.equal((await pending()).commands.length,1);
 const e2=event('wamid.2');e2.message.text.body='bitácora hoy 2';
 const e3=event('wamid.3');e3.message.text.body='ventas hoy';
 assert.equal((await webhook({batch:true,data:[e2,e3]})).status,200);
 list=(await pending()).commands;assert.equal(list.length,3);
 assert.deepEqual(new Set(list.map(x=>x.command)),new Set(['menu','ventas hoy','bitacora hoy 2']));
 assert.equal((await mf.dispatchFetch('https://bot.example/ack',{method:'POST',body:JSON.stringify({ids:list.map(x=>x.id)}),headers:{Authorization:'Bearer '+token}})).status,200);
 assert.equal((await pending()).commands.length,0);
 await webhook(event());assert.equal((await pending()).commands.length,0);
 const sql=event('wamid.sql');sql.message.text.body='DROP TABLE commands;';await webhook(sql);
 assert.equal((await pending()).commands[0].command,'menu');
 assert.equal((await webhook('x'.repeat(262145))).status,413);
 assert.equal((await webhook('{bad json')).status,400);
 assert.equal((await mf.dispatchFetch('https://bot.example/ack',{method:'POST',body:JSON.stringify({ids:['x']}),headers:{Authorization:'Bearer '+token}})).status,400);
 // DB unavailable => do not acknowledge; Kapso may retry.
 await db.prepare('DROP TABLE commands').run();
 assert.equal((await webhook(event('wamid.dbdown'))).status,503);
 console.log('PASS Cloudflare runtime + D1: HMAC, invalid headers, unauthorized owner, other channel, inbound only, TTL, batching, dedupe, durable ACK, SQL text harmless, size limit, DB failure.');
} finally {await mf.dispose();}
