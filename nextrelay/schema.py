"""Versioned, additive SQLite DDL. No business approval is encoded in T03."""

V1 = ("""CREATE TABLE foundation_scopes (
    id TEXT PRIMARY KEY,
    owner_subject TEXT NOT NULL,
    label TEXT NOT NULL CHECK(label = 'synthetic-access-fixture')
) STRICT""",)


def record(name, columns, constraints=()):
    return f"""CREATE TABLE {name} (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        {columns},
        UNIQUE(project_id, id)
        {''.join(', ' + item for item in constraints)}
    ) STRICT"""


def ref(column, table):
    return f"FOREIGN KEY(project_id, {column}) REFERENCES {table}(project_id, id)"


EXTERNAL = """namespace TEXT, external_id TEXT,
    CHECK((namespace IS NULL AND external_id IS NULL) OR
          (length(namespace) > 0 AND namespace IS NOT NULL AND
           length(external_id) > 0 AND external_id IS NOT NULL)),
    UNIQUE(project_id, namespace, external_id)"""

V2 = ["""CREATE TABLE projects (
    id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
    owner_subject TEXT NOT NULL CHECK(length(owner_subject) > 0),
    title TEXT NOT NULL CHECK(length(title) > 0),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    created_at TEXT NOT NULL
) STRICT"""]
V2 += [
    record("tasks", f"title TEXT NOT NULL, goal TEXT NOT NULL, completion_conditions TEXT NOT NULL, conditions_version INTEGER NOT NULL DEFAULT 1 CHECK(conditions_version > 0), {EXTERNAL}", ("UNIQUE(project_id, id, conditions_version)",)),
    record("sessions", f"title TEXT NOT NULL, {EXTERNAL}"),
    record("attempts", f"task_id TEXT NOT NULL, title TEXT NOT NULL, {EXTERNAL}",
           (ref("task_id", "tasks"), "UNIQUE(project_id, task_id, id)")),
    record("sources", """namespace TEXT, external_id TEXT, reference TEXT,
        fingerprint TEXT, storage_choice TEXT NOT NULL CHECK(storage_choice IN ('reference-only','user-local','cloud-requested')),
        observed_at TEXT, git_commit TEXT, source_path TEXT,
        availability TEXT NOT NULL CHECK(availability IN ('unknown','available','unavailable')),
        read_result TEXT NOT NULL, metadata_json TEXT NOT NULL,
        CHECK(external_id IS NULL OR (namespace IS NOT NULL AND length(namespace) > 0)),
        CHECK(namespace IS NULL OR length(namespace) > 0)"""),
    record("artifacts", f"title TEXT NOT NULL, {EXTERNAL}"),
    record("artifact_versions", """artifact_id TEXT NOT NULL, ordinal INTEGER NOT NULL CHECK(ordinal > 0),
        content TEXT NOT NULL, content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
        media_type TEXT NOT NULL, revision_reason TEXT NOT NULL""",
           (ref("artifact_id", "artifacts"), "UNIQUE(project_id, artifact_id, ordinal)",
            "UNIQUE(project_id, artifact_id, id)")),
]

