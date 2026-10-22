"""Restore the actual historical-service v3 dump into real SQLite files, then upgrade."""
from pathlib import Path
from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from nextrelay.auth import Principal
from nextrelay.changes import ChangeError
from nextrelay.db import SCHEMA_VERSION, SchemaError, connect, initialize, verify_schema
from nextrelay.schema import MIGRATIONS
from nextrelay.store import unit_of_work


class T05MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nextrelay-t05-upgrade-')
        self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'historical.sqlite3'
        with closing(sqlite3.connect(self.db,autocommit=True)) as c:
            c.executescript((Path(__file__).parent/'fixtures/schema_v3_history.sql').read_text(encoding='utf-8'))
        with connect(self.db) as c:
            self.tables={r[0]:[r[1] for r in c.execute(f'PRAGMA table_info({r[0]})')] for r in c.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
            self.project=dict(c.execute('SELECT * FROM projects').fetchone())
            self.task=c.execute('SELECT task_id FROM formal_task_states LIMIT 1').fetchone()[0]
            self.original={table:[tuple(r) for r in c.execute(f"SELECT {','.join(columns)} FROM {table} ORDER BY rowid")]
                           for table,columns in self.tables.items()}
            self.commits=[dict(r) for r in c.execute('SELECT * FROM change_commits')]

    def snapshot(self):
        with connect(self.db) as c:
            return dict(catalog=[tuple(r) for r in c.execute("SELECT type,name,sql FROM sqlite_schema ORDER BY type,name")],
                        data={r[0]:[tuple(v) for v in c.execute(f'SELECT * FROM {r[0]} ORDER BY rowid')] for r in c.execute("SELECT name FROM sqlite_schema WHERE type='table'")},
                        version=c.execute('PRAGMA user_version').fetchone()[0])

    def test_v3_complete_history_pending_continuation_retry_and_repeated_upgrade(self):
        initialize(self.db)
        with connect(self.db) as c:
            verify_schema(c)
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],SCHEMA_VERSION)
            for table,columns in self.tables.items():
                self.assertEqual([tuple(r) for r in c.execute(f"SELECT {','.join(columns)} FROM {table} ORDER BY rowid")],self.original[table],table)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(c.execute('SELECT count(*) FROM recheck_requests').fetchone()[0],3)
            processing=[dict(r) for r in c.execute('SELECT * FROM recheck_processing')]
            self.assertEqual(len(processing),3)
            self.assertTrue(all(p['processed_revision']==5 for p in processing))
            self.assertCountEqual([p['target_revision'] for p in processing],[3,4,5])
        owner=Principal(self.project['owner_subject'])
        with unit_of_work(self.db,owner,write=True) as s:
            state=s.formal_state(self.project['id'])
            self.assertEqual(state['derived']['revision'],5)
            self.assertEqual(state['pending_rechecks'],[])
            self.assertEqual(state['derived']['tasks'][0]['validity'],'pending-review')
            self.assertEqual(len(state['review_reasons']),3)
            self.assertEqual(state['acceptances'],[])
            self.assertEqual(state['readiness'],'not-evaluated')
            self.assertEqual(state['derived']['sources'][0]['availability'],'unavailable')
            for commit in self.commits:
                result=s.commit_candidates(self.project['id'],{k:v for k,v in json.loads(commit['request_json']).items() if k in ('request_key','base_revision','selection')} | {'request_key':commit['request_key']})
                self.assertEqual(result,json.loads(commit['result_json']))
        once=self.snapshot();initialize(self.db)
        self.assertEqual(self.snapshot(),once)

    def test_migration_failure_after_rebuild_or_pending_processing_rolls_back_original_file(self):
        before=self.snapshot()
        with patch('nextrelay.db.verify_schema',side_effect=SchemaError('synthetic post-DDL verification fault')):
            with self.assertRaises(SchemaError):initialize(self.db)
        self.assertEqual(before,self.snapshot())
        from nextrelay.lifecycle import Lifecycle
        original=Lifecycle.sync
        def fail(self,*args):
            original(self,*args)
            raise RuntimeError('synthetic post-processing migration failure')
        with patch.object(Lifecycle,'sync',fail):
            with self.assertRaises(RuntimeError):initialize(self.db)
        self.assertEqual(before,self.snapshot())
        initialize(self.db)
        # T07 adds import records after the unchanged v4/v5 history.
        self.assertEqual(self.snapshot()['version'],SCHEMA_VERSION)

    def test_new_database_and_v1_v2_sequential_upgrades_have_identical_target_structure(self):
        paths=[]
        for origin in (0,1,2,3):
            db=Path(self.temp.name)/f'from-{origin}.sqlite3'
            if origin:
                with closing(sqlite3.connect(db,autocommit=True)) as c:
                    for number in range(1,origin+1):
                        for statement in MIGRATIONS[number]:c.execute(statement)
                    c.execute(f'PRAGMA user_version={origin}')
            initialize(db);initialize(db)
            with connect(db) as c:
                verify_schema(c)
                paths.append([(r['type'],r['name']) for r in c.execute("SELECT * FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY name")])
        self.assertTrue(all(value==paths[0] for value in paths))

    def test_target_verification_detects_new_missing_protection_and_foreign_keys(self):
        initialize(self.db)
        with connect(self.db) as c:
            c.execute('DROP TRIGGER review_resolutions_t05_no_delete')
            with self.assertRaises(SchemaError):verify_schema(c)

    def test_missing_source_protection_is_not_silently_repaired_by_rebuild(self):
        with connect(self.db) as c:c.execute('DROP TRIGGER formal_task_states_t04_no_update')
        before=self.snapshot()
        with self.assertRaisesRegex(SchemaError,'Unexpected source schema'):initialize(self.db)
        self.assertEqual(before,self.snapshot())


if __name__=='__main__':unittest.main()
