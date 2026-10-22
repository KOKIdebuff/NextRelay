"""Transactional v4 migration. Legacy reserved rows retain their identity and meaning."""
OPERATIONS = ('task.create','task.update','version.confirm','baseline.set','task.start',
              'task.submit','acceptance.human','acceptance.auto','check.authorize',
              'dependency.add','recheck.resolve')
T05_TABLES = ('task_events','check_authorizations','check_executions','review_reasons',
              'review_resolutions','recheck_processing','derived_snapshots','auto_requests')


def migration(record, ref, v2, v3):
    statements = []
    # None of these tables is a foreign-key parent. Copy every old column verbatim.
    replacements = {
        'candidate_specs': (v3, [("'baseline.set'", "'baseline.set','task.start','task.submit','acceptance.human','acceptance.auto','check.authorize','dependency.add','recheck.resolve'")]),
        'formal_task_states': (v3, [("CHECK(lifecycle='todo')", "CHECK(lifecycle IN ('todo','in-progress','awaiting-acceptance','accepted'))")]),
        'dependencies': (v2, [("CHECK(phase = 'reserved')", "CHECK(phase IN ('reserved','formal'))"),
                              ("CHECK(predecessor_id <> successor_id)", "change_id TEXT, CHECK(phase='reserved' OR change_id IS NOT NULL), FOREIGN KEY(project_id,change_id) REFERENCES applied_changes(project_id,id), CHECK(predecessor_id <> successor_id)")]),
        'acceptances': (v2, [("CHECK(phase = 'reserved')", "CHECK(phase IN ('reserved','formal'))"),
                             ("UNIQUE(project_id, id)", "mode TEXT CHECK(mode IN ('human','check')), conditions_version INTEGER, context_sha256 TEXT, submission_id TEXT, check_id TEXT, authorization_id TEXT, basis TEXT, CHECK(phase='reserved' OR (mode IS NOT NULL AND conditions_version IS NOT NULL AND context_sha256 IS NOT NULL AND submission_id IS NOT NULL AND basis IS NOT NULL)), UNIQUE(project_id,submission_id), FOREIGN KEY(project_id,submission_id) REFERENCES task_events(project_id,id), FOREIGN KEY(project_id,check_id) REFERENCES check_executions(project_id,id), FOREIGN KEY(project_id,authorization_id) REFERENCES check_authorizations(project_id,id), UNIQUE(project_id, id)")]),
    }
    for table, (source, edits) in replacements.items():
        ddl = next(s for s in source if s.startswith(f'CREATE TABLE {table} '))
        for old, new in edits:
            ddl = ddl.replace(old, new)
        statements.append(ddl.replace(f'CREATE TABLE {table} ', f'CREATE TABLE {table}_v4 '))
        # PRAGMA is evaluated by migration construction, not against a user database.
        import sqlite3
        c = sqlite3.connect(':memory:')
        try:
            c.execute(next(s for s in source if s.startswith(f'CREATE TABLE {table} ')))
            cols = ','.join(r[1] for r in c.execute(f'PRAGMA table_info({table})'))
        finally:
            c.close()
        statements += [f'INSERT INTO {table}_v4 ({cols}) SELECT {cols} FROM {table}',
                       f'DROP TABLE {table}', f'ALTER TABLE {table}_v4 RENAME TO {table}']
        statements.extend(s for s in source if s.startswith('CREATE TRIGGER ') and f' ON {table} ' in s)
    statements += [
        "CREATE TRIGGER tasks_conditions_no_update BEFORE UPDATE OF completion_conditions,conditions_version ON tasks BEGIN SELECT RAISE(ABORT,'immutable task conditions'); END",
        """CREATE TRIGGER version_sources_formal_guard BEFORE INSERT ON version_sources
            WHEN NOT EXISTS(SELECT 1 FROM version_sources s WHERE s.project_id=NEW.project_id AND s.version_id=NEW.version_id AND s.source_id=NEW.source_id)
            AND (EXISTS(SELECT 1 FROM confirmed_version_links l WHERE l.project_id=NEW.project_id AND l.version_id=NEW.version_id)
                 OR EXISTS(SELECT 1 FROM baseline_history b WHERE b.project_id=NEW.project_id AND b.version_id=NEW.version_id))
            BEGIN SELECT RAISE(ABORT,'formal provenance requires a new reviewed version'); END""",
        record('task_events', '''task_id TEXT NOT NULL, version_id TEXT, attempt_id TEXT, revision INTEGER NOT NULL CHECK(revision>0),
            event TEXT NOT NULL CHECK(event IN ('start','submit','accept','rework')), change_id TEXT NOT NULL,
            basis TEXT NOT NULL''', (ref('task_id','tasks'),ref('version_id','artifact_versions'),ref('change_id','applied_changes'),
                                   'FOREIGN KEY(project_id,task_id,attempt_id) REFERENCES attempts(project_id,task_id,id)')),
        record('check_authorizations', '''task_id TEXT NOT NULL, version_id TEXT NOT NULL, conditions_version INTEGER NOT NULL,
            config_json TEXT NOT NULL, config_sha256 TEXT NOT NULL CHECK(length(config_sha256)=64),
            context_sha256 TEXT NOT NULL CHECK(length(context_sha256)=64), expires_at TEXT NOT NULL,
            scope TEXT NOT NULL CHECK(scope='accept-exact-version'), basis TEXT NOT NULL,
            input_origin TEXT NOT NULL CHECK(input_origin IN ('local-user','synthetic-test')), change_id TEXT NOT NULL''',
            (ref('task_id','tasks'),ref('version_id','artifact_versions'),ref('change_id','applied_changes'))),
        record('check_executions', '''task_id TEXT NOT NULL, version_id TEXT NOT NULL, conditions_version INTEGER NOT NULL,
            config_json TEXT NOT NULL, config_sha256 TEXT NOT NULL CHECK(length(config_sha256)=64),
            context_sha256 TEXT NOT NULL CHECK(length(context_sha256)=64), revision INTEGER NOT NULL CHECK(revision>=0),
            mechanism TEXT NOT NULL CHECK(mechanism='builtin-v1'), result TEXT NOT NULL CHECK(result IN ('pass','fail','missing','error')),
            details TEXT NOT NULL, evidence_id TEXT NOT NULL, check_result_id TEXT NOT NULL''',
            (ref('task_id','tasks'),ref('version_id','artifact_versions'),ref('evidence_id','evidence'),ref('check_result_id','check_results'))),
        record('review_reasons', '''task_id TEXT NOT NULL, version_id TEXT, trigger_revision INTEGER NOT NULL CHECK(trigger_revision>0),
            trigger_change_id TEXT NOT NULL, reason TEXT NOT NULL, root_task_id TEXT,
            request_id TEXT, UNIQUE(project_id,task_id,trigger_change_id)''',
            (ref('task_id','tasks'),ref('version_id','artifact_versions'),ref('trigger_change_id','applied_changes'),ref('root_task_id','tasks'),ref('request_id','recheck_requests'))),
        record('review_resolutions', '''reason_id TEXT NOT NULL, task_id TEXT NOT NULL, version_id TEXT,
            decision TEXT NOT NULL CHECK(decision IN ('continue','needs-evidence','rework')),
            revision INTEGER NOT NULL CHECK(revision>0), change_id TEXT NOT NULL, basis TEXT NOT NULL, context_sha256 TEXT NOT NULL''',
            (ref('reason_id','review_reasons'),ref('task_id','tasks'),ref('version_id','artifact_versions'),ref('change_id','applied_changes'))),
        record('recheck_processing', '''request_id TEXT NOT NULL, target_revision INTEGER NOT NULL,
            processed_revision INTEGER NOT NULL, UNIQUE(project_id,request_id)''', (ref('request_id','recheck_requests'),)),
        record('derived_snapshots', '''revision INTEGER NOT NULL CHECK(revision>=0), state_json TEXT NOT NULL,
            UNIQUE(project_id,revision)'''),
        record('auto_requests', '''request_key TEXT NOT NULL, fingerprint TEXT NOT NULL, result_json TEXT NOT NULL,
            UNIQUE(project_id,request_key)'''),
    ]
    for table in T05_TABLES + ('dependencies','acceptances'):
        for action in ('UPDATE','DELETE'):
            statements.append(f"CREATE TRIGGER {table}_t05_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'append-only T05 record'); END")
    statements += [
        'CREATE INDEX dependency_successors ON dependencies(project_id,successor_id,phase)',
        'CREATE INDEX reasons_task ON review_reasons(project_id,task_id,trigger_revision)',
        'CREATE INDEX resolutions_reason ON review_resolutions(project_id,reason_id,revision)',
        'CREATE INDEX events_task ON task_events(project_id,task_id,revision)',
    ]
    # Referenced v4 tables must exist before copying even legacy rows with NULL refs.
    new_tables = [s for s in statements if any(s.startswith(f'CREATE TABLE {t} ') for t in T05_TABLES)]
    return tuple(new_tables + [s for s in statements if s not in new_tables])
