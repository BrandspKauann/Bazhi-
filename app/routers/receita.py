"""Prospecting by saved segments, contact channels and existing evidence."""
import asyncio
from contextlib import asynccontextmanager
import re
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth import get_current_user
from app.database import get_db
from app.models import Lead, ProspectList, User
from app.receita_source import search_source, fetch_roots, get_catalog

router = APIRouter(prefix='/api/receita', tags=['receita'])
_gate = asyncio.Semaphore(1)

@asynccontextmanager
async def source_slot():
    try:
        await asyncio.wait_for(_gate.acquire(), timeout=3)
    except asyncio.TimeoutError:
        raise HTTPException(429, 'Uma consulta à base ainda está em andamento. Aguarde a conclusão antes de tentar novamente.')
    try:
        yield
    finally:
        _gate.release()


class SearchFilters(BaseModel):
    segmentos: list[str] = Field(default_factory=list, max_length=15)
    uf: str = Field('', max_length=2, pattern=r'^[a-zA-Z]{0,2}$')
    com_email: bool = True
    telefone: Literal['', 'com', 'sem'] = ''
    confiabilidade: Literal['','smtp_comprovado','inconclusivo','nao_verificado','recusado'] = ''
    tipo_email: Literal['','corporativo','publico'] = ''

class ImportRequest(BaseModel):
    cnpjs: list[str] = Field(min_length=1, max_length=50)
    lista_id: str | None = None
    tag: str = Field("", max_length=80)

    @field_validator('cnpjs')
    @classmethod
    def validate_roots(cls, value):
        if any(not re.fullmatch(r'\d{8}', root) for root in value):
            raise ValueError('Selecione raízes de CNPJ válidas, com 8 dígitos.')
        return list(dict.fromkeys(value))

class SaveListRequest(ImportRequest):
    nome: str = Field(min_length=1, max_length=150)
    filtros: SearchFilters = Field(default_factory=SearchFilters)

    @field_validator('nome')
    @classmethod
    def validate_name(cls, value):
        if not value.strip():
            raise ValueError('Dê um nome à lista.')
        return value.strip()

@router.get('/segmentos')
async def segments():
    items = await asyncio.to_thread(get_catalog)
    return {'segmentos':items, 'nota':'Contagens das tags na base salva; os filtros de contato podem reduzir os resultados.'}

@router.get('/empresas')
async def search(segmentos: list[str] = Query(default=[]), uf: str = '', com_email: bool = True, telefone: str = '', confiabilidade: str = '', tipo_email: str = ''):
    from pydantic import ValidationError
    try:
        filters = SearchFilters(segmentos=segmentos, uf=uf, com_email=com_email, telefone=telefone, confiabilidade=confiabilidade, tipo_email=tipo_email)
    except ValidationError:
        raise HTTPException(422, 'Revise os filtros selecionados.')
    async with source_slot():
        return await asyncio.to_thread(search_source, filters)

@router.get('/listas')
async def lists(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.scalars(select(ProspectList).where(ProspectList.user_id==user.id).order_by(ProspectList.created_at.desc()).limit(100))
    return {'listas':[{'id':item.id,'nome':item.name,'quantidade':len(item.cnpjs),'criado_em':item.created_at} for item in result]}

@router.post('/listas', status_code=201)
async def save_list(data: SaveListRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    async with source_slot():
        rows = await asyncio.to_thread(fetch_roots, data.cnpjs)
    if len(rows) != len(data.cnpjs):
        raise HTTPException(422, 'Uma empresa selecionada não foi encontrada na base ativa. Atualize a busca.')
    item = ProspectList(user_id=user.id, name=data.nome, cnpjs=data.cnpjs, companies=rows, filters=data.filtros.model_dump())
    db.add(item)
    await db.flush()
    return {'id':item.id,'nome':item.name,'quantidade':len(rows)}

@router.get('/listas/{list_id}')
async def get_list(list_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    item = await db.scalar(select(ProspectList).where(ProspectList.id==list_id, ProspectList.user_id==user.id))
    if not item:
        raise HTTPException(404, 'Lista não encontrada.')
    return {'id':item.id,'nome':item.name,'rows':item.companies,'cnpjs':item.cnpjs,'filtros':item.filters,'criado_em':item.created_at,'has_more':False}

@router.post('/importar')
async def import_contacts(data: ImportRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if data.lista_id:
        item = await db.scalar(select(ProspectList).where(ProspectList.id==data.lista_id, ProspectList.user_id==user.id))
        if not item or not set(data.cnpjs).issubset(set(item.cnpjs)):
            raise HTTPException(422, 'Selecione empresas de uma lista sua.')
    async with source_slot():
        rows = await asyncio.to_thread(fetch_roots, data.cnpjs)
    await db.execute(text('SELECT pg_advisory_xact_lock(782491)'))
    manual_tag = data.tag.strip()
    created = skipped = invalid = updated = 0
    for row in rows:
        email = (row.get('email') or '').strip().lower()
        if len(email)>255 or not re.fullmatch(r'[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+',email):
            invalid += 1; continue
        existing = await db.scalar(select(Lead).where(func.lower(Lead.email)==email).limit(1))
        if existing:
            # Preserve opt-outs, email-verification states and all previous data.
            old = dict(existing.custom_data or {})
            roots = set(old.get('receita_cnpjs', []))
            if old.get('cnpj_basico'):
                roots.add(old['cnpj_basico'])
            roots.add(row['cnpj_basico'])
            old['receita_cnpjs'] = sorted(roots)
            old['tags'] = sorted(set(old.get('tags',[])) | set(row['tags']) | ({manual_tag} if manual_tag else set()))
            old['receita_ultima_consulta'] = {'confiabilidade':row['confiabilidade'],'resultado_smtp':row['resultado_smtp'],'verificado_em':row['verificado_em'],'cnpj_basico':row['cnpj_basico']}
            if data.lista_id:
                old['receita_listas'] = sorted(set(old.get('receita_listas',[])) | {data.lista_id})
            existing.custom_data = old
            skipped += 1; updated += 1; continue
        custom = {**row, 'tags':sorted(set(row['tags']) | ({manual_tag} if manual_tag else set())),'company':row['razao_social'],'cnpj':''.join(row.get(k) or '' for k in ('cnpj_basico','cnpj_ordem','cnpj_dv')),'origem':'Receita Federal','competencia':'2026-10','receita_cnpjs':[row['cnpj_basico']], 'receita_listas':[data.lista_id] if data.lista_id else []}
        db.add(Lead(email=email,name=(row.get('nome_fantasia') or row['razao_social'] or '')[:255],custom_data=custom,status='active'))
        await db.flush(); created += 1
    return {'criados':created,'duplicados':skipped,'atualizados':updated,'sem_email_valido':invalid,'nao_encontrados':len(data.cnpjs)-len(rows)}
