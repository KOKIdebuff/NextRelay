"""Version 5: append-only compensations and immutable impact previews."""
T06_TABLES = ('reversal_previews', 'effect_corrections')


def migration(record, ref, v2, v3, v4):
    import sqlite3
    statements = ['DROP TRIGGER version_sources_formal_guard']
    # Preserve every historical row and all protections while relaxing only the
    # obsolete lifetime uniqueness of relations (current uniqueness is checked
    # inside BEGIN IMMEDIATE against effective rows).
    for table, source, edits in (
        ('candidate_specs', v4, [("'recheck.resolve'", "'recheck.resolve','change.revoke'")]),
        ('dependencies', v4, [('UNIQUE(project_id, predecessor_id, successor_id)', 'UNIQUE(project_id, change_id)')]),
        ('confirmed_version_links', v3, [('UNIQUE(project_id,task_id,version_id)', 'UNIQUE(project_id,change_id)')]),
        ('acceptances', v4, [(', UNIQUE(project_id,submission_id)', '')]),
    ):
        # v4 uses a temporary name in its CREATE statements.
        ddl = next(s for s in source if s.startswith(f'CREATE TABLE {table} ') or s.startswith(f'CREATE TABLE {table}_v4 '))
        ddl = ddl.replace(f'CREATE TABLE {table}_v4 ', f'CREATE TABLE {table} ')
        old = ddl
        for before, after in edits:
            assert before in ddl, (table, before)
            ddl = ddl.replace(before, after)
        c = sqlite3.connect(':memory:')
        try:
            c.execute(old)
            columns = ','.join(r[1] for r in c.execute(f'PRAGMA table_info({table})'))
        finally:
            c.close()
        statements.extend([ddl.replace(f'CREATE TABLE {table} ', f'CREATE TABLE {table}_v5 '),
                           f'INSERT INTO {table}_v5 ({columns}) SELECT {columns} FROM {table}',
                           f'DROP TABLE {table}', f'ALTER TABLE {table}_v5 RENAME TO {table}'])
        # Recreate the exact original triggers and indexes, including v2 identity guards.
        for s in v2 + v3 + v4:
            if (s.startswith('CREATE TRIGGER ') and f' ON {table} ' in s) or (s.startswith('CREATE INDEX ') and f' ON {table}(' in s):
                if s not in statements:
                    statements.append(s)
    # Reserved T03 rows may legally share an effective identity and NULL
    # submission. Constrain real formal effects without rejecting old data.
    statements.append("CREATE UNIQUE INDEX acceptance_formal_effect ON acceptances(project_id,effective_change_id) WHERE phase='formal'")
    statements.append(next(s for s in v4 if s.startswith('CREATE TRIGGER version_sources_formal_guard ')))
    statements.extend([
        record('reversal_previews', '''original_change_id TEXT NOT NULL, base_revision INTEGER NOT NULL CHECK(base_revision>=0),
            preview_json TEXT NOT NULL, fingerprint TEXT NOT NULL CHECK(length(fingerprint)=64)''',
               (ref('original_change_id', 'applied_changes'),)),
        record('effect_corrections', '''original_change_id TEXT NOT NULL, change_id TEXT NOT NULL,
            preview_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
            UNIQUE(project_id,original_change_id), UNIQUE(project_id,change_id)''',
               (ref('original_change_id', 'applied_changes'), ref('change_id', 'applied_changes'), ref('preview_id', 'reversal_previews'))),
    ])
    for table in T06_TABLES:
        for action in ('UPDATE', 'DELETE'):
            statements.append(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'append-only T06 record'); END")
    return tuple(statements)