V2 += [
    """CREATE TABLE task_sessions (
        project_id TEXT NOT NULL, task_id TEXT NOT NULL, session_id TEXT NOT NULL,
        created_by TEXT NOT NULL, PRIMARY KEY(project_id, task_id, session_id),
        FOREIGN KEY(project_id, task_id) REFERENCES tasks(project_id, id),
        FOREIGN KEY(project_id, session_id) REFERENCES sessions(project_id, id)
    ) STRICT""",
    """CREATE TABLE attempt_sessions (
        project_id TEXT NOT NULL, task_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
        session_id TEXT NOT NULL, created_by TEXT NOT NULL,
        PRIMARY KEY(project_id, attempt_id, session_id),
        FOREIGN KEY(project_id, task_id, attempt_id) REFERENCES attempts(project_id, task_id, id),
        FOREIGN KEY(project_id, task_id, session_id) REFERENCES task_sessions(project_id, task_id, session_id)
    ) STRICT""",
    """CREATE TABLE artifact_tasks (
        project_id TEXT NOT NULL, artifact_id TEXT NOT NULL, task_id TEXT NOT NULL,
        created_by TEXT NOT NULL, PRIMARY KEY(project_id, artifact_id, task_id),
        FOREIGN KEY(project_id, artifact_id) REFERENCES artifacts(project_id, id),
        FOREIGN KEY(project_id, task_id) REFERENCES tasks(project_id, id)
    ) STRICT""",
    """CREATE TABLE artifact_version_tasks (
        project_id TEXT NOT NULL, artifact_id TEXT NOT NULL, version_id TEXT NOT NULL,
        task_id TEXT NOT NULL, created_by TEXT NOT NULL,
        PRIMARY KEY(project_id, task_id, version_id),
        FOREIGN KEY(project_id, artifact_id, task_id) REFERENCES artifact_tasks(project_id, artifact_id, task_id),
        FOREIGN KEY(project_id, artifact_id, version_id) REFERENCES artifact_versions(project_id, artifact_id, id)
    ) STRICT""",
    """CREATE TABLE version_sources (
        project_id TEXT NOT NULL, version_id TEXT NOT NULL, source_id TEXT NOT NULL,
        created_by TEXT NOT NULL, PRIMARY KEY(project_id, version_id, source_id),
        FOREIGN KEY(project_id, version_id) REFERENCES artifact_versions(project_id, id),
        FOREIGN KEY(project_id, source_id) REFERENCES sources(project_id, id)
    ) STRICT""",
    record("source_attributions", """source_id TEXT NOT NULL, task_id TEXT, session_id TEXT,
        attempt_id TEXT, supersedes_id TEXT, reason TEXT NOT NULL CHECK(length(reason) > 0),
        CHECK(attempt_id IS NULL OR task_id IS NOT NULL),
        UNIQUE(project_id, source_id, id), UNIQUE(project_id, supersedes_id),
        CHECK(supersedes_id IS NULL OR supersedes_id <> id)""",
           (ref("source_id", "sources"), ref("task_id", "tasks"), ref("session_id", "sessions"),
            "FOREIGN KEY(project_id, task_id, attempt_id) REFERENCES attempts(project_id, task_id, id)",
            "FOREIGN KEY(project_id, source_id, supersedes_id) REFERENCES source_attributions(project_id, source_id, id)")),
    record("evidence", """task_id TEXT, version_id TEXT NOT NULL, source_id TEXT,
        kind TEXT NOT NULL CHECK(kind IN ('claim','pending','observation','human-basis')),
        mechanism TEXT NOT NULL, subject TEXT NOT NULL, result TEXT NOT NULL,
        conditions_version INTEGER, configuration_version TEXT NOT NULL,
        CHECK(task_id IS NULL OR (conditions_version IS NOT NULL AND conditions_version > 0))""",
           ("UNIQUE(project_id, task_id, version_id, id)", ref("version_id", "artifact_versions"), ref("source_id", "sources"),
            "FOREIGN KEY(project_id, task_id, conditions_version) REFERENCES tasks(project_id, id, conditions_version)",
            "FOREIGN KEY(project_id, task_id, version_id) REFERENCES artifact_version_tasks(project_id, task_id, version_id)")),
    record("check_results", """evidence_id TEXT NOT NULL, mechanism TEXT NOT NULL,
        subject TEXT NOT NULL, configuration_version TEXT NOT NULL,
        result TEXT NOT NULL CHECK(result IN ('pass','fail','unknown','error')),
        details TEXT NOT NULL""", (ref("evidence_id", "evidence"),)),
    record("import_batches", """manifest_fingerprint TEXT, processing_version TEXT,
        phase TEXT NOT NULL DEFAULT 'reserved' CHECK(phase = 'reserved')"""),
    record("import_items", """batch_id TEXT NOT NULL, source_id TEXT,
        phase TEXT NOT NULL DEFAULT 'reserved' CHECK(phase = 'reserved'), reason TEXT NOT NULL""",
           (ref("batch_id", "import_batches"), ref("source_id", "sources"))),
    record("dependencies", """predecessor_id TEXT NOT NULL, successor_id TEXT NOT NULL,
        phase TEXT NOT NULL DEFAULT 'reserved' CHECK(phase = 'reserved'),
        CHECK(predecessor_id <> successor_id), UNIQUE(project_id, predecessor_id, successor_id)""",
           (ref("predecessor_id", "tasks"), ref("successor_id", "tasks"))),
    record("candidate_changes", """base_revision INTEGER NOT NULL CHECK(base_revision >= 0),
        task_id TEXT, version_id TEXT, source_id TEXT,
        phase TEXT NOT NULL DEFAULT 'reserved' CHECK(phase = 'reserved')""",
           (ref("task_id", "tasks"), ref("version_id", "artifact_versions"), ref("source_id", "sources"))),
    record("effective_changes", """candidate_id TEXT NOT NULL,
        phase TEXT NOT NULL DEFAULT 'reserved' CHECK(phase = 'reserved')""",
           (ref("candidate_id", "candidate_changes"),)),
    record("acceptances", """task_id TEXT NOT NULL, version_id TEXT NOT NULL,
        effective_change_id TEXT NOT NULL, evidence_id TEXT NOT NULL,
        phase TEXT NOT NULL DEFAULT 'reserved' CHECK(phase = 'reserved')""",
           ("FOREIGN KEY(project_id, task_id, version_id) REFERENCES artifact_version_tasks(project_id, task_id, version_id)",
            ref("effective_change_id", "effective_changes"),
            "FOREIGN KEY(project_id, task_id, version_id, evidence_id) REFERENCES evidence(project_id, task_id, version_id, id)")),
    record("document_confirmations", """version_id TEXT NOT NULL,
        phase TEXT NOT NULL DEFAULT 'reserved' CHECK(phase = 'reserved')""",
           (ref("version_id", "artifact_versions"),)),
]

