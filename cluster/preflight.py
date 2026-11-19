"""Connectivity diagnostic: SMTP greeting only, no recipient or message."""
import argparse
import ipaddress
import json
import socket
import smtp_probe

def main():
    p=argparse.ArgumentParser();p.add_argument('--public-ip');p.add_argument('--helo',default='bazhi.com.br');a=p.parse_args()
    result={'smtp_greetings':{},'ptr':None,'forward_confirmed':False}
    if a.public_ip:
        ip=ipaddress.ip_address(a.public_ip)
        if not ip.is_global:raise RuntimeError('Informe um IP publico real.')
        try:
            ptr=socket.gethostbyaddr(str(ip))[0];result['ptr']=ptr
            addresses={r[4][0] for r in socket.getaddrinfo(ptr,None)}
            result['forward_confirmed']=str(ip) in addresses
        except OSError:pass
    cfg={'timeout':8,'helo':a.helo}
    for domain in ('gmail.com','outlook.com'):
        try:
            hosts,problem=smtp_probe.resolve_mx(domain,cfg)
            if problem:raise RuntimeError(problem)
            client=smtp_probe.dial_smtp(hosts[0],cfg);client.close()
            result['smtp_greetings'][domain]='OK'
        except Exception as exc:result['smtp_greetings'][domain]=type(exc).__name__
    result['ready_for_review']=bool(result['ptr'] and result['forward_confirmed'] and all(v=='OK' for v in result['smtp_greetings'].values()))
    print(json.dumps(result,indent=2))
    print('Diagnostico nao garante aceitacao de destinatarios nem velocidade. Nenhum RCPT TO foi enviado.')

if __name__=='__main__':main()
