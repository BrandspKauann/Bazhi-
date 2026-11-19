import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import AsyncMock,patch
import uuid

import asyncpg
import httpx

ROOT=Path(__file__).resolve().parent

@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'),'PostgreSQL de teste nao configurado')
class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.url=os.environ['TEST_DATABASE_URL'];self.schema='test_'+uuid.uuid4().hex
        self.db=await asyncpg.connect(self.url)
        await self.db.execute('CREATE SCHEMA '+self.schema)
        os.environ.update(DATABASE_URL=self.url,PG_SCHEMA=self.schema,CLUSTER_MODE='simulation',ADMIN_TOKEN='a'*48,AGENT_TOKEN='b'*48)
        spec=importlib.util.spec_from_file_location('isolated_server',ROOT/'server.py')
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        self.lifespan=self.module.app.router.lifespan_context(self.module.app)
        await self.lifespan.__aenter__()
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.module.app),base_url='http://test')
        self.admin={'Authorization':'Bearer '+'a'*48};self.agent={'Authorization':'Bearer '+'b'*48}

    async def asyncTearDown(self):
        await self.client.aclose();await self.lifespan.__aexit__(None,None,None)
        await self.db.execute('DROP SCHEMA '+self.schema+' CASCADE');await self.db.close()

    async def call(self,path,body=None,admin=False,method='POST'):
        return await self.client.request(method,path,json=body,headers=self.admin if admin else self.agent)

    async def seed(self,emails):
        r=await self.call('/v1/import',{'source':'fixture','rows':[{'email':e,'source_id':i+1} for i,e in enumerate(emails)]},admin=True)
        self.assertEqual(r.status_code,200,r.text)

    async def enable(self):
        r=await self.call('/v1/processing',{'enabled':True},admin=True);self.assertEqual(r.status_code,200)

    async def claim(self,owner='worker'):
        r=await self.call('/v1/claim',{'owner':owner,'limit':5});self.assertEqual(r.status_code,200,r.text);return r.json()

    async def complete(self,claim,job,owner='worker'):
        lease={'lease':claim['lease'],'owner':owner}
        r=await self.call(f'/v1/jobs/{job["id"]}/start',lease);self.assertEqual(r.status_code,200,r.text)
        r=await self.call(f'/v1/jobs/{job["id"]}/finish',{**lease,'result':{'status':'simulado','smtp_verificado':False}})
        self.assertEqual(r.status_code,200,r.text)
        return lease

    async def test_auth_and_paused_by_default(self):
        self.assertEqual((await self.client.post('/v1/claim',json={'owner':'x'})).status_code,401)
        self.assertEqual((await self.call('/v1/import',{'source':'x','rows':[{'email':'x@a.test','source_id':1}]})).status_code,401)
        self.assertEqual((await self.call('/v1/claim',{'owner':'x'},admin=True)).status_code,401)
        await self.seed(['x@a.test']);self.assertEqual((await self.claim())['jobs'],[])

    async def test_no_real_emails_in_simulation_and_import_idempotence(self):
        r=await self.call('/v1/import',{'source':'x','rows':[{'email':'x@gmail.com','source_id':1}]},admin=True)
        self.assertEqual(r.status_code,422)
        await self.seed(['x@a.test']);await self.seed(['x@a.test'])
        self.assertEqual(await self.db.fetchval('SELECT count(*) FROM '+self.schema+'.jobs'),1)

    async def test_concurrent_claims_do_not_duplicate_domain(self):
        await self.seed([f'u{i}@same.test' for i in range(20)]);await self.enable()
        claims=await asyncio.gather(*(self.claim(str(i)) for i in range(20)))
        with_jobs=[c for c in claims if c['jobs']]
        self.assertEqual(len(with_jobs),1)
        self.assertEqual(len({j['id'] for c in with_jobs for j in c['jobs']}),5)

    async def test_different_domains_claim_in_parallel(self):
        await self.seed([f'u@d{i}.test' for i in range(30)]);await self.enable()
        claims=await asyncio.gather(*(self.claim(str(i)) for i in range(20)))
        jobs=[j['id'] for c in claims for j in c['jobs']]
        self.assertEqual(len(jobs),20);self.assertEqual(len(set(jobs)),20)

    async def test_expired_started_is_not_retried(self):
        await self.seed(['a@a.test','b@a.test']);await self.enable();claim=await self.claim()
        first=claim['jobs'][0]
        await self.call(f'/v1/jobs/{first["id"]}/start',{'owner':'worker','lease':claim['lease']})
        await self.db.execute(f"UPDATE {self.schema}.jobs SET lease_until=now()-interval '1 second'")
        await self.db.execute(f"UPDATE {self.schema}.domains SET lease_until=now()-interval '1 second'")
        recovered=await self.claim('other')
        self.assertNotIn(first['id'],[j['id'] for j in recovered['jobs']])
        self.assertEqual(len(recovered['jobs']),1)
        row=await self.db.fetchrow(f'SELECT state,result FROM {self.schema}.jobs WHERE id=$1',first['id'])
        self.assertEqual(row['state'],'done');self.assertEqual(json.loads(row['result'])['status'],'inconclusivo')

    async def test_finish_idempotent_and_wrong_owner_rejected(self):
        await self.seed(['x@a.test']);await self.enable();claim=await self.claim();job=claim['jobs'][0]
        lease=await self.complete(claim,job)
        r=await self.call(f'/v1/jobs/{job["id"]}/finish',{**lease,'result':{'status':'simulado'}})
        self.assertTrue(r.json()['duplicate'])
        r=await self.call(f'/v1/jobs/{job["id"]}/start',{**lease,'owner':'wrong'})
        self.assertEqual(r.status_code,409)

    async def test_outbox_does_not_skip_late_low_id(self):
        await self.seed(['a@a.test','b@b.test']);await self.enable()
        claims=[await self.claim(),await self.claim()];claims.sort(key=lambda c:c['jobs'][0]['id'])
        high=claims[1];low=claims[0]
        await self.complete(high,high['jobs'][0])
        r=await self.call('/v1/results',admin=True,method='GET');rows=r.json()['rows']
        await self.call('/v1/results/ack',{'ids':[r['id'] for r in rows]},admin=True)
        await self.complete(low,low['jobs'][0])
        r=await self.call('/v1/results',admin=True,method='GET')
        self.assertEqual([r['id'] for r in r.json()['rows']],[low['jobs'][0]['id']])

    async def test_provider_limit_and_live_status_rejected(self):
        a=await self.call('/v1/slot',{'provider':'same.mx.test'})
        b=await self.call('/v1/slot',{'provider':'same.mx.test'})
        self.assertTrue(a.json()['granted']);self.assertFalse(b.json()['granted'])
        await self.seed(['a@a.test']);await self.enable();claim=await self.claim();job=claim['jobs'][0]
        r=await self.call(f'/v1/jobs/{job["id"]}/finish',{'owner':'worker','lease':claim['lease'],'result':{'status':'smtp_aceito'}})
        self.assertEqual(r.status_code,422)

class ProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_acceptance_needs_control_and_policy_is_inconclusive(self):
        import agent
        for control,actual,expected in [((550,b'5.1.1 no such user'),(250,b'OK'),'smtp_aceito'),((250,b'OK'),(250,b'OK'),'inconclusivo'),((550,b'5.1.1 unknown user'),(550,b'5.7.1 policy'),'inconclusivo')]:
            class FakeSMTP:
                def rset(self):return 250,b'OK'
                def mail(self,sender):return 250,b'OK'
                def rcpt(self,address):return control if address.startswith('bazhi-check-') else actual
                def close(self):pass
            async def api(*args,**kwargs):return {}
            with patch.object(agent.smtp,'resolve_mx',return_value=(['mx.test'],None)),patch.object(agent.smtp,'dial_smtp',return_value=FakeSMTP()),patch.object(agent,'wait_slot',new=AsyncMock()),patch.object(agent,'request',side_effect=api),patch.object(agent.asyncio,'sleep',new=AsyncMock()):
                session=agent.DomainSession(None,{'owner':'x','lease':str(uuid.uuid4())})
                result=await session.verify('a@domain.test','domain.test')
                self.assertEqual(result['status'],expected)
                session.close()

class MigrationTests(unittest.TestCase):
    def test_read_only_existing_results_and_invalid_nul(self):
        import migrate
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'fila.sqlite';con=sqlite3.connect(p)
            con.executescript('CREATE TABLE emails(id INTEGER PRIMARY KEY,email TEXT,attempts INTEGER,last_id INTEGER);CREATE TABLE attempts(id INTEGER PRIMARY KEY,status TEXT,confiabilidade TEXT,smtp_verificado INTEGER,codigo_smtp INTEGER,etapa_smtp TEXT,mx TEXT,catch_all TEXT,testado_em TEXT,observacao TEXT);CREATE TABLE domains(lease_until REAL);')
            con.execute("INSERT INTO attempts VALUES(1,'inconclusivo','inconclusivo',0,NULL,'conexao','','INCONCLUSIVO','2026','timeout')")
            con.executemany('INSERT INTO emails VALUES(?,?,?,?)',[(1,'done@x.test',1,1),(2,'pending@x.test',0,None),(3,'bad\x00@x.test',0,None)]);con.commit();con.close()
            before=p.read_bytes();rows=[r for batch in migrate.pages(p,batch=2) for r in batch]
            self.assertEqual(len(rows),3);self.assertIsNotNone(rows[0]['result']);self.assertIsNone(rows[1]['result']);self.assertEqual(rows[2]['result']['status'],'invalido_formato')
            with self.assertRaises(RuntimeError):migrate.paused(p)
            self.assertEqual(before,p.read_bytes())
            (Path(folder)/'PARAR').touch();migrate.paused(p)

if __name__=='__main__':unittest.main(verbosity=2)
