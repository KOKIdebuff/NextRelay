CREATE TABLE foundation_scopes (
    id TEXT PRIMARY KEY,
    owner_subject TEXT NOT NULL,
    label TEXT NOT NULL CHECK(label = 'synthetic-access-fixture')
) STRICT;
CREATE TABLE projects (
    id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
    owner_subject TEXT NOT NULL CHECK(length(owner_subject) > 0),
    title TEXT NOT NULL CHECK(length(title) > 0),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    created_at TEXT NOT NULL
) STRICT;
CREATE TABLE tasks (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        title TEXT NOT NULL, goal TEXT NOT NULL, completion_conditions TEXT NOT NULL, conditions_version INTEGER NOT NULL DEFAULT 1 CHECK(conditions_version > 0), namespace TEXT, external_id TEXT,
    CHECK((namespace IS NULL AND external_id IS NULL) OR
          (length(namespace) > 0 AND namespace IS NOT NULL AND
           length(external_id) > 0 AND external_id IS NOT NULL)),
    UNIQUE(project_id, namespace, external_id),
        UNIQUE(project_id, id)
        , UNIQUE(project_id, id, conditions_version)
    ) STRICT;
CREATE TABLE sessions (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        title TEXT NOT NULL, namespace TEXT, external_id TEXT,
    CHECK((namespace IS NULL AND external_id IS NULL) OR
          (length(namespace) > 0 AND namespace IS NOT NULL AND
           length(external_id) > 0 AND external_id IS NOT NULL)),
    UNIQUE(project_id, namespace, external_id),
        UNIQUE(project_id, id)
        
    ) STRICT;
CREATE TABLE attempts (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        task_id TEXT NOT NULL, title TEXT NOT NULL, namespace TEXT, external_id TEXT,
    CHECK((namespace IS NULL AND external_id IS NULL) OR
          (length(namespace) > 0 AND namespace IS NOT NULL AND
           length(external_id) > 0 AND external_id IS NOT NULL)),
    UNIQUE(project_id, namespace, external_id),
        UNIQUE(project_id, id)
        , FOREIGN KEY(project_id, task_id) REFERENCES tasks(project_id, id), UNIQUE(project_id, task_id, id)
    ) STRICT;
CREATE TABLE sources (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        namespace TEXT, external_id TEXT, reference TEXT,
        fingerprint TEXT, storage_choice TEXT NOT NULL CHECK(storage_choice IN ('reference-only','user-local','cloud-requested')),
        observed_at TEXT, git_commit TEXT, source_path TEXT,
        availability TEXT NOT NULL CHECK(availability IN ('unknown','available','unavailable')),
        read_result TEXT NOT NULL, metadata_json TEXT NOT NULL,
        CHECK(external_id IS NULL OR (namespace IS NOT NULL AND length(namespace) > 0)),
        CHECK(namespace IS NULL OR length(namespace) > 0),
        UNIQUE(project_id, id)
        
    ) STRICT;
CREATE TABLE artifacts (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        title TEXT NOT NULL, namespace TEXT, external_id TEXT,
    CHECK((namespace IS NULL AND external_id IS NULL) OR
          (length(namespace) > 0 AND namespace IS NOT NULL AND
           length(external_id) > 0 AND external_id IS NOT NULL)),
    UNIQUE(project_id, namespace, external_id),
        UNIQUE(project_id, id)
        
    ) STRICT;
CREATE TABLE artifact_versions (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        artifact_id TEXT NOT NULL, ordinal INTEGER NOT NULL CHECK(ordinal > 0),
        content TEXT NOT NULL, content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
        media_type TEXT NOT NULL, revision_reason TEXT NOT NULL,
        UNIQUE(project_id, id)
        , FOREIGN KEY(project_id, artifact_id) REFERENCES artifacts(project_id, id), UNIQUE(project_id, artifact_id, ordinal), UNIQUE(project_id, artifact_id, id)
    ) STRICT;
CREATE TABLE task_sessions (
        project_id TEXT NOT NULL, task_id TEXT NOT NULL, session_id TEXT NOT NULL,
        created_by TEXT NOT NULL, PRIMARY KEY(project_id, task_id, session_id),
        FOREIGN KEY(project_id, task_id) REFERENCES tasks(project_id, id),
        FOREIGN KEY(project_id, session_id) REFERENCES sessions(project_id, id)
    ) STRICT;
