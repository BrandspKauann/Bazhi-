"""Behavioral tests with local synthetic Receita data; no SMTP or source writes."""
import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import duckdb
from fastapi import HTTPException
from pydantic import ValidationError
from app import receita_source as source
from app.routers.receita import SearchFilters, SaveListRequest, ImportRequest

class ProspectingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        base = self.folder/'empresas.parquet'
        workspace = self.folder/'workspace.duckdb'
        ops = self.folder/'ops.duckdb'
        with duckdb.connect() as con:
            cols = source.COLUMNS.split(', ')
            con.execute('CREATE TABLE empresas (' + ','.join(c+' VARCHAR' for c in cols) + ', situacao_cadastral VARCHAR)')
            for n in range(1,7):
                values = {c:'' for c in cols}
                values.update(cnpj_basico=f'{n:08}',cnpj_ordem='0001',cnpj_dv='00',razao_social=f'Empresa {n}',email=f'contato{n}@empresa.com',uf='SP',municipio='7107',porte='01',cnae_principal='6201501',telefone_1='999999999' if n in (1,2) else '',ddd_1='11',telefone_2='33333333' if n==6 else '')
                con.execute('INSERT INTO empresas VALUES('+','.join('?' for _ in range(len(cols)+1))+')',[values[c] for c in cols]+['02'])
            con.execute('COPY empresas TO ? (FORMAT PARQUET)',[str(base)])
            con.execute('CREATE TABLE leads AS SELECT *, NULL::VARCHAR AS classificacao_confiabilidade, NULL::VARCHAR AS status_verificacao_email, NULL::VARCHAR AS etapa_smtp, NULL::INTEGER AS codigo_smtp, NULL::VARCHAR AS verificado_em FROM empresas WHERE cnpj_basico IN (\'00000001\',\'00000002\',\'00000004\',\'00000005\',\'00000006\')')
            con.execute("UPDATE leads SET classificacao_confiabilidade='alta_confiabilidade',status_verificacao_email='aceito_pelo_servidor',etapa_smtp='rcpt_to',codigo_smtp=250,verificado_em='2026-11-01'")
            con.execute("UPDATE leads SET email='antigo@empresa.com' WHERE cnpj_basico='00000004'")
            con.execute('COPY leads TO ? (FORMAT PARQUET)',[str(self.folder/'leads.parquet')])
        with duckdb.connect(str(workspace)) as con:
            for table,col in source.TAG_TABLES.items():
                con.execute(f'CREATE TABLE {table}(cnpj_basico VARCHAR,{col} VARCHAR)')
            con.execute("INSERT INTO tags_tipos_b2b VALUES ('00000001','TECNOLOGIA_DADOS'),('00000002','RH_TERCEIRIZACAO'),('00000003','RH_TERCEIRIZACAO')")
            con.execute('CREATE TABLE smtp_rh_resultados(cnpj_basico VARCHAR,email VARCHAR,status_smtp VARCHAR,catch_all VARCHAR,testado_em TIMESTAMP)')
            con.execute("INSERT INTO smtp_rh_resultados VALUES ('00000001','contato1@empresa.com','SMTP_ACEITO','NAO_DETECTADO','2026-11-12'),('00000002','contato2@empresa.com','CONEXAO_INCONCLUSIVA',NULL,'2026-11-12'),('00000005','contato5@empresa.com','SMTP_RECUSADO',NULL,'2026-11-12')")
            con.execute('CREATE TABLE classificacao_emails_b2b(cnpj_basico VARCHAR,dominio_email VARCHAR,tag_email_corporativo VARCHAR,tag_provedor VARCHAR)')
            con.execute("INSERT INTO classificacao_emails_b2b VALUES ('00000001','empresa.com','corporativo_prioritario','provedor_proprio_presumido')")
        with duckdb.connect(str(ops)) as con:
            con.execute('CREATE TABLE ajustes(cnpj_basico VARCHAR,classificacao VARCHAR)')
            con.execute("INSERT INTO ajustes VALUES ('00000001','pendente')")
            con.execute('CREATE TABLE segmentos(id VARCHAR,nome VARCHAR,fonte VARCHAR,filtros VARCHAR,descricao VARCHAR,contagem BIGINT,ativo BOOLEAN)')
            con.execute('INSERT INTO segmentos VALUES(?,?,?,?,?,?,TRUE)',['alta','Alta confiabilidade','leads',json.dumps({'classificacao':'alta_confiabilidade'}),'Teste',5])
        (self.folder/'base-de-trabalho.json').write_text(json.dumps({'base_de_trabalho':'C:\\origem\\leads.parquet'}))
        self.patch = patch.multiple(source,SOURCE=str(base),WORKSPACE=str(workspace),OPERATIONS=str(ops),LEADS_DIR=self.folder)
        self.patch.start()
    def tearDown(self):
        self.patch.stop(); self.temp.cleanup()
    def ids(self,**kwargs):
        return {r['cnpj_basico'] for r in source.search_source(SearchFilters(**kwargs))['rows']}
    def test_segments_or_and_contact_filters(self):
        self.assertEqual(self.ids(segmentos=['tags_tipos_b2b:TECNOLOGIA_DADOS','tags_tipos_b2b:RH_TERCEIRIZACAO'],telefone='com'),{'00000001','00000002'})
    def test_saved_segment_applies_latest_classification(self):
        self.assertNotIn('00000001',self.ids(segmentos=['segmento:alta']))
        self.assertIn('00000006',self.ids(segmentos=['segmento:alta']))
    def test_latest_result_wins_and_same_email_required(self):
        self.assertEqual(self.ids(confiabilidade='smtp_comprovado'),{'00000001','00000006'})
        self.assertEqual(self.ids(confiabilidade='inconclusivo'),{'00000002'})
        self.assertEqual(self.ids(confiabilidade='nao_verificado'),{'00000003','00000004'})
        self.assertEqual(self.ids(confiabilidade='recusado'),{'00000005'})
    def test_phone_checks_both_numbers(self):
        self.assertEqual(self.ids(telefone='com'),{'00000001','00000002','00000006'})
    def test_email_unchecked_ignores_hidden_filters(self):
        self.assertEqual(len(self.ids(com_email=False,confiabilidade='smtp_comprovado',tipo_email='corporativo')),6)
    def test_corporate_filter_uses_saved_classification(self):
        self.assertEqual(self.ids(tipo_email='corporativo'),{'00000001'})
    def test_invalid_segments_rejected(self):
        with self.assertRaises(HTTPException) as error:
            self.ids(segmentos=["invalid' OR 1=1"])
        self.assertEqual(error.exception.status_code,422)
    def test_limit_and_root_validation(self):
        with self.assertRaises(ValidationError):
            SaveListRequest(nome='Mais de 50',cnpjs=[f'{n:08}' for n in range(51)])
        with self.assertRaises(ValidationError):
            ImportRequest(cnpjs=['invalid'])
        with self.assertRaises(ValidationError):
            SaveListRequest(nome='   ',cnpjs=['00000001'])
    def test_empty_combination_suggests_phone_without_weakening_evidence(self):
        filters=SearchFilters(confiabilidade='smtp_comprovado',tipo_email='corporativo',telefone='sem')
        data=source.search_source(filters)
        self.assertEqual(data['rows'],[])
        suggestion=next(x for x in data['alternativas'] if x['id']=='telefone')
        self.assertEqual(suggestion['quantidade'],1)
        self.assertEqual(suggestion['filtros'],{'telefone':''})
        adjusted=source.search_source(filters.model_copy(update=suggestion['filtros']))
        self.assertEqual(len(adjusted['rows']),1)
        self.assertEqual(adjusted['rows'][0]['confiabilidade'],'smtp_comprovado')

    def test_tags_and_evidence_enriched(self):
        row=source.fetch_roots(['00000001'])[0]
        self.assertIn('TECNOLOGIA_DADOS',row['tags'])
        self.assertEqual(row['confiabilidade'],'smtp_comprovado')
        self.assertEqual(row['resultado_smtp'],'SMTP_ACEITO')

if __name__=='__main__':
    unittest.main()
