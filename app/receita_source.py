"""Read-only access to Receita and the user's saved segmentation layers."""
import contextlib
import json
import os
import threading
from pathlib import Path, PureWindowsPath
import duckdb
from fastapi import HTTPException

SOURCE = os.getenv('RECEITA_PARQUET', '/receita/EmpresasAtivas.parquet')
WORKSPACE = os.getenv('RECEITA_WORKSPACE', '/receita-tags/sql/workspace.duckdb')
OPERATIONS = os.getenv('RECEITA_OPERACOES', '/receita-tags/operacoes.duckdb')
LEADS_DIR = Path(os.getenv('RECEITA_LEADS_DIR', '/receita-leads'))
TAG_TABLES = {
    'tags_b2b_servicos': 'tag_b2b',
    'tags_tipos_b2b': 'tag_tipo_b2b',
    'tags_contabilizei_b2b': 'tag',
}
LABELS = {
    'B2B_PROVAVEL': ('Serviços para empresas', 'b2b serviços empresas corporativo'),
    'TECNOLOGIA_DADOS': ('Tecnologia e dados', 'tecnologia software ti informática dados sistemas'),
    'MARKETING_PUBLICIDADE': ('Marketing e publicidade', 'marketing publicidade agência propaganda comunicação'),
    'ADMINISTRATIVO_COBRANCA': ('Administrativo e cobrança', 'administrativo administração cobrança escritório'),
    'RH_TERCEIRIZACAO': ('RH e terceirização', 'rh recursos humanos recrutamento terceirização pessoal'),
    'CONSULTORIA_EMPRESARIAL': ('Consultoria empresarial', 'consultoria gestão negócios empresarial'),
    'USA_CONTABILIZEI': ('Usa Contabilizei', 'contabilizei contabilidade'),
}
COLUMNS = 'cnpj_basico, cnpj_ordem, cnpj_dv, razao_social, nome_fantasia, email, uf, municipio, cnae_principal, porte, ddd_1, telefone_1, ddd_2, telefone_2'


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def records(cursor):
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


@contextlib.contextmanager
def source_connection():
    try:
        con = duckdb.connect()
        deadline = threading.Timer(90, con.interrupt)
        deadline.daemon = True
        deadline.start()
        con.execute("SET memory_limit='1GB'")
        con.execute('SET threads=2')
        con.execute('SET preserve_insertion_order=false')
        con.execute('CREATE TEMP VIEW empresas AS SELECT * FROM read_parquet(' + literal(SOURCE) + ')')
        con.execute('ATTACH ' + literal(WORKSPACE) + ' AS tags (READ_ONLY)')
        con.execute('ATTACH ' + literal(OPERATIONS) + ' AS ops (READ_ONLY)')
        config = json.loads((LEADS_DIR / 'base-de-trabalho.json').read_text(encoding='utf-8-sig'))
        lead_file = LEADS_DIR / PureWindowsPath(config['base_de_trabalho']).name
        con.execute('CREATE TEMP VIEW leads_original AS SELECT * FROM read_parquet(' + literal(lead_file) + ')')
        con.execute('''CREATE TEMP VIEW leads_segmentados AS
            SELECT b.* REPLACE(coalesce(a.classificacao,b.classificacao_confiabilidade) AS classificacao_confiabilidade)
            FROM leads_original b LEFT JOIN ops.ajustes a USING(cnpj_basico)''')
        # A newer RH result takes precedence over the legacy test for the SAME address.
        # An SMTP acceptance is evidence of acceptance at that time, not proof of ownership.
        con.execute('''CREATE TEMP VIEW evidencia_email AS
            SELECT * EXCLUDE(prioridade) FROM (
              SELECT cnpj_basico, lower(trim(email)) AS email,
                CASE WHEN r.status_smtp='SMTP_ACEITO' AND r.catch_all='NAO_DETECTADO' THEN 'smtp_comprovado'
                     WHEN r.status_smtp='SMTP_RECUSADO' THEN 'recusado'
                     ELSE 'inconclusivo' END AS confiabilidade,
                r.status_smtp AS resultado_smtp, cast(r.testado_em AS VARCHAR) AS verificado_em,
                1 AS prioridade
              FROM tags.smtp_rh_resultados r
              UNION ALL
              SELECT cnpj_basico, lower(trim(email)),
                CASE WHEN status_verificacao_email='aceito_pelo_servidor' AND etapa_smtp='rcpt_to' AND codigo_smtp IN (250,251) THEN 'smtp_comprovado'
                     WHEN etapa_smtp='rcpt_to' AND codigo_smtp >= 500 THEN 'recusado'
                     WHEN status_verificacao_email LIKE 'inconclusivo%' THEN 'inconclusivo'
                     WHEN status_verificacao_email='invalido_formato_ou_dns' THEN 'recusado'
                     ELSE 'nao_verificado' END,
                status_verificacao_email, verificado_em, 2
              FROM leads_original
            ) QUALIFY row_number() OVER(PARTITION BY cnpj_basico,email ORDER BY prioridade)=1''')
        yield con
    except duckdb.InterruptException:
        raise HTTPException(504, 'A consulta ultrapassou 90 segundos. Selecione um segmento ou um estado e tente novamente.')
    except HTTPException:
        raise
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning('Receita source unavailable: %s', exc)
        raise HTTPException(503, 'Não foi possível ler a base e suas segmentações. Tente novamente; a base pode estar sendo atualizada.')
    finally:
        if 'deadline' in locals():
            deadline.cancel()
        if 'con' in locals():
            con.close()


