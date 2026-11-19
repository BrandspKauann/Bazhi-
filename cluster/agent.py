"""Bounded asynchronous agent. Real SMTP requires two explicit live-mode flags."""
import asyncio
import json
import os
import random
import time
from urllib.parse import urlparse
import uuid

import httpx
import smtp_probe as smtp

BASE=os.getenv('COORDINATOR_URL','http://127.0.0.1:8788').rstrip('/')
TOKEN=os.getenv('AGENT_TOKEN','')
OWNER=os.getenv('NODE_NAME','node')+'-'+uuid.uuid4().hex[:12]
CONCURRENCY=max(1,min(64,int(os.getenv('CONCURRENCY','16'))))
CFG={'timeout':10,'helo':os.getenv('SMTP_HELO','bazhi.com.br'),'remetente':os.getenv('SMTP_SENDER','')}

async def request(client,method,path,body=None):
    for attempt in range(4):
        try:
            r=await client.request(method,BASE+path,json=body)
            if r.status_code>=500:raise httpx.TransportError('Coordenador indisponivel')
            r.raise_for_status()
            return r.json()
        except (httpx.TransportError,httpx.TimeoutException):
            if attempt==3:raise
            await asyncio.sleep(1+attempt)

async def wait_slot(client,mx):
    while True:
        slot=await request(client,'POST','/v1/slot',{'provider':mx})
        if slot['granted']:return
        await asyncio.sleep(max(.1,slot['wait'])+random.random()*.3)

class DomainSession:
    def __init__(self,client,claim):
        self.api=client;self.claim=claim;self.client=None;self.mx=None;self.control='INCONCLUSIVO'

    async def open(self,domain):
        hosts,problem=await asyncio.to_thread(smtp.resolve_mx,domain,CFG)
        if problem:return smtp.result('invalido_dns',stage='dns',message=problem)
        for mx in hosts:
            try:
                await wait_slot(self.api,mx)
                self.client=await asyncio.to_thread(smtp.dial_smtp,mx,CFG)
                self.mx=mx;break
            except Exception:self.client=None
        if not self.client:return smtp.result(message='Os MX nao responderam; nao significa endereco inexistente.')
        cache=await request(self.api,'GET','/v1/control/'+domain)
        if cache.get('mx')==self.mx:self.control=cache['verdict']
        else:
            await wait_slot(self.api,self.mx)
            c,m,stage=await asyncio.to_thread(smtp.mailbox,self.client,'bazhi-check-'+uuid.uuid4().hex+'@'+domain,CFG['remetente'])
            self.control='DETECTADO' if stage=='rcpt_to' and c in (250,251) else 'NAO_DETECTADO' if stage=='rcpt_to' and smtp.missing_mailbox(c,m) else 'INCONCLUSIVO'
            await request(self.api,'POST','/v1/control',{**self.claim,'domain':domain,'mx':self.mx,'verdict':self.control})
            await asyncio.sleep(3)
        return None

    async def verify(self,email,domain):
        valid=smtp.valid_email(email)
        if valid is False:return smtp.result('invalido_formato',stage='formato',message='Formato invalido; SMTP nao consultado.')
        if valid is None:return smtp.result(stage='formato',message='Sintaxe especial nao suportada; nao classificada como invalida.')
        if not self.client:
            early=await self.open(domain)
            if early:return early
        await wait_slot(self.api,self.mx)
        code,message,stage=await asyncio.to_thread(smtp.mailbox,self.client,email,CFG['remetente'])
        text=message.decode('utf-8','replace') if isinstance(message,bytes) else str(message)
        status='inconclusivo'
        if stage=='rcpt_to' and code in (250,251) and self.control=='NAO_DETECTADO':status='smtp_aceito'
        elif stage=='rcpt_to' and smtp.missing_mailbox(code,message):status='smtp_recusado'
        return smtp.result(status,code,stage,self.mx,self.control,text,stage=='rcpt_to')

    def close(self):
        if self.client:self.client.close();self.client=None

async def heartbeat(client,lease,stop,lost):
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(),timeout=30)
        except asyncio.TimeoutError:
            try:
                r=await request(client,'POST','/v1/heartbeat',lease)
                if not r['renewed']:lost.set();return
            except Exception:lost.set();return

async def process_claim(client,claim):
    lease={'owner':OWNER,'lease':claim['lease']}
    stop=asyncio.Event();lost=asyncio.Event()
    pulse=asyncio.create_task(heartbeat(client,lease,stop,lost))
    session=DomainSession(client,lease)
    try:
        for job in claim['jobs']:
            if lost.is_set():break
            await request(client,'POST',f'/v1/jobs/{job["id"]}/start',lease)
            if claim['mode']=='simulation':
                result={'status':'simulado','smtp_verificado':False,'observacao':'Teste sintetico da fila, sem DNS ou SMTP.'}
            else:
                try:result=await session.verify(job['email'],job['domain'])
                except Exception as exc:
                    session.close()
                    result=smtp.result(message=type(exc).__name__+': '+str(exc)[:250])
            await request(client,'POST',f'/v1/jobs/{job["id"]}/finish',{**lease,'result':result})
            if claim['mode']=='live':await asyncio.sleep(3)
    finally:
        stop.set();await pulse
        session.close()
        try:await request(client,'POST','/v1/release',lease)
        except Exception:pass

async def worker(client):
    while True:
        try:
            claim=await request(client,'POST','/v1/claim',{'owner':OWNER,'limit':5})
            if not claim['jobs']:await asyncio.sleep(3);continue
            await process_claim(client,claim)
        except asyncio.CancelledError:raise
        except Exception as exc:
            print('Falha de infraestrutura; aguardando sem repetir SMTP iniciado:',type(exc).__name__,flush=True)
            await asyncio.sleep(5)

async def main():
    url=urlparse(BASE)
    if url.scheme!='https' and url.hostname not in ('localhost','127.0.0.1','coordinator'):
        raise RuntimeError('Use HTTPS para um coordenador remoto.')
    if len(TOKEN)<32:raise RuntimeError('Configure AGENT_TOKEN privado.')
    limits=httpx.Limits(max_connections=CONCURRENCY*2+4,max_keepalive_connections=CONCURRENCY*2)
    async with httpx.AsyncClient(headers={'Authorization':'Bearer '+TOKEN},timeout=20,limits=limits) as client:
        health=await request(client,'GET','/health')
        if health['mode']=='live':
            if os.getenv('ALLOW_REAL_SMTP')!='1' or smtp.valid_email(CFG['remetente']) is not True:
                raise RuntimeError('SMTP real exige ALLOW_REAL_SMTP=1 e SMTP_SENDER real configurado.')
        print(f'Agente {OWNER}: {CONCURRENCY} consultas concorrentes, modo {health["mode"]}.',flush=True)
        await asyncio.gather(*(worker(client) for _ in range(CONCURRENCY)))

if __name__=='__main__':
    try:asyncio.run(main())
    except KeyboardInterrupt:print('Agente parado; reservas serao recuperadas sem repetir SMTP iniciado.')
