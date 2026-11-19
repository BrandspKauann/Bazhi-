"""Generate local Docker secrets without printing them or touching the old bot."""
from pathlib import Path
import os
import secrets

root=Path(__file__).resolve().parent
target=root/'.env'
if target.exists():
    print('.env ja existe; nenhuma credencial foi substituida.')
else:
    body='\n'.join([
      'POSTGRES_PASSWORD='+secrets.token_urlsafe(32),
      'ADMIN_TOKEN='+secrets.token_urlsafe(48),
      'AGENT_TOKEN='+secrets.token_urlsafe(48),
      'CLUSTER_MODE=simulation','ALLOW_REAL_SMTP=0','CONCURRENCY=16',
      'SMTP_HELO=bazhi.com.br','SMTP_SENDER=','COORDINATOR_DOMAIN=',''])
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as output:output.write(body)
    print('Configuracao privada criada. Modo simulacao; nenhum SMTP real sera consultado.')
