const crypto = require('node:crypto');
const attempts = new Map();
module.exports = async (req,res) => {
 res.setHeader('Content-Type','application/json; charset=utf-8');res.setHeader('Cache-Control','no-store');
 const send=(status,data)=>{res.statusCode=status;res.end(JSON.stringify(data));};
 let config;try{config=JSON.parse(process.env.BAZHI_ACCESS_CONFIG||'null');}catch{}
 if(!config?.hash||!config?.salt||!config?.secret||!config?.email)return send(503,{detail:'Acesso ainda não configurado.'});
 const url=new URL(req.url,'https://bazhi.invalid');const route=req.query?.route||url.searchParams.get('route')||url.pathname.split('/').pop();
 const user={id:1,username:config.email.split('@')[0],email:config.email,role:'admin',is_active:true,demo:true};
 const sign=body=>crypto.createHmac('sha256',config.secret).update(body).digest('base64url');
 const token=()=>{const body=Buffer.from(JSON.stringify({email:config.email,exp:Date.now()+7*86400000})).toString('base64url');return body+'.'+sign(body);};
 const valid=value=>{try{const [body,sig]=value.split('.');const expected=sign(body);if(!sig||sig.length!==expected.length||!crypto.timingSafeEqual(Buffer.from(sig),Buffer.from(expected)))return false;const data=JSON.parse(Buffer.from(body,'base64url').toString());return data.email===config.email&&data.exp>Date.now();}catch{return false;}};
 const cookie=Object.fromEntries((req.headers.cookie||'').split(';').map(x=>x.trim().split('=')));
 const setSession=value=>res.setHeader('Set-Cookie',[`access_token=${value}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=604800`,`refresh_token=${value}; Path=/api/auth; HttpOnly; Secure; SameSite=Lax; Max-Age=604800`]);
 if(route==='setup-status'&&req.method==='GET')return send(200,{setup_complete:true});
 if(route==='login'&&req.method==='POST'){
  const ip=req.headers['x-forwarded-for']||'local';const now=Date.now();let limit=attempts.get(ip);if(!limit||now-limit.time>60000)limit={time:now,count:0};limit.count++;attempts.set(ip,limit);if(attempts.size>1000)for(const [key,value]of attempts)if(now-value.time>60000)attempts.delete(key);if(limit.count>10)return send(429,{detail:'Aguarde um minuto antes de tentar novamente.'});
  let body=req.body;if(body===undefined){const chunks=[];for await(const chunk of req)chunks.push(Buffer.from(chunk));body=Buffer.concat(chunks).toString();}try{if(typeof body==='string'||Buffer.isBuffer(body))body=JSON.parse(body.toString());}catch{return send(400,{detail:'Dados inválidos.'});}
  const password=body?.password;if(typeof password!=='string'||password.length>128)return send(401,{detail:'Credenciais inválidas.'});
  const hash=crypto.scryptSync(password,config.salt,64).toString('hex');const identifier=String(body?.username||'').trim().toLowerCase();
  if(![config.email,config.email.split('@')[0]].includes(identifier)||hash.length!==config.hash.length||!crypto.timingSafeEqual(Buffer.from(hash),Buffer.from(config.hash)))return send(401,{detail:'Credenciais inválidas.'});
  attempts.delete(ip);const value=token();setSession(value);return send(200,{access_token:value,token_type:'bearer',expires_in:604800});
 }
 if(route==='logout'&&req.method==='POST'){res.setHeader('Set-Cookie',['access_token=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0','refresh_token=; Path=/api/auth; HttpOnly; Secure; SameSite=Lax; Max-Age=0']);return send(200,{ok:true});}
 const credential=route==='refresh'?cookie.refresh_token:(req.headers.authorization||'').replace(/^Bearer /,'')||cookie.access_token;
 if(!valid(credential||''))return send(401,{detail:'Sessão expirada.'});
 if(route==='me'&&req.method==='GET')return send(200,user);
 if(route==='refresh'&&req.method==='POST'){const value=token();setSession(value);return send(200,{access_token:value,token_type:'bearer',expires_in:604800});}
 return send(405,{detail:'Operação indisponível.'});
};
