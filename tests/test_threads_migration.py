"""Real populated schema-v10 upgrade; no historical migration edits or data inference."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from test_reversals import ReversalJourney
from test_t06_migration import snapshot
from test_lifecycle import BASIS
from nextrelay.app import create_app
from nextrelay.auth import Principal
from nextrelay.config import Settings
from nextrelay.db import initialize,connect,verify_schema,SchemaError,_version_catalog
from nextrelay.schema import MIGRATIONS
from nextrelay.schema_t19 import T19_TABLES
from nextrelay.store import unit_of_work


class ThreadMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nextrelay-t19-migration-');self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'synthetic-v10.sqlite3'
        j=self.j=ReversalJourney();j.db=self.db;j.owner=Principal('dev-t19-migration')
        with patch('nextrelay.db.SCHEMA_VERSION',10),patch('nextrelay.db._target_catalog',lambda:_version_catalog(10)):
            initialize(self.db)
            with j.work() as s:
                j.p=s.create_project('Synthetic old history')['id'];j.q=s.create_project('Other')['id']
                self.session=s.create_session(j.p,'Legacy',namespace='synthetic',external_id='stable')['id']
                self.source=s.create_source(j.p,reference='synthetic://legacy')['id']
            self.task,self.version,_=j.task('Legacy task');j.submit(self.task,self.version);j.human(self.task,self.version)
            update=j.effect('task.update',self.task,payload=dict(title='Legacy rename'));j.revoke(update)
            with j.work() as s:
                attempt=s.create_attempt(j.p,self.task,'Legacy attempt')['id'];s.link_attempt_session(j.p,attempt,self.session)
                old=s.attribution(j.p,self.source);s.attribute_source(j.p,self.source,task_id=self.task,session_id=self.session,attempt_id=attempt,supersedes_id=old['id'],reason=BASIS)
                artifact=s.get(j.p,'artifact_versions',self.version)['artifact_id']
                s.create_version(j.p,artifact,'Synthetic sourced next version',reason=BASIS,source_ids=[self.source],task_ids=[self.task])
            self.before=snapshot(self.db)

    def test_populated_upgrade_preserves_every_old_row_unknown_duty_and_unassigned_work(self):
        initialize(self.db);after=snapshot(self.db)
        self.assertEqual(after['version'],11)
        for table,rows in self.before['data'].items():self.assertEqual(after['data'][table],rows,table)
        with self.j.work(False) as s:
            state=s.thread_state(self.j.p)
            self.assertEqual(state['threads'][0]['id'],self.session)
            self.assertTrue(state['historical_contributions']['attempt_sessions'])
            self.assertTrue(all(r['duty_version_id'] is None for r in state['historical_contributions']['task_sessions']))
            self.assertTrue(all(not rows for rows in state['current'].values()))
            self.assertTrue(all(not rows for rows in state['history'].values()))
            self.assertEqual(s.formal_state(self.j.p)['effective_acceptances'][0]['task_id'],self.task)
        initialize(self.db);self.assertEqual(snapshot(self.db),after)
        with connect(self.db) as c:
            verify_schema(c);self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_migration_failure_rolls_back_catalog_data_version_and_retries(self):
        migration=MIGRATIONS[11]
        with patch.dict(MIGRATIONS,{11:migration[:8]+('SELECT * FROM synthetic_missing_table',)+migration[8:]}):
            with self.assertRaises(sqlite3.OperationalError):initialize(self.db)
        self.assertEqual(snapshot(self.db),self.before)
        with patch('nextrelay.db.verify_schema',side_effect=SchemaError('synthetic final verify failure')):
            with self.assertRaises(SchemaError):initialize(self.db)
        self.assertEqual(snapshot(self.db),self.before)
        initialize(self.db);self.assertEqual(snapshot(self.db)['version'],11)

    def test_service_start_and_business_requests_do_not_upgrade(self):
        with self.assertRaises(SchemaError):create_app(Settings(self.db,'x'*40,subject='dev-t19-migration'))
        with self.assertRaises(SchemaError):
            with unit_of_work(self.db,self.j.owner,write=True) as s:s.create_session(self.j.p,'No upgrade')
        self.assertEqual(snapshot(self.db),self.before)

    def test_new_database_constraints_and_append_only_protection(self):
        initialize(self.db)
        candidate=self.j.effect('thread.duty.set',self.session,payload=dict(main='Synthetic duty',basis=BASIS))
        with connect(self.db) as c:
            change=c.execute('SELECT id FROM applied_changes WHERE candidate_id=?',(candidate['candidate_id'],)).fetchone()[0]
            for table in T19_TABLES:
                for action in ('UPDATE','DELETE'):
                    self.assertTrue(c.execute('SELECT 1 FROM sqlite_schema WHERE type=? AND name=?',('trigger',table+'_no_'+action.lower())).fetchone())
            with self.assertRaises(sqlite3.IntegrityError):c.execute("UPDATE thread_duties SET main='tamper'")
            with self.assertRaises(sqlite3.IntegrityError):c.execute('DELETE FROM thread_duties')
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute('''INSERT INTO task_leads(id,project_id,created_at,created_by,task_id,session_id,basis,revision,change_id)
                    VALUES ('bad',?,'synthetic','synthetic',?,?,'synthetic',999,?)''',(self.j.p,self.task,self.session,change))
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute('''INSERT INTO thread_successions(id,project_id,created_at,created_by,predecessor_id,successor_id,active,basis,revision,change_id)
                    VALUES ('bad',?,'synthetic','synthetic',?,?,1,'synthetic',999,?)''',(self.j.q,self.session,self.session,change))
