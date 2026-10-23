"""Trusted in-process services with project ownership and fail-closed units.

Use a server-authenticated Principal. Base record methods preserve T03 storage;
T04 candidate/review/commit methods alone produce the formal read model.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
from uuid import uuid4

from .auth import AccessError, Principal
from .db import connect, transaction, verify_schema
from .schema import ENTITY_TABLES, RELATION_TABLES


class TransactionAborted(RuntimeError):
    pass


def operation(*, write=False):
    def decorate(function):
        @wraps(function)
        def call(self, *args, **kwargs):
            try:
                if self._failed:
                    raise TransactionAborted('Unit of work already failed')
                if write and not self._write:
                    raise TransactionAborted('Read-only unit of work')
                return function(self, *args, **kwargs)
            except BaseException:
                self._failed = True
                raise
        return call
    return decorate


def text_value(value, label, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError(f'{label} must be a string' + ('' if empty else ' with content'))
    return value


def external(namespace, external_id):
    if namespace is None and external_id is None:
        return {'namespace': None, 'external_id': None}
    return {'namespace': text_value(namespace, 'namespace'),
            'external_id': text_value(external_id, 'external_id')}


@contextmanager
def unit_of_work(database, principal, *, write=False):
    if not isinstance(principal, Principal) or not isinstance(principal.subject, str) or not principal.subject.strip():
        raise AccessError(401, 'authentication_required')
    with connect(database) as connection:
        if not write:
            connection.execute('PRAGMA query_only = ON')
        with transaction(connection, write=write):
            verify_schema(connection)
            store = Store(connection, principal, write)
            yield store
            if store._failed:
                raise TransactionAborted('A failed operation requires whole-unit rollback')


class Store:
    """Construct through unit_of_work; a Principal is trusted code input, never a client ID."""
    def __init__(self, connection, principal, write):
        self._connection = connection
        self._principal = principal
        self._write = write
        self._failed = False
        self._projection_cache = {}

    def _project(self, project_id):
        row = self._connection.execute(
            'SELECT * FROM projects WHERE id = ? AND owner_subject = ?',
            (project_id, self._principal.subject),
        ).fetchone()
        if row is None:
            raise AccessError(404, 'object_not_found')
        return dict(row)

    def _get(self, project_id, kind, object_id):
        self._project(project_id)
        if kind not in ENTITY_TABLES:
            raise ValueError('Unknown entity kind')
        row = self._connection.execute(
            f'SELECT * FROM {kind} WHERE project_id = ? AND id = ?', (project_id, object_id)
        ).fetchone()
        if row is None:
            raise AccessError(404, 'object_not_found')
        return dict(row)

    def _require_version(self, project_id, version_id):
        """Existence/ownership without loading an untrusted, potentially oversized body."""
        self._project(project_id)
        if self._connection.execute('SELECT 1 FROM artifact_versions WHERE project_id=? AND id=?',
                                    (project_id,version_id)).fetchone() is None:
            raise AccessError(404,'object_not_found')

    def _insert(self, project_id, table, **values):
        self._projection_cache.clear()
        self._project(project_id)
        if table not in ENTITY_TABLES:
            raise ValueError('Unknown entity table')
        values = dict(id=str(uuid4()), project_id=project_id,
                      created_at=datetime.now(timezone.utc).isoformat(),
                      created_by=self._principal.subject, **values)
        # Identifiers originate only in fixed code paths; all caller values are parameters.
        self._connection.execute(
            f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join('?' for _ in values)})",
            tuple(values.values()),
        )
        return self._get(project_id, table, values['id'])

    def _link(self, project_id, table, **values):
        self._projection_cache.clear()
        self._project(project_id)
        if table not in RELATION_TABLES:
            raise ValueError('Unknown relation kind')
        values = dict(project_id=project_id, **values, created_by=self._principal.subject)
        # Only the intended relation identity is a no-op; other constraints still fail.
        conflict = {
            'task_sessions': 'project_id, task_id, session_id',
            'attempt_sessions': 'project_id, attempt_id, session_id',
            'artifact_tasks': 'project_id, artifact_id, task_id',
            'artifact_version_tasks': 'project_id, task_id, version_id',
            'version_sources': 'project_id, version_id, source_id',
        }[table]
        self._connection.execute(
            f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join('?' for _ in values)}) ON CONFLICT({conflict}) DO NOTHING",
            tuple(values.values()),
        )

    @operation(write=True)
    def create_project(self, title):
        project_id = str(uuid4())
        self._connection.execute(
            'INSERT INTO projects(id, owner_subject, title, created_at) VALUES (?, ?, ?, ?)',
            (project_id, self._principal.subject, text_value(title, 'title'), datetime.now(timezone.utc).isoformat()),
        )
        from .lifecycle import Lifecycle
        Lifecycle(self).sync(project_id,0)
        return self._project(project_id)

    @operation()
    def project(self, project_id):
        return self._project(project_id)

    @operation()
    def projects(self):
        return [dict(row) for row in self._connection.execute(
            'SELECT * FROM projects WHERE owner_subject = ? ORDER BY created_at, id',
            (self._principal.subject,),
        )]

    @operation()
    def get(self, project_id, kind, object_id):
        return self._get(project_id, kind, object_id)

    @operation()
    def records(self, project_id, kind):
        self._project(project_id)
        if kind not in ENTITY_TABLES + RELATION_TABLES:
            raise ValueError('Unknown record kind')
        return [dict(row) for row in self._connection.execute(
            f'SELECT * FROM {kind} WHERE project_id = ?', (project_id,)
        )]

    @operation(write=True)
    def create_task(self, project_id, title, *, goal='', completion_conditions='', namespace=None, external_id=None):
        return self._insert(project_id, 'tasks', title=text_value(title, 'title'),
                            goal=text_value(goal, 'goal', empty=True),
                            completion_conditions=text_value(completion_conditions, 'completion_conditions', empty=True),
                            **external(namespace, external_id))

    @operation(write=True)
    def create_session(self, project_id, title, *, namespace=None, external_id=None):
        return self._insert(project_id, 'sessions', title=text_value(title, 'title'), **external(namespace, external_id))

    @operation(write=True)
    def create_attempt(self, project_id, task_id, title, *, namespace=None, external_id=None):
        self._get(project_id, 'tasks', task_id)
        return self._insert(project_id, 'attempts', task_id=task_id,
                            title=text_value(title, 'title'), **external(namespace, external_id))

    @operation(write=True)
    def link_task_session(self, project_id, task_id, session_id):
        self._get(project_id, 'tasks', task_id)
        self._get(project_id, 'sessions', session_id)
        self._link(project_id, 'task_sessions', task_id=task_id, session_id=session_id)

    @operation(write=True)
    def link_attempt_session(self, project_id, attempt_id, session_id):
        attempt = self._get(project_id, 'attempts', attempt_id)
        self.link_task_session(project_id, attempt['task_id'], session_id)
        self._link(project_id, 'attempt_sessions', task_id=attempt['task_id'], attempt_id=attempt_id, session_id=session_id)

    @operation(write=True)
    def create_source(self, project_id, *, namespace=None, external_id=None, reference=None,
                      fingerprint=None, storage_choice='reference-only', observed_at=None,
                      git_commit=None, source_path=None, availability='unknown', read_result='not-read', metadata=None):
        # References are inert strings. No file or network reads, original copying or cloud storage.
        if namespace is not None:
            text_value(namespace, 'namespace')
        if external_id is not None:
            text_value(namespace, 'namespace')
            text_value(external_id, 'external_id')
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError('metadata must be an object')
        source = self._insert(project_id, 'sources', namespace=namespace, external_id=external_id,
                              reference=reference, fingerprint=fingerprint, storage_choice=storage_choice,
                              observed_at=observed_at, git_commit=git_commit, source_path=source_path,
                              availability=availability, read_result=read_result,
                              metadata_json=json.dumps(metadata or {}, ensure_ascii=False, allow_nan=False))
        self.attribute_source(project_id, source['id'], reason='Saved with unresolved attribution')
        return source

    @operation(write=True)
    def attribute_source(self, project_id, source_id, *, task_id=None, session_id=None, attempt_id=None,
                         supersedes_id=None, reason):
        self._get(project_id, 'sources', source_id)
        for kind, value in (('tasks', task_id), ('sessions', session_id), ('attempts', attempt_id)):
            if value is not None:
                obj = self._get(project_id, kind, value)
                if kind == 'attempts' and obj['task_id'] != task_id:
                    raise ValueError('Attempt must belong to the specified task')
        if supersedes_id is not None:
            old = self._get(project_id, 'source_attributions', supersedes_id)
            if old['source_id'] != source_id:
                raise ValueError('Correction must preserve the original source')
        return self._insert(project_id, 'source_attributions', source_id=source_id, task_id=task_id,
                            session_id=session_id, attempt_id=attempt_id, supersedes_id=supersedes_id,
                            reason=text_value(reason, 'reason'))

    @operation()
    def attribution(self, project_id, source_id):
        self._get(project_id, 'sources', source_id)
        row = self._connection.execute('''
            SELECT a.* FROM source_attributions a WHERE a.project_id = ? AND a.source_id = ?
            AND NOT EXISTS (SELECT 1 FROM source_attributions b
                            WHERE b.project_id = a.project_id AND b.supersedes_id = a.id)
        ''', (project_id, source_id)).fetchone()
        result = dict(row)
        result['pending'] = [name for name in ('task_id', 'session_id', 'attempt_id') if result[name] is None]
        return result

    @operation(write=True)
    def create_artifact(self, project_id, title, *, namespace=None, external_id=None):
        return self._insert(project_id, 'artifacts', title=text_value(title, 'title'), **external(namespace, external_id))

    @operation(write=True)
    def link_artifact_task(self, project_id, artifact_id, task_id):
        self._get(project_id, 'artifacts', artifact_id)
        self._get(project_id, 'tasks', task_id)
        self._link(project_id, 'artifact_tasks', artifact_id=artifact_id, task_id=task_id)

    @operation(write=True)
    def link_version_task(self, project_id, version_id, task_id):
        version = self._get(project_id, 'artifact_versions', version_id)
        self.link_artifact_task(project_id, version['artifact_id'], task_id)
        self._link(project_id, 'artifact_version_tasks', artifact_id=version['artifact_id'], version_id=version_id, task_id=task_id)

    @operation(write=True)
    def link_version_source(self, project_id, version_id, source_id):
        self._get(project_id, 'artifact_versions', version_id)
        self._get(project_id, 'sources', source_id)
        self._link(project_id, 'version_sources', version_id=version_id, source_id=source_id)

    @operation(write=True)
    def create_version(self, project_id, artifact_id, content, *, reason, media_type='text/plain', task_ids=(), source_ids=()):
        self._get(project_id, 'artifacts', artifact_id)
        content = text_value(content, 'content', empty=True)
        ordinal = self._connection.execute(
            'SELECT COALESCE(MAX(ordinal), 0) + 1 FROM artifact_versions WHERE project_id = ? AND artifact_id = ?',
            (project_id, artifact_id),
        ).fetchone()[0]
        version = self._insert(project_id, 'artifact_versions', artifact_id=artifact_id, ordinal=ordinal,
                               content=content, content_sha256=hashlib.sha256(content.encode('utf-8')).hexdigest(),
                               media_type=text_value(media_type, 'media_type'), revision_reason=text_value(reason, 'reason'))
        for task_id in task_ids:
            self.link_version_task(project_id, version['id'], task_id)
        for source_id in source_ids:
            self.link_version_source(project_id, version['id'], source_id)
        return version

    @operation(write=True)
    def record_evidence(self, project_id, version_id, *, task_id=None, source_id=None, kind='pending',
                        mechanism, subject, result, configuration_version, conditions_version=None):
        self._require_version(project_id, version_id)
        if source_id is not None:
            self._get(project_id, 'sources', source_id)
        if task_id is not None:
            task = self._get(project_id, 'tasks', task_id)
            if conditions_version != task['conditions_version']:
                raise ValueError('Evidence must name the task conditions version')
        elif conditions_version is not None:
            raise ValueError('Project reference evidence has no task conditions')
        return self._insert(project_id, 'evidence', task_id=task_id, version_id=version_id, source_id=source_id,
                            kind=kind, mechanism=text_value(mechanism, 'mechanism'), subject=text_value(subject, 'subject'),
                            result=text_value(result, 'result'), conditions_version=conditions_version,
                            configuration_version=text_value(configuration_version, 'configuration_version'))

    @operation(write=True)
    def record_check(self, project_id, evidence_id, *, mechanism, subject, configuration_version, result, details=''):
        self._get(project_id, 'evidence', evidence_id)
        return self._insert(project_id, 'check_results', evidence_id=evidence_id,
                            mechanism=text_value(mechanism, 'mechanism'), subject=text_value(subject, 'subject'),
                            configuration_version=text_value(configuration_version, 'configuration_version'), result=result,
                            details=text_value(details, 'details', empty=True))

    @operation()
    def evidence_for(self, project_id, task_id, version_id):
        # An exact version and task are mandatory inputs. There is no inherited 'current pass'.
        self._get(project_id, 'artifact_versions', version_id)
        if task_id is not None:
            self._get(project_id, 'tasks', task_id)
        return [dict(row) for row in self._connection.execute('''
            SELECT e.*, c.id AS check_id, c.result AS check_result,
                   c.mechanism AS check_mechanism, c.configuration_version AS check_configuration_version
            FROM evidence e LEFT JOIN check_results c
              ON c.project_id = e.project_id AND c.evidence_id = e.id
            WHERE e.project_id = ? AND e.task_id IS ? AND e.version_id = ?
        ''', (project_id, task_id, version_id))]

    @operation()
    def version_provenance(self, project_id, version_id):
        self._get(project_id, 'artifact_versions', version_id)
        sources = [dict(row) for row in self._connection.execute(
            """SELECT s.* FROM sources s JOIN version_sources v
                 ON s.project_id = v.project_id AND s.id = v.source_id
                 WHERE v.project_id = ? AND v.version_id = ? ORDER BY s.id""",
            (project_id, version_id),
        )]
        return {'version_id': version_id, 'source_status': 'linked' if sources else 'pending',
                'sources': sources,
                'attributions': [self.attribution(project_id, source['id']) for source in sources],
                # Independent duplicate sources remain visible without silently
                # extending the frozen evidence basis of a formal version.
                'native_origins': [dict(r) for r in self._connection.execute('''
                    SELECT d.id AS document_id,d.locator_json,r.source_id,r.input_id,r.item_id
                    FROM native_documents d JOIN native_runs r ON r.project_id=d.project_id AND r.id=d.run_id
                    WHERE d.project_id=? AND d.version_id=?''',(project_id,version_id))]}


    @operation(write=True)
    def save_candidate(self, project_id, request):
        from .changes import Changes
        return Changes(self).save(project_id, request)

    @operation(write=True)
    def review_candidates(self, project_id, request):
        from .changes import Changes
        return Changes(self).review(project_id, request)

    @operation(write=True)
    def commit_candidates(self, project_id, request):
        from .changes import Changes
        return Changes(self).commit(project_id, request)

    @operation()
    def candidate(self, project_id, candidate_id):
        from .changes import Changes
        return Changes(self).spec(project_id, candidate_id)

    @operation()
    def formal_state(self, project_id):
        from .changes import Changes
        return Changes(self).state(project_id)

    @operation()
    def commit_result(self, project_id, request_key):
        from .changes import Changes
        result = Changes(self).result(project_id, request_key)
        if result is None:
            return None
        return json.loads(result['result_json'])

    @operation(write=True)
    def run_check(self, project_id, task_id, version_id, configuration):
        from .lifecycle import Lifecycle
        return Lifecycle(self).run(project_id,task_id,version_id,configuration)

    @operation(write=True)
    def accept_pre_authorized(self, project_id, request):
        from .lifecycle import Lifecycle
        return Lifecycle(self).auto_accept(project_id,request)

    @operation(write=True)
    def preview_reversal(self, project_id, original_change_id):
        from .reversals import Reversals
        return Reversals(self).preview(project_id, original_change_id)
