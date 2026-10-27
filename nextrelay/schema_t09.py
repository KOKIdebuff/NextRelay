"""T09 append-only consent, send claims and derived proposals; no raw payload storage."""
T09_TABLES = ('model_batches', 'model_jobs', 'model_events', 'model_results', 'model_proposals', 'model_requests')


def migration(record, ref):
    statements = [
        record('model_batches', """import_batch_id TEXT NOT NULL, request_key TEXT NOT NULL,
            selection_json TEXT NOT NULL, manifest_json TEXT NOT NULL, fingerprint TEXT NOT NULL,
            guard_sha256 TEXT NOT NULL, UNIQUE(project_id,request_key)""", (ref('import_batch_id','ingest_batches'),)),
        record('model_jobs', """batch_id TEXT NOT NULL, item_id TEXT NOT NULL, input_id TEXT NOT NULL,
            request_sha256 TEXT NOT NULL, UNIQUE(project_id,batch_id,item_id), UNIQUE(project_id,batch_id,id)""",
            (ref('batch_id','model_batches'), ref('item_id','ingest_items'),
             'FOREIGN KEY(project_id,item_id,input_id) REFERENCES ingest_inputs(project_id,item_id,id)')),
        record('model_events', """batch_id TEXT NOT NULL, job_id TEXT, sequence INTEGER NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('prepared','approved','denied','sending','failed','unknown','invalid','saved','stale')),
            code TEXT NOT NULL, metadata_json TEXT NOT NULL, UNIQUE(project_id,batch_id,sequence)""",
            (ref('batch_id','model_batches'),
             'FOREIGN KEY(project_id,batch_id,job_id) REFERENCES model_jobs(project_id,batch_id,id)')),
        record('model_results', """job_id TEXT NOT NULL, response_sha256 TEXT NOT NULL,
            provider_request_id TEXT, usage_json TEXT NOT NULL, UNIQUE(project_id,job_id)""", (ref('job_id','model_jobs'),)),
        record('model_proposals', """result_id TEXT NOT NULL, position INTEGER NOT NULL,
            core_sha256 TEXT NOT NULL, request_json TEXT NOT NULL, rationale TEXT NOT NULL, citations_json TEXT NOT NULL,
            UNIQUE(project_id,result_id,position)""", (ref('result_id','model_results'),)),
        record('model_requests', '''batch_id TEXT NOT NULL, request_key TEXT NOT NULL,
            route TEXT NOT NULL, fingerprint TEXT NOT NULL, UNIQUE(created_by,request_key)''', (ref('batch_id','model_batches'),)),
        'CREATE INDEX model_proposal_core ON model_proposals(project_id,core_sha256)',
    ]
    for table in T09_TABLES:
        for action in ('UPDATE','DELETE'):
            statements.append(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'append-only T09 record'); END")
    return tuple(statements)
