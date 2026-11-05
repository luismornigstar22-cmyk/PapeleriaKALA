"""Receptor opcional de confirmaciones Meta. Desplegar con HTTPS, fuera de la PC de caja."""
import os,json,hmac,hashlib,sqlite3,re
from pathlib import Path
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import PlainTextResponse

APP_SECRET=os.environ.get('META_APP_SECRET','')
VERIFY_TOKEN=os.environ.get('META_VERIFY_TOKEN','')
READ_TOKEN=os.environ.get('KALA_STATUS_TOKEN','')
PHONE_ID=os.environ.get('META_PHONE_NUMBER_ID','')
DB=Path(os.environ.get('KALA_WEBHOOK_DB','estados.sqlite3'))
app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)

def validate_config():
    if not APP_SECRET or len(VERIFY_TOKEN)<24 or len(READ_TOKEN)<32 or not PHONE_ID.isdigit():
        raise RuntimeError('Configura META_APP_SECRET, META_VERIFY_TOKEN (24+), KALA_STATUS_TOKEN (32+) y META_PHONE_NUMBER_ID.')

def connect():
    c=sqlite3.connect(DB);c.row_factory=sqlite3.Row
    c.execute('CREATE TABLE IF NOT EXISTS estados(id text PRIMARY KEY,recipient text NOT NULL,status text NOT NULL,ts integer NOT NULL,rank integer NOT NULL)')
    return c

@app.get('/webhook',response_class=PlainTextResponse)
def verify(request:Request):
    validate_config();q=request.query_params
    if q.get('hub.mode')!='subscribe' or not hmac.compare_digest(q.get('hub.verify_token',''),VERIFY_TOKEN):raise HTTPException(403)
    return q.get('hub.challenge','')

@app.post('/webhook')
async def event(request:Request):
    validate_config();body=bytearray()
    async for part in request.stream():
        body.extend(part)
        if len(body)>2_000_000:raise HTTPException(413)
    signature='sha256='+hmac.new(APP_SECRET.encode(),body,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature,request.headers.get('x-hub-signature-256','')):raise HTTPException(403)
    try:d=json.loads(body)
    except ValueError:raise HTTPException(400)
    if d.get('object')!='whatsapp_business_account':return {'ok':True}
    with connect() as c:
        for entry in d.get('entry',[]):
            for change in entry.get('changes',[]):
                value=change.get('value',{})
                if str(value.get('metadata',{}).get('phone_number_id',''))!=PHONE_ID:continue
                for s in value.get('statuses',[]):
                    mid=s.get('id','');recipient=s.get('recipient_id','');status=s.get('status','');ts=s.get('timestamp','')
                    if not isinstance(mid,str) or not 1<=len(mid)<=512 or not re.fullmatch(r'[1-9][0-9]{7,14}',str(recipient)) or not str(ts).isdigit():continue
                    rank={'failed':0,'sent':1,'delivered':2,'read':3}.get(status)
                    if rank is None:continue
                    c.execute('''INSERT INTO estados(id,recipient,status,ts,rank) VALUES(?,?,?,?,?)
                      ON CONFLICT(id) DO UPDATE SET status=excluded.status,ts=excluded.ts,rank=excluded.rank
                      WHERE estados.recipient=excluded.recipient AND ((excluded.rank>=estados.rank AND excluded.ts>=estados.ts) OR (excluded.status='failed' AND estados.rank<2 AND excluded.ts>=estados.ts))''',(mid,str(recipient),status,int(ts),rank))
    return {'ok':True}

@app.get('/status')
def status(request:Request,message_id:str):
    validate_config()
    if not hmac.compare_digest(request.headers.get('authorization',''),'Bearer '+READ_TOKEN):raise HTTPException(403)
    if len(message_id)>512:raise HTTPException(400)
    with connect() as c:r=c.execute('SELECT id,recipient,status,ts FROM estados WHERE id=?',(message_id,)).fetchone()
    if not r:raise HTTPException(404)
    return dict(message_id=r['id'],recipient=r['recipient'],status=r['status'],timestamp=r['ts'])
