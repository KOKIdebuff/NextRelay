"""T10 bounded GitHub snapshots, exact expansion grants, and T07 bridge."""
T10_TABLES=('github_snapshots','github_entries','github_scopes','github_requests','github_events','github_request_results')

def migration(record,ref):
    ddl=[
        record('github_snapshots', '''input_json TEXT NOT NULL, parent_id TEXT, source_id TEXT,
            repo TEXT, git_commit TEXT, root_tree TEXT, selection_path TEXT, link_kind TEXT,
            state TEXT NOT NULL DEFAULT 'new', code TEXT NOT NULL DEFAULT '', complete INTEGER NOT NULL DEFAULT 0,
            unknown_json TEXT NOT NULL DEFAULT '[]', metadata_bytes INTEGER NOT NULL DEFAULT 0,
            content_reserved INTEGER NOT NULL DEFAULT 0, metadata_reserved INTEGER NOT NULL DEFAULT 0,
            content_bytes INTEGER NOT NULL DEFAULT 0, content_reads INTEGER NOT NULL DEFAULT 0,
            request_count INTEGER NOT NULL DEFAULT 0, lease TEXT, lease_until REAL,
            CHECK(content_bytes>=0 AND content_reads>=0 AND metadata_bytes>=0 AND request_count>=0)''',
            (ref('parent_id','github_snapshots'),ref('source_id','sources'))),
        record('github_entries', '''snapshot_id TEXT NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL,
            mode TEXT NOT NULL, object_sha TEXT NOT NULL, byte_size INTEGER, metadata_status TEXT NOT NULL, children_status TEXT NOT NULL DEFAULT 'not-applicable',
            read_status TEXT NOT NULL DEFAULT 'not-selected', code TEXT NOT NULL DEFAULT '',
            attempts INTEGER NOT NULL DEFAULT 0, sha256 TEXT, item_id TEXT, input_id TEXT, UNIQUE(project_id,snapshot_id,path)''',
            (ref('snapshot_id','github_snapshots'),ref('item_id','ingest_items'),
             'FOREIGN KEY(project_id,item_id,input_id) REFERENCES ingest_inputs(project_id,item_id,id)')),
        record('github_scopes', '''snapshot_id TEXT NOT NULL, paths_json TEXT NOT NULL, fingerprint TEXT NOT NULL,
            expires REAL NOT NULL, approved_at REAL, kind TEXT NOT NULL''',(ref('snapshot_id','github_snapshots'),)),
        record('github_requests', '''snapshot_id TEXT NOT NULL, request_key TEXT NOT NULL, action TEXT NOT NULL,
            fingerprint TEXT NOT NULL, UNIQUE(created_by,request_key)''',(ref('snapshot_id','github_snapshots'),)),
        record('github_request_results', '''request_id TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('done','failed')),
            code TEXT NOT NULL, http_status INTEGER NOT NULL, error_kind TEXT NOT NULL, UNIQUE(project_id,request_id)''',
            (ref('request_id','github_requests'),)),
        record('github_events', '''snapshot_id TEXT NOT NULL, entry_id TEXT, state TEXT NOT NULL, code TEXT NOT NULL''',
            (ref('snapshot_id','github_snapshots'),ref('entry_id','github_entries'))),
    ]
    for t in T10_TABLES:
        ddl.append(f"CREATE TRIGGER {t}_identity BEFORE UPDATE OF id,project_id ON {t} BEGIN SELECT RAISE(ABORT,'immutable identity'); END")
    for t in ('github_requests','github_events','github_request_results'):
        for op in ('UPDATE','DELETE'):
            ddl.append(f"CREATE TRIGGER {t}_no_{op.lower()} BEFORE {op} ON {t} BEGIN SELECT RAISE(ABORT,'append-only T10'); END")
    ddl.append("""CREATE TRIGGER github_snapshot_pin BEFORE UPDATE OF input_json,parent_id,git_commit,repo,root_tree,selection_path,link_kind ON github_snapshots
        WHEN OLD.git_commit IS NOT NULL BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END""")
    ddl.append("""CREATE TRIGGER github_entry_pin BEFORE UPDATE OF snapshot_id,path,kind,mode,object_sha,byte_size ON github_entries
        BEGIN SELECT RAISE(ABORT,'immutable tree entry'); END""")
    ddl.append("""CREATE TRIGGER github_scope_pin BEFORE UPDATE OF snapshot_id,paths_json,fingerprint,expires,kind ON github_scopes
        BEGIN SELECT RAISE(ABORT,'immutable scope'); END""")
    ddl.append("""CREATE TRIGGER github_entry_input_pin BEFORE UPDATE OF item_id,input_id ON github_entries
        WHEN OLD.input_id IS NOT NULL AND (NEW.item_id IS NOT OLD.item_id OR NEW.input_id IS NOT OLD.input_id)
        BEGIN SELECT RAISE(ABORT,'immutable GitHub input'); END""")
    return tuple(ddl)
