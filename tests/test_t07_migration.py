"""Real complete T06 v5 file -> v6; history, reserved data and guards remain."""
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from test_reversals import ReversalJourney
from test_t06_migration import snapshot
from nextrelay.auth import Principal
from nextrelay.db import SCHEMA_VERSION, SchemaError, _version_catalog, connect, initialize, verify_schema
from nextrelay.ingestion import ImportService, SelectedFile
from nextrelay.schema import MIGRATIONS
from nextrelay.schema_t07 import T07_TABLES


class T07MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nextrelay-t07-migration-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'complete-v5.sqlite3'
        self.j=ReversalJourney();self.j.db=self.db;self.j.owner=Principal('dev-t07-migration')
        # Exact original v5 DDL and real T06 service; no version-tag spoofing.
        with patch('nextrelay.db.SCHEMA_VERSION',5),patch('nextrelay.db._target_catalog',lambda:_version_catalog(5)):
            initialize(self.db)
            with self.j.work() as s:
                self.j.p=s.create_project('Complete synthetic T06')['id'];self.j.q=s.create_project('Other')['id']
            a,av,artifact=self.j.task('A');b,bv,_=self.j.task('B')
            self.j.edge(a,b);self.j.submit(a,av)
            grant=self.j.grant(a,av);run=self.j.check_run(a,av)
            self.auto_request=self.j.auto_request(a,av,run,grant);self.auto_result=self.j.auto(self.auto_request)
            self.j.submit(b,bv);self.j.human(b,bv);self.j.resolve_all(b)
            update=self.j.effect('task.update',a,payload={'title':'wrong'})
            self.j.revoke(update)
            self.j.effect('baseline.set',artifact,av)
            self.j.resolve(a,'needs-evidence')
            with self.j.work(False) as s:
                self.before_state=s.formal_state(self.j.p)
                self.commits=s.records(self.j.p,'change_commits')
            with connect(self.db) as c:
                original=dict(c.execute("SELECT * FROM acceptances WHERE phase='formal' LIMIT 1").fetchone())
                for identity in ('reserved-a','reserved-b'):
                    c.execute('''INSERT INTO acceptances(id,project_id,created_at,created_by,task_id,version_id,effective_change_id,evidence_id)
                        VALUES (?,?,?,?,?,?,?,?)''',(identity,self.j.p,'synthetic',self.j.owner.subject,original['task_id'],original['version_id'],original['effective_change_id'],original['evidence_id']))
                c.execute("INSERT INTO import_batches(id,project_id,created_at,created_by,manifest_fingerprint,processing_version) VALUES ('reserved-batch',?,'synthetic',?,'legacy','reserved')",(self.j.p,self.j.owner.subject))
                c.execute("INSERT INTO import_items(id,project_id,created_at,created_by,batch_id,reason) VALUES ('reserved-item',?,'synthetic',?,'reserved-batch','legacy untouched')",(self.j.p,self.j.owner.subject))
            with self.j.work(False) as s:
                self.before_state=s.formal_state(self.j.p)
            self.before=snapshot(self.db)
        self.assertEqual(self.before['version'],5)
        for table in ('reversal_previews','effect_corrections','auto_requests','acceptances','review_reasons','derived_snapshots'):
            self.assertTrue(self.before['data'][table],table)

    def test_complete_v5_history_reserved_idempotency_and_revoked_effect_preserved(self):
        initialize(self.db);after=snapshot(self.db);self.assertEqual(after['version'],SCHEMA_VERSION)
        for table,rows in self.before['data'].items():self.assertEqual(after['data'][table],rows,table)
        with self.j.work() as s:
            self.assertEqual(s.formal_state(self.j.p),self.before_state)
            for commit in self.commits:
                req=json.loads(commit['request_json']);req.pop('project_id');req.pop('action');req['request_key']=commit['request_key']
                self.assertEqual(s.commit_candidates(self.j.p,req),json.loads(commit['result_json']))
            self.assertEqual(s.accept_pre_authorized(self.j.p,self.auto_request),self.auto_result)
            self.assertEqual(s.formal_state(self.j.p),self.before_state)
        initialize(self.db);self.assertEqual(snapshot(self.db),after)
        store=self.root/'originals';store.mkdir();source=self.root/'file.txt';source.write_bytes(b'new input')
        service=ImportService(self.db,self.j.owner,store)
        b=service.import_files(self.j.p,'after-upgrade',[SelectedFile(source,'file.txt')])
        self.assertEqual(service.read_original(self.j.p,b['items'][0]['id']),b'new input')
        with self.j.work(False) as s:self.assertEqual(s.formal_state(self.j.p),self.before_state)
        with connect(self.db) as c:
            verify_schema(c);self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            for table in T07_TABLES:
                if c.execute(f'SELECT 1 FROM {table}').fetchone():
                    for action in ('UPDATE','DELETE'):
                        sql=f'UPDATE {table} SET created_by=created_by' if action=='UPDATE' else f'DELETE FROM {table}'
                        with self.assertRaises(sqlite3.IntegrityError):c.execute(sql)
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute('UPDATE sources SET fingerprint=\'fake\'')

    def test_ddl_target_and_followup_failure_rollback_entire_upgrade(self):
        original=MIGRATIONS[6]
        with patch.dict(MIGRATIONS,{6:original[:3]+('SELECT * FROM missing_synthetic_table',)+original[3:]}):
            with self.assertRaises(sqlite3.OperationalError):initialize(self.db)
        self.assertEqual(snapshot(self.db),self.before)
        with patch('nextrelay.db.verify_schema',side_effect=SchemaError('synthetic target failure')):
            with self.assertRaises(SchemaError):initialize(self.db)
        self.assertEqual(snapshot(self.db),self.before)
        verify=verify_schema
        def followup(c):
            verify(c);c.execute('SELECT * FROM missing_after_full_target')
        with patch('nextrelay.db.verify_schema',side_effect=followup):
            with self.assertRaises(sqlite3.OperationalError):initialize(self.db)
        self.assertEqual(snapshot(self.db),self.before)

    def test_earlier_versions_continuous_upgrade_structure_and_composite_foreign_keys(self):
        for version in range(6):
            db=self.root/f'old-{version}.sqlite3'
            with connect(db) as c:
                for v in range(1,version+1):
                    for sql in MIGRATIONS[v]:c.execute(sql)
                c.execute(f'PRAGMA user_version={version}')
            initialize(db);initialize(db)
            with connect(db) as c:
                verify_schema(c);self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],SCHEMA_VERSION)
                for table in T07_TABLES:self.assertTrue(c.execute(f'PRAGMA foreign_key_list({table})').fetchall())
        with connect(self.db) as c:c.execute('DROP TRIGGER effect_corrections_no_delete')
        before=snapshot(self.db)
        with self.assertRaises(SchemaError):initialize(self.db)
        self.assertEqual(snapshot(self.db),before)
