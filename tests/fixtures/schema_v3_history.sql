-- Synthetic v3 file generated with local historical abf96bc T04 services, no real approval.
BEGIN TRANSACTION;
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
CREATE TABLE applied_changes (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        effective_change_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
            review_id TEXT NOT NULL, commit_id TEXT NOT NULL, effect_json TEXT NOT NULL,
            UNIQUE(project_id,candidate_id), UNIQUE(project_id,effective_change_id),
        UNIQUE(project_id, id)
        , FOREIGN KEY(project_id, effective_change_id) REFERENCES effective_changes(project_id, id), FOREIGN KEY(project_id, candidate_id) REFERENCES candidate_changes(project_id, id), FOREIGN KEY(project_id, review_id) REFERENCES change_reviews(project_id, id), FOREIGN KEY(project_id, commit_id) REFERENCES change_commits(project_id, id), FOREIGN KEY(project_id,candidate_id,review_id) REFERENCES change_reviews(project_id,candidate_id,id)
    ) STRICT;
INSERT INTO "applied_changes" VALUES('4bac5b1b-a374-44d0-855d-324952757b06','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.119430+00:00','dev-v3-fixture','d7f3e1d3-a390-40b0-9166-2d7ebf1b7c79','4f0bcfa7-297f-418a-b791-888763adf7f1','f00fadc3-47dd-4fcf-9cdd-a59f299474df','16f1f359-2715-452a-8b65-01496b8ba81d','{"base_revision":0,"conflicts":[],"evidence_ids":[],"impact":"Create one formal todo task; no acceptance or dependency release.","operation":"task.create","payload":{"completion_conditions":"Synthetic condition","goal":"Historical goal","title":"Synthetic old task"},"preconditions":{"attributions":[{"attempt_id":null,"created_at":"2026-10-20T05:46:42.097066+00:00","created_by":"dev-v3-fixture","id":"7277816b-bd8b-4ee8-8143-e37c9e04d782","pending":["task_id","session_id","attempt_id"],"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","reason":"Saved with unresolved attribution","session_id":null,"source_id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","supersedes_id":null,"task_id":null}],"evidence":[],"sources":[{"availability":"unavailable","created_at":"2026-10-20T05:46:42.096460+00:00","created_by":"dev-v3-fixture","external_id":null,"fingerprint":null,"git_commit":null,"id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","metadata_json":"{}","namespace":null,"observed_at":null,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","read_result":"synthetic missing original","reference":"synthetic://v3-fixture","source_path":null,"storage_choice":"reference-only"}]},"risk":"ordinary","source_ids":["64c47e3e-c496-4474-8ae1-4aa64401f77b"],"target_id":"8c31da2a-d666-4eff-a736-e38324040c21","target_version_id":null}');
INSERT INTO "applied_changes" VALUES('b943363b-47ec-4b62-804d-bb3fa2503249','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.138543+00:00','dev-v3-fixture','b5ae9f36-0fe4-464a-bf18-95d22f2345fc','860a2651-0af9-471d-80be-80c4ee3db3d5','d7fe3bda-8bf8-485a-beba-707d103bb2a6','15212e57-31b7-410a-9371-f9cbea6752a1','{"base_revision":1,"conflicts":[],"evidence_ids":[],"impact":"Confirm this exact task/version relation; no acceptance or authority inheritance.","operation":"version.confirm","payload":{},"preconditions":{"attributions":[{"attempt_id":null,"created_at":"2026-10-20T05:46:42.097066+00:00","created_by":"dev-v3-fixture","id":"7277816b-bd8b-4ee8-8143-e37c9e04d782","pending":["task_id","session_id","attempt_id"],"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","reason":"Saved with unresolved attribution","session_id":null,"source_id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","supersedes_id":null,"task_id":null}],"evidence":[],"sources":[{"availability":"unavailable","created_at":"2026-10-20T05:46:42.096460+00:00","created_by":"dev-v3-fixture","external_id":null,"fingerprint":null,"git_commit":null,"id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","metadata_json":"{}","namespace":null,"observed_at":null,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","read_result":"synthetic missing original","reference":"synthetic://v3-fixture","source_path":null,"storage_choice":"reference-only"}],"task":{"change_id":"4bac5b1b-a374-44d0-855d-324952757b06","completion_conditions":"Synthetic condition","created_at":"2026-10-20T05:46:42.120973+00:00","created_by":"dev-v3-fixture","goal":"Historical goal","id":"45e03b14-422c-4d57-bd3c-d42610dfbee2","lifecycle":"todo","project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","revision":1,"task_id":"8c31da2a-d666-4eff-a736-e38324040c21","title":"Synthetic old task"},"task_record":{"completion_conditions":"Synthetic condition","conditions_version":1,"created_at":"2026-10-20T05:46:42.120099+00:00","created_by":"dev-v3-fixture","external_id":null,"goal":"Historical goal","id":"8c31da2a-d666-4eff-a736-e38324040c21","namespace":null,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","title":"Synthetic old task"},"version":{"artifact_id":"155ec3e1-2a27-41c6-b76d-253eabf1cfc8","content":"# Requirements\nSynthetic baseline only","content_sha256":"b087a2583238b7b622985a6b3974dbf3a56e800c789624dd84f8fd1965b55749","created_at":"2026-10-20T05:46:42.097938+00:00","created_by":"dev-v3-fixture","id":"88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9","media_type":"text/plain","ordinal":1,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","revision_reason":"synthetic-test"},"version_sources":[{"created_by":"dev-v3-fixture","project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","source_id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","version_id":"88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9"}]},"risk":"ordinary","source_ids":["64c47e3e-c496-4474-8ae1-4aa64401f77b"],"target_id":"8c31da2a-d666-4eff-a736-e38324040c21","target_version_id":"88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9"}');
INSERT INTO "applied_changes" VALUES('e9ffab95-12d6-463e-adfa-81dcd704afaa','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.173419+00:00','dev-v3-fixture','ccd6ace2-2bfc-4da1-9b9b-e37b1e8ac813','d062c84b-a18c-48da-b9fb-c531bd7c7882','698c691a-5695-47a2-860c-94666d69328c','bc93620c-278a-4df0-8173-a2f951ccef99','{"base_revision":2,"conflicts":[],"evidence_ids":[],"impact":"Switch the single requirements baseline to this exact version and record a pending recheck; readiness is not evaluated.","operation":"baseline.set","payload":{},"preconditions":{"attributions":[{"attempt_id":null,"created_at":"2026-10-20T05:46:42.097066+00:00","created_by":"dev-v3-fixture","id":"7277816b-bd8b-4ee8-8143-e37c9e04d782","pending":["task_id","session_id","attempt_id"],"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","reason":"Saved with unresolved attribution","session_id":null,"source_id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","supersedes_id":null,"task_id":null}],"baseline":null,"evidence":[],"sources":[{"availability":"unavailable","created_at":"2026-10-20T05:46:42.096460+00:00","created_by":"dev-v3-fixture","external_id":null,"fingerprint":null,"git_commit":null,"id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","metadata_json":"{}","namespace":null,"observed_at":null,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","read_result":"synthetic missing original","reference":"synthetic://v3-fixture","source_path":null,"storage_choice":"reference-only"}],"version":{"artifact_id":"155ec3e1-2a27-41c6-b76d-253eabf1cfc8","content":"# Requirements\nSynthetic baseline only","content_sha256":"b087a2583238b7b622985a6b3974dbf3a56e800c789624dd84f8fd1965b55749","created_at":"2026-10-20T05:46:42.097938+00:00","created_by":"dev-v3-fixture","id":"88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9","media_type":"text/plain","ordinal":1,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","revision_reason":"synthetic-test"},"version_sources":[{"created_by":"dev-v3-fixture","project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","source_id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","version_id":"88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9"}]},"risk":"high","source_ids":["64c47e3e-c496-4474-8ae1-4aa64401f77b"],"target_id":"155ec3e1-2a27-41c6-b76d-253eabf1cfc8","target_version_id":"88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9"}');
INSERT INTO "applied_changes" VALUES('2f65378a-e12e-4316-9646-c19a51988b06','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.191327+00:00','dev-v3-fixture','400b6abf-9120-4c2a-bde7-a10791b62a49','199fb911-b0a3-4e4d-b59c-cf840b33598f','456508e4-591e-4b9b-9b59-c4433fe3ecdd','26bcb09a-90b6-411c-9a03-10a767248312','{"base_revision":3,"conflicts":[],"evidence_ids":[],"impact":"Append a formal title/goal snapshot and a pending recheck; preserve history.","operation":"task.update","payload":{"goal":"Updated historical goal"},"preconditions":{"attributions":[{"attempt_id":null,"created_at":"2026-10-20T05:46:42.097066+00:00","created_by":"dev-v3-fixture","id":"7277816b-bd8b-4ee8-8143-e37c9e04d782","pending":["task_id","session_id","attempt_id"],"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","reason":"Saved with unresolved attribution","session_id":null,"source_id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","supersedes_id":null,"task_id":null}],"evidence":[],"sources":[{"availability":"unavailable","created_at":"2026-10-20T05:46:42.096460+00:00","created_by":"dev-v3-fixture","external_id":null,"fingerprint":null,"git_commit":null,"id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","metadata_json":"{}","namespace":null,"observed_at":null,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","read_result":"synthetic missing original","reference":"synthetic://v3-fixture","source_path":null,"storage_choice":"reference-only"}],"task":{"change_id":"4bac5b1b-a374-44d0-855d-324952757b06","completion_conditions":"Synthetic condition","created_at":"2026-10-20T05:46:42.120973+00:00","created_by":"dev-v3-fixture","goal":"Historical goal","id":"45e03b14-422c-4d57-bd3c-d42610dfbee2","lifecycle":"todo","project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","revision":1,"task_id":"8c31da2a-d666-4eff-a736-e38324040c21","title":"Synthetic old task"},"task_record":{"completion_conditions":"Synthetic condition","conditions_version":1,"created_at":"2026-10-20T05:46:42.120099+00:00","created_by":"dev-v3-fixture","external_id":null,"goal":"Historical goal","id":"8c31da2a-d666-4eff-a736-e38324040c21","namespace":null,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","title":"Synthetic old task"}},"risk":"ordinary","source_ids":["64c47e3e-c496-4474-8ae1-4aa64401f77b"],"target_id":"8c31da2a-d666-4eff-a736-e38324040c21","target_version_id":null}');
INSERT INTO "applied_changes" VALUES('5f0590e2-c0e1-4a8f-8af2-3fb6878561be','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.209312+00:00','dev-v3-fixture','f2be4dfc-24e8-4e34-85fe-6c2024ab4676','eb8212da-fcb1-4cea-a3c6-ae7c48787c80','372b981b-76c8-40c7-803f-4cbf7ced2e40','92efc1f3-6378-4211-bd6f-458e0bfba59f','{"base_revision":4,"conflicts":[],"evidence_ids":[],"impact":"Switch the single requirements baseline to this exact version and record a pending recheck; readiness is not evaluated.","operation":"baseline.set","payload":{},"preconditions":{"attributions":[{"attempt_id":null,"created_at":"2026-10-20T05:46:42.097066+00:00","created_by":"dev-v3-fixture","id":"7277816b-bd8b-4ee8-8143-e37c9e04d782","pending":["task_id","session_id","attempt_id"],"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","reason":"Saved with unresolved attribution","session_id":null,"source_id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","supersedes_id":null,"task_id":null}],"baseline":{"change_id":"e9ffab95-12d6-463e-adfa-81dcd704afaa","created_at":"2026-10-20T05:46:42.173717+00:00","created_by":"dev-v3-fixture","id":"03c27083-7c70-4cbe-9790-24af393ba884","previous_version_id":null,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","revision":3,"version_id":"88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9"},"evidence":[],"sources":[{"availability":"unavailable","created_at":"2026-10-20T05:46:42.096460+00:00","created_by":"dev-v3-fixture","external_id":null,"fingerprint":null,"git_commit":null,"id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","metadata_json":"{}","namespace":null,"observed_at":null,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","read_result":"synthetic missing original","reference":"synthetic://v3-fixture","source_path":null,"storage_choice":"reference-only"}],"version":{"artifact_id":"155ec3e1-2a27-41c6-b76d-253eabf1cfc8","content":"# Requirements\nChanged synthetic baseline","content_sha256":"ef4e1fc451ac7593f7554afe2a3d12e9480c73dee7857c661d1ce54edb36f81b","created_at":"2026-10-20T05:46:42.098454+00:00","created_by":"dev-v3-fixture","id":"b7e22b59-3ad0-46b0-8f3b-3322890e6ecd","media_type":"text/plain","ordinal":2,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","revision_reason":"synthetic-test"},"version_sources":[{"created_by":"dev-v3-fixture","project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","source_id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","version_id":"b7e22b59-3ad0-46b0-8f3b-3322890e6ecd"}]},"risk":"high","source_ids":["64c47e3e-c496-4474-8ae1-4aa64401f77b"],"target_id":"155ec3e1-2a27-41c6-b76d-253eabf1cfc8","target_version_id":"b7e22b59-3ad0-46b0-8f3b-3322890e6ecd"}');
CREATE TABLE artifact_tasks (
        project_id TEXT NOT NULL, artifact_id TEXT NOT NULL, task_id TEXT NOT NULL,
        created_by TEXT NOT NULL, PRIMARY KEY(project_id, artifact_id, task_id),
        FOREIGN KEY(project_id, artifact_id) REFERENCES artifacts(project_id, id),
        FOREIGN KEY(project_id, task_id) REFERENCES tasks(project_id, id)
    ) STRICT;