CREATE TABLE attempt_sessions (
        project_id TEXT NOT NULL, task_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
        session_id TEXT NOT NULL, created_by TEXT NOT NULL,
        PRIMARY KEY(project_id, attempt_id, session_id),
        FOREIGN KEY(project_id, task_id, attempt_id) REFERENCES attempts(project_id, task_id, id),
        FOREIGN KEY(project_id, task_id, session_id) REFERENCES task_sessions(project_id, task_id, session_id)
    ) STRICT;
CREATE TABLE artifact_tasks (
        project_id TEXT NOT NULL, artifact_id TEXT NOT NULL, task_id TEXT NOT NULL,
        created_by TEXT NOT NULL, PRIMARY KEY(project_id, artifact_id, task_id),
        FOREIGN KEY(project_id, artifact_id) REFERENCES artifacts(project_id, id),
        FOREIGN KEY(project_id, task_id) REFERENCES tasks(project_id, id)
    ) STRICT;
CREATE TABLE artifact_version_tasks (
        project_id TEXT NOT NULL, artifact_id TEXT NOT NULL, version_id TEXT NOT NULL,
        task_id TEXT NOT NULL, created_by TEXT NOT NULL,
        PRIMARY KEY(project_id, task_id, version_id),
        FOREIGN KEY(project_id, artifact_id, task_id) REFERENCES artifact_tasks(project_id, artifact_id, task_id),
        FOREIGN KEY(project_id, artifact_id, version_id) REFERENCES artifact_versions(project_id, artifact_id, id)
    ) STRICT;
CREATE TABLE version_sources (
        project_id TEXT NOT NULL, version_id TEXT NOT NULL, source_id TEXT NOT NULL,
        created_by TEXT NOT NULL, PRIMARY KEY(project_id, version_id, source_id),
        FOREIGN KEY(project_id, version_id) REFERENCES artifact_versions(project_id, id),
        FOREIGN KEY(project_id, source_id) REFERENCES sources(project_id, id)
    ) STRICT;
CREATE TABLE source_attributions (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        source_id TEXT NOT NULL, task_id TEXT, session_id TEXT,
        attempt_id TEXT, supersedes_id TEXT, reason TEXT NOT NULL CHECK(length(reason) > 0),
        CHECK(attempt_id IS NULL OR task_id IS NOT NULL),
        UNIQUE(project_id, source_id, id), UNIQUE(project_id, supersedes_id),
        CHECK(supersedes_id IS NULL OR supersedes_id <> id),
        UNIQUE(project_id, id)
        , FOREIGN KEY(project_id, source_id) REFERENCES sources(project_id, id), FOREIGN KEY(project_id, task_id) REFERENCES tasks(project_id, id), FOREIGN KEY(project_id, session_id) REFERENCES sessions(project_id, id), FOREIGN KEY(project_id, task_id, attempt_id) REFERENCES attempts(project_id, task_id, id), FOREIGN KEY(project_id, source_id, supersedes_id) REFERENCES source_attributions(project_id, source_id, id)
    ) STRICT;
CREATE TABLE evidence (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        task_id TEXT, version_id TEXT NOT NULL, source_id TEXT,
        kind TEXT NOT NULL CHECK(kind IN ('claim','pending','observation','human-basis')),
        mechanism TEXT NOT NULL, subject TEXT NOT NULL, result TEXT NOT NULL,
        conditions_version INTEGER, configuration_version TEXT NOT NULL,
        CHECK(task_id IS NULL OR (conditions_version IS NOT NULL AND conditions_version > 0)),
        UNIQUE(project_id, id)
        , UNIQUE(project_id, task_id, version_id, id), FOREIGN KEY(project_id, version_id) REFERENCES artifact_versions(project_id, id), FOREIGN KEY(project_id, source_id) REFERENCES sources(project_id, id), FOREIGN KEY(project_id, task_id, conditions_version) REFERENCES tasks(project_id, id, conditions_version), FOREIGN KEY(project_id, task_id, version_id) REFERENCES artifact_version_tasks(project_id, task_id, version_id)
    ) STRICT;
CREATE TABLE check_results (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        evidence_id TEXT NOT NULL, mechanism TEXT NOT NULL,
        subject TEXT NOT NULL, configuration_version TEXT NOT NULL,
        result TEXT NOT NULL CHECK(result IN ('pass','fail','unknown','error')),
        details TEXT NOT NULL,
        UNIQUE(project_id, id)
        , FOREIGN KEY(project_id, evidence_id) REFERENCES evidence(project_id, id)
    ) STRICT;
