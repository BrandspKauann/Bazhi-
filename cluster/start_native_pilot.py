"""Explicitly start only the approved 50-address native pilot; no secrets in argv."""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import smtp_probe

ROOT=Path(__file__).resolve().parent
BASE='http://127.0.0.1:8789'

def main():
    p=argparse.ArgumentParser();p.add_argument('--start',action='store_true');p.add_argument('--confirm-50',action='store_true')
    p.add_argument('--source-config',required=True);a=p.parse_args()
    config=dict(line.split('=',1) for line in (ROOT/'.env').read_text().splitlines() if '=' in line)
    source=json.loads(Path(a.source_config).read_text(encoding='utf-8-sig'))
    if smtp_probe.valid_email(source.get('remetente','')) is not True:raise RuntimeError('Configure a caixa real do remetente.')
    headers={'Authorization':'Bearer '+config['ADMIN_TOKEN']}
    with urllib.request.urlopen(urllib.request.Request(BASE+'/v1/stats',headers=headers),timeout=10) as r:stats=json.loads(r.read())
    if stats['mode']!='live' or stats['processing_enabled'] or stats['states']!={'pending':50}:
        raise RuntimeError('O piloto deve conter exatamente 50 pendentes e estar pausado.')
    print('Pronto: 50 pendentes, fila pausada, caixa do remetente configurada. Nenhum SMTP consultado.',flush=True)
    if not a.start:return
    if not a.confirm_50:raise RuntimeError('A inicializacao exige confirmacao explicita dos 50 enderecos.')
    env=os.environ.copy()
    for key in ('ADMIN_TOKEN','POSTGRES_PASSWORD','DATABASE_URL'):env.pop(key,None)
    env.update(COORDINATOR_URL=BASE,AGENT_TOKEN=config['AGENT_TOKEN'],ALLOW_REAL_SMTP='1',CONCURRENCY='8',
      SMTP_SENDER=source['remetente'],SMTP_HELO=source.get('helo','bazhi.com.br'),NODE_NAME='windows-pilot-task21')
    flags=(subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP) if os.name=='nt' else 0
    with (ROOT/'native-pilot.stdout.log').open('a',encoding='utf-8') as out,(ROOT/'native-pilot.stderr.log').open('a',encoding='utf-8') as err:
        process=subprocess.Popen([sys.executable,'-u',str(ROOT/'agent.py')],cwd=ROOT,env=env,stdout=out,stderr=err,creationflags=flags)
    (ROOT/'native-pilot-process.json').write_text(json.dumps({'pid':process.pid,'started':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'50 enderecos reservados, tarefa 21'}),encoding='utf-8')
    time.sleep(1)
    if process.poll() is not None:raise RuntimeError('O agente nao iniciou; consulte native-pilot.stderr.log. Fila mantida pausada.')
    request=urllib.request.Request(BASE+'/v1/processing',data=json.dumps({'enabled':True}).encode(),
      headers={**headers,'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(request,timeout=10) as r:assert json.loads(r.read())['processing_enabled']
    print('Agente do piloto iniciado. PID:',process.pid,'; apenas 50 enderecos, sem encerrar o bot original.',flush=True)

if __name__=='__main__':main()
