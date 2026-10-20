"""Synthetic integration tests; all databases and credentials are temporary."""
from dataclasses import replace
import http.client
import io
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from wsgiref.validate import validator

from nextrelay.app import create_app
from nextrelay.store import unit_of_work
from nextrelay.auth import AccessError, Principal, require_owned_scope
from nextrelay.config import ConfigError, Settings, load_settings
from nextrelay.db import SCHEMA_VERSION, SchemaError, connect, initialize, seed_synthetic, transaction


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nextrelay-t02-")
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "test.sqlite3"
        initialize(self.database)

    def test_initialization_is_repeatable_and_domain_tables_are_empty(self):
        initialize(self.database)
        with connect(self.database) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA synchronous").fetchone()[0], 2)
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("SELECT count(*) FROM projects").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT count(*) FROM tasks").fetchone()[0], 0)

    def test_commit_is_visible_after_reopening(self):
        with connect(self.database) as connection:
            with transaction(connection):
                connection.execute(
                    "INSERT INTO foundation_scopes VALUES (?, ?, ?)",
                    ("committed", "dev-test", "synthetic-access-fixture"),
                )
        with connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM foundation_scopes").fetchone()[0], 1)

    def test_two_writes_roll_back_on_constraint_failure(self):
        with connect(self.database) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                with transaction(connection):
                    connection.execute(
                        "INSERT INTO foundation_scopes VALUES (?, ?, ?)",
                        ("rollback", "dev-test", "synthetic-access-fixture"),
                    )
                    connection.execute(
                        "INSERT INTO foundation_scopes VALUES (?, ?, ?)",
                        ("rollback", "dev-test", "synthetic-access-fixture"),
                    )
            self.assertFalse(connection.in_transaction)
        with connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM foundation_scopes").fetchone()[0], 0)

    def test_exception_rolls_back_and_connection_remains_usable(self):
        with connect(self.database) as connection:
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                with transaction(connection):
                    connection.execute(
                        "INSERT INTO foundation_scopes VALUES (?, ?, ?)",
                        ("rollback", "dev-test", "synthetic-access-fixture"),
                    )
                    raise RuntimeError("synthetic failure")
            with transaction(connection):
                self.assertEqual(connection.execute("SELECT count(*) FROM foundation_scopes").fetchone()[0], 0)

    def test_uncommitted_writes_are_invisible_to_other_connections(self):
        with connect(self.database) as writer, connect(self.database) as reader:
            with transaction(writer):
                writer.execute(
                    "INSERT INTO foundation_scopes VALUES (?, ?, ?)",
                    ("isolated", "dev-test", "synthetic-access-fixture"),
                )
                self.assertEqual(reader.execute("SELECT count(*) FROM foundation_scopes").fetchone()[0], 0)
            self.assertEqual(reader.execute("SELECT count(*) FROM foundation_scopes").fetchone()[0], 1)

    def test_process_exit_before_commit_is_recovered(self):
        code = """
import os, sys
from pathlib import Path
from nextrelay.db import connect, transaction
with connect(Path(sys.argv[1])) as connection:
    with transaction(connection):
        connection.execute("INSERT INTO foundation_scopes VALUES (?, ?, ?)",
                           ("crash", "dev-test", "synthetic-access-fixture"))
        os._exit(23)
"""
        result = subprocess.run([sys.executable, "-c", code, str(self.database)], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 23)
        with connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM foundation_scopes").fetchone()[0], 0)
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_future_schema_is_rejected_without_downgrade(self):
        with connect(self.database) as connection:
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        with self.assertRaises(SchemaError):
            initialize(self.database)
        with connect(self.database) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION + 1)

    def test_incompatible_existing_schema_is_not_adopted(self):
        other = Path(self.temp.name) / "incompatible.sqlite3"
        with connect(other) as connection:
            connection.execute("CREATE TABLE foundation_scopes (unknown TEXT)")
        with self.assertRaises(SchemaError):
            initialize(other)
        with connect(other) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)

    def test_seed_is_idempotent_and_does_not_reassign_ownership(self):
        seed_synthetic(self.database, "dev-test")
        seed_synthetic(self.database, "dev-test")
        with self.assertRaises(SchemaError):
            seed_synthetic(self.database, "dev-different")
        with connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM foundation_scopes").fetchone()[0], 2)
            self.assertEqual(require_owned_scope(connection, Principal("dev-test"), "synthetic-owned")["id"], "synthetic-owned")
            for scope in ("synthetic-foreign", "missing", "' OR 1=1 --"):
                with self.subTest(scope=scope), self.assertRaises(AccessError):
                    require_owned_scope(connection, Principal("dev-test"), scope)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            database=Path(tempfile.gettempdir()).resolve() / "nextrelay-config-only.sqlite3",
            token=secrets.token_urlsafe(32),
        )

    def test_insecure_or_unsupported_modes_are_rejected(self):
        for change in (
            {"environment": "production"}, {"auth_mode": "none"}, {"host": "0.0.0.0"},
            {"token": ""}, {"token": "short"}, {"token": "x" * 257},
            {"subject": "real-user"}, {"subject": "dev-other-user"}, {"port": 0}, {"database": Path("relative.sqlite3")},
            {"database": Path(__file__).resolve().parents[1] / "local.sqlite3"},
        ):
            with self.subTest(change=list(change)), self.assertRaises(ConfigError):
                replace(self.settings, **change)

    def test_environment_requires_explicit_opt_in(self):
        with self.assertRaises(ConfigError):
            load_settings({})
        env = {
            "NEXTRELAY_ENV": "development", "NEXTRELAY_AUTH_MODE": "dev-token",
            "NEXTRELAY_DEV_TOKEN": self.settings.token,
            "NEXTRELAY_DB_PATH": str(self.settings.database),
        }
        self.assertEqual(load_settings(env).subject, "dev-synthetic-user")
        with self.assertRaises(ConfigError):
            load_settings(dict(env, NEXTRELAY_PORT="invalid"))

    def test_token_is_redacted_from_settings_repr(self):
        self.assertNotIn(self.settings.token, repr(self.settings))


