/**
 * Preview local do projeto Bazhi.
 *
 * Reproduz o roteamento do `vercel.json` sem precisar do Vercel CLI:
 *   - serve o build em `frontend/dist` (outputDirectory)
 *   - `/api/auth/(setup-status|login|refresh|me|logout)` -> `api/access.js`
 *   - `/(api|oauth|o|c|u)/*`                          -> `api/gateway.js`
 *   - fallback da SPA                                 -> `index.html`
 *
 * Uso:
 *   npm --prefix frontend install
 *   npm --prefix frontend run build
 *   node local-preview.cjs [porta]
 *
 * Acesso:
 *   Por padrão lê as credenciais do arquivo `.bazhi-access.json` (não versionado)
 *   ou da variável de ambiente `BAZHI_ACCESS_CONFIG`. Para gerar o arquivo a
 *   partir de um e-mail e uma senha:
 *
 *     node local-preview.cjs --set-password seu@email.com 'sua-senha'
 *
 *   Isso grava o mesmo JSON que a Vercel espera em `BAZHI_ACCESS_CONFIG`,
 *   com a senha apenas em hash scrypt. Copie esse valor para as Environment
 *   Variables do projeto na Vercel para o login funcionar lá também.
 */
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { URL } = require('node:url');

const ROOT = __dirname;
const DIST = path.join(ROOT, 'frontend', 'dist');
const ACCESS_FILE = path.join(ROOT, '.bazhi-access.json');

/* ------------------------------------------------------------------ *
 * Credenciais                                                        *
 * ------------------------------------------------------------------ */

function buildAccessConfig(email, password) {
  const salt = crypto.randomBytes(16).toString('hex');
  return {
    email,
    salt,
    hash: crypto.scryptSync(password, salt, 64).toString('hex'),
    secret: crypto.randomBytes(32).toString('hex'),
  };
}

const args = process.argv.slice(2);
const setPasswordIdx = args.indexOf('--set-password');
if (setPasswordIdx !== -1) {
  const email = args[setPasswordIdx + 1];
  const password = args[setPasswordIdx + 2];
  if (!email || !password) {
    console.error('Uso: node local-preview.cjs --set-password <email> <senha>');
    process.exit(1);
  }
  const config = buildAccessConfig(email, password);
  fs.writeFileSync(ACCESS_FILE, JSON.stringify(config, null, 2) + '\n');
  console.log(`Credenciais gravadas em ${ACCESS_FILE}`);
  console.log('\nBAZHI_ACCESS_CONFIG (cole na Vercel):\n');
  console.log(JSON.stringify(config));
  process.exit(0);
}

function loadAccessConfig() {
  if (process.env.BAZHI_ACCESS_CONFIG) return process.env.BAZHI_ACCESS_CONFIG;
  if (fs.existsSync(ACCESS_FILE)) return fs.readFileSync(ACCESS_FILE, 'utf8').trim();
  console.error(
    'Nenhuma credencial configurada.\n' +
      'Crie o arquivo .bazhi-access.json com:\n' +
      "  node local-preview.cjs --set-password seu@email.com 'sua-senha'",
  );
  process.exit(1);
}

process.env.BAZHI_ACCESS_CONFIG = loadAccessConfig();

const access = require('./api/access.js');
const gateway = require('./api/gateway.js');

/* ------------------------------------------------------------------ *
 * Servidor                                                           *
 * ------------------------------------------------------------------ */

const PORT = Number(args[0] || process.env.PORT || 4173);

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.map': 'application/json; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
};

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(Buffer.from(chunk));
  return Buffer.concat(chunks);
}

function sendFile(res, file) {
  const ext = path.extname(file).toLowerCase();
  res.setHeader('Content-Type', MIME[ext] || 'application/octet-stream');
  if (file.includes(`${path.sep}assets${path.sep}`)) {
    res.setHeader('Cache-Control', 'public, max-age=31536000, immutable');
  } else {
    res.setHeader('Cache-Control', 'no-cache');
  }
  fs.createReadStream(file).pipe(res);
}

const server = http.createServer(async (req, res) => {
  let url;
  try {
    url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  } catch {
    res.statusCode = 400;
    return res.end('Bad request');
  }

  // Corpo lido uma única vez, como a Vercel entrega `req.body` às funções.
  let body;
  if (!['GET', 'HEAD'].includes(req.method)) body = await readBody(req);

  const invoke = (fn, params) => {
    const fake = Object.create(req);
    fake.url = req.url;
    fake.body = body;
    fake.query = params;
    return fn(fake, res);
  };

  const pathname = decodeURIComponent(url.pathname);

  // 1) /api/auth/(setup-status|login|refresh|me|logout)
  const authMatch = pathname.match(/^\/api\/auth\/(setup-status|login|refresh|me|logout)\/?$/);
  if (authMatch) return invoke(access, { route: authMatch[1] });

  // 2) /(api|oauth|o|c|u)/(.*)
  const gwMatch = pathname.match(/^\/(api|oauth|o|c|u)\/(.*)$/);
  if (gwMatch) return invoke(gateway, { route: `${gwMatch[1]}/${gwMatch[2]}` });

  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.statusCode = 405;
    return res.end('Method not allowed');
  }

  // 3) arquivos do build
  const rel = pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '');
  const candidate = path.join(DIST, rel);
  if (candidate.startsWith(DIST) && fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
    return sendFile(res, candidate);
  }

  // 4) fallback da SPA
  const indexFile = path.join(DIST, 'index.html');
  if (!fs.existsSync(indexFile)) {
    res.statusCode = 500;
    res.setHeader('Content-Type', 'text/plain; charset=utf-8');
    return res.end('Build ausente. Rode: npm --prefix frontend run build');
  }
  return sendFile(res, indexFile);
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`Bazhi (preview local da Vercel) em http://127.0.0.1:${PORT}`);
});
