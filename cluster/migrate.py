"""Read-only migration. Requires the original queue paused before any upload."""
import argparse
from contextlib import closing
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlparse

import httpx

def source_path(config):
    cfg=json.loads(Path(config).read_text(encoding='utf-8-sig'))
    return Path(cfg['dados']).resolve()/'fila.sqlite'

def readonly(path):
    con=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)
    con.row_factory=sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    return con

def paused(path):
    if not (path.parent/'PARAR').exists():
        raise RuntimeError('A origem continua ativa. A migracao nao cria nem altera o arquivo PARAR. Planeje a parada primeiro.')
    with closing(readonly(path)) as con:
        if con.execute('SELECT 1 FROM domains WHERE lease_until>? LIMIT 1',(time.time(),)).fetchone():
            raise RuntimeError('Ainda existem reservas ativas; aguarde os trabalhadores terminarem.')

def pages(path,after=0,batch=5000):
    while True:
        con=readonly(path)
        try:
            rows=con.execute('''SELECT e.id,e.email,e.attempts,a.status,a.confiabilidade,a.smtp_verificado,
              a.codigo_smtp,a.etapa_smtp,a.mx,a.catch_all,a.testado_em,a.observacao
              FROM emails e LEFT JOIN attempts a ON a.id=e.last_id
              WHERE e.id>? ORDER BY e.id LIMIT ?''',(after,batch)).fetchall()
        finally:con.close()
        if not rows:return
        records=[]
        for row in rows:
            email=row['email'];result=None
            if row['attempts']:
                result={k:row[k] for k in ('status','confiabilidade','smtp_verificado','codigo_smtp','etapa_smtp','mx','catch_all','testado_em','observacao')}
                if not result['status']:
                    result.update(status='inconclusivo',confiabilidade='inconclusivo',smtp_verificado=False,observacao='Tentativa anterior registrada sem resultado; nao repetir.')
            if len(email)>1024 or '\x00' in email:
                # PostgreSQL text/jsonb do not accept NUL. Keep a reversible
                # original representation in metadata, never turn it into SMTP.
                raw=email.encode('utf-8')
                email='invalid-'+hashlib.sha256(raw).hexdigest()+'@invalid.test'
                result={'status':'invalido_formato','smtp_verificado':False,'source_raw_b64':base64.b64encode(raw).decode('ascii'),'observacao':'Endereco original nao representavel; nao consultar SMTP.'}
            records.append({'email':email,'source_id':row['id'],'result':result})
        after=rows[-1]['id']
        yield records

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-config',required=True)
    parser.add_argument('--inspect',action='store_true')
    parser.add_argument('--upload',action='store_true')
    args=parser.parse_args();path=source_path(args.source_config)
    with closing(readonly(path)) as con:
        info={'queue_last_id':con.execute('SELECT max(id) FROM emails').fetchone()[0],
          'attempts_last_id':con.execute('SELECT max(id) FROM attempts').fetchone()[0]}
        row=con.execute("SELECT value FROM meta WHERE key='execucao'").fetchone()
        run=row[0] if row else hashlib.sha256(str(path).encode()).hexdigest()
    print(json.dumps(info),flush=True)
    if not args.upload:
        print('Somente leitura. Nenhuma origem foi alterada e nenhum dado foi enviado.');return
    paused(path)
    url=os.environ['COORDINATOR_URL'].rstrip('/')
    if urlparse(url).scheme!='https' and urlparse(url).hostname not in ('127.0.0.1','localhost'):
        raise RuntimeError('A migracao remota exige HTTPS.')
    token=os.environ['ADMIN_TOKEN']
    with httpx.Client(headers={'Authorization':'Bearer '+token},timeout=120) as client:
        health=client.get(url+'/health');health.raise_for_status()
        if health.json()['mode']!='live':raise RuntimeError('Nao envie a base real ao banco de simulacao.')
        r=client.get(url+'/v1/import/'+run+'/cursor');r.raise_for_status()
        last=r.json()['last_id']
        for rows in pages(path,last):
            paused(path)
            r=client.post(url+'/v1/import',json={'source':run,'rows':rows});r.raise_for_status()
            print('Confirmado no servidor ate o ID:',r.json()['last_id'],flush=True)
    print('Importacao concluida. A nova fila permanece pausada; valide as contagens antes de ativar.')

if __name__=='__main__':main()
