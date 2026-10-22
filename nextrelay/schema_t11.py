"""Transport receipts only; business authority remains in the T04-T07 services."""
V7 = (
    '''CREATE TABLE http_receipts (
        subject TEXT NOT NULL, request_key TEXT NOT NULL, route TEXT NOT NULL,
        fingerprint TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(subject,request_key)
    ) STRICT''',
    '''CREATE TABLE browser_uploads (
        project_id TEXT NOT NULL REFERENCES projects(id), request_key TEXT NOT NULL,
        manifest_json TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(project_id,request_key)
    ) STRICT''',
    *tuple(f"CREATE TRIGGER {t}_no_{a.lower()} BEFORE {a} ON {t} BEGIN SELECT RAISE(ABORT,'append-only transport record'); END"
           for t in ('http_receipts','browser_uploads') for a in ('UPDATE','DELETE')),
)
