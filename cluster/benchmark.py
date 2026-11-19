"""Synthetic queue benchmark on an isolated schema. Does not measure SMTP."""
import asyncio
import json
from pathlib import Path
import time
from test_cluster import QueueTests

async def main():
    test=QueueTests(methodName='test_auth_and_paused_by_default')
    await test.asyncSetUp()
    total=5000;done=0;seen=set()
    try:
        for first in range(0,total,1000):
            rows=[{'email':f'user{i}@domain{i%500}.example.test','source_id':i+1} for i in range(first,min(first+1000,total))]
            r=await test.call('/v1/import',{'source':'benchmark','rows':rows},admin=True)
            r.raise_for_status()
        await test.enable()
        start=time.perf_counter()
        async def worker(index):
            nonlocal done
            owner='benchmark-'+str(index)
            while done<total:
                if time.perf_counter()-start>180:raise RuntimeError('Benchmark excedeu 180 segundos; nao e resultado SMTP.')
                claim=await test.claim(owner)
                if not claim['jobs']:
                    await asyncio.sleep(.02);continue
                for job in claim['jobs']:
                    if job['id'] in seen:raise AssertionError('Tarefa repetida durante o benchmark')
                    seen.add(job['id'])
                    await test.complete(claim,job,owner)
                    done+=1
                await test.call('/v1/release',{'owner':owner,'lease':claim['lease']})
        await asyncio.gather(*(worker(i) for i in range(32)))
        elapsed=time.perf_counter()-start
        report={'mode':'simulation','smtp_queries':0,'jobs_completed':done,'unique_jobs':len(seen),
          'concurrency':32,'seconds':round(elapsed,3),'queue_jobs_per_second':round(done/elapsed,2),
          'scope':'Somente fila/API/PostgreSQL. Nao mede SMTP, DNS, provedores ou capacidade em producao.'}
        Path('pilot-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))
    finally:await test.asyncTearDown()

if __name__=='__main__':asyncio.run(main())