CREATE TABLE import_batches (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        manifest_fingerprint TEXT, processing_version TEXT,
        phase TEXT NOT NULL DEFAULT 'reserved' CHECK(phase = 'reserved'),
        UNIQUE(project_id, id)
        
    ) STRICT;
CREATE TABLE import_items (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        batch_id TEXT NOT NULL, source_id TEXT,
        phase TEXT NOT NULL DEFAULT 'reserved' CHECK(phase = 'reserved'), reason TEXT NOT NULL,
        UNIQUE(project_id, id)
        , FOREIGN KEY(project_id, batch_id) REFERENCES import_batches(project_id, id), FOREIGN KEY(project_id, source_id) REFERENCES sources(project_id, id)
    ) STRICT;
CREATE TABLE dependencies (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        predecessor_id TEXT NOT NULL, successor_id TEXT NOT NULL,
        phase TEXT NOT NULL DEFAULT 'reserved' CHECK(phase = 'reserved'),
        CHECK(predecessor_id <> successor_id), UNIQUE(project_id, predecessor_id, successor_id),
        UNIQUE(project_id, id)
        , FOREIGN KEY(project_id, predecessor_id) REFERENCES tasks(project_id, id), FOREIGN KEY(project_id, successor_id) REFERENCES tasks(project_id, id)
    ) STRICT;
CREATE TABLE candidate_changes (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        base_revision INTEGER NOT NULL CHECK(base_revision >= 0),
        task_id TEXT, version_id TEXT, source_id TEXT,
        phase TEXT NOT NULL DEFAULT 'reserved' CHECK(phase = 'reserved'),
        UNIQUE(project_id, id)
        , FOREIGN KEY(project_id, task_id) REFERENCES tasks(project_id, id), FOREIGN KEY(project_id, version_id) REFERENCES artifact_versions(project_id, id), FOREIGN KEY(project_id, source_id) REFERENCES sources(project_id, id)
    ) STRICT;
CREATE TABLE effective_changes (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        candidate_id TEXT NOT NULL,
        phase TEXT NOT NULL DEFAULT 'reserved' CHECK(phase = 'reserved'),
        UNIQUE(project_id, id)
        , FOREIGN KEY(project_id, candidate_id) REFERENCES candidate_changes(project_id, id)
    ) STRICT;
CREATE TABLE acceptances (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        task_id TEXT NOT NULL, version_id TEXT NOT NULL,
        effective_change_id TEXT NOT NULL, evidence_id TEXT NOT NULL,
        phase TEXT NOT NULL DEFAULT 'reserved' CHECK(phase = 'reserved'),
        UNIQUE(project_id, id)
        , FOREIGN KEY(project_id, task_id, version_id) REFERENCES artifact_version_tasks(project_id, task_id, version_id), FOREIGN KEY(project_id, effective_change_id) REFERENCES effective_changes(project_id, id), FOREIGN KEY(project_id, task_id, version_id, evidence_id) REFERENCES evidence(project_id, task_id, version_id, id)
    ) STRICT;
CREATE TABLE document_confirmations (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        version_id TEXT NOT NULL,
        phase TEXT NOT NULL DEFAULT 'reserved' CHECK(phase = 'reserved'),
        UNIQUE(project_id, id)
        , FOREIGN KEY(project_id, version_id) REFERENCES artifact_versions(project_id, id)
    ) STRICT;
CREATE TRIGGER tasks_identity BEFORE UPDATE OF id, project_id ON tasks
        BEGIN SELECT RAISE(ABORT, 'immutable identity'); END;
CREATE TRIGGER sessions_identity BEFORE UPDATE OF id, project_id ON sessions
        BEGIN SELECT RAISE(ABORT, 'immutable identity'); END;
CREATE TRIGGER attempts_identity BEFORE UPDATE OF id, project_id ON attempts
        BEGIN SELECT RAISE(ABORT, 'immutable identity'); END;
CREATE TRIGGER sources_identity BEFORE UPDATE OF id, project_id ON sources
        BEGIN SELECT RAISE(ABORT, 'immutable identity'); END;