ENTITY_TABLES = (
    'tasks', 'sessions', 'attempts', 'sources', 'artifacts', 'artifact_versions',
    'source_attributions', 'evidence', 'check_results', 'import_batches', 'import_items',
    'dependencies', 'candidate_changes', 'effective_changes', 'acceptances', 'document_confirmations',
)
RELATION_TABLES = ('task_sessions', 'attempt_sessions', 'artifact_tasks', 'artifact_version_tasks', 'version_sources')

# Identity/project moves require a future explicit migration, never an in-place reassignment.
for table in ENTITY_TABLES:
    V2.append(f"""CREATE TRIGGER {table}_identity BEFORE UPDATE OF id, project_id ON {table}
        BEGIN SELECT RAISE(ABORT, 'immutable identity'); END""")
V2.append("""CREATE TRIGGER projects_identity BEFORE UPDATE OF id, owner_subject ON projects
    BEGIN SELECT RAISE(ABORT, 'immutable ownership'); END""")
for table in ('artifact_versions', 'sources', 'source_attributions', 'evidence', 'check_results') + RELATION_TABLES:
    for operation in ('UPDATE', 'DELETE'):
        V2.append(f"""CREATE TRIGGER {table}_no_{operation.lower()} BEFORE {operation} ON {table}
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END""")
V2.append("CREATE UNIQUE INDEX source_attributions_root ON source_attributions(project_id, source_id) WHERE supersedes_id IS NULL")
V2 = tuple(V2)
from .schema_t04 import migration, T04_TABLES

V3 = migration(record, ref)

ENTITY_TABLES += T04_TABLES
from .schema_t05 import migration as t05_migration, T05_TABLES
V4 = t05_migration(record, ref, V2, V3)
ENTITY_TABLES += T05_TABLES
from .schema_t06 import migration as t06_migration, T06_TABLES
V5 = t06_migration(record, ref, V2, V3, V4)
ENTITY_TABLES += T06_TABLES
from .schema_t07 import migration as t07_migration, T07_TABLES
V6 = t07_migration(record, ref)
ENTITY_TABLES += T07_TABLES
from .schema_t11 import V7
from .schema_t08 import migration as t08_migration, T08_TABLES
V8 = t08_migration(record, ref)
ENTITY_TABLES += T08_TABLES
MIGRATIONS = {1: V1, 2: V2, 3: V3, 4: V4, 5: V5, 6: V6, 7: V7, 8: V8}
