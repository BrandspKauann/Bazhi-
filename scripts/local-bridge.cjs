// Exposes only the application, through a private shared key held by Vercel.
const http = require('node:http');
const crypto = require('node:crypto');
const fs = require('node:fs');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
if (!config.secret || config.secret.length < 32) throw new Error('Bridge secret required');
http.createServer((req, res) => {
  const key = String(req.headers['x-bazhi-bridge-key'] || '');
  const digest = value => crypto.createHash('sha256').update(value).digest();
  const equal = crypto.timingSafeEqual(digest(key), digest(config.secret));
  if (!equal) { res.writeHead(403); return res.end('Forbidden'); }
  if (!/^\/(api|oauth|o|c|u)\//.test(req.url)) { res.writeHead(404); return res.end(); }
  const headers = {...req.headers, host:'localhost:8000'};
  delete headers['x-bazhi-bridge-key'];
  const upstream = http.request({hostname:'127.0.0.1',port:8000,path:req.url,method:req.method,headers}, response => {
    res.writeHead(response.statusCode,response.headers);response.pipe(res);
  });
  upstream.setTimeout(115000,()=>upstream.destroy());
  upstream.on('error',()=>{ if(!res.headersSent) res.writeHead(502);res.end(); });
  req.on('aborted',()=>upstream.destroy());
  req.pipe(upstream);
}).listen(8787, '127.0.0.1',()=>console.log('Bazhi protected bridge listening on loopback:8787'));
