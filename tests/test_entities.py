"""Real SQLite-file behavior and service boundaries, using only synthetic data."""
from pathlib import Path
import hashlib
import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from nextrelay.auth import AccessError, Principal
from nextrelay.db import SCHEMA_VERSION, SchemaError, connect, initialize, transaction, verify_schema
from nextrelay.schema import ENTITY_TABLES, RELATION_TABLES
from nextrelay.store import TransactionAborted, unit_of_work

V1_SNAPSHOT = Path(__file__).parent / 'fixtures' / 'schema_v1.sql'


def old_database(path):
    with connect(path) as c:
        c.executescript(V1_SNAPSHOT.read_text(encoding='utf-8'))
        c.execute('INSERT INTO foundation_scopes VALUES (?, ?, ?)',
                  ('before-upgrade', 'dev-original', 'synthetic-access-fixture'))


def catalog(c):
    return [tuple(row) for row in c.execute(
        "SELECT type, name, sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
    )]


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nextrelay-t03-migration-')
        self.addCleanup(self.temp.cleanup)
        self.old = Path(self.temp.name) / 'old.sqlite3'
        self.new = Path(self.temp.name) / 'new.sqlite3'
        old_database(self.old)

    def test_frozen_v1_upgrade_retains_data_and_matches_fresh_schema(self):
        initialize(self.old)
        initialize(self.new)
        initialize(self.old)
        initialize(self.new)
        with connect(self.old) as old, connect(self.new) as new:
            self.assertEqual(catalog(old), catalog(new))
            self.assertEqual(old.execute('PRAGMA user_version').fetchone()[0], SCHEMA_VERSION)
            self.assertEqual(tuple(old.execute('SELECT * FROM foundation_scopes').fetchone()),
                             ('before-upgrade', 'dev-original', 'synthetic-access-fixture'))
            self.assertEqual(old.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(old.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_upgrade_mid_ddl_collision_rolls_back_all_tables_and_version(self):
        with connect(self.old) as c:
            # The collision occurs after projects/tasks/etc have been created by v2.
            c.execute('CREATE TABLE artifacts (untouched TEXT)')
            c.execute("INSERT INTO artifacts VALUES ('existing-unknown-data')")
            before = catalog(c)
        with self.assertRaises(sqlite3.OperationalError):
            initialize(self.old)
        with connect(self.old) as c:
            self.assertEqual(catalog(c), before)
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT count(*) FROM foundation_scopes').fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT untouched FROM artifacts').fetchone()[0], 'existing-unknown-data')

    def test_failure_after_version_update_rolls_back_and_retry_succeeds(self):
        with connect(self.old) as c:
            before = catalog(c)
        # Failure injection changes the final checker, not SQLite or its transaction behavior.
        with patch('nextrelay.db.verify_schema', side_effect=SchemaError('injected final validation failure')):
            with self.assertRaises(SchemaError):
                initialize(self.old)
        with connect(self.old) as c:
            self.assertEqual(catalog(c), before)
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT id FROM foundation_scopes').fetchone()[0], 'before-upgrade')
        initialize(self.old)
        with connect(self.old) as c:
            verify_schema(c)

    def test_upgrade_through_actual_cli_is_repeatable(self):
        env = dict(os.environ, NEXTRELAY_ENV='development', NEXTRELAY_AUTH_MODE='dev-token',
                   NEXTRELAY_DEV_TOKEN=secrets.token_urlsafe(32), NEXTRELAY_DB_PATH=str(self.old))
        for _ in range(2):
            result = subprocess.run([sys.executable, '-m', 'nextrelay', 'init-db'], env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f'schema v{SCHEMA_VERSION}', result.stdout)
        with connect(self.old) as c:
            self.assertEqual(c.execute('SELECT id FROM foundation_scopes').fetchone()[0], 'before-upgrade')

    def test_missing_immutability_trigger_is_rejected(self):
        initialize(self.new)
        with connect(self.new) as c:
            c.execute('DROP TRIGGER artifact_versions_no_update')
            with self.assertRaises(SchemaError):
                verify_schema(c)
        with self.assertRaises(SchemaError):
            initialize(self.new)

    def test_old_schema_cannot_be_used_without_explicit_upgrade(self):
        with self.assertRaises(SchemaError):
            with unit_of_work(self.old, Principal('dev-original')):
                self.fail('Old schema accepted')
        with connect(self.old) as c:
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0], 1)


class EntityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nextrelay-t03-entities-')
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'domain.sqlite3'
        initialize(self.db)
        self.owner = Principal('dev-owner')
        self.other = Principal('dev-stranger')
        with self.work() as s:
            self.p = s.create_project('same title')['id']
            self.q = s.create_project('same title')['id']
            self.t = s.create_task(self.p, 'same task')['id']
            self.t2 = s.create_task(self.p, 'same task')['id']
            self.qt = s.create_task(self.q, 'foreign task')['id']
            self.session = s.create_session(self.p, 'session', namespace='codex:local', external_id='42')['id']
            self.qsession = s.create_session(self.q, 'other')['id']
            self.attempt = s.create_attempt(self.p, self.t, 'round 1')['id']
            self.artifact = s.create_artifact(self.p, 'report.md')['id']
            self.v = s.create_version(self.p, self.artifact, 'version one', reason='synthetic original', task_ids=(self.t, self.t2))['id']
            self.source = s.create_source(self.p, reference='synthetic://source', fingerprint='same-content')['id']
        with self.work(principal=self.other) as s:
            self.foreign = s.create_project('external owner')['id']

    def work(self, *, principal=None, write=True):
        return unit_of_work(self.db, self.owner if principal is None else principal, write=write)

    def test_project_ownership_is_persistent_and_missing_matches_foreign(self):
        with self.work(write=False) as s:
            self.assertEqual({p['id'] for p in s.projects()}, {self.p, self.q})
            self.assertEqual(s.project(self.p)['owner_subject'], self.owner.subject)
        codes = []
        for project in (self.foreign, 'missing-project'):
            with self.assertRaises(AccessError) as error:
                with self.work(write=False) as s:
                    s.project(project)
            codes.append((error.exception.status, error.exception.code))
        self.assertEqual(codes, [(404, 'object_not_found')] * 2)
        with self.work(principal=self.other, write=False) as s:
            self.assertEqual([p['id'] for p in s.projects()], [self.foreign])

    def test_missing_identity_rejects_reads_and_writes(self):
        for principal in (None, 'dev-owner', Principal(''), Principal(' ')):
            for write in (False, True):
                with self.subTest(principal=repr(principal), write=write), self.assertRaises(AccessError):
                    with unit_of_work(self.db, principal, write=write):
                        self.fail('Anonymous unit opened')

    def test_all_read_entrypoints_enforce_owner(self):
        calls = [lambda s: s.get(self.p, 'tasks', self.t), lambda s: s.records(self.p, 'task_sessions'),
                 lambda s: s.attribution(self.p, self.source), lambda s: s.evidence_for(self.p, self.t, self.v),
                 lambda s: s.version_provenance(self.p, self.v)]
        for call in calls:
            with self.subTest(call=call), self.assertRaises(AccessError):
                with self.work(principal=self.other, write=False) as s:
                    call(s)

    def test_write_entrypoints_reject_foreign_project(self):
        calls = [lambda s: s.create_task(self.p, 'unauthorized'), lambda s: s.create_session(self.p, 'unauthorized'),
                 lambda s: s.create_attempt(self.p, self.t, 'unauthorized'), lambda s: s.create_source(self.p),
                 lambda s: s.create_artifact(self.p, 'unauthorized'),
                 lambda s: s.create_version(self.p, self.artifact, 'unauthorized', reason='x'),
                 lambda s: s.link_task_session(self.p, self.t, self.session),
                 lambda s: s.link_attempt_session(self.p, self.attempt, self.session),
                 lambda s: s.link_version_task(self.p, self.v, self.t),
                 lambda s: s.link_artifact_task(self.p, self.artifact, self.t),
                 lambda s: s.link_version_source(self.p, self.v, self.source),
                 lambda s: s.attribute_source(self.p, self.source, reason='x'),
                 lambda s: s.record_evidence(self.p, self.v, mechanism='x', subject='x', result='x', configuration_version='1'),
                 lambda s: s.record_check(self.p, 'missing-evidence', mechanism='x', subject='x', configuration_version='1', result='pass')]
        for index, call in enumerate(calls):
            with self.subTest(index=index), self.assertRaises(AccessError):
                with self.work(principal=self.other) as s:
                    call(s)

    def test_cross_project_associations_are_rejected_by_service(self):
        calls = [lambda s: s.link_task_session(self.p, self.t, self.qsession),
                 lambda s: s.link_attempt_session(self.p, self.attempt, self.qsession),
                 lambda s: s.create_attempt(self.p, self.qt, 'wrong'),
                 lambda s: s.link_version_task(self.p, self.v, self.qt),
                 lambda s: s.attribute_source(self.p, self.source, task_id=self.qt, reason='wrong')]
        for call in calls:
            with self.assertRaises(AccessError):
                with self.work() as s:
                    call(s)
        with self.work(write=False) as s:
            self.assertEqual(s.records(self.p, 'task_sessions'), [])

    def test_direct_sql_cross_project_and_dangling_references_fail(self):
        statements = [
            ('INSERT INTO task_sessions VALUES (?, ?, ?, ?)', (self.p, self.t, self.qsession, 'dev-owner')),
            ('INSERT INTO task_sessions VALUES (?, ?, ?, ?)', (self.p, self.t, 'missing', 'dev-owner')),
            ('INSERT INTO artifact_tasks VALUES (?, ?, ?, ?)', (self.p, self.artifact, self.qt, 'dev-owner')),
            ('''INSERT INTO artifact_version_tasks VALUES (?, ?, ?, ?, ?)''', (self.p, self.artifact, self.v, self.qt, 'dev-owner')),
            ('''INSERT INTO version_sources VALUES (?, ?, ?, ?)''', (self.q, self.v, self.source, 'dev-owner')),
        ]
        with connect(self.db) as c:
            for sql, values in statements:
                with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    with transaction(c):
                        c.execute(sql, values)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_names_are_not_identity_and_rename_keeps_id(self):
        self.assertNotEqual(self.p, self.q)
        self.assertNotEqual(self.t, self.t2)
        with connect(self.db) as c:
            c.execute('UPDATE tasks SET title = ? WHERE id = ?', ('renamed task', self.t))
        with self.work(write=False) as s:
            self.assertEqual(s.get(self.p, 'tasks', self.t)['title'], 'renamed task')
            self.assertEqual(s.get(self.p, 'tasks', self.t2)['title'], 'same task')

    def test_external_id_namespace_and_project_are_both_required_for_identity(self):
        with self.work() as s:
            other_namespace = s.create_session(self.p, 'same session', namespace='claude:local', external_id='42')
            other_project = s.create_session(self.q, 'same session', namespace='codex:local', external_id='42')
            self.assertEqual(len({self.session, other_namespace['id'], other_project['id']}), 3)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.work() as s:
                s.create_session(self.p, 'duplicate', namespace='codex:local', external_id='42')
        with self.assertRaises(ValueError):
            with self.work() as s:
                s.create_session(self.p, 'no namespace', external_id='42')

    def test_many_to_many_sessions_and_separate_attempts_survive_reopen(self):
        with self.work() as s:
            session2 = s.create_session(self.p, 'session 2')['id']
            attempt2 = s.create_attempt(self.p, self.t, 'round 2')['id']
            other_task_attempt = s.create_attempt(self.p, self.t2, 'task 2 round')['id']
            s.link_attempt_session(self.p, self.attempt, self.session)
            s.link_attempt_session(self.p, self.attempt, session2)
            s.link_attempt_session(self.p, attempt2, session2)
            s.link_attempt_session(self.p, other_task_attempt, self.session)
        with self.work(write=False) as s:
            self.assertEqual(len(s.records(self.p, 'task_sessions')), 3)
            self.assertEqual(len(s.records(self.p, 'attempt_sessions')), 4)
            self.assertEqual(len(s.records(self.p, 'attempts')), 3)
            self.assertEqual(s.get(self.p, 'attempts', self.attempt)['task_id'], self.t)

    def test_unknown_attribution_saves_then_correction_preserves_all_originals(self):
        with self.work() as s:
            source = s.create_source(self.p)
            original = s.attribution(self.p, source['id'])
            self.assertEqual(original['pending'], ['task_id', 'session_id', 'attempt_id'])
            first = s.attribute_source(self.p, source['id'], task_id=self.t, supersedes_id=original['id'], reason='synthetic match')
            corrected = s.attribute_source(self.p, source['id'], task_id=self.t2, supersedes_id=first['id'], reason='correct task')
        with self.work(write=False) as s:
            current = s.attribution(self.p, source['id'])
            self.assertEqual(current['id'], corrected['id'])
            self.assertEqual(current['task_id'], self.t2)
            self.assertIn('attempt_id', current['pending'])
            self.assertEqual(s.get(self.p, 'source_attributions', original['id'])['task_id'], None)
            self.assertEqual(s.get(self.p, 'source_attributions', first['id'])['task_id'], self.t)
            self.assertEqual(s.get(self.p, 'sources', source['id'])['namespace'], None)

    def test_attribution_attempt_must_match_task_and_source_correction_cannot_switch_source(self):
        with self.work(write=False) as s:
            original = s.attribution(self.p, self.source)
        with self.assertRaises(ValueError):
            with self.work() as s:
                s.attribute_source(self.p, self.source, task_id=self.t2, attempt_id=self.attempt,
                                   supersedes_id=original['id'], reason='wrong task')
        with self.work() as s:
            source2 = s.create_source(self.p)['id']
        with self.assertRaises(ValueError):
            with self.work() as s:
                s.attribute_source(self.p, source2, supersedes_id=original['id'], reason='wrong source')
        with self.assertRaises(sqlite3.IntegrityError):
            with self.work() as s:
                s.attribute_source(self.p, self.source, reason='duplicate root')

    def test_repeated_correction_of_superseded_record_is_rejected(self):
        with self.work() as s:
            original = s.attribution(self.p, self.source)
            s.attribute_source(self.p, self.source, task_id=self.t, supersedes_id=original['id'], reason='first')
        with self.assertRaises(sqlite3.IntegrityError):
            with self.work() as s:
                s.attribute_source(self.p, self.source, task_id=self.t2, supersedes_id=original['id'], reason='stale correction')

    def test_project_only_artifact_and_multitask_version_are_independent(self):
        with self.work() as s:
            general = s.create_artifact(self.p, 'general reference')
            version = s.create_version(self.p, general['id'], 'general content', reason='reference only')
        with self.work(write=False) as s:
            links = s.records(self.p, 'artifact_version_tasks')
            self.assertEqual({r['task_id'] for r in links if r['version_id'] == self.v}, {self.t, self.t2})
            self.assertFalse(any(r['version_id'] == version['id'] for r in links))
            self.assertEqual(s.get(self.p, 'artifact_versions', version['id'])['content'], 'general content')
            self.assertEqual(s.evidence_for(self.p, self.t, version['id']), [])
            self.assertEqual(s.version_provenance(self.p, version['id'])['source_status'], 'pending')

    def test_independent_sources_with_same_fingerprint_and_external_id_are_retained(self):
        with self.work() as s:
            a = s.create_source(self.p, namespace='synthetic', external_id='same', reference='file-a', fingerprint='same-content')
            b = s.create_source(self.p, namespace='synthetic', external_id='same', reference='file-b', fingerprint='same-content')
            s.link_version_source(self.p, self.v, self.source)
            s.link_version_source(self.p, self.v, a['id'])
            s.link_version_source(self.p, self.v, b['id'])
        with self.work(write=False) as s:
            self.assertNotEqual(a['id'], b['id'])
            self.assertEqual(len(s.records(self.p, 'version_sources')), 3)
            self.assertEqual(len(s.records(self.p, 'sources')), 3)
            provenance = s.version_provenance(self.p, self.v)
            self.assertEqual(provenance['source_status'], 'linked')
            self.assertEqual(len(provenance['attributions']), 3)

    def test_version_revision_keeps_old_content_hash_and_evidence(self):
        with self.work() as s:
            evidence = s.record_evidence(self.p, self.v, task_id=self.t, source_id=self.source,
                                         kind='observation', mechanism='synthetic-check', subject='dev-checker',
                                         result='observed', configuration_version='check-1', conditions_version=1)
            s.record_check(self.p, evidence['id'], mechanism='synthetic-check', subject='dev-checker',
                           configuration_version='check-1', result='pass')
            v2 = s.create_version(self.p, self.artifact, 'version two', reason='explicit revision', task_ids=(self.t, self.t2))
        with self.work(write=False) as s:
            original = s.get(self.p, 'artifact_versions', self.v)
            self.assertEqual(original['content'], 'version one')
            self.assertEqual(original['content_sha256'], hashlib.sha256(b'version one').hexdigest())
            self.assertEqual((original['ordinal'], v2['ordinal']), (1, 2))
            self.assertEqual(s.evidence_for(self.p, self.t, self.v)[0]['check_result'], 'pass')
            self.assertEqual(s.evidence_for(self.p, self.t, v2['id']), [])
            self.assertEqual(s.evidence_for(self.p, self.t2, self.v), [])
            self.assertEqual(s.records(self.p, 'acceptances'), [])
            self.assertEqual(s.project(self.p)['revision'], 0)

    def test_database_rejects_version_rewrite_delete_and_original_source_edits(self):
        statements = [
            ('UPDATE artifact_versions SET content = ? WHERE id = ?', ('overwrite', self.v)),
            ('UPDATE artifact_versions SET content_sha256 = ? WHERE id = ?', ('0' * 64, self.v)),
            ('DELETE FROM artifact_versions WHERE id = ?', (self.v,)),
            ('UPDATE sources SET reference = ? WHERE id = ?', ('replacement', self.source)),
            ('DELETE FROM sources WHERE id = ?', (self.source,)),
            ('UPDATE projects SET owner_subject = ? WHERE id = ?', ('dev-stranger', self.p)),
            ('UPDATE tasks SET project_id = ? WHERE id = ?', (self.q, self.t)),
        ]
        with connect(self.db) as c:
            for sql, values in statements:
                with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    c.execute(sql, values)

    def test_evidence_on_unlinked_task_or_wrong_conditions_cannot_be_recorded(self):
        with self.work() as s:
            third_task = s.create_task(self.p, 'unlinked')['id']
        with self.assertRaises(sqlite3.IntegrityError):
            with self.work() as s:
                s.record_evidence(self.p, self.v, task_id=third_task, conditions_version=1,
                                  mechanism='x', subject='x', result='pass', configuration_version='1')
        with self.assertRaises(ValueError):
            with self.work() as s:
                s.record_evidence(self.p, self.v, task_id=self.t, conditions_version=2,
                                  mechanism='x', subject='x', result='pass', configuration_version='1')

    def test_raw_sql_attribution_and_evidence_enforce_exact_project_task_and_version(self):
        with self.work() as s:
            evidence = s.record_evidence(self.p, self.v, task_id=self.t, source_id=self.source,
                                         conditions_version=1, mechanism='observed', subject='dev-check',
                                         result='recorded', configuration_version='1')
            check = s.record_check(self.p, evidence['id'], mechanism='recorded-check', subject='dev-check',
                                   configuration_version='1', result='pass')
            root = s.attribution(self.p, self.source)
        with connect(self.db) as c:
            tests = [
                ("UPDATE source_attributions SET task_id = ? WHERE id = ?", (self.t, root['id'])),
                ("DELETE FROM source_attributions WHERE id = ?", (root['id'],)),
                ("UPDATE evidence SET version_id = ? WHERE id = ?", ('wrong-version', evidence['id'])),
                ("DELETE FROM check_results WHERE id = ?", (check['id'],)),
                ("""INSERT INTO source_attributions
                    (id, project_id, created_at, created_by, source_id, task_id, attempt_id, reason, supersedes_id)
                    VALUES ('invalid-attribution', ?, 'synthetic-time', 'dev-owner', ?, ?, ?, 'wrong task', ?)""",
                 (self.p, self.source, self.t2, self.attempt, root['id'])),
                ("""INSERT INTO evidence
                    (id, project_id, created_at, created_by, task_id, version_id, kind, mechanism,
                     subject, result, conditions_version, configuration_version)
                    VALUES ('wrong-version-evidence', ?, 'synthetic-time', 'dev-owner', ?, ?, 'claim', 'x', 'x', 'x', 1, '1')""",
                 (self.q, self.qt, self.v)),
                ("""INSERT INTO check_results
                    (id, project_id, created_at, created_by, evidence_id, mechanism, subject, configuration_version, result, details)
                    VALUES ('cross-project-check', ?, 'synthetic-time', 'dev-owner', ?, 'x', 'x', '1', 'pass', '')""",
                 (self.q, evidence['id'])),
            ]
            for sql, values in tests:
                with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    with transaction(c):
                        c.execute(sql, values)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_reserved_future_objects_do_not_allow_false_effect_or_cross_task_acceptance(self):
        with self.work() as s:
            evidence = s.record_evidence(self.p, self.v, task_id=self.t, source_id=self.source,
                                         conditions_version=1, mechanism='synthetic', subject='dev-check',
                                         result='recorded', configuration_version='1')
        with connect(self.db) as c:
            with transaction(c):
                c.execute("""INSERT INTO candidate_changes
                    (id, project_id, created_at, created_by, base_revision)
                    VALUES ('reserved-candidate', ?, 'synthetic-time', 'dev-owner', 0)""", (self.p,))
                c.execute("""INSERT INTO effective_changes
                    (id, project_id, created_at, created_by, candidate_id)
                    VALUES ('reserved-change', ?, 'synthetic-time', 'dev-owner', 'reserved-candidate')""", (self.p,))
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("UPDATE effective_changes SET phase = 'effective' WHERE id = 'reserved-change'")
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("""INSERT INTO acceptances
                    (id, project_id, created_at, created_by, task_id, version_id, effective_change_id, evidence_id)
                    VALUES ('wrong-task-acceptance', ?, 'synthetic-time', 'dev-owner', ?, ?, 'reserved-change', ?)""",
                          (self.p, self.t2, self.v, evidence['id']))
            self.assertEqual(c.execute('SELECT count(*) FROM acceptances').fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT revision FROM projects WHERE id = ?', (self.p,)).fetchone()[0], 0)

    def test_two_writers_create_distinct_immutable_version_numbers(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        ready = Barrier(2)

        def revision(content):
            ready.wait(timeout=5)
            with self.work() as s:
                return s.create_version(self.p, self.artifact, content, reason='synthetic concurrent revision')

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(revision, ('revision-A', 'revision-B')))
        self.assertEqual({r['ordinal'] for r in results}, {2, 3})
        with self.work(write=False) as s:
            self.assertEqual(s.get(self.p, 'artifact_versions', self.v)['content'], 'version one')
            self.assertEqual(len(s.records(self.p, 'artifact_versions')), 3)

    def test_duplicate_links_are_no_ops_but_invalid_refs_still_fail(self):
        with self.work() as s:
            for _ in range(3):
                s.link_task_session(self.p, self.t, self.session)
                s.link_attempt_session(self.p, self.attempt, self.session)
                s.link_artifact_task(self.p, self.artifact, self.t)
                s.link_version_task(self.p, self.v, self.t)
                s.link_version_source(self.p, self.v, self.source)
        with self.work(write=False) as s:
            for kind, count in (('task_sessions', 1), ('attempt_sessions', 1), ('artifact_tasks', 2),
                                ('artifact_version_tasks', 2), ('version_sources', 1)):
                self.assertEqual(len(s.records(self.p, kind)), count, kind)
        with self.assertRaises(AccessError):
            with self.work() as s:
                s.link_version_source(self.p, self.v, 'missing-source')

    def test_multistep_creation_rolls_back_every_entity_and_link(self):
        with self.work(write=False) as s:
            before = {kind: s.records(self.p, kind) for kind in ENTITY_TABLES + RELATION_TABLES}
        with self.assertRaises(AccessError):
            with self.work() as s:
                artifact = s.create_artifact(self.p, 'must disappear')
                source = s.create_source(self.p, reference='must-disappear')
                s.create_version(self.p, artifact['id'], 'temporary', reason='failure test',
                                 task_ids=(self.t,), source_ids=(source['id'], 'missing-source'))
        with self.work(write=False) as s:
            after = {kind: s.records(self.p, kind) for kind in ENTITY_TABLES + RELATION_TABLES}
            self.assertEqual(before, after)

    def test_caught_operation_failure_still_aborts_entire_unit(self):
        with self.assertRaises(TransactionAborted):
            with self.work() as s:
                s.create_task(self.p, 'must roll back')
                try:
                    s.link_task_session(self.p, self.t, self.qsession)
                except AccessError:
                    pass
        with self.work(write=False) as s:
            self.assertEqual(len(s.records(self.p, 'tasks')), 2)

    def test_read_only_unit_cannot_write(self):
        with self.assertRaises(TransactionAborted):
            with self.work(write=False) as s:
                s.create_project('forbidden')

    def test_external_values_are_parameters_and_unknown_table_is_rejected(self):
        value = "report'); DROP TABLE projects; --"
        with self.work() as s:
            task = s.create_task(self.p, value)
        with self.work(write=False) as s:
            self.assertEqual(s.get(self.p, 'tasks', task['id'])['title'], value)
        with self.assertRaises(ValueError):
            with self.work(write=False) as s:
                s.records(self.p, 'tasks; DROP TABLE projects')


if __name__ == '__main__':
    unittest.main()
