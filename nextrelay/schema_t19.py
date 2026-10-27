"""Schema 11: Thread facts reuse Session identities; old contributions stay unknown."""
OPERATIONS = ('thread.duty.set', 'thread.duty.suggest', 'thread.duty.confirm',
              'task.participation.set', 'task.lead.set', 'thread.succession.set')
T19_TABLES = ('thread_duties', 'task_participation', 'task_leads',
              'thread_successions', 'contribution_duties')


def migration(record, ref, *prior):
    source = next(s for s in prior[-1] if s.startswith('CREATE TABLE candidate_specs_v5 '))
    ddl = source.replace('candidate_specs_v5 ', 'candidate_specs_v11 ').replace(
        "'change.revoke'", "'change.revoke'," + ','.join(repr(op) for op in OPERATIONS))
    columns = 'id,project_id,created_at,created_by,candidate_id,operation,target_id,target_version_id,spec_json,fingerprint,risk'
    statements = [ddl, f'INSERT INTO candidate_specs_v11 ({columns}) SELECT {columns} FROM candidate_specs',
                  'DROP TABLE candidate_specs', 'ALTER TABLE candidate_specs_v11 RENAME TO candidate_specs']
    for version in prior:
        for sql in version:
            if sql.startswith('CREATE TRIGGER ') and ' ON candidate_specs ' in sql and sql not in statements:
                statements.append(sql)
    statements += [
        record('thread_duties', '''session_id TEXT NOT NULL, ordinal INTEGER NOT NULL CHECK(ordinal>0),
            status TEXT NOT NULL CHECK(status IN ('confirmed','unspecified','suggested')),
            main TEXT, auxiliary_json TEXT NOT NULL, basis TEXT NOT NULL CHECK(length(trim(basis))>0),
            suggestion_id TEXT, revision INTEGER NOT NULL CHECK(revision>0), change_id TEXT NOT NULL,
            CHECK((status='unspecified' AND main IS NULL AND auxiliary_json='[]') OR
                  (status<>'unspecified' AND main IS NOT NULL AND length(trim(main))>0)),
            UNIQUE(project_id,session_id,ordinal), UNIQUE(project_id,session_id,id), UNIQUE(project_id,change_id)''',
               (ref('session_id','sessions'), ref('change_id','applied_changes'),
                'FOREIGN KEY(project_id,session_id,suggestion_id) REFERENCES thread_duties(project_id,session_id,id)')),
        record('task_participation', '''task_id TEXT NOT NULL, session_id TEXT NOT NULL,
            active INTEGER NOT NULL CHECK(active IN (0,1)), description TEXT NOT NULL,
            basis TEXT NOT NULL CHECK(length(trim(basis))>0), revision INTEGER NOT NULL CHECK(revision>0),
            change_id TEXT NOT NULL, UNIQUE(project_id,task_id,session_id,revision), UNIQUE(project_id,change_id)''',
               (ref('task_id','tasks'),ref('session_id','sessions'),ref('change_id','applied_changes'))),
        record('task_leads', '''task_id TEXT NOT NULL, session_id TEXT,
            basis TEXT NOT NULL CHECK(length(trim(basis))>0), revision INTEGER NOT NULL CHECK(revision>0),
            change_id TEXT NOT NULL, UNIQUE(project_id,task_id,revision), UNIQUE(project_id,change_id)''',
               (ref('task_id','tasks'),ref('session_id','sessions'),ref('change_id','applied_changes'))),
        record('thread_successions', '''predecessor_id TEXT NOT NULL, successor_id TEXT NOT NULL,
            active INTEGER NOT NULL CHECK(active IN (0,1)), basis TEXT NOT NULL CHECK(length(trim(basis))>0),
            revision INTEGER NOT NULL CHECK(revision>0), change_id TEXT NOT NULL,
            CHECK(predecessor_id<>successor_id), UNIQUE(project_id,predecessor_id,successor_id,revision),
            UNIQUE(project_id,change_id)''',
               (ref('predecessor_id','sessions'),ref('successor_id','sessions'),ref('change_id','applied_changes'))),
        record('contribution_duties', '''session_id TEXT NOT NULL, duty_id TEXT, task_id TEXT,
            attempt_id TEXT, attribution_id TEXT, relation_key TEXT NOT NULL,
            UNIQUE(project_id,relation_key)''',
               (ref('session_id','sessions'),ref('task_id','tasks'),ref('attempt_id','attempts'),
                ref('attribution_id','source_attributions'),
                'FOREIGN KEY(project_id,session_id,duty_id) REFERENCES thread_duties(project_id,session_id,id)')),
    ]
    for table in T19_TABLES:
        for action in ('UPDATE','DELETE'):
            statements.append(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'append-only T19 record'); END")
    keys = {'thread_duties':('session_id',), 'task_participation':('task_id','session_id'),
            'task_leads':('task_id',), 'thread_successions':('predecessor_id','successor_id')}
    for table, fields in keys.items():
        same = ' AND '.join(f'b.{f}=a.{f}' for f in fields)
        ordering = 'b.ordinal>a.ordinal' if table=='thread_duties' else 'b.revision>a.revision'
        status = " AND a.status<>'suggested'" if table=='thread_duties' else ''
        other_status = " AND b.status<>'suggested'" if table=='thread_duties' else ''
        statements.append(f'''CREATE VIEW current_{table} AS SELECT a.* FROM {table} a
            WHERE NOT EXISTS(SELECT 1 FROM effect_corrections x WHERE x.project_id=a.project_id AND x.original_change_id=a.change_id){status}
            AND NOT EXISTS(SELECT 1 FROM {table} b WHERE b.project_id=a.project_id AND {same} AND {ordering}{other_status}
            AND NOT EXISTS(SELECT 1 FROM effect_corrections y WHERE y.project_id=b.project_id AND y.original_change_id=b.change_id))''')
    # These guards also protect compensations that reveal an older relation.
    invalid_lead = '''EXISTS(SELECT 1 FROM current_task_leads l WHERE l.project_id=NEW.project_id AND l.session_id IS NOT NULL
        AND NOT EXISTS(SELECT 1 FROM current_task_participation p WHERE p.project_id=l.project_id AND p.task_id=l.task_id AND p.session_id=l.session_id AND p.active=1))'''
    cycle = '''EXISTS(WITH RECURSIVE reach(a,b) AS (
        SELECT predecessor_id,successor_id FROM current_thread_successions WHERE project_id=NEW.project_id AND active=1
        UNION SELECT r.a,s.successor_id FROM reach r JOIN current_thread_successions s ON s.predecessor_id=r.b WHERE s.project_id=NEW.project_id AND s.active=1)
        SELECT 1 FROM reach WHERE a=b)'''
    for table, condition in (('task_leads',invalid_lead),('task_participation',invalid_lead),
                             ('thread_successions',cycle),('effect_corrections',f'{invalid_lead} OR {cycle}')):
        statements.append(f"CREATE TRIGGER {table}_t19_integrity AFTER INSERT ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT,'invalid Thread relationship'); END")
    return tuple(statements)
