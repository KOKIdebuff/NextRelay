"""T04 additive extension; T03 reserved identities and history stay intact."""
T04_TABLES = ('candidate_specs','candidate_supersessions','change_reviews','change_commits',
              'applied_changes','formal_task_states','confirmed_version_links','baseline_history','recheck_requests')


def migration(record, ref):
    V3 = [
        record('candidate_specs', '''candidate_id TEXT NOT NULL, operation TEXT NOT NULL CHECK(operation IN ('task.create','task.update','version.confirm','baseline.set')),
            target_id TEXT NOT NULL CHECK(length(target_id)>0), target_version_id TEXT, spec_json TEXT NOT NULL,
            fingerprint TEXT NOT NULL CHECK(length(fingerprint)=64),
            risk TEXT NOT NULL CHECK(risk IN ('ordinary','high','conflict')),
            UNIQUE(project_id,candidate_id)''', (ref('candidate_id','candidate_changes'),
                                               ref('target_version_id','artifact_versions'))),
        record('candidate_supersessions', '''old_candidate_id TEXT NOT NULL, new_candidate_id TEXT NOT NULL,
            CHECK(old_candidate_id <> new_candidate_id), UNIQUE(project_id,old_candidate_id)''',
               (ref('old_candidate_id','candidate_changes'),ref('new_candidate_id','candidate_changes'))),
        record('change_reviews', '''candidate_id TEXT NOT NULL, fingerprint TEXT NOT NULL CHECK(length(fingerprint)=64),
            decision TEXT NOT NULL CHECK(decision IN ('approve','reject','defer')),
            mode TEXT NOT NULL CHECK(mode IN ('ordinary','explicit')),
            sequence INTEGER NOT NULL CHECK(sequence>0),
            basis TEXT NOT NULL CHECK(length(basis)>0),
            input_origin TEXT NOT NULL CHECK(input_origin IN ('local-user','synthetic-test')),
            authorization_json TEXT NOT NULL, UNIQUE(project_id,candidate_id,id), UNIQUE(project_id,candidate_id,sequence)''', (ref('candidate_id','candidate_changes'),)),
        record('change_commits', '''action TEXT NOT NULL CHECK(action='commit-candidates'),
            request_key TEXT NOT NULL CHECK(length(request_key)>0),
            request_fingerprint TEXT NOT NULL CHECK(length(request_fingerprint)=64),
            request_json TEXT NOT NULL, result_json TEXT NOT NULL,
            base_revision INTEGER NOT NULL CHECK(base_revision>=0),
            revision INTEGER NOT NULL CHECK(revision=base_revision+1),
            UNIQUE(project_id,action,request_key), UNIQUE(project_id,revision)'''),
        record('applied_changes', '''effective_change_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
            review_id TEXT NOT NULL, commit_id TEXT NOT NULL, effect_json TEXT NOT NULL,
            UNIQUE(project_id,candidate_id), UNIQUE(project_id,effective_change_id)''',
               (ref('effective_change_id','effective_changes'),ref('candidate_id','candidate_changes'),
                ref('review_id','change_reviews'),ref('commit_id','change_commits'),
                'FOREIGN KEY(project_id,candidate_id,review_id) REFERENCES change_reviews(project_id,candidate_id,id)')),
        record('formal_task_states', '''task_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
            title TEXT NOT NULL CHECK(length(title)>0), goal TEXT NOT NULL,
            completion_conditions TEXT NOT NULL,
            lifecycle TEXT NOT NULL DEFAULT 'todo' CHECK(lifecycle='todo'),
            change_id TEXT NOT NULL, UNIQUE(project_id,task_id,revision)''',
               (ref('task_id','tasks'),ref('change_id','applied_changes'))),
        record('confirmed_version_links', '''task_id TEXT NOT NULL, version_id TEXT NOT NULL,
            change_id TEXT NOT NULL, UNIQUE(project_id,task_id,version_id)''',
               (ref('task_id','tasks'),ref('version_id','artifact_versions'),ref('change_id','applied_changes'))),
        record('baseline_history', '''version_id TEXT NOT NULL, previous_version_id TEXT,
            revision INTEGER NOT NULL CHECK(revision>0), change_id TEXT NOT NULL,
            UNIQUE(project_id,revision), UNIQUE(project_id,change_id)''',
               (ref('version_id','artifact_versions'),ref('previous_version_id','artifact_versions'),
                ref('change_id','applied_changes'))),
        record('recheck_requests', '''revision INTEGER NOT NULL CHECK(revision>0),
            change_id TEXT NOT NULL, reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status='pending'),
            UNIQUE(project_id,change_id)''', (ref('change_id','applied_changes'),)),
    ]
    for table in T04_TABLES + ('candidate_changes','effective_changes'):
        for action in ('UPDATE','DELETE'):
            V3.append(f"CREATE TRIGGER {table}_t04_no_{action.lower()} BEFORE {action} ON {table} "
                      "BEGIN SELECT RAISE(ABORT, 'append-only T04 record'); END")
    V3.append('CREATE INDEX reviews_candidate_order ON change_reviews(project_id,candidate_id,sequence)')
    V3 = tuple(V3)
    return V3
