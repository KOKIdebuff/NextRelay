-- Frozen T02 schema, copied from the original db.py before T03 migration.
CREATE TABLE foundation_scopes (
    id TEXT PRIMARY KEY,
    owner_subject TEXT NOT NULL,
    label TEXT NOT NULL CHECK(label = 'synthetic-access-fixture')
) STRICT;
PRAGMA user_version = 1;
