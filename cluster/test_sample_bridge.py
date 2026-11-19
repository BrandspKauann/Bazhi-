import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
import sample_bridge as bridge

class SampleTests(unittest.TestCase):
    def test_reserves_only_idle_pending_and_applies_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fila.sqlite';c=sqlite3.connect(path)
            c.executescript('''CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
              CREATE TABLE domains(domain TEXT PRIMARY KEY,shard INTEGER,next_at REAL DEFAULT 0,lease_until REAL DEFAULT 0,owner TEXT);
              CREATE TABLE emails(id INTEGER PRIMARY KEY,email TEXT UNIQUE,domain TEXT,state TEXT DEFAULT 'pendente',attempts INTEGER DEFAULT 0,next_at REAL DEFAULT 0,last_id INTEGER);
              CREATE TABLE attempts(id INTEGER PRIMARY KEY,email TEXT,domain TEXT,execucao_id TEXT,status TEXT,confiabilidade TEXT,smtp_verificado INTEGER,codigo_smtp INTEGER,etapa_smtp TEXT,mx TEXT,catch_all TEXT,testado_em TEXT,observacao TEXT,worker TEXT);
              CREATE INDEX emails_work ON emails(domain,state,next_at,id);''')
            c.execute("INSERT INTO meta VALUES('execucao','source-run')")
            c.executemany('INSERT INTO domains(domain,shard,lease_until,owner) VALUES(?,?,?,?)',[('idle.test',0,0,None),('busy.test',0,time.time()+900,'original'),('other.test',0,100,'pilot-unrelated')])
            c.executemany('INSERT INTO emails(id,email,domain,state,attempts) VALUES(?,?,?,?,?)',[(1,'one@idle.test','idle.test','pendente',0),(2,'done@idle.test','idle.test','smtp_aceito',1),(3,'busy@busy.test','busy.test','pendente',0)])
            c.commit();c.close()
            run,rows=bridge.reserve(path,1)
            self.assertEqual([r['id'] for r in rows],[1])
            c=sqlite3.connect(path)
            self.assertEqual(c.execute('SELECT state FROM emails WHERE id=1').fetchone()[0],'cluster_pilot')
            self.assertEqual(c.execute('SELECT state FROM emails WHERE id=3').fetchone()[0],'pendente');c.close()
            with self.assertRaises(RuntimeError):bridge.reserve(path,1)
            item={'id':55,'email':'one@idle.test','result':{'status':'inconclusivo','smtp_verificado':False,'observacao':'timeout'}}
            self.assertEqual(bridge.apply(path,[item]),[55]);self.assertEqual(bridge.apply(path,[item]),[55])
            c=sqlite3.connect(path)
            self.assertEqual(c.execute('SELECT attempts FROM emails WHERE id=1').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM attempts').fetchone()[0],1)
            self.assertEqual(c.execute("SELECT owner FROM domains WHERE domain='other.test'").fetchone()[0],'pilot-unrelated')
            self.assertEqual(c.execute("SELECT owner FROM domains WHERE domain='busy.test'").fetchone()[0],'original')
            c.close()

if __name__=='__main__':unittest.main(verbosity=2)
