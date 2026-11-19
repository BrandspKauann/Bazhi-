"""Coordinator: persistent PostgreSQL queue; agents never open the database."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime,timezone
import hmac
import json
import os
from pathlib import Path
import uuid

import asyncpg
from fastapi import FastAPI,Depends,Header,HTTPException
from pydantic import BaseModel,Field

MODE=os.getenv('CLUSTER_MODE','simulation')
ADMIN=os.getenv('ADMIN_TOKEN','')
AGENT=os.getenv('AGENT_TOKEN','')
SCHEMA=os.getenv('PG_SCHEMA','public')
PROVIDER_INTERVAL=max(.5,float(os.getenv('PROVIDER_INTERVAL','1')))
DOMAIN_INTERVAL=0 if MODE=='simulation' else max(2,float(os.getenv('DOMAIN_INTERVAL','3')))
LEASE_SECONDS=180

@asynccontextmanager
async def lifespan(app):
    if len(ADMIN)<32 or len(AGENT)<32 or ADMIN==AGENT:
        raise RuntimeError('Configure dois tokens diferentes, com pelo menos 32 caracteres.')
    if MODE not in ('simulation','live') or not SCHEMA.replace('_','').isalnum():
        raise RuntimeError('Modo ou schema invalido.')
    pool=await asyncpg.create_pool(os.environ['DATABASE_URL'],min_size=1,max_size=8,
          command_timeout=30,server_settings={'search_path':SCHEMA})
    app.state.pool=pool
    try:
        async with pool.acquire() as con:
            await con.execute(Path(__file__).with_name('schema.sql').read_text())
            await con.execute('INSERT INTO cluster_settings(id,mode) VALUES (1,$1) ON CONFLICT DO NOTHING',MODE)
            actual=await con.fetchval('SELECT mode FROM cluster_settings WHERE id=1')
            if actual!=MODE:raise RuntimeError('Nao misture simulacao e SMTP real no mesmo banco.')
        yield
    finally:await pool.close()

app=FastAPI(title='Bazhi Cluster',lifespan=lifespan,docs_url=None,redoc_url=None)

def auth(expected):
    async def check(authorization:str=Header(default='')):
        supplied=authorization.removeprefix('Bearer ')
        if not expected or not hmac.compare_digest(supplied.encode(),expected.encode()):
            raise HTTPException(401,'Acesso negado')
    return check

admin=Depends(auth(ADMIN))
agent=Depends(auth(AGENT))

class ImportRow(BaseModel):
    email:str=Field(min_length=1,max_length=1024)
    source_id:int=Field(ge=1)
    result:dict|None=None

class ImportBatch(BaseModel):
    source:str=Field(min_length=1,max_length=200)
    rows:list[ImportRow]=Field(min_length=1,max_length=5000)

class Claim(BaseModel):
    owner:str=Field(min_length=1,max_length=100)
    limit:int=Field(default=5,ge=1,le=20)

class Lease(BaseModel):
    lease:uuid.UUID
    owner:str=Field(min_length=1,max_length=100)

class Finish(Lease):
    result:dict

class Slot(BaseModel):
    provider:str=Field(min_length=1,max_length=255)

class Processing(BaseModel):
    enabled:bool

class Acknowledge(BaseModel):
    ids:list[int]=Field(min_length=1,max_length=5000)

class Control(Lease):
    domain:str=Field(min_length=1,max_length=255)
    mx:str=Field(min_length=1,max_length=255)
    verdict:str

@app.get('/health')
async def health():return {'ok':True,'mode':MODE}

@app.post('/v1/import',dependencies=[admin])
async def import_batch(body:ImportBatch):
    records=[]
    for row in body.rows:
        email=row.email.strip().lower()
        if MODE=='simulation' and not email.endswith('.test'):
            raise HTTPException(422,'Simulacao aceita somente enderecos .test')
        records.append((email,email.rsplit('@',1)[-1],row.source_id,json.dumps(row.result) if row.result is not None else None))
    async with app.state.pool.acquire() as con,con.transaction():
        if await con.fetchval('SELECT enabled FROM cluster_settings WHERE id=1 FOR UPDATE'):
            raise HTTPException(409,'Pause a nova fila antes de importar.')
        await con.execute('CREATE TEMP TABLE import_stage(email text,domain text,source_id bigint,result jsonb) ON COMMIT DROP')
        await con.copy_records_to_table('import_stage',records=records)
        await con.execute('''INSERT INTO jobs(email,domain,source_id,state,result,finished_at)
          SELECT DISTINCT ON(email) email,domain,source_id,CASE WHEN result IS NULL THEN 'pending' ELSE 'done' END,result,
          CASE WHEN result IS NULL THEN NULL ELSE now() END FROM import_stage ORDER BY email,source_id DESC
          ON CONFLICT(email) DO UPDATE SET state='done',result=excluded.result,finished_at=excluded.finished_at
          WHERE jobs.state='pending' AND excluded.result IS NOT NULL''')
        await con.execute('INSERT INTO domains(domain) SELECT DISTINCT domain FROM import_stage WHERE result IS NULL ON CONFLICT DO NOTHING')
        last=max(row.source_id for row in body.rows)
        await con.execute('''INSERT INTO import_sessions(source,last_id) VALUES($1,$2)
          ON CONFLICT(source) DO UPDATE SET last_id=greatest(import_sessions.last_id,excluded.last_id),updated_at=now()''',body.source,last)
    return {'accepted':len(records),'last_id':last}

@app.get('/v1/import/{source}/cursor',dependencies=[admin])
async def import_cursor(source:str):
    async with app.state.pool.acquire() as con:
        return {'last_id':await con.fetchval('SELECT last_id FROM import_sessions WHERE source=$1',source) or 0}

async def recover_expired(con):
    # A job which reached SMTP must never be automatically probed again.
    await con.execute("""UPDATE jobs SET state='done',finished_at=now(),result=
      '{"status":"inconclusivo","confiabilidade":"inconclusivo","smtp_verificado":false,"observacao":"Agente interrompido apos iniciar. Nao repetir automaticamente."}'::jsonb
      WHERE state='started' AND lease_until<now()""")
    await con.execute("UPDATE jobs SET state='pending',lease=NULL,owner=NULL WHERE state='leased' AND lease_until<now()")

@app.post('/v1/claim',dependencies=[agent])
async def claim(body:Claim):
    async with app.state.pool.acquire() as con,con.transaction():
        if not await con.fetchval('SELECT enabled FROM cluster_settings WHERE id=1'):
            return {'jobs':[],'mode':MODE,'paused':True}
        await recover_expired(con)
        row=await con.fetchrow("""SELECT d.domain FROM domains d WHERE d.available_at<=now() AND d.lease_until<=now()
          AND EXISTS(SELECT 1 FROM jobs j WHERE j.domain=d.domain AND j.state='pending')
          ORDER BY d.available_at LIMIT 1 FOR UPDATE OF d SKIP LOCKED""")
        if not row:return {'jobs':[],'mode':MODE}
        domain=row['domain'];lease=uuid.uuid4()
        await con.execute("UPDATE domains SET lease=$1,lease_until=now()+make_interval(secs=>$2) WHERE domain=$3",lease,LEASE_SECONDS,domain)
        jobs=await con.fetch("""UPDATE jobs SET state='leased',lease=$1,owner=$2,lease_until=now()+make_interval(secs=>$3)
          WHERE id IN (SELECT id FROM jobs WHERE domain=$4 AND state='pending' ORDER BY id LIMIT $5 FOR UPDATE SKIP LOCKED)
          RETURNING id,email,domain""",lease,body.owner,LEASE_SECONDS,domain,body.limit)
    return {'lease':str(lease),'jobs':[dict(j) for j in jobs],'mode':MODE}

@app.post('/v1/heartbeat',dependencies=[agent])
async def heartbeat(body:Lease):
    async with app.state.pool.acquire() as con,con.transaction():
        ids=await con.fetch("""UPDATE jobs SET lease_until=now()+make_interval(secs=>$1)
          WHERE lease=$2 AND owner=$3 AND state IN ('leased','started') AND lease_until>now() RETURNING id""",LEASE_SECONDS,body.lease,body.owner)
        if ids:await con.execute('UPDATE domains SET lease_until=now()+make_interval(secs=>$1) WHERE lease=$2',LEASE_SECONDS,body.lease)
    return {'renewed':len(ids)}

@app.post('/v1/jobs/{job_id}/start',dependencies=[agent])
async def start(job_id:int,body:Lease):
    async with app.state.pool.acquire() as con:
        row=await con.fetchrow("""UPDATE jobs SET state='started',started_at=coalesce(started_at,now())
          WHERE id=$1 AND lease=$2 AND owner=$3 AND state IN ('leased','started') AND lease_until>now() RETURNING id""",job_id,body.lease,body.owner)
    if not row:raise HTTPException(409,'Reserva expirada ou endereco ja concluido')
    return {'started':True}

@app.post('/v1/jobs/{job_id}/finish',dependencies=[agent])
async def finish(job_id:int,body:Finish):
    status=body.result.get('status')
    allowed={'simulado'} if MODE=='simulation' else {'smtp_aceito','smtp_recusado','inconclusivo','invalido_dns','invalido_formato'}
    if status not in allowed:raise HTTPException(422,'Resultado incompativel com o modo')
    if status=='smtp_aceito' and not (body.result.get('codigo_smtp') in (250,251) and body.result.get('etapa_smtp')=='rcpt_to' and body.result.get('catch_all')=='NAO_DETECTADO' and body.result.get('smtp_verificado')):
        raise HTTPException(422,'Aceitacao SMTP exige RCPT positivo e controle negativo.')
    async with app.state.pool.acquire() as con,con.transaction():
        row=await con.fetchrow('SELECT state,lease,owner FROM jobs WHERE id=$1 FOR UPDATE',job_id)
        if not row or row['lease']!=body.lease or row['owner']!=body.owner:raise HTTPException(409,'Reserva incorreta')
        if row['state']=='done':return {'saved':True,'duplicate':True}
        if row['state']!='started':raise HTTPException(409,'Marque o inicio antes de verificar')
        await con.execute("UPDATE jobs SET state='done',result=$1::jsonb,finished_at=now() WHERE id=$2",json.dumps(body.result),job_id)
    return {'saved':True}

@app.post('/v1/release',dependencies=[agent])
async def release(body:Lease):
    async with app.state.pool.acquire() as con,con.transaction():
        await con.execute("UPDATE jobs SET state='pending',lease=NULL,owner=NULL WHERE lease=$1 AND owner=$2 AND state='leased'",body.lease,body.owner)
        # Started jobs stay unavailable until their lease expires; never repeat SMTP.
        unfinished=await con.fetchval("SELECT exists(SELECT 1 FROM jobs WHERE lease=$1 AND state='started')",body.lease)
        if not unfinished:
            await con.execute('UPDATE domains SET lease=NULL,lease_until=\'-infinity\',available_at=now()+make_interval(secs=>$1) WHERE lease=$2',DOMAIN_INTERVAL,body.lease)
    return {'released':True}

@app.post('/v1/slot',dependencies=[agent])
async def slot(body:Slot):
    async with app.state.pool.acquire() as con,con.transaction():
        await con.execute('INSERT INTO provider_limits VALUES($1,now()) ON CONFLICT DO NOTHING',body.provider.lower())
        wait=await con.fetchval('SELECT greatest(0,extract(epoch FROM(next_at-now()))) FROM provider_limits WHERE provider=$1 FOR UPDATE',body.provider.lower())
        if wait<=0:await con.execute('UPDATE provider_limits SET next_at=now()+make_interval(secs=>$1) WHERE provider=$2',PROVIDER_INTERVAL,body.provider.lower())
    return {'wait':min(10,float(wait)),'granted':wait<=0}

@app.post('/v1/control',dependencies=[agent])
async def put_control(body:Control):
    if body.verdict not in ('DETECTADO','NAO_DETECTADO','INCONCLUSIVO'):raise HTTPException(422,'Controle invalido')
    async with app.state.pool.acquire() as con:
        valid=await con.fetchval('SELECT exists(SELECT 1 FROM jobs WHERE domain=$1 AND lease=$2 AND owner=$3 AND lease_until>now())',body.domain,body.lease,body.owner)
        if not valid:raise HTTPException(409,'Reserva expirada')
        await con.execute('INSERT INTO control_cache VALUES($1,$2,$3,now()+interval \'6 hours\') ON CONFLICT(domain) DO UPDATE SET mx=excluded.mx,verdict=excluded.verdict,expires_at=excluded.expires_at',body.domain,body.mx,body.verdict)
    return {'saved':True}

@app.get('/v1/control/{domain}',dependencies=[agent])
async def get_control(domain:str):
    async with app.state.pool.acquire() as con:
        row=await con.fetchrow('SELECT mx,verdict FROM control_cache WHERE domain=$1 AND expires_at>now()',domain)
    return dict(row) if row else {}

@app.get('/v1/stats',dependencies=[admin])
async def stats():
    async with app.state.pool.acquire() as con:
        states=await con.fetch('SELECT state,count(*) count FROM jobs GROUP BY state')
        recent=await con.fetchval("SELECT count(*) FROM jobs WHERE finished_at>now()-interval '60 seconds'")
        counts=await con.fetch("SELECT result->>'status' status,count(*) count FROM jobs WHERE state='done' GROUP BY 1")
        enabled=await con.fetchval('SELECT enabled FROM cluster_settings WHERE id=1')
    return {'mode':MODE,'processing_enabled':enabled,'states':{r['state']:r['count'] for r in states},'results':{r['status']:r['count'] for r in counts},'finished_last_minute':recent}

@app.post('/v1/processing',dependencies=[admin])
async def processing(body:Processing):
    async with app.state.pool.acquire() as con:
        await con.execute('UPDATE cluster_settings SET enabled=$1 WHERE id=1',body.enabled)
    return {'processing_enabled':body.enabled}

@app.get('/v1/results',dependencies=[admin])
async def results(limit:int=1000):
    async with app.state.pool.acquire() as con:
        rows=await con.fetch("SELECT id,email,result FROM jobs WHERE exported_at IS NULL AND state='done' ORDER BY id LIMIT $1",min(5000,max(1,limit)))
    return {'rows':[{'id':r['id'],'email':r['email'],'result':json.loads(r['result'])} for r in rows]}

@app.post('/v1/results/ack',dependencies=[admin])
async def acknowledge(body:Acknowledge):
    async with app.state.pool.acquire() as con:
        await con.execute("UPDATE jobs SET exported_at=now() WHERE id=ANY($1::bigint[]) AND state='done'",body.ids)
    return {'acknowledged':True}
