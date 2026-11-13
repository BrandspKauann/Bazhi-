const { Readable } = require('node:stream');

// Vercel hosts the interface; the persistent Bazhi server owns data and jobs.
module.exports = async function gateway(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  const configured = process.env.BAZHI_BACKEND_URL;
  if (!configured) {
    res.statusCode = 503;
    res.setHeader('Content-Type','application/json; charset=utf-8');
    return res.end(JSON.stringify({detail:'Configure BAZHI_BACKEND_URL na Vercel com o endereço HTTPS do servidor Bazhi. A interface está online, mas o servidor ainda não está conectado.'}));
  }
  const incoming = new URL(req.url, 'https://bazhi.invalid');
  const routeValue = req.query?.route || incoming.searchParams.get('route') || incoming.pathname;
  const route = '/' + (typeof routeValue === 'string' ? routeValue : '').replace(/^\/+/, '');
  incoming.searchParams.delete('route');
  if (!/^\/(api|oauth|o|c|u)\//.test(route) || route.includes('..') || route.includes('\\')) {
    res.statusCode = 400; return res.end(JSON.stringify({detail:'Rota inválida.'}));
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 110000);
  try {
    const base = new URL(configured);
    if (base.protocol !== 'https:' && process.env.NODE_ENV !== 'test') throw new Error('HTTPS required');
    const target = new URL(route + incoming.search, base.origin);
    const headers = new Headers();
    for (const [key,value] of Object.entries(req.headers)) {
      if (!['host','connection','content-length','transfer-encoding','accept-encoding'].includes(key.toLowerCase()) && value !== undefined) headers.set(key, Array.isArray(value) ? value.join(', ') : value);
    }
    headers.set('x-forwarded-host', req.headers.host || '');
    headers.set('x-forwarded-proto','https');
    // Never trust a client-supplied bridge credential.
    headers.delete('x-bazhi-bridge-key');
    if (process.env.BAZHI_BRIDGE_SECRET) headers.set('x-bazhi-bridge-key',process.env.BAZHI_BRIDGE_SECRET);
    headers.set('ngrok-skip-browser-warning','1');
    let body;
    if (!['GET','HEAD'].includes(req.method)) {
      if (req.body !== undefined) body = Buffer.isBuffer(req.body) || typeof req.body === 'string' ? req.body : JSON.stringify(req.body);
      else { const chunks=[]; for await (const chunk of req) chunks.push(Buffer.from(chunk)); body=Buffer.concat(chunks); }
    }
    const upstream = await fetch(target, {method:req.method,headers,body,redirect:'manual',signal:controller.signal});
    res.statusCode = upstream.status;
    for (const [key,value] of upstream.headers) {
      if (!['set-cookie','content-length','content-encoding','transfer-encoding','connection'].includes(key)) res.setHeader(key,value);
    }
    const cookies = upstream.headers.getSetCookie();
    if (cookies.length) res.setHeader('Set-Cookie',cookies);
    if (!upstream.body || req.method==='HEAD') return res.end();
    await new Promise((resolve,reject) => {
      const stream=Readable.fromWeb(upstream.body);
      stream.on('error',reject);res.on('finish',resolve);res.on('close',()=>{controller.abort();resolve();});stream.pipe(res);
    });
  } catch (error) {
    if (!res.headersSent) {
      res.statusCode=error.name==='AbortError'?504:502;
      res.setHeader('Content-Type','application/json; charset=utf-8');
      res.end(JSON.stringify({detail:'Não foi possível conectar ao servidor Bazhi. Verifique BAZHI_BACKEND_URL e se o servidor está online.'}));
    } else res.end();
  } finally { clearTimeout(timer); }
};
