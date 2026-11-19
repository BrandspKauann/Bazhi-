"""SMTP primitives. No DATA, message submission, auth or mailbox password."""
import datetime as dt
import ipaddress
import re
import smtplib
import socket

def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')

def valid_email(email):
    if len(email)>254 or any(ch in email for ch in '\r\n\x00') or email.count('@')!=1:
        return False
    local,domain=email.rsplit('@',1)
    if not local or len(local)>64 or not domain or '.' not in domain:
        return False
    # Valid but unsupported exotic/SMTPUTF8 addresses remain inconclusive.
    if not re.fullmatch(r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+",local):
        return None
    if local.startswith('.') or local.endswith('.') or '..' in local:
        return False
    try:
        ascii_domain=domain.encode('idna').decode('ascii')
        return all(re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?',x) for x in ascii_domain.split('.'))
    except UnicodeError:
        return False

def public_addresses(host, port):
    # Never probe LAN, loopback, link-local or metadata endpoints from MX data.
    results=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
    ips=[]
    for family,_,_,_,address in results:
        if ipaddress.ip_address(address[0]).is_global:
            item=(family,address)
            if item not in ips:ips.append(item)
    return ips

def dial_smtp(host,cfg):
    last=None
    for family,address in public_addresses(host,25)[:3]:
        client=smtplib.SMTP(timeout=cfg['timeout'],local_hostname=cfg['helo'])
        try:
            sock=socket.socket(family,socket.SOCK_STREAM)
            sock.settimeout(cfg['timeout'])
            client.sock=sock
            sock.connect(address)
            code,message=client.getreply()
            if code!=220:raise smtplib.SMTPConnectError(code,message)
            client._host=host
            code,message=client.ehlo()
            if code>=400:
                code,message=client.helo()
            if code>=400:raise smtplib.SMTPHeloError(code,message)
            # STARTTLS, if advertised, is used with certificate validation.
            if client.has_extn('starttls'):
                import ssl
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            return client
        except Exception as exc:
            last=exc;client.close()
    raise last or OSError('MX sem endereco IP publico acessivel')

def resolve_mx(domain,cfg):
    import dns.resolver
    import dns.exception
    resolver=dns.resolver.Resolver()
    resolver.timeout=cfg['timeout'];resolver.lifetime=cfg['timeout']
    domain=domain.encode('idna').decode('ascii')
    try:
        answer=resolver.resolve(domain,'MX')
        values=sorted((int(r.preference),str(r.exchange)) for r in answer)
        if any(p==0 and host=='.' for p,host in values):return [],'null_mx'
        return [host.rstrip('.') for _,host in values][:3],None
    except dns.resolver.NXDOMAIN:return [],'dominio_inexistente'
    except dns.resolver.NoAnswer:
        # RFC 5321 implicit MX: try the domain itself when A/AAAA exists.
        for kind in ('A','AAAA'):
            try:
                resolver.resolve(domain,kind);return [domain],None
            except dns.resolver.NoAnswer:continue
            except dns.resolver.NXDOMAIN:return [],'dominio_inexistente'
        return [],'sem_mx_ou_ip'

def missing_mailbox(code,message):
    msg=message.decode('utf-8','replace') if isinstance(message,bytes) else str(message)
    return code>=500 and (bool(re.search(r'\b5\.1\.[13]\b',msg)) or bool(re.search(r'no such (user|recipient|mailbox)|user unknown|unknown (user|recipient)|recipient (not found|does not exist)|mailbox (not found|does not exist)|address rejected: user unknown',msg,re.I)))

def result(status='inconclusivo',code=None,stage='conexao',mx='',catchall='INCONCLUSIVO',message='',smtp=False):
    return dict(status=status,codigo_smtp=code,etapa_smtp=stage,mx=mx,catch_all=catchall,
      observacao=str(message)[:1000],smtp_verificado=int(smtp),testado_em=now_iso(),
      confiabilidade='smtp_comprovado' if status=='smtp_aceito' else 'recusado' if status=='smtp_recusado' else 'inconclusivo' if status=='inconclusivo' else 'invalido')

def mailbox(client,address,sender):
    client.rset()
    code,message=client.mail(sender)
    if code not in (250,251):return code,message,'mail_from'
    code,message=client.rcpt(address)
    return code,message,'rcpt_to'
