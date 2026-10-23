"""Real v4 files with complete T05 journeys; no version-tag-only fixtures."""
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from test_lifecycle import Journey, BASIS
from nextrelay.auth import Principal
from nextrelay.db import SCHEMA_VERSION, SchemaError, _version_catalog, connect, initialize, verify_schema
from nextrelay.schema import MIGRATIONS
from nextrelay.schema_t06 import T06_TABLES
from nextrelay.store import Store, unit_of_work


def snapshot(database):
    with connect(database) as c:
        return dict(version=c.execute('PRAGMA user_version').fetchone()[0],
                    catalog=[tuple(r) for r in c.execute('SELECT type,name,sql FROM sqlite_schema ORDER BY type,name')],
                    data={r[0]:[tuple(v) for v in c.execute(f'SELECT * FROM {r[0]} ORDER BY rowid')]
                          for r in c.execute("SELECT name FROM sqlite_schema WHERE type='table'")})


class T06MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nextrelay-t06-upgrade-')
        self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'complete-v4.sqlite3'
        self.j=Journey();self.j.db=self.db;self.j.owner=Principal('dev-t06-migration')
        records=Store.records
        def t05_records(store,project,table):
            # T06 tables do not exist in v4. This compatibility shim only supplies
            # empty correction history; T05 writes execute real service logic,
            # schema/constraints/immutability are the exact unmodified v4 DDL.
            if table in T06_TABLES:
                store._project(project)
                return []
            return records(store,project,table)
        # Native extraction did not exist in v4. Disable only its new advisory
        # lookup while constructing the real historical fixture, never during
        # migration or the post-upgrade assertions below.
        with patch('nextrelay.db.SCHEMA_VERSION',4),patch('nextrelay.db._target_catalog',lambda:_version_catalog(4)),patch.object(Store,'records',t05_records),patch('nextrelay.native.Native.requirements',return_value={'conflicts':[]}):
            initialize(self.db)
            with self.j.work() as s:
                self.j.p=s.create_project('Synthetic complete T05 v4')['id'];self.j.q=s.create_project('Other synthetic')['id']
            a,av,artifact=self.j.task('A');b,bv,_=self.j.task('B')
            self.j.edge(a,b);self.j.effect('task.start',a,payload=dict(basis=BASIS));self.j.submit(a,av)
            grant=self.j.grant(a,av);run=self.j.check_run(a,av)
            self.auto_request=self.j.auto_request(a,av,run,grant);self.auto_result=self.j.auto(self.auto_request)
            self.j.submit(b,bv);self.j.human(b,bv);self.j.resolve_all(b)
            self.j.effect('task.update',a,payload=dict(goal='changed goal'));self.j.resolve(a,'rework')
            self.j.submit(a,av);self.j.human(a,av);self.j.resolve_all(b)
            self.j.effect('baseline.set',artifact,av);self.j.resolve(a,'needs-evidence')
            # Legal T03 reserved history can share an effect identity. It must
            # survive v5 without being promoted into formal acceptance history.
            with connect(self.db) as c:
                original=dict(c.execute("SELECT * FROM acceptances WHERE phase='formal' LIMIT 1").fetchone())
                self.reserved_task=original['task_id']
                for identity in ('synthetic-reserved-one','synthetic-reserved-two'):
                    c.execute('''INSERT INTO acceptances(id,project_id,created_at,created_by,task_id,version_id,effective_change_id,evidence_id)
                        VALUES (?,?,?,?,?,?,?,?)''',(identity,self.j.p,'synthetic-time',self.j.owner.subject,original['task_id'],original['version_id'],original['effective_change_id'],original['evidence_id']))
            self.before=snapshot(self.db)
            with self.j.work(False) as s:
                self.commits=s.records(self.j.p,'change_commits')
        self.assertEqual(self.before['version'],4)
        # The old file really contains each T05 history, not just an empty schema.
        for table in ('attempts','acceptances','check_authorizations','check_executions','dependencies',
                      'review_reasons','review_resolutions','recheck_processing','derived_snapshots','auto_requests'):
            self.assertTrue(self.before['data'][table],table)

    def test_complete_v4_upgrade_preserves_all_rows_old_commit_and_auto_results(self):
        initialize(self.db)
        after=snapshot(self.db);self.assertEqual(after['version'],SCHEMA_VERSION)
        for table,rows in self.before['data'].items():self.assertEqual(after['data'][table],rows,table)
        with self.j.work() as s:
            for commit in self.commits:
                req=json.loads(commit['request_json']);req.pop('project_id');req.pop('action');req['request_key']=commit['request_key']
                self.assertEqual(s.commit_candidates(self.j.p,req),json.loads(commit['result_json']))
            self.assertEqual(s.accept_pre_authorized(self.j.p,self.auto_request),self.auto_result)
            state=s.formal_state(self.j.p)
            self.assertEqual(state['project']['revision'],state['derived']['revision'])
        initialize(self.db);self.assertEqual(snapshot(self.db),after)
        self.j.effect('task.update',self.reserved_task,payload=dict(title='After migration display'))
        value=self.j.value(self.reserved_task)
        self.assertFalse({'synthetic-reserved-one','synthetic-reserved-two'} & set(value['historical_acceptance_ids']))
        with connect(self.db) as c:
            verify_schema(c);self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_migration_mid_ddl_and_final_failure_restore_source_and_all_protections(self):
        # A failure after relation copies must restore data, original protections,
        # the cross-table provenance guard and the original version atomically.
        original=MIGRATIONS[5]
        with patch.dict(MIGRATIONS,{5:original[:8]+('SELECT * FROM synthetic_missing_migration_table',)+original[8:]}):
            with self.assertRaises(sqlite3.OperationalError):initialize(self.db)
        self.assertEqual(snapshot(self.db),self.before)
        with patch('nextrelay.db.verify_schema',side_effect=SchemaError('synthetic final structure failure')):
            with self.assertRaises(SchemaError):initialize(self.db)
        self.assertEqual(snapshot(self.db),self.before)
        initialize(self.db);self.assertEqual(snapshot(self.db)['version'],SCHEMA_VERSION)

    def test_source_missing_protection_rejected_and_target_constraints_guard_history(self):
        with connect(self.db) as c:c.execute('DROP TRIGGER dependencies_t05_no_delete')
        before=snapshot(self.db)
        with self.assertRaisesRegex(SchemaError,'Unexpected source schema'):initialize(self.db)
        self.assertEqual(snapshot(self.db),before)

    def test_all_prior_versions_upgrade_to_complete_v6_and_append_only_guards(self):
        for source in range(5):
            db=Path(self.temp.name)/f'origin-{source}.sqlite3'
            with connect(db) as c:
                for v in range(1,source+1):
                    for sql in MIGRATIONS[v]:c.execute(sql)
                c.execute(f'PRAGMA user_version={source}')
            initialize(db);initialize(db)
            from test_reversals import ReversalJourney
            journey=ReversalJourney();journey.db=db;journey.owner=Principal('dev-migration-guard')
            with journey.work() as s:journey.p=s.create_project('Synthetic guard')['id']
            task=journey.effect('task.create',payload=dict(title='guard'))['target_id']
            update=journey.effect('task.update',task,payload=dict(title='changed'))
            journey.revoke(update)
            with connect(db) as c:
                verify_schema(c);self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],SCHEMA_VERSION)
                for table in T06_TABLES:
                    with self.assertRaises(sqlite3.IntegrityError):c.execute(f'DELETE FROM {table}')
                c.execute('DROP TRIGGER effect_corrections_no_update')
                with self.assertRaises(SchemaError):verify_schema(c)