def catalog(con):
    result = []
    for table, column in TAG_TABLES.items():
        for row in records(con.execute(f'SELECT {column} AS tag, count(*) AS quantidade FROM tags.{table} GROUP BY 1 ORDER BY 1')):
            if not row['tag']:
                continue
            label, terms = LABELS.get(row['tag'], (row['tag'].replace('_', ' ').capitalize(), row['tag']))
            result.append({'id': table + ':' + row['tag'], 'nome': label, 'busca': terms, 'quantidade': row['quantidade'], 'tipo': 'Tag salva', 'tag': row['tag']})
    for row in records(con.execute('SELECT id,nome,fonte,filtros,descricao,contagem FROM ops.segmentos WHERE ativo ORDER BY nome')):
        result.append({'id': 'segmento:' + row['id'], 'nome': row['nome'], 'busca': row['descricao'] or '', 'quantidade': row['contagem'], 'tipo': 'Segmento salvo', 'fonte': row['fonte'], 'filtros': json.loads(row['filtros']), 'tag': row['nome']})
    return result


def segment_predicate(item):
    if item['id'].startswith('segmento:'):
        clauses, args = [], []
        f = item['filtros']
        for key, col in [('uf','s.uf'),('cnae','s.cnae_principal'),('classificacao','s.classificacao_confiabilidade')]:
            if f.get(key):
                clauses.append(col + ' = ?'); args.append(f[key])
        if f.get('dominio_email'):
            clauses.append("lower(trim(split_part(s.email,'@',2))) = ?"); args.append(f['dominio_email'].lower().lstrip('@'))
        if f.get('nome'):
            clauses.append('(s.razao_social ILIKE ? OR s.nome_fantasia ILIKE ?)'); args.extend(['%' + f['nome'] + '%'] * 2)
        table = 'leads_segmentados' if item['fonte']=='leads' else 'empresas'
        return f"e.cnpj_basico IN (SELECT s.cnpj_basico FROM {table} s WHERE " + (' AND '.join(clauses) or 'TRUE') + ')', args
    table, value = item['id'].split(':', 1)
    column = TAG_TABLES[table]
    return f'e.cnpj_basico IN (SELECT s.cnpj_basico FROM tags.{table} s WHERE s.{column}=?)', [value]


def build_where(con, filters):
    clauses, args = ["e.situacao_cadastral='02'"], []
    choices = {item['id']: item for item in catalog(con)}
    if filters.segmentos:
        sub = []
        for sid in filters.segmentos:
            if sid not in choices:
                raise HTTPException(422, 'Um dos segmentos não existe mais. Atualize as sugestões.')
            clause, values = segment_predicate(choices[sid]); sub.append(clause); args.extend(values)
        clauses.append('(' + ' OR '.join(sub) + ')')
    if filters.uf:
        clauses.append('e.uf=?'); args.append(filters.uf.upper())
    if filters.com_email:
        clauses.append("e.email IS NOT NULL AND trim(e.email) <> ''")
    if filters.telefone == 'com':
        clauses.append("(length(regexp_replace(coalesce(e.telefone_1,''),'[^0-9]','','g'))>=8 OR length(regexp_replace(coalesce(e.telefone_2,''),'[^0-9]','','g'))>=8)")
    elif filters.telefone == 'sem':
        clauses.append("(length(regexp_replace(coalesce(e.telefone_1,''),'[^0-9]','','g'))<8 AND length(regexp_replace(coalesce(e.telefone_2,''),'[^0-9]','','g'))<8)")
    if filters.com_email and filters.confiabilidade:
        if filters.confiabilidade == 'nao_verificado':
            clauses.append("(e.cnpj_basico,lower(trim(e.email))) NOT IN (SELECT v.cnpj_basico,v.email FROM evidencia_email v WHERE v.confiabilidade<>'nao_verificado' AND v.email IS NOT NULL)")
        else:
            clauses.append('(e.cnpj_basico,lower(trim(e.email))) IN (SELECT v.cnpj_basico,v.email FROM evidencia_email v WHERE v.confiabilidade=?)'); args.append(filters.confiabilidade)
    if filters.com_email and filters.tipo_email:
        clauses.append("(e.cnpj_basico,lower(trim(split_part(e.email,'@',2)))) IN (SELECT m.cnpj_basico,m.dominio_email FROM tags.classificacao_emails_b2b m WHERE m.tag_email_corporativo IN ('corporativo_candidato','corporativo_prioritario'))" if filters.tipo_email=='corporativo' else "(e.cnpj_basico,lower(trim(split_part(e.email,'@',2)))) IN (SELECT m.cnpj_basico,m.dominio_email FROM tags.classificacao_emails_b2b m WHERE m.tag_provedor IN ('gmail','hotmail','outlook_live','yahoo','outro_provedor_publico'))")
    return ' AND '.join(clauses), args