INSERT INTO "artifact_tasks" VALUES('55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','155ec3e1-2a27-41c6-b76d-253eabf1cfc8','8c31da2a-d666-4eff-a736-e38324040c21','dev-v3-fixture');
CREATE TABLE artifact_version_tasks (
        project_id TEXT NOT NULL, artifact_id TEXT NOT NULL, version_id TEXT NOT NULL,
        task_id TEXT NOT NULL, created_by TEXT NOT NULL,
        PRIMARY KEY(project_id, task_id, version_id),
        FOREIGN KEY(project_id, artifact_id, task_id) REFERENCES artifact_tasks(project_id, artifact_id, task_id),
        FOREIGN KEY(project_id, artifact_id, version_id) REFERENCES artifact_versions(project_id, artifact_id, id)
    ) STRICT;
INSERT INTO "artifact_version_tasks" VALUES('55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','155ec3e1-2a27-41c6-b76d-253eabf1cfc8','88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9','8c31da2a-d666-4eff-a736-e38324040c21','dev-v3-fixture');
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
INSERT INTO "artifact_versions" VALUES('88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.097938+00:00','dev-v3-fixture','155ec3e1-2a27-41c6-b76d-253eabf1cfc8',1,'# Requirements
Synthetic baseline only','b087a2583238b7b622985a6b3974dbf3a56e800c789624dd84f8fd1965b55749','text/plain','synthetic-test');
INSERT INTO "artifact_versions" VALUES('b7e22b59-3ad0-46b0-8f3b-3322890e6ecd','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.098454+00:00','dev-v3-fixture','155ec3e1-2a27-41c6-b76d-253eabf1cfc8',2,'# Requirements
Changed synthetic baseline','ef4e1fc451ac7593f7554afe2a3d12e9480c73dee7857c661d1ce54edb36f81b','text/plain','synthetic-test');
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
INSERT INTO "artifacts" VALUES('155ec3e1-2a27-41c6-b76d-253eabf1cfc8','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.097504+00:00','dev-v3-fixture','synthetic requirements',NULL,NULL);
CREATE TABLE attempt_sessions (
        project_id TEXT NOT NULL, task_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
        session_id TEXT NOT NULL, created_by TEXT NOT NULL,
        PRIMARY KEY(project_id, attempt_id, session_id),
        FOREIGN KEY(project_id, task_id, attempt_id) REFERENCES attempts(project_id, task_id, id),
        FOREIGN KEY(project_id, task_id, session_id) REFERENCES task_sessions(project_id, task_id, session_id)
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
CREATE TABLE baseline_history (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        version_id TEXT NOT NULL, previous_version_id TEXT,
            revision INTEGER NOT NULL CHECK(revision>0), change_id TEXT NOT NULL,
            UNIQUE(project_id,revision), UNIQUE(project_id,change_id),
        UNIQUE(project_id, id)
        , FOREIGN KEY(project_id, version_id) REFERENCES artifact_versions(project_id, id), FOREIGN KEY(project_id, previous_version_id) REFERENCES artifact_versions(project_id, id), FOREIGN KEY(project_id, change_id) REFERENCES applied_changes(project_id, id)
    ) STRICT;
INSERT INTO "baseline_history" VALUES('03c27083-7c70-4cbe-9790-24af393ba884','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.173717+00:00','dev-v3-fixture','88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9',NULL,3,'e9ffab95-12d6-463e-adfa-81dcd704afaa');
INSERT INTO "baseline_history" VALUES('466ae239-e657-42f5-af0f-0f40910f2752','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.209701+00:00','dev-v3-fixture','b7e22b59-3ad0-46b0-8f3b-3322890e6ecd','88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9',5,'5f0590e2-c0e1-4a8f-8af2-3fb6878561be');
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
INSERT INTO "candidate_changes" VALUES('4f0bcfa7-297f-418a-b791-888763adf7f1','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.113885+00:00','dev-v3-fixture',0,NULL,NULL,'64c47e3e-c496-4474-8ae1-4aa64401f77b','reserved');
INSERT INTO "candidate_changes" VALUES('860a2651-0af9-471d-80be-80c4ee3db3d5','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.132118+00:00','dev-v3-fixture',1,'8c31da2a-d666-4eff-a736-e38324040c21','88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9','64c47e3e-c496-4474-8ae1-4aa64401f77b','reserved');
INSERT INTO "candidate_changes" VALUES('d062c84b-a18c-48da-b9fb-c531bd7c7882','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.166218+00:00','dev-v3-fixture',2,NULL,'88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9','64c47e3e-c496-4474-8ae1-4aa64401f77b','reserved');
INSERT INTO "candidate_changes" VALUES('199fb911-b0a3-4e4d-b59c-cf840b33598f','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.186499+00:00','dev-v3-fixture',3,'8c31da2a-d666-4eff-a736-e38324040c21',NULL,'64c47e3e-c496-4474-8ae1-4aa64401f77b','reserved');
INSERT INTO "candidate_changes" VALUES('eb8212da-fcb1-4cea-a3c6-ae7c48787c80','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.204393+00:00','dev-v3-fixture',4,NULL,'b7e22b59-3ad0-46b0-8f3b-3322890e6ecd','64c47e3e-c496-4474-8ae1-4aa64401f77b','reserved');
CREATE TABLE candidate_specs (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        candidate_id TEXT NOT NULL, operation TEXT NOT NULL CHECK(operation IN ('task.create','task.update','version.confirm','baseline.set')),
            target_id TEXT NOT NULL CHECK(length(target_id)>0), target_version_id TEXT, spec_json TEXT NOT NULL,
            fingerprint TEXT NOT NULL CHECK(length(fingerprint)=64),
            risk TEXT NOT NULL CHECK(risk IN ('ordinary','high','conflict')),
            UNIQUE(project_id,candidate_id),
        UNIQUE(project_id, id)
        , FOREIGN KEY(project_id, candidate_id) REFERENCES candidate_changes(project_id, id), FOREIGN KEY(project_id, target_version_id) REFERENCES artifact_versions(project_id, id)
    ) STRICT;
INSERT INTO "candidate_specs" VALUES('ee2b3a98-483c-4241-bf73-c561d535854b','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.116417+00:00','dev-v3-fixture','4f0bcfa7-297f-418a-b791-888763adf7f1','task.create','8c31da2a-d666-4eff-a736-e38324040c21',NULL,'{"base_revision":0,"conflicts":[],"evidence_ids":[],"impact":"Create one formal todo task; no acceptance or dependency release.","operation":"task.create","payload":{"completion_conditions":"Synthetic condition","goal":"Historical goal","title":"Synthetic old task"},"preconditions":{"attributions":[{"attempt_id":null,"created_at":"2026-10-20T05:46:42.097066+00:00","created_by":"dev-v3-fixture","id":"7277816b-bd8b-4ee8-8143-e37c9e04d782","pending":["task_id","session_id","attempt_id"],"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","reason":"Saved with unresolved attribution","session_id":null,"source_id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","supersedes_id":null,"task_id":null}],"evidence":[],"sources":[{"availability":"unavailable","created_at":"2026-10-20T05:46:42.096460+00:00","created_by":"dev-v3-fixture","external_id":null,"fingerprint":null,"git_commit":null,"id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","metadata_json":"{}","namespace":null,"observed_at":null,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","read_result":"synthetic missing original","reference":"synthetic://v3-fixture","source_path":null,"storage_choice":"reference-only"}]},"risk":"ordinary","source_ids":["64c47e3e-c496-4474-8ae1-4aa64401f77b"],"target_id":"8c31da2a-d666-4eff-a736-e38324040c21","target_version_id":null}','af5d18d6658f3522ebc24a661dc90f539530343509bcdb665128f0354fd07274','ordinary');
INSERT INTO "candidate_specs" VALUES('0ad7de47-9ac3-42b9-a554-271f12fd0c05','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.133531+00:00','dev-v3-fixture','860a2651-0af9-471d-80be-80c4ee3db3d5','version.confirm','8c31da2a-d666-4eff-a736-e38324040c21','88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9','{"base_revision":1,"conflicts":[],"evidence_ids":[],"impact":"Confirm this exact task/version relation; no acceptance or authority inheritance.","operation":"version.confirm","payload":{},"preconditions":{"attributions":[{"attempt_id":null,"created_at":"2026-10-20T05:46:42.097066+00:00","created_by":"dev-v3-fixture","id":"7277816b-bd8b-4ee8-8143-e37c9e04d782","pending":["task_id","session_id","attempt_id"],"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","reason":"Saved with unresolved attribution","session_id":null,"source_id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","supersedes_id":null,"task_id":null}],"evidence":[],"sources":[{"availability":"unavailable","created_at":"2026-10-20T05:46:42.096460+00:00","created_by":"dev-v3-fixture","external_id":null,"fingerprint":null,"git_commit":null,"id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","metadata_json":"{}","namespace":null,"observed_at":null,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","read_result":"synthetic missing original","reference":"synthetic://v3-fixture","source_path":null,"storage_choice":"reference-only"}],"task":{"change_id":"4bac5b1b-a374-44d0-855d-324952757b06","completion_conditions":"Synthetic condition","created_at":"2026-10-20T05:46:42.120973+00:00","created_by":"dev-v3-fixture","goal":"Historical goal","id":"45e03b14-422c-4d57-bd3c-d42610dfbee2","lifecycle":"todo","project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","revision":1,"task_id":"8c31da2a-d666-4eff-a736-e38324040c21","title":"Synthetic old task"},"task_record":{"completion_conditions":"Synthetic condition","conditions_version":1,"created_at":"2026-10-20T05:46:42.120099+00:00","created_by":"dev-v3-fixture","external_id":null,"goal":"Historical goal","id":"8c31da2a-d666-4eff-a736-e38324040c21","namespace":null,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","title":"Synthetic old task"},"version":{"artifact_id":"155ec3e1-2a27-41c6-b76d-253eabf1cfc8","content":"# Requirements\nSynthetic baseline only","content_sha256":"b087a2583238b7b622985a6b3974dbf3a56e800c789624dd84f8fd1965b55749","created_at":"2026-10-20T05:46:42.097938+00:00","created_by":"dev-v3-fixture","id":"88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9","media_type":"text/plain","ordinal":1,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","revision_reason":"synthetic-test"},"version_sources":[{"created_by":"dev-v3-fixture","project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","source_id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","version_id":"88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9"}]},"risk":"ordinary","source_ids":["64c47e3e-c496-4474-8ae1-4aa64401f77b"],"target_id":"8c31da2a-d666-4eff-a736-e38324040c21","target_version_id":"88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9"}','f1f64afaf9ae535373c844323cc00fcf0f2525f4cf202dff4a850f97b64963c3','ordinary');
INSERT INTO "candidate_specs" VALUES('ddf5548e-74d4-4782-a61f-172f7260d734','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.169096+00:00','dev-v3-fixture','d062c84b-a18c-48da-b9fb-c531bd7c7882','baseline.set','155ec3e1-2a27-41c6-b76d-253eabf1cfc8','88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9','{"base_revision":2,"conflicts":[],"evidence_ids":[],"impact":"Switch the single requirements baseline to this exact version and record a pending recheck; readiness is not evaluated.","operation":"baseline.set","payload":{},"preconditions":{"attributions":[{"attempt_id":null,"created_at":"2026-10-20T05:46:42.097066+00:00","created_by":"dev-v3-fixture","id":"7277816b-bd8b-4ee8-8143-e37c9e04d782","pending":["task_id","session_id","attempt_id"],"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","reason":"Saved with unresolved attribution","session_id":null,"source_id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","supersedes_id":null,"task_id":null}],"baseline":null,"evidence":[],"sources":[{"availability":"unavailable","created_at":"2026-10-20T05:46:42.096460+00:00","created_by":"dev-v3-fixture","external_id":null,"fingerprint":null,"git_commit":null,"id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","metadata_json":"{}","namespace":null,"observed_at":null,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","read_result":"synthetic missing original","reference":"synthetic://v3-fixture","source_path":null,"storage_choice":"reference-only"}],"version":{"artifact_id":"155ec3e1-2a27-41c6-b76d-253eabf1cfc8","content":"# Requirements\nSynthetic baseline only","content_sha256":"b087a2583238b7b622985a6b3974dbf3a56e800c789624dd84f8fd1965b55749","created_at":"2026-10-20T05:46:42.097938+00:00","created_by":"dev-v3-fixture","id":"88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9","media_type":"text/plain","ordinal":1,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","revision_reason":"synthetic-test"},"version_sources":[{"created_by":"dev-v3-fixture","project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","source_id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","version_id":"88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9"}]},"risk":"high","source_ids":["64c47e3e-c496-4474-8ae1-4aa64401f77b"],"target_id":"155ec3e1-2a27-41c6-b76d-253eabf1cfc8","target_version_id":"88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9"}','07efa390e2493771c17a55f6a6fec94df0b127d9649728a2043cfef1889f3365','high');
INSERT INTO "candidate_specs" VALUES('6fdb3fd8-b971-412f-8a86-371b2020815a','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.187925+00:00','dev-v3-fixture','199fb911-b0a3-4e4d-b59c-cf840b33598f','task.update','8c31da2a-d666-4eff-a736-e38324040c21',NULL,'{"base_revision":3,"conflicts":[],"evidence_ids":[],"impact":"Append a formal title/goal snapshot and a pending recheck; preserve history.","operation":"task.update","payload":{"goal":"Updated historical goal"},"preconditions":{"attributions":[{"attempt_id":null,"created_at":"2026-10-20T05:46:42.097066+00:00","created_by":"dev-v3-fixture","id":"7277816b-bd8b-4ee8-8143-e37c9e04d782","pending":["task_id","session_id","attempt_id"],"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","reason":"Saved with unresolved attribution","session_id":null,"source_id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","supersedes_id":null,"task_id":null}],"evidence":[],"sources":[{"availability":"unavailable","created_at":"2026-10-20T05:46:42.096460+00:00","created_by":"dev-v3-fixture","external_id":null,"fingerprint":null,"git_commit":null,"id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","metadata_json":"{}","namespace":null,"observed_at":null,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","read_result":"synthetic missing original","reference":"synthetic://v3-fixture","source_path":null,"storage_choice":"reference-only"}],"task":{"change_id":"4bac5b1b-a374-44d0-855d-324952757b06","completion_conditions":"Synthetic condition","created_at":"2026-10-20T05:46:42.120973+00:00","created_by":"dev-v3-fixture","goal":"Historical goal","id":"45e03b14-422c-4d57-bd3c-d42610dfbee2","lifecycle":"todo","project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","revision":1,"task_id":"8c31da2a-d666-4eff-a736-e38324040c21","title":"Synthetic old task"},"task_record":{"completion_conditions":"Synthetic condition","conditions_version":1,"created_at":"2026-10-20T05:46:42.120099+00:00","created_by":"dev-v3-fixture","external_id":null,"goal":"Historical goal","id":"8c31da2a-d666-4eff-a736-e38324040c21","namespace":null,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","title":"Synthetic old task"}},"risk":"ordinary","source_ids":["64c47e3e-c496-4474-8ae1-4aa64401f77b"],"target_id":"8c31da2a-d666-4eff-a736-e38324040c21","target_version_id":null}','1a1e3cd425fcb8df43ea1ba334cb4b3b2633cfd02f565af715599e28835dedae','ordinary');
INSERT INTO "candidate_specs" VALUES('90e8aa3e-ccd1-4904-89e8-dec0c506744b','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.206352+00:00','dev-v3-fixture','eb8212da-fcb1-4cea-a3c6-ae7c48787c80','baseline.set','155ec3e1-2a27-41c6-b76d-253eabf1cfc8','b7e22b59-3ad0-46b0-8f3b-3322890e6ecd','{"base_revision":4,"conflicts":[],"evidence_ids":[],"impact":"Switch the single requirements baseline to this exact version and record a pending recheck; readiness is not evaluated.","operation":"baseline.set","payload":{},"preconditions":{"attributions":[{"attempt_id":null,"created_at":"2026-10-20T05:46:42.097066+00:00","created_by":"dev-v3-fixture","id":"7277816b-bd8b-4ee8-8143-e37c9e04d782","pending":["task_id","session_id","attempt_id"],"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","reason":"Saved with unresolved attribution","session_id":null,"source_id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","supersedes_id":null,"task_id":null}],"baseline":{"change_id":"e9ffab95-12d6-463e-adfa-81dcd704afaa","created_at":"2026-10-20T05:46:42.173717+00:00","created_by":"dev-v3-fixture","id":"03c27083-7c70-4cbe-9790-24af393ba884","previous_version_id":null,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","revision":3,"version_id":"88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9"},"evidence":[],"sources":[{"availability":"unavailable","created_at":"2026-10-20T05:46:42.096460+00:00","created_by":"dev-v3-fixture","external_id":null,"fingerprint":null,"git_commit":null,"id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","metadata_json":"{}","namespace":null,"observed_at":null,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","read_result":"synthetic missing original","reference":"synthetic://v3-fixture","source_path":null,"storage_choice":"reference-only"}],"version":{"artifact_id":"155ec3e1-2a27-41c6-b76d-253eabf1cfc8","content":"# Requirements\nChanged synthetic baseline","content_sha256":"ef4e1fc451ac7593f7554afe2a3d12e9480c73dee7857c661d1ce54edb36f81b","created_at":"2026-10-20T05:46:42.098454+00:00","created_by":"dev-v3-fixture","id":"b7e22b59-3ad0-46b0-8f3b-3322890e6ecd","media_type":"text/plain","ordinal":2,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","revision_reason":"synthetic-test"},"version_sources":[{"created_by":"dev-v3-fixture","project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","source_id":"64c47e3e-c496-4474-8ae1-4aa64401f77b","version_id":"b7e22b59-3ad0-46b0-8f3b-3322890e6ecd"}]},"risk":"high","source_ids":["64c47e3e-c496-4474-8ae1-4aa64401f77b"],"target_id":"155ec3e1-2a27-41c6-b76d-253eabf1cfc8","target_version_id":"b7e22b59-3ad0-46b0-8f3b-3322890e6ecd"}','1c0dae9fdc2dabc2326b66c95c43bd293e5cc07f02148c7fd7bda0b198c691a5','high');
CREATE TABLE candidate_supersessions (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        old_candidate_id TEXT NOT NULL, new_candidate_id TEXT NOT NULL,
            CHECK(old_candidate_id <> new_candidate_id), UNIQUE(project_id,old_candidate_id),
        UNIQUE(project_id, id)
        , FOREIGN KEY(project_id, old_candidate_id) REFERENCES candidate_changes(project_id, id), FOREIGN KEY(project_id, new_candidate_id) REFERENCES candidate_changes(project_id, id)
    ) STRICT;
CREATE TABLE change_commits (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        action TEXT NOT NULL CHECK(action='commit-candidates'),
            request_key TEXT NOT NULL CHECK(length(request_key)>0),
            request_fingerprint TEXT NOT NULL CHECK(length(request_fingerprint)=64),
            request_json TEXT NOT NULL, result_json TEXT NOT NULL,
            base_revision INTEGER NOT NULL CHECK(base_revision>=0),
            revision INTEGER NOT NULL CHECK(revision=base_revision+1),
            UNIQUE(project_id,action,request_key), UNIQUE(project_id,revision),
        UNIQUE(project_id, id)

    ) STRICT;
INSERT INTO "change_commits" VALUES('16f1f359-2715-452a-8b65-01496b8ba81d','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.118864+00:00','dev-v3-fixture','commit-candidates','v3-original-create','12f3acab69cbda7773fb4470ec9355674ca23f7f56a75363ac917447fb7fb7fa','{"action":"commit-candidates","base_revision":0,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","selection":[{"candidate_id":"4f0bcfa7-297f-418a-b791-888763adf7f1","review_id":"f00fadc3-47dd-4fcf-9cdd-a59f299474df"}]}','{"base_revision":0,"changes":[{"candidate_id":"4f0bcfa7-297f-418a-b791-888763adf7f1","change_id":"4bac5b1b-a374-44d0-855d-324952757b06","effective_change_id":"d7f3e1d3-a390-40b0-9166-2d7ebf1b7c79","operation":"task.create","target_id":"8c31da2a-d666-4eff-a736-e38324040c21","target_version_id":null}],"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","revision":1}',0,1);
INSERT INTO "change_commits" VALUES('15212e57-31b7-410a-9371-f9cbea6752a1','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.137838+00:00','dev-v3-fixture','commit-candidates','860a2651-0af9-471d-80be-80c4ee3db3d5','be87fc4cf25610c45efd4261ce1505430ba5609d85dd2620012e68e20f436392','{"action":"commit-candidates","base_revision":1,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","selection":[{"candidate_id":"860a2651-0af9-471d-80be-80c4ee3db3d5","review_id":"d7fe3bda-8bf8-485a-beba-707d103bb2a6"}]}','{"base_revision":1,"changes":[{"candidate_id":"860a2651-0af9-471d-80be-80c4ee3db3d5","change_id":"b943363b-47ec-4b62-804d-bb3fa2503249","effective_change_id":"b5ae9f36-0fe4-464a-bf18-95d22f2345fc","operation":"version.confirm","target_id":"8c31da2a-d666-4eff-a736-e38324040c21","target_version_id":"88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9"}],"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","revision":2}',1,2);
INSERT INTO "change_commits" VALUES('bc93620c-278a-4df0-8173-a2f951ccef99','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.172751+00:00','dev-v3-fixture','commit-candidates','d062c84b-a18c-48da-b9fb-c531bd7c7882','4abacc5d1dcad574ebf3c8d2d22978137bbaaadaf1b448c326b4f8917a52147e','{"action":"commit-candidates","base_revision":2,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","selection":[{"candidate_id":"d062c84b-a18c-48da-b9fb-c531bd7c7882","review_id":"698c691a-5695-47a2-860c-94666d69328c"}]}','{"base_revision":2,"changes":[{"candidate_id":"d062c84b-a18c-48da-b9fb-c531bd7c7882","change_id":"e9ffab95-12d6-463e-adfa-81dcd704afaa","effective_change_id":"ccd6ace2-2bfc-4da1-9b9b-e37b1e8ac813","operation":"baseline.set","target_id":"155ec3e1-2a27-41c6-b76d-253eabf1cfc8","target_version_id":"88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9"}],"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","revision":3}',2,3);
INSERT INTO "change_commits" VALUES('26bcb09a-90b6-411c-9a03-10a767248312','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.190684+00:00','dev-v3-fixture','commit-candidates','199fb911-b0a3-4e4d-b59c-cf840b33598f','282877091b2adaeb6a50175df9e86e21550ac9f52ab99344ae71b3579872308e','{"action":"commit-candidates","base_revision":3,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","selection":[{"candidate_id":"199fb911-b0a3-4e4d-b59c-cf840b33598f","review_id":"456508e4-591e-4b9b-9b59-c4433fe3ecdd"}]}','{"base_revision":3,"changes":[{"candidate_id":"199fb911-b0a3-4e4d-b59c-cf840b33598f","change_id":"2f65378a-e12e-4316-9646-c19a51988b06","effective_change_id":"400b6abf-9120-4c2a-bde7-a10791b62a49","operation":"task.update","target_id":"8c31da2a-d666-4eff-a736-e38324040c21","target_version_id":null}],"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","revision":4}',3,4);
INSERT INTO "change_commits" VALUES('92efc1f3-6378-4211-bd6f-458e0bfba59f','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.208728+00:00','dev-v3-fixture','commit-candidates','eb8212da-fcb1-4cea-a3c6-ae7c48787c80','711835f4356f9680901eb0461295a95902d04b2e563580be147fe3d4a6dcf62e','{"action":"commit-candidates","base_revision":4,"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","selection":[{"candidate_id":"eb8212da-fcb1-4cea-a3c6-ae7c48787c80","review_id":"372b981b-76c8-40c7-803f-4cbf7ced2e40"}]}','{"base_revision":4,"changes":[{"candidate_id":"eb8212da-fcb1-4cea-a3c6-ae7c48787c80","change_id":"5f0590e2-c0e1-4a8f-8af2-3fb6878561be","effective_change_id":"f2be4dfc-24e8-4e34-85fe-6c2024ab4676","operation":"baseline.set","target_id":"155ec3e1-2a27-41c6-b76d-253eabf1cfc8","target_version_id":"b7e22b59-3ad0-46b0-8f3b-3322890e6ecd"}],"project_id":"55f7b6ab-55ae-42b9-a230-b881a1dbb0e0","revision":5}',4,5);
CREATE TABLE change_reviews (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        candidate_id TEXT NOT NULL, fingerprint TEXT NOT NULL CHECK(length(fingerprint)=64),
            decision TEXT NOT NULL CHECK(decision IN ('approve','reject','defer')),
            mode TEXT NOT NULL CHECK(mode IN ('ordinary','explicit')),
            sequence INTEGER NOT NULL CHECK(sequence>0),
            basis TEXT NOT NULL CHECK(length(basis)>0),
            input_origin TEXT NOT NULL CHECK(input_origin IN ('local-user','synthetic-test')),
            authorization_json TEXT NOT NULL, UNIQUE(project_id,candidate_id,id), UNIQUE(project_id,candidate_id,sequence),
        UNIQUE(project_id, id)
        , FOREIGN KEY(project_id, candidate_id) REFERENCES candidate_changes(project_id, id)
    ) STRICT;
INSERT INTO "change_reviews" VALUES('f00fadc3-47dd-4fcf-9cdd-a59f299474df','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.117630+00:00','dev-v3-fixture','4f0bcfa7-297f-418a-b791-888763adf7f1','af5d18d6658f3522ebc24a661dc90f539530343509bcdb665128f0354fd07274','approve','ordinary',1,'Synthetic test input from historical T04 service','synthetic-test','{}');
INSERT INTO "change_reviews" VALUES('d7fe3bda-8bf8-485a-beba-707d103bb2a6','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.136391+00:00','dev-v3-fixture','860a2651-0af9-471d-80be-80c4ee3db3d5','f1f64afaf9ae535373c844323cc00fcf0f2525f4cf202dff4a850f97b64963c3','approve','ordinary',1,'Synthetic test input from historical T04 service','synthetic-test','{}');
INSERT INTO "change_reviews" VALUES('698c691a-5695-47a2-860c-94666d69328c','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.171302+00:00','dev-v3-fixture','d062c84b-a18c-48da-b9fb-c531bd7c7882','07efa390e2493771c17a55f6a6fec94df0b127d9649728a2043cfef1889f3365','approve','explicit',1,'Synthetic test input from historical T04 service','synthetic-test','{"base_revision":2,"candidate_id":"d062c84b-a18c-48da-b9fb-c531bd7c7882","fingerprint":"07efa390e2493771c17a55f6a6fec94df0b127d9649728a2043cfef1889f3365","preconditions_sha256":"7614316eba3f1654f794248fa7f128887b20d5b669211c5edc1a24f572068019","target_id":"155ec3e1-2a27-41c6-b76d-253eabf1cfc8","target_version_id":"88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9"}');
INSERT INTO "change_reviews" VALUES('456508e4-591e-4b9b-9b59-c4433fe3ecdd','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.189502+00:00','dev-v3-fixture','199fb911-b0a3-4e4d-b59c-cf840b33598f','1a1e3cd425fcb8df43ea1ba334cb4b3b2633cfd02f565af715599e28835dedae','approve','ordinary',1,'Synthetic test input from historical T04 service','synthetic-test','{}');
INSERT INTO "change_reviews" VALUES('372b981b-76c8-40c7-803f-4cbf7ced2e40','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.207714+00:00','dev-v3-fixture','eb8212da-fcb1-4cea-a3c6-ae7c48787c80','1c0dae9fdc2dabc2326b66c95c43bd293e5cc07f02148c7fd7bda0b198c691a5','approve','explicit',1,'Synthetic test input from historical T04 service','synthetic-test','{"base_revision":4,"candidate_id":"eb8212da-fcb1-4cea-a3c6-ae7c48787c80","fingerprint":"1c0dae9fdc2dabc2326b66c95c43bd293e5cc07f02148c7fd7bda0b198c691a5","preconditions_sha256":"5e83956afe77e905c46cd81dceae86b9fa3e4e503abd47c49bb5af1c680968ce","target_id":"155ec3e1-2a27-41c6-b76d-253eabf1cfc8","target_version_id":"b7e22b59-3ad0-46b0-8f3b-3322890e6ecd"}');
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
INSERT INTO "check_results" VALUES('eadb209d-f8e3-4a3d-ad4d-8a15f23cec4a','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.152655+00:00','dev-v3-fixture','10c7ffa2-27df-4d36-b70d-0d3a25f8e6c3','caller-claim','synthetic-test','legacy-v1','pass','');
CREATE TABLE confirmed_version_links (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        task_id TEXT NOT NULL, version_id TEXT NOT NULL,
            change_id TEXT NOT NULL, UNIQUE(project_id,task_id,version_id),
        UNIQUE(project_id, id)
        , FOREIGN KEY(project_id, task_id) REFERENCES tasks(project_id, id), FOREIGN KEY(project_id, version_id) REFERENCES artifact_versions(project_id, id), FOREIGN KEY(project_id, change_id) REFERENCES applied_changes(project_id, id)
    ) STRICT;
INSERT INTO "confirmed_version_links" VALUES('fa1a1692-e7cc-49bd-8938-7e725dfddde1','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.139219+00:00','dev-v3-fixture','8c31da2a-d666-4eff-a736-e38324040c21','88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9','b943363b-47ec-4b62-804d-bb3fa2503249');
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
INSERT INTO "effective_changes" VALUES('d7f3e1d3-a390-40b0-9166-2d7ebf1b7c79','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.119201+00:00','dev-v3-fixture','4f0bcfa7-297f-418a-b791-888763adf7f1','reserved');
INSERT INTO "effective_changes" VALUES('b5ae9f36-0fe4-464a-bf18-95d22f2345fc','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.138315+00:00','dev-v3-fixture','860a2651-0af9-471d-80be-80c4ee3db3d5','reserved');
INSERT INTO "effective_changes" VALUES('ccd6ace2-2bfc-4da1-9b9b-e37b1e8ac813','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.173185+00:00','dev-v3-fixture','d062c84b-a18c-48da-b9fb-c531bd7c7882','reserved');
INSERT INTO "effective_changes" VALUES('400b6abf-9120-4c2a-bde7-a10791b62a49','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.191108+00:00','dev-v3-fixture','199fb911-b0a3-4e4d-b59c-cf840b33598f','reserved');
INSERT INTO "effective_changes" VALUES('f2be4dfc-24e8-4e34-85fe-6c2024ab4676','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.209111+00:00','dev-v3-fixture','eb8212da-fcb1-4cea-a3c6-ae7c48787c80','reserved');
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
INSERT INTO "evidence" VALUES('10c7ffa2-27df-4d36-b70d-0d3a25f8e6c3','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.151025+00:00','dev-v3-fixture','8c31da2a-d666-4eff-a736-e38324040c21','88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9',NULL,'pending','caller-claim','synthetic-test','pass is only a historical claim',1,'legacy-v1');
CREATE TABLE formal_task_states (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        task_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
            title TEXT NOT NULL CHECK(length(title)>0), goal TEXT NOT NULL,
            completion_conditions TEXT NOT NULL,
            lifecycle TEXT NOT NULL DEFAULT 'todo' CHECK(lifecycle='todo'),
            change_id TEXT NOT NULL, UNIQUE(project_id,task_id,revision),
        UNIQUE(project_id, id)
        , FOREIGN KEY(project_id, task_id) REFERENCES tasks(project_id, id), FOREIGN KEY(project_id, change_id) REFERENCES applied_changes(project_id, id)
    ) STRICT;
INSERT INTO "formal_task_states" VALUES('45e03b14-422c-4d57-bd3c-d42610dfbee2','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.120973+00:00','dev-v3-fixture','8c31da2a-d666-4eff-a736-e38324040c21',1,'Synthetic old task','Historical goal','Synthetic condition','todo','4bac5b1b-a374-44d0-855d-324952757b06');
INSERT INTO "formal_task_states" VALUES('a075b463-898a-48f0-b551-226a1f838c74','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.191588+00:00','dev-v3-fixture','8c31da2a-d666-4eff-a736-e38324040c21',4,'Synthetic old task','Updated historical goal','Synthetic condition','todo','2f65378a-e12e-4316-9646-c19a51988b06');
CREATE TABLE foundation_scopes (
    id TEXT PRIMARY KEY,
    owner_subject TEXT NOT NULL,
    label TEXT NOT NULL CHECK(label = 'synthetic-access-fixture')
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
CREATE TABLE projects (
    id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
    owner_subject TEXT NOT NULL CHECK(length(owner_subject) > 0),
    title TEXT NOT NULL CHECK(length(title) > 0),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    created_at TEXT NOT NULL
) STRICT;
INSERT INTO "projects" VALUES('55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','dev-v3-fixture','Synthetic actual T04 history',5,'2026-10-20T05:46:42.094097+00:00');
CREATE TABLE recheck_requests (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id) > 0),
        project_id TEXT NOT NULL REFERENCES projects(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision>0),
            change_id TEXT NOT NULL, reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status='pending'),
            UNIQUE(project_id,change_id),
        UNIQUE(project_id, id)
        , FOREIGN KEY(project_id, change_id) REFERENCES applied_changes(project_id, id)
    ) STRICT;
INSERT INTO "recheck_requests" VALUES('7b78360f-ad38-4fb0-964c-5cf6528ecedb','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.174202+00:00','dev-v3-fixture',3,'e9ffab95-12d6-463e-adfa-81dcd704afaa','baseline-changed','pending');
INSERT INTO "recheck_requests" VALUES('61e41876-5cba-4f40-bb60-567d1d97164f','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.191838+00:00','dev-v3-fixture',4,'2f65378a-e12e-4316-9646-c19a51988b06','task-content-changed','pending');
INSERT INTO "recheck_requests" VALUES('52248fb6-6b18-493c-97f9-86ca085ba3a9','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.210554+00:00','dev-v3-fixture',5,'5f0590e2-c0e1-4a8f-8af2-3fb6878561be','baseline-changed','pending');
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
INSERT INTO "source_attributions" VALUES('7277816b-bd8b-4ee8-8143-e37c9e04d782','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.097066+00:00','dev-v3-fixture','64c47e3e-c496-4474-8ae1-4aa64401f77b',NULL,NULL,NULL,NULL,'Saved with unresolved attribution');
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
INSERT INTO "sources" VALUES('64c47e3e-c496-4474-8ae1-4aa64401f77b','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.096460+00:00','dev-v3-fixture',NULL,NULL,'synthetic://v3-fixture',NULL,'reference-only',NULL,NULL,NULL,'unavailable','synthetic missing original','{}');
CREATE TABLE task_sessions (
        project_id TEXT NOT NULL, task_id TEXT NOT NULL, session_id TEXT NOT NULL,
        created_by TEXT NOT NULL, PRIMARY KEY(project_id, task_id, session_id),
        FOREIGN KEY(project_id, task_id) REFERENCES tasks(project_id, id),
        FOREIGN KEY(project_id, session_id) REFERENCES sessions(project_id, id)
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
INSERT INTO "tasks" VALUES('8c31da2a-d666-4eff-a736-e38324040c21','55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','2026-10-20T05:46:42.120099+00:00','dev-v3-fixture','Synthetic old task','Historical goal','Synthetic condition',1,NULL,NULL);
CREATE TABLE version_sources (
        project_id TEXT NOT NULL, version_id TEXT NOT NULL, source_id TEXT NOT NULL,
        created_by TEXT NOT NULL, PRIMARY KEY(project_id, version_id, source_id),
        FOREIGN KEY(project_id, version_id) REFERENCES artifact_versions(project_id, id),
        FOREIGN KEY(project_id, source_id) REFERENCES sources(project_id, id)
    ) STRICT;
INSERT INTO "version_sources" VALUES('55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','88e7ca93-3b3e-41f4-bc7f-cbeae85afaa9','64c47e3e-c496-4474-8ae1-4aa64401f77b','dev-v3-fixture');
INSERT INTO "version_sources" VALUES('55f7b6ab-55ae-42b9-a230-b881a1dbb0e0','b7e22b59-3ad0-46b0-8f3b-3322890e6ecd','64c47e3e-c496-4474-8ae1-4aa64401f77b','dev-v3-fixture');
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
CREATE TRIGGER candidate_specs_t04_no_update BEFORE UPDATE ON candidate_specs BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER candidate_specs_t04_no_delete BEFORE DELETE ON candidate_specs BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER candidate_supersessions_t04_no_update BEFORE UPDATE ON candidate_supersessions BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER candidate_supersessions_t04_no_delete BEFORE DELETE ON candidate_supersessions BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER change_reviews_t04_no_update BEFORE UPDATE ON change_reviews BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER change_reviews_t04_no_delete BEFORE DELETE ON change_reviews BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER change_commits_t04_no_update BEFORE UPDATE ON change_commits BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER change_commits_t04_no_delete BEFORE DELETE ON change_commits BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER applied_changes_t04_no_update BEFORE UPDATE ON applied_changes BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER applied_changes_t04_no_delete BEFORE DELETE ON applied_changes BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER formal_task_states_t04_no_update BEFORE UPDATE ON formal_task_states BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER formal_task_states_t04_no_delete BEFORE DELETE ON formal_task_states BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER confirmed_version_links_t04_no_update BEFORE UPDATE ON confirmed_version_links BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER confirmed_version_links_t04_no_delete BEFORE DELETE ON confirmed_version_links BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER baseline_history_t04_no_update BEFORE UPDATE ON baseline_history BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER baseline_history_t04_no_delete BEFORE DELETE ON baseline_history BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER recheck_requests_t04_no_update BEFORE UPDATE ON recheck_requests BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER recheck_requests_t04_no_delete BEFORE DELETE ON recheck_requests BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER candidate_changes_t04_no_update BEFORE UPDATE ON candidate_changes BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER candidate_changes_t04_no_delete BEFORE DELETE ON candidate_changes BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER effective_changes_t04_no_update BEFORE UPDATE ON effective_changes BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE TRIGGER effective_changes_t04_no_delete BEFORE DELETE ON effective_changes BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END;
CREATE INDEX reviews_candidate_order ON change_reviews(project_id,candidate_id,sequence);
COMMIT;
PRAGMA user_version=3;
