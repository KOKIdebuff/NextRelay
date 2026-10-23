"""Append-only native extraction, provenance and correctable organization."""
T08_TABLES = ('native_runs', 'native_documents', 'native_relations', 'native_decisions', 'native_proposals')


def migration(record, ref):
    statements = [
        record('native_runs', '''item_id TEXT NOT NULL, input_id TEXT NOT NULL,
            source_id TEXT NOT NULL, processor TEXT NOT NULL, parsed_sha256 TEXT NOT NULL,
            UNIQUE(project_id,input_id,processor,parsed_sha256)''',
               (ref('item_id','ingest_items'), ref('input_id','ingest_inputs'), ref('source_id','sources'),
                'FOREIGN KEY(project_id,item_id,input_id) REFERENCES ingest_inputs(project_id,item_id,id)')),
        record('native_documents', '''run_id TEXT NOT NULL, position INTEGER NOT NULL,
            version_id TEXT NOT NULL, title TEXT NOT NULL, locator_json TEXT NOT NULL,
            findings_json TEXT NOT NULL, UNIQUE(project_id,run_id,position)''',
               (ref('run_id','native_runs'), ref('version_id','artifact_versions'))),
        record('native_relations', '''version_id TEXT NOT NULL, family_id TEXT NOT NULL,
            parent_version_id TEXT, relation TEXT NOT NULL CHECK(relation IN ('initial','revision','separate')),
            basis_json TEXT NOT NULL, supersedes_id TEXT, UNIQUE(project_id,supersedes_id)''',
               (ref('version_id','artifact_versions'), ref('family_id','artifacts'),
                ref('parent_version_id','artifact_versions'), ref('supersedes_id','native_relations'))),
        record('native_decisions', '''document_id TEXT NOT NULL, base_revision INTEGER NOT NULL,
            matches_json TEXT NOT NULL, basis TEXT NOT NULL, supersedes_id TEXT,
            UNIQUE(project_id,supersedes_id), UNIQUE(project_id,document_id,id)''',
               (ref('document_id','native_documents'),ref('supersedes_id','native_decisions'))),
        record('native_proposals', '''document_id TEXT NOT NULL, decision_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL, UNIQUE(project_id,document_id,decision_id,candidate_id)''',
               (ref('document_id','native_documents'),ref('decision_id','native_decisions'),
                'FOREIGN KEY(project_id,document_id,decision_id) REFERENCES native_decisions(project_id,document_id,id)',
                ref('candidate_id','candidate_changes'))),
        'CREATE UNIQUE INDEX native_relation_root ON native_relations(project_id,version_id) WHERE supersedes_id IS NULL',
        'CREATE UNIQUE INDEX native_decision_root ON native_decisions(project_id,document_id) WHERE supersedes_id IS NULL',
    ]
    for table, key in (('native_relations','version_id'),('native_decisions','document_id')):
        statements.append(f'''CREATE TRIGGER {table}_chain BEFORE INSERT ON {table}
            WHEN NEW.supersedes_id IS NOT NULL AND NOT EXISTS(
              SELECT 1 FROM {table} o WHERE o.project_id=NEW.project_id
              AND o.id=NEW.supersedes_id AND o.{key}=NEW.{key})
            BEGIN SELECT RAISE(ABORT,'invalid native correction chain'); END''')
    for table in T08_TABLES:
        for action in ('UPDATE','DELETE'):
            statements.append(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'append-only T08 record'); END")
    return tuple(statements)