def enrich(con, rows):
    if not rows:
        return rows
    ids = [row['cnpj_basico'] for row in rows]
    placeholders = ','.join('?' for _ in ids)
    by_id = {row['cnpj_basico']: row for row in rows}
    for row in rows:
        row.update(tags=[], segmentos=[], confiabilidade='nao_verificado', resultado_smtp=None, verificado_em=None)
    for item in catalog(con):
        predicate, args = segment_predicate(item)
        matched = con.execute(f'SELECT e.cnpj_basico FROM (VALUES {",".join("(?)" for _ in ids)}) e(cnpj_basico) WHERE {predicate}', ids + args).fetchall()
        for (root,) in matched:
            by_id[root]['tags'].append(item['tag'])
            by_id[root]['segmentos'].append({'id': item['id'], 'nome': item['nome']})
    for evidence in records(con.execute(f'SELECT * FROM evidencia_email WHERE cnpj_basico IN ({placeholders})', ids)):
        row = by_id[evidence['cnpj_basico']]
        if (row.get('email') or '').strip().lower() == evidence['email']:
            row.update({k: evidence[k] for k in ('confiabilidade','resultado_smtp','verificado_em')})
    return rows


def search_source(filters):
    with source_connection() as con:
        where, args = build_where(con, filters)
        # Reduce the 27-million-row source before evaluating contact evidence.
        # Materialization keeps the large source out of tuple/mark-join plans.
        sets, candidate_args = [], []
        if filters.segmentos:
            choices = {item['id']:item for item in catalog(con)}
            segment_queries = []
            for sid in filters.segmentos:
                predicate, values = segment_predicate(choices[sid])
                segment_queries.append(predicate[len('e.cnpj_basico IN ('):-1])
                candidate_args.extend(values)
            sets.append('(' + ' UNION '.join(segment_queries) + ')')
        if filters.com_email and filters.confiabilidade and filters.confiabilidade != 'nao_verificado':
            sets.append('SELECT cnpj_basico FROM evidencia_email WHERE confiabilidade=?')
            candidate_args.append(filters.confiabilidade)
        relation = 'empresas'
        if sets:
            con.execute('CREATE TEMP TABLE candidate_roots AS ' + ' INTERSECT '.join(sets), candidate_args)
            con.execute('CREATE TEMP TABLE empresas_candidatas AS SELECT ' + ','.join('e.'+c.strip() for c in (COLUMNS+',situacao_cadastral').split(',')) + ' FROM empresas e SEMI JOIN candidate_roots c ON c.cnpj_basico=e.cnpj_basico')
            relation = 'empresas_candidatas'
        rows = records(con.execute(f'SELECT {", ".join("e."+c.strip() for c in COLUMNS.split(","))} FROM {relation} e WHERE {where} LIMIT 51', args))
        alternatives = []
        if not rows:
            # Keep segment/location/evidence constraints; relax contact filters explicitly.
            patches = []
            if filters.telefone:
                patches.append(('telefone', {'telefone':''}, 'Incluir empresas com ou sem telefone'))
            if filters.com_email and filters.tipo_email:
                patches.append(('tipo_email', {'tipo_email':''}, 'Incluir todos os tipos de e-mail'))
            if filters.telefone and filters.tipo_email:
                patches.append(('contatos', {'telefone':'','tipo_email':''}, 'Ampliar telefone e tipo de e-mail'))
            for key, patch, label in patches:
                relaxed_where, relaxed_args = build_where(con, filters.model_copy(update=patch))
                count = con.execute(f'SELECT count(*) FROM {relation} e WHERE {relaxed_where}', relaxed_args).fetchone()[0]
                if count:
                    alternatives.append({'id':key,'filtros':patch,'nome':label,'quantidade':count})
        return {'rows': enrich(con, rows[:50]), 'has_more': len(rows)>50, 'competencia':'2026-10','alternativas':alternatives}



def fetch_roots(roots):
    with source_connection() as con:
        rows = records(con.execute(f'SELECT {COLUMNS} FROM empresas WHERE cnpj_basico IN ({",".join("?" for _ in roots)}) AND situacao_cadastral=\'02\'', roots))
        return enrich(con, rows)


def get_catalog():
    with source_connection() as con:
        return [{k:v for k,v in item.items() if k not in ('filtros','fonte')} for item in catalog(con)]