CREATE TRIGGER artifacts_identity BEFORE UPDATE OF id, project_id ON artifacts
        BEGIN SELECT RAISE(ABORT, 'immutable identity'); END;
CREATE TRIGGER artifact_versions_identity BEFORE UPDATE OF id, project_id ON artifact_versions
        BEGIN SELECT RAISE(ABORT, 'immutable identity'); END;
CREATE TRIGGER source_attributions_identity BEFORE UPDATE OF id, project_id ON source_attributions
        BEGIN SELECT RAISE(ABORT, 'immutable identity'); END;
CREATE TRIGGER evidence_identity BEFORE UPDATE OF id, project_id ON evidence
        BEGIN SELECT RAISE(ABORT, 'immutable identity'); END;
CREATE TRIGGER check_results_identity BEFORE UPDATE OF id, project_id ON check_results
        BEGIN SELECT RAISE(ABORT, 'immutable identity'); END;
CREATE TRIGGER import_batches_identity BEFORE UPDATE OF id, project_id ON import_batches
        BEGIN SELECT RAISE(ABORT, 'immutable identity'); END;
CREATE TRIGGER import_items_identity BEFORE UPDATE OF id, project_id ON import_items
        BEGIN SELECT RAISE(ABORT, 'immutable identity'); END;
CREATE TRIGGER dependencies_identity BEFORE UPDATE OF id, project_id ON dependencies
        BEGIN SELECT RAISE(ABORT, 'immutable identity'); END;
CREATE TRIGGER candidate_changes_identity BEFORE UPDATE OF id, project_id ON candidate_changes
        BEGIN SELECT RAISE(ABORT, 'immutable identity'); END;
CREATE TRIGGER effective_changes_identity BEFORE UPDATE OF id, project_id ON effective_changes
        BEGIN SELECT RAISE(ABORT, 'immutable identity'); END;
CREATE TRIGGER acceptances_identity BEFORE UPDATE OF id, project_id ON acceptances
        BEGIN SELECT RAISE(ABORT, 'immutable identity'); END;
CREATE TRIGGER document_confirmations_identity BEFORE UPDATE OF id, project_id ON document_confirmations
        BEGIN SELECT RAISE(ABORT, 'immutable identity'); END;
CREATE TRIGGER projects_identity BEFORE UPDATE OF id, owner_subject ON projects
    BEGIN SELECT RAISE(ABORT, 'immutable ownership'); END;
CREATE TRIGGER artifact_versions_no_update BEFORE UPDATE ON artifact_versions
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE TRIGGER artifact_versions_no_delete BEFORE DELETE ON artifact_versions
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE TRIGGER sources_no_update BEFORE UPDATE ON sources
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE TRIGGER sources_no_delete BEFORE DELETE ON sources
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE TRIGGER source_attributions_no_update BEFORE UPDATE ON source_attributions
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE TRIGGER source_attributions_no_delete BEFORE DELETE ON source_attributions
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE TRIGGER evidence_no_update BEFORE UPDATE ON evidence
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE TRIGGER evidence_no_delete BEFORE DELETE ON evidence
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE TRIGGER check_results_no_update BEFORE UPDATE ON check_results
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE TRIGGER check_results_no_delete BEFORE DELETE ON check_results
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE TRIGGER task_sessions_no_update BEFORE UPDATE ON task_sessions
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE TRIGGER task_sessions_no_delete BEFORE DELETE ON task_sessions
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE TRIGGER attempt_sessions_no_update BEFORE UPDATE ON attempt_sessions
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE TRIGGER attempt_sessions_no_delete BEFORE DELETE ON attempt_sessions
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE TRIGGER artifact_tasks_no_update BEFORE UPDATE ON artifact_tasks
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE TRIGGER artifact_tasks_no_delete BEFORE DELETE ON artifact_tasks
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE TRIGGER artifact_version_tasks_no_update BEFORE UPDATE ON artifact_version_tasks
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE TRIGGER artifact_version_tasks_no_delete BEFORE DELETE ON artifact_version_tasks
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE TRIGGER version_sources_no_update BEFORE UPDATE ON version_sources
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE TRIGGER version_sources_no_delete BEFORE DELETE ON version_sources
            BEGIN SELECT RAISE(ABORT, 'append-only T03 record'); END;
CREATE UNIQUE INDEX source_attributions_root ON source_attributions(project_id, source_id) WHERE supersedes_id IS NULL;
PRAGMA user_version = 2;
