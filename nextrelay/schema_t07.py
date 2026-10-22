"""T07 append-only imports; old reserved identities are deliberately untouched."""
T07_TABLES = ('ingest_batches', 'ingest_items', 'ingest_inputs', 'ingest_attempts',
              'ingest_retry_plans', 'ingest_requests', 'original_links')


def migration(record, ref):
    statements = [
        record('ingest_batches', '''request_key TEXT NOT NULL, manifest_json TEXT NOT NULL,
            fingerprint TEXT NOT NULL, processing_version TEXT NOT NULL,
            UNIQUE(project_id, request_key)'''),
        record('ingest_items', '''batch_id TEXT NOT NULL, position INTEGER NOT NULL,
            UNIQUE(project_id,batch_id,position), UNIQUE(project_id,batch_id,id)''',
               (ref('batch_id', 'ingest_batches'),)),
        record('ingest_inputs', '''item_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
            selection_json TEXT NOT NULL, fingerprint TEXT, byte_size INTEGER,
            preflight_error TEXT, UNIQUE(project_id,item_id,ordinal),
            UNIQUE(project_id,item_id,id)''', (ref('item_id', 'ingest_items'),)),
        record('ingest_attempts', '''item_id TEXT NOT NULL, input_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL, source_id TEXT,
            save_status TEXT NOT NULL CHECK(save_status IN ('saved','failed','rejected')),
            parse_status TEXT NOT NULL CHECK(parse_status IN ('parsed','failed','unsupported','not-requested','not-run')),
            failure_stage TEXT, reason TEXT, result_sha256 TEXT, processor TEXT NOT NULL,
            UNIQUE(project_id,item_id,ordinal), UNIQUE(project_id,item_id,id)''',
               (ref('item_id', 'ingest_items'), ref('source_id', 'sources'),
                'FOREIGN KEY(project_id,item_id,input_id) REFERENCES ingest_inputs(project_id,item_id,id)')),
        record('ingest_retry_plans', '''item_id TEXT NOT NULL, input_id TEXT NOT NULL,
            request_key TEXT NOT NULL, request_json TEXT NOT NULL, UNIQUE(project_id,item_id,request_key)''',
               ('FOREIGN KEY(project_id,item_id,input_id) REFERENCES ingest_inputs(project_id,item_id,id)',)),
        record('ingest_requests', '''item_id TEXT NOT NULL, request_key TEXT NOT NULL,
            request_json TEXT NOT NULL, attempt_id TEXT NOT NULL,
            UNIQUE(project_id,item_id,request_key)''',
               ('FOREIGN KEY(project_id,item_id,attempt_id) REFERENCES ingest_attempts(project_id,item_id,id)',)),
        record('original_links', '''input_id TEXT NOT NULL, location TEXT NOT NULL,
            result_location TEXT, supersedes_id TEXT, UNIQUE(project_id,supersedes_id)''',
               (ref('input_id', 'ingest_inputs'), ref('supersedes_id', 'original_links'))),
    ]
    statements += [
        'CREATE INDEX ingest_items_batch ON ingest_items(project_id,batch_id,position)',
        'CREATE INDEX ingest_attempts_item ON ingest_attempts(project_id,item_id,ordinal)',
        'CREATE INDEX original_links_input ON original_links(project_id,input_id,created_at)',
        'CREATE UNIQUE INDEX original_links_root ON original_links(project_id,input_id) WHERE supersedes_id IS NULL',
        '''CREATE TRIGGER original_links_chain BEFORE INSERT ON original_links
            WHEN NEW.supersedes_id IS NOT NULL AND NOT EXISTS(
                SELECT 1 FROM original_links o WHERE o.project_id=NEW.project_id
                AND o.id=NEW.supersedes_id AND o.input_id=NEW.input_id)
            BEGIN SELECT RAISE(ABORT,'invalid original chain'); END''',
    ]
    for table in T07_TABLES:
        for action in ('UPDATE','DELETE'):
            statements.append(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'append-only T07 record'); END")
    return tuple(statements)