class HttpTests(unittest.TestCase):
    """Exercise the actual CLI subprocess and real TCP HTTP, with restart."""
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="nextrelay-http-")
        cls.database = Path(cls.temp.name) / "http.sqlite3"
        cls.token = secrets.token_urlsafe(32)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.port = probe.getsockname()[1]
        cls.env = dict(
            os.environ,
            NEXTRELAY_ENV="development", NEXTRELAY_AUTH_MODE="dev-token",
            NEXTRELAY_DEV_TOKEN=cls.token, NEXTRELAY_DEV_SUBJECT="dev-http-user",
            NEXTRELAY_HOST="127.0.0.1", NEXTRELAY_PORT=str(cls.port),
            NEXTRELAY_DB_PATH=str(cls.database), PYTHONDONTWRITEBYTECODE="1",
        )
        cls.addClassCleanup(cls.temp.cleanup)
        for command in ("init-db", "init-db", "seed-dev", "seed-dev"):
            result = subprocess.run(
                [sys.executable, "-m", "nextrelay", command], env=cls.env,
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode:
                raise AssertionError(f"CLI {command} failed: {result.stderr}")
        with unit_of_work(cls.database, Principal('dev-http-user'), write=True) as store:
            cls.project_id = store.create_project('synthetic HTTP project')['id']
        with unit_of_work(cls.database, Principal('dev-http-stranger'), write=True) as store:
            cls.foreign_project_id = store.create_project('synthetic foreign project')['id']
        cls.start_server()
        cls.addClassCleanup(cls.stop_server)

    @classmethod
    def start_server(cls):
        cls.process = subprocess.Popen(
            [sys.executable, "-m", "nextrelay", "serve"], env=cls.env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if cls.process.poll() is not None:
                out, err = cls.process.communicate()
                raise AssertionError(f"Server exited: {out} {err}")
            try:
                if cls.request("/health/live")[0] == 200:
                    return
            except OSError:
                time.sleep(0.05)
        cls.stop_server()
        raise AssertionError("Server did not become live")

    @classmethod
    def stop_server(cls):
        if cls.process.poll() is None:
            cls.process.terminate()
        out, err = cls.process.communicate(timeout=10)
        if cls.token in out + err:
            raise AssertionError("Credential leaked in server output")
        # Request URLs, query strings and headers must not appear in ordinary logs.
        if "sensitive-query" in out + err or "sensitive-header" in out + err:
            raise AssertionError("Request data leaked in server output")
        cls.server_output = out + err

    @classmethod
    def request(cls, path, *, token=None, headers=None, method="GET"):
        request_headers = dict(headers or {})
        if token is not None:
            request_headers["Authorization"] = f"Bearer {token}"
        connection = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=5)
        try:
            connection.request(method, path, headers=request_headers)
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def test_public_landing_and_liveness(self):
        for path in ("/", "/health/live"):
            status, body, headers = self.request(path)
            self.assertEqual(status, 200)
            self.assertNotIn(self.token.encode(), body)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertIn("default-src 'none'", headers["Content-Security-Policy"])

    def test_protected_status_requires_authentication(self):
        for token in (None, "wrong", self.token + "x"):
            self.assertEqual(self.request("/api/foundation", token=token)[0], 401)
        status, body, _ = self.request("/api/foundation", token=self.token)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["identity"]["subject"], "dev-http-user")
        self.assertFalse(data["model"]["enabled"])
        self.assertEqual(data['storage']['schema_version'], SCHEMA_VERSION)
        self.assertNotIn(str(self.database).encode(), body)

    def test_missing_and_foreign_objects_have_identical_denial(self):
        owned = self.request("/api/foundation/scopes/synthetic-owned", token=self.token)
        self.assertEqual(owned[0], 200)
        foreign = self.request("/api/foundation/scopes/synthetic-foreign", token=self.token)
        missing = self.request("/api/foundation/scopes/does-not-exist", token=self.token)
        self.assertEqual(foreign[:2], missing[:2])
        self.assertEqual(foreign[0], 404)

    def test_spoofed_identity_headers_do_not_grant_access(self):
        status, _, _ = self.request(
            "/api/foundation/scopes/synthetic-foreign", token=self.token,
            headers={"X-User-ID": "dev-other-user", "X-Forwarded-User": "dev-other-user"},
        )
        self.assertEqual(status, 404)
        self.assertEqual(self.request("/api/foundation", headers={"X-User-ID": "dev-http-user"})[0], 401)

    def test_cross_origin_and_untrusted_host_are_rejected(self):
        for origin in ("https://untrusted.example", "null", f"http://127.0.0.1:{self.port + 1}"):
            with self.subTest(origin=origin):
                status, _, headers = self.request(
                    "/api/foundation", token=self.token, headers={"Origin": origin},
                )
                self.assertEqual(status, 403)
                self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(self.request("/health/live", headers={"Host": "untrusted.example"})[0], 400)

    def test_write_methods_are_closed_and_query_token_is_not_auth(self):
        self.assertEqual(self.request("/api/foundation", token=self.token, method="POST")[0], 405)
        self.assertEqual(self.request("/api/foundation?sensitive-query", headers={"X-Test": "sensitive-header"})[0], 401)
        self.assertEqual(self.request("/api/not-built", token=self.token)[0], 404)

    def test_server_restart_retains_storage_and_access_boundary(self):
        self.stop_server()
        self.start_server()
        self.assertEqual(self.request("/api/foundation/scopes/synthetic-owned", token=self.token)[0], 200)
        self.assertEqual(self.request("/api/foundation/scopes/synthetic-foreign", token=self.token)[0], 404)
        self.assertEqual(self.request('/api/projects/' + self.project_id, token=self.token)[0], 200)

    def test_storage_failure_is_redacted_and_service_recovers(self):
        with connect(self.database) as connection:
            connection.execute("ALTER TABLE foundation_scopes RENAME TO unavailable_scopes")
        try:
            status, body, _ = self.request(
                "/api/foundation/scopes/synthetic-owned", token=self.token,
            )
            self.assertEqual(status, 503)
            self.assertEqual(json.loads(body), {"error": "storage_unavailable"})
            self.assertNotIn(str(self.database).encode(), body)
        finally:
            with connect(self.database) as connection:
                connection.execute("ALTER TABLE unavailable_scopes RENAME TO foundation_scopes")
        self.assertEqual(self.request("/api/foundation", token=self.token)[0], 200)

    def test_projects_http_enforces_identity_owner_and_non_disclosure(self):
        self.assertEqual(self.request('/api/projects')[0], 401)
        self.assertEqual(self.request('/api/projects', token='invalid')[0], 401)
        status, body, _ = self.request('/api/projects', token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual([row['id'] for row in json.loads(body)['projects']], [self.project_id])
        self.assertEqual(self.request('/api/projects/' + self.project_id, token=self.token)[0], 200)
        foreign = self.request('/api/projects/' + self.foreign_project_id, token=self.token,
                               headers={'X-User-ID': 'dev-http-stranger'})
        missing = self.request('/api/projects/missing-project', token=self.token)
        self.assertEqual(foreign[:2], missing[:2])
        self.assertEqual(foreign[0], 404)
        self.assertEqual(self.request('/api/projects', token=self.token, method='POST')[0], 405)

    def test_t04_service_commit_is_visible_over_real_authenticated_http(self):
        principal=Principal('dev-http-user')
        with unit_of_work(self.database,principal,write=True) as s:
            pid=s.create_project('synthetic T04 TCP journey')['id']
            candidate=s.save_candidate(pid,dict(base_revision=0,operation='task.create',payload={'title':'observable over TCP'}))
        status,body,_=self.request('/api/projects/'+pid+'/formal',token=self.token)
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['tasks'],[])
        with unit_of_work(self.database,principal,write=True) as s:
            review=s.review_candidates(pid,dict(selection=[dict(candidate_id=candidate['candidate_id'],fingerprint=candidate['fingerprint'])],
                decision='approve',mode='ordinary',basis='Synthetic TCP test input only',input_origin='synthetic-test'))[0]
        with unit_of_work(self.database,principal,write=True) as s:
            result=s.commit_candidates(pid,dict(request_key='synthetic-tcp',base_revision=0,
                selection=[dict(candidate_id=candidate['candidate_id'],review_id=review['id'])]))
        status,body,_=self.request('/api/projects/'+pid+'/formal',token=self.token)
        self.assertEqual(status,200);formal=json.loads(body)
        self.assertEqual(formal['tasks'][0]['title'],'observable over TCP')
        self.assertEqual(formal['tasks'][0]['lifecycle'],'todo')
        self.assertEqual(formal['project']['revision'],result['revision'])
        status,body,_=self.request('/api/projects/'+pid+'/history',token=self.token)
        self.assertEqual(status,200);history=json.loads(body)
        self.assertEqual(len(history['applied_changes']),1)
        self.assertEqual(json.loads(history['change_commits'][0]['result_json']),result)
        self.assertEqual(self.request('/api/projects/'+pid+'/candidates',token=self.token)[0],200)
        self.stop_server();self.start_server()
        self.assertEqual(self.request('/api/projects/'+pid+'/formal',token=self.token)[0],200)

    def test_t04_read_routes_enforce_auth_owner_and_forged_headers(self):
        for suffix in ('formal','history','candidates'):
            path='/api/projects/'+self.foreign_project_id+'/'+suffix
            self.assertEqual(self.request(path)[0],401)
            foreign=self.request(path,token=self.token,headers={'X-User-ID':'dev-http-stranger'})
            missing=self.request('/api/projects/missing/'+suffix,token=self.token)
            self.assertEqual(foreign[:2],missing[:2]);self.assertEqual(foreign[0],404)

    def test_wsgi_contract(self):
        settings = load_settings(self.env)
        application = validator(create_app(settings))
        environ = {
            "REQUEST_METHOD": "GET", "SCRIPT_NAME": "", "PATH_INFO": "/health/live",
            "QUERY_STRING": "", "SERVER_NAME": "127.0.0.1", "SERVER_PORT": str(self.port),
            "SERVER_PROTOCOL": "HTTP/1.1", "HTTP_HOST": f"127.0.0.1:{self.port}",
            "wsgi.version": (1, 0), "wsgi.url_scheme": "http",
            "wsgi.input": io.BytesIO(), "wsgi.errors": io.StringIO(),
            "wsgi.multithread": False, "wsgi.multiprocess": False, "wsgi.run_once": False,
        }
        statuses = []
        result = application(environ, lambda status, headers, exc_info=None: statuses.append(status))
        try:
            self.assertTrue(b"alive" in b"".join(result))
        finally:
            result.close()
        self.assertEqual(statuses, ["200 OK"])


if __name__ == "__main__":
    unittest.main()
