"""Small administrative CLI; never prints tokens."""
import argparse
import json
import os
from urllib.parse import urlparse
from pathlib import Path
import httpx

def main():
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=['stats','enable','pause','seed-simulation','download'])
    p.add_argument('--count',type=int,default=10000)
    p.add_argument('--output',default='results.jsonl')
    a=p.parse_args();base=os.getenv('COORDINATOR_URL','http://127.0.0.1:8788').rstrip('/')
    if urlparse(base).scheme!='https' and urlparse(base).hostname not in ('127.0.0.1','localhost','coordinator'):
        raise RuntimeError('Administracao remota exige HTTPS.')
    with httpx.Client(headers={'Authorization':'Bearer '+os.environ['ADMIN_TOKEN']},timeout=120) as c:
        if a.command=='stats':
            r=c.get(base+'/v1/stats');r.raise_for_status();print(json.dumps(r.json(),indent=2))
        elif a.command in ('enable','pause'):
            r=c.post(base+'/v1/processing',json={'enabled':a.command=='enable'});r.raise_for_status();print(r.json())
        elif a.command=='seed-simulation':
            health=c.get(base+'/health');health.raise_for_status()
            if health.json()['mode']!='simulation':raise RuntimeError('Recusado: nao carregue dados de teste no banco real.')
            for start in range(0,a.count,1000):
                rows=[{'email':f'user{i}@domain{i%500}.example.test','source_id':i+1} for i in range(start,min(start+1000,a.count))]
                r=c.post(base+'/v1/import',json={'source':'simulation','rows':rows});r.raise_for_status()
            print('Dados sinteticos carregados; nenhum SMTP foi consultado. Ative a fila para medir.')
        else:
            # Durable local append before acknowledgement. Duplicate rows after
            # an interrupted ACK are harmless and can be keyed by job id.
            with Path(a.output).open('a',encoding='utf-8') as output:
                while True:
                    r=c.get(base+'/v1/results');r.raise_for_status();rows=r.json()['rows']
                    if not rows:break
                    for row in rows:output.write(json.dumps(row,ensure_ascii=False)+'\n')
                    output.flush();os.fsync(output.fileno())
                    r=c.post(base+'/v1/results/ack',json={'ids':[r['id'] for r in rows]});r.raise_for_status()
            print('Resultados gravados localmente antes da confirmacao de recebimento.')

if __name__=='__main__':main()
