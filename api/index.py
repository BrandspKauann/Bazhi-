"""Native Vercel API: cloud database, independent of the local computer."""
import os
import hashlib
from urllib.parse import parse_qsl, urlencode
from fastapi import FastAPI
from fastapi.responses import JSONResponse

os.environ['BAZHI_SERVERLESS'] = '1'
os.environ['QUICKLY_TELEMETRY'] = 'false'
os.environ.setdefault('QUICKLY_MODE', 'production')
os.environ.setdefault('BASE_URL', 'https://bazhi-three.vercel.app')
connection = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL')
if connection:
    os.environ['DATABASE_URL'] = connection
    # Stable signing secret derived from the private database credential.
    os.environ.setdefault('QUICKLY_SECRET_KEY', hashlib.sha256(('bazhi-session-v1:'+connection).encode()).hexdigest())
    from app.main import app
else:
    app = FastAPI(title='Bazhi')
    @app.api_route('/{path:path}', methods=['GET','POST','PUT','PATCH','DELETE'])
    async def missing_database(path: str):
        return JSONResponse({'detail':'Conecte um banco PostgreSQL ao projeto Bazhi na Vercel para criar sua conta.'},status_code=503)

@app.middleware('http')
async def original_route(request, call_next):
    params = parse_qsl(request.scope.get('query_string', b'').decode())
    route = next((v for k,v in params if k=='route'), None)
    if route:
        request.scope['path'] = '/' + route.lstrip('/')
        request.scope['raw_path'] = request.scope['path'].encode()
        request.scope['root_path'] = ''
        request.scope['query_string'] = urlencode([(k,v) for k,v in params if k!='route']).encode()
    return await call_next(request)
