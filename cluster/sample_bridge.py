"""Reserve a small pending sample atomically, return actual outcomes to SQLite.

Does not stop the old bot or repeat completed e-mails. Interrupted samples stay
reserved until their saved results can be reconciled; they are never blindly reset.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
from urllib.parse import urlparse

import httpx
import smtp_probe

LEDGER='''CREATE TABLE IF NOT EXISTS cluster_pilot_sample(
 run_id TEXT NOT NULL,email_id INTEGER PRIMARY KEY,email TEXT NOT NULL,domain TEXT NOT NULL,
 reserved_at TEXT NOT NULL,applied_at TEXT)'''

def connect(path):
    con=sqlite3.connect(path,timeout=60);con.row_factory=sqlite3.Row
    con.execute('PRAGMA busy_timeout=60000')
    return con

def reserve(path,count):
    con=connect(path);run=str(uuid.uuid4());now=time.time()
    try:
        con.execute('BEGIN IMMEDIATE');con.execute(LEDGER)
        deadline=time.monotonic()+3
        con.set_progress_handler(lambda:int(time.monotonic()>deadline),500)
        if con.execute('SELECT 1 FROM cluster_pilot_sample WHERE applied_at IS NULL LIMIT 1').fetchone():
            raise RuntimeError('Existe amostra reservada. Use --action reconcile, nao reserve outra.')
        shard_row=con.execute("SELECT value FROM meta WHERE key='workers'").fetchone()
        shards=int(shard_row[0]) if shard_row else 1
        domains=[]
        # Use the existing shard-leading index; never scan/sort millions of
        # domains while holding the SQLite write lock.
        for shard in range(shards):
            domains.extend(con.execute("""SELECT d.domain FROM domains d WHERE d.shard=? AND d.owner IS NULL AND d.lease_until<=? AND d.next_at<=?
              AND EXISTS(SELECT 1 FROM emails e WHERE e.domain=d.domain AND e.state='pendente' AND e.attempts=0)
              ORDER BY d.next_at LIMIT ?""",(shard,now,now,max(1,count//shards+1))).fetchall())
        rows=[]
        for d in domains:
            pending=con.execute("SELECT id,email,domain FROM emails INDEXED BY emails_work WHERE domain=? AND state='pendente' AND next_at<=? AND attempts=0 ORDER BY next_at,id LIMIT 10",(d['domain'],now)).fetchall()
            accepted=[]
            for row in pending:
                if smtp_probe.valid_email(row['email']) is not True or '\x00' in row['email']:continue
                accepted.append(row)
                if len(accepted)==5 or len(rows)+len(accepted)>=count:break
            if not accepted:continue
            # Reserve only an idle domain, before any worker can claim it.
            con.execute('UPDATE domains SET owner=?,lease_until=? WHERE domain=?',('pilot-'+run,now+1800,d['domain']))
            for row in accepted:
                con.execute("UPDATE emails SET state='cluster_pilot' WHERE id=? AND state='pendente' AND attempts=0",(row['id'],))
                con.execute('INSERT INTO cluster_pilot_sample VALUES(?,?,?,?,?,NULL)',(run,row['id'],row['email'],row['domain'],smtp_probe.now_iso()))
                rows.append(dict(row))
            if len(rows)>=count:break
        if not rows:raise RuntimeError('Nao encontrei enderecos elegiveis sem reserva ativa.')
        con.commit();return run,rows
    except BaseException:con.rollback();raise
    finally:con.close()

def pending(path):
    con=connect(path)
    try:
        con.execute(LEDGER)
        return [dict(r) for r in con.execute('SELECT * FROM cluster_pilot_sample WHERE applied_at IS NULL')]
    finally:con.close()

def apply(path,results):
    con=connect(path);applied=[]
    try:
        con.execute('BEGIN IMMEDIATE')
        deadline=time.monotonic()+5
        con.set_progress_handler(lambda:int(time.monotonic()>deadline),500)
        original_run=con.execute("SELECT value FROM meta WHERE key='execucao'").fetchone()[0]
        for item in results:
            source=con.execute('SELECT * FROM cluster_pilot_sample WHERE email=?',(item['email'],)).fetchone()
            if not source:continue
            if source['applied_at']:
                applied.append(item['id']);continue
            result=item['result'];status=result.get('status','inconclusivo')
            allowed={'smtp_aceito','smtp_recusado','inconclusivo','invalido_dns','invalido_formato'}
            if status not in allowed:raise RuntimeError('Resultado de simulacao ou desconhecido recusado.')
            if status=='smtp_aceito' and not (result.get('codigo_smtp') in (250,251) and result.get('catch_all')=='NAO_DETECTADO' and result.get('etapa_smtp')=='rcpt_to'):
                raise RuntimeError('Aceitacao sem evidencia suficiente recusada.')
            row=con.execute('SELECT attempts,state FROM emails WHERE id=?',(source['email_id'],)).fetchone()
            if row['attempts']!=0 or row['state']!='cluster_pilot':raise RuntimeError('A origem mudou; reconciliacao manual necessaria.')
            confidence='smtp_comprovado' if status=='smtp_aceito' else 'recusado' if status=='smtp_recusado' else 'inconclusivo' if status=='inconclusivo' else 'invalido'
            cur=con.execute('''INSERT INTO attempts(email,domain,execucao_id,status,confiabilidade,smtp_verificado,codigo_smtp,etapa_smtp,mx,catch_all,testado_em,observacao,worker)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(source['email'],source['domain'],original_run,status,confidence,int(bool(result.get('smtp_verificado'))),result.get('codigo_smtp'),result.get('etapa_smtp'),result.get('mx'),result.get('catch_all'),result.get('testado_em',smtp_probe.now_iso()),result.get('observacao','')[:1000],'cluster-pilot'))
            con.execute('UPDATE emails SET state=?,attempts=1,last_id=?,next_at=0 WHERE id=?',(status,cur.lastrowid,source['email_id']))
            con.execute('UPDATE cluster_pilot_sample SET applied_at=? WHERE email_id=?',(smtp_probe.now_iso(),source['email_id']))
            applied.append(item['id'])
        # Only release domain reservations which belong to this pilot and have
        # no unreconciled addresses. Never release another worker's lease.
        con.execute("""UPDATE domains SET owner=NULL,lease_until=0,next_at=? WHERE owner LIKE 'pilot-%'
          AND domain IN (SELECT domain FROM cluster_pilot_sample WHERE applied_at IS NOT NULL)
          AND EXISTS(SELECT 1 FROM cluster_pilot_sample p WHERE p.domain=domains.domain AND domains.owner='pilot-'||p.run_id)
          AND NOT EXISTS(SELECT 1 FROM cluster_pilot_sample p WHERE p.domain=domains.domain AND p.applied_at IS NULL)""",(time.time()+3,))
        con.commit();return applied
    except BaseException:con.rollback();raise
    finally:con.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--source-config',required=True)
    p.add_argument('--action',choices=['reserve','resume','reconcile'],required=True);p.add_argument('--count',type=int,default=50)
    a=p.parse_args();cfg=json.loads(Path(a.source_config).read_text(encoding='utf-8-sig'));path=Path(cfg['dados'])/'fila.sqlite'
    base=os.environ['COORDINATOR_URL'].rstrip('/')
    if urlparse(base).scheme!='https' and urlparse(base).hostname not in ('localhost','127.0.0.1'):raise RuntimeError('Use HTTPS fora do computador local.')
    with httpx.Client(headers={'Authorization':'Bearer '+os.environ['ADMIN_TOKEN']},timeout=120) as client:
        r=client.get(base+'/v1/stats');r.raise_for_status();stats=r.json()
        if stats['mode']!='live':raise RuntimeError('Nao envie amostras reais a uma simulacao.')
        if a.action in ('reserve','resume'):
            if stats['processing_enabled']:raise RuntimeError('Pause a fila nova antes de reservar a amostra.')
            if a.action=='reserve':
                run,rows=reserve(path,max(1,min(100,a.count)))
                rows=[{'email':r['email'],'id':r['id']} for r in rows]
            else:
                saved=pending(path)
                if not saved:raise RuntimeError('Nao existe amostra pendente para retomar.')
                if len({r['run_id'] for r in saved})!=1:raise RuntimeError('Amostras de mais de uma rodada; revisar antes de retomar.')
                run=saved[0]['run_id'];rows=[{'email':r['email'],'id':r['email_id']} for r in saved]
            r=client.post(base+'/v1/import',json={'source':run,'rows':[{'email':row['email'],'source_id':row['id']} for row in rows]});r.raise_for_status()
            print(json.dumps({'reserved':len(rows),'run_id':run,'uploaded':True}),flush=True)
            print('Os enderecos foram reservados na origem; nenhum foi repetido. Ative a fila nova para o piloto.')
        else:
            r=client.get(base+'/v1/results');r.raise_for_status()
            ids=apply(path,r.json()['rows'])
            if ids:
                r=client.post(base+'/v1/results/ack',json={'ids':ids});r.raise_for_status()
            print(json.dumps({'applied':len(ids),'remaining_sample':len(pending(path))}),flush=True)

if __name__=='__main__':main()
