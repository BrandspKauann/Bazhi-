const http = require('node:http');
const assert = require('node:assert/strict');
const gateway = require('../api/gateway.js');
const listen = server => new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
(async()=>{
 process.env.NODE_ENV='test';
 const backend=http.createServer(async(req,res)=>{
  if(req.url==='/oauth/app/google/authorize'){res.writeHead(303,{Location:'https://accounts.google.com/example'});return res.end();}
  const chunks=[];for await(const chunk of req)chunks.push(chunk);
  res.setHeader('Content-Type','application/json');res.setHeader('Set-Cookie',['access_token=test; HttpOnly; Path=/','refresh_token=test; HttpOnly; Path=/api/auth']);
  res.end(JSON.stringify({url:req.url,method:req.method,body:Buffer.concat(chunks).toString(),auth:req.headers.authorization}));
 });
 const proxy=http.createServer((req,res)=>gateway(req,res));
 try {
  await listen(backend);await listen(proxy);
  const base='http://127.0.0.1:'+proxy.address().port;
  delete process.env.BAZHI_BACKEND_URL;
  assert.equal((await fetch(base+'/api/gateway?route=api/leads')).status,503);
  process.env.BAZHI_BACKEND_URL='http://127.0.0.1:'+backend.address().port;
  let r=await fetch(base+'/api/gateway?route=api/leads&tag=Bazhi',{headers:{Authorization:'Bearer test'}});
  assert.equal(r.headers.getSetCookie().length,2);assert.deepEqual(await r.json(),{url:'/api/leads?tag=Bazhi',method:'GET',body:'',auth:'Bearer test'});
  r=await fetch(base+'/api/auth/login',{method:'POST',body:'{"username":"test"}',headers:{'Content-Type':'application/json'}});assert.equal((await r.json()).body,'{"username":"test"}');
  r=await fetch(base+'/api/gateway?route=oauth/app/google/authorize',{redirect:'manual'});assert.equal(r.status,303);
  r=await fetch(base+'/api/gateway?route=api/../private');assert.equal(r.status,400);
  console.log('PASS: unconfigured server, query forwarding, auth header, cookies, POST, redirect and invalid route');
 } finally {await new Promise(r=>proxy.close(r));await new Promise(r=>backend.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
