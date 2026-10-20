"""Minimal WSGI application. Only liveness and a static landing page are public."""
from http import HTTPStatus
import json
import logging
import sqlite3

from .auth import AccessError, authenticate, require_owned_scope
from .db import SCHEMA_VERSION, connect, verify_schema
from .store import unit_of_work

logger = logging.getLogger("nextrelay")


def create_app(settings):
    with connect(settings.database) as connection:
        verify_schema(connection)

    def application(environ, start_response):
        status, payload, content_type = 200, {}, "application/json; charset=utf-8"
        extra_headers = []
        try:
            expected = f"{settings.host}:{settings.port}"
            if environ.get("HTTP_HOST") != expected:
                raise AccessError(400, "invalid_host")
            origin = environ.get("HTTP_ORIGIN")
            if origin and origin != f"http://{expected}":
                raise AccessError(403, "origin_denied")
            if environ.get("REQUEST_METHOD") != "GET":
                raise AccessError(405, "method_not_allowed")
            path = environ.get("PATH_INFO", "")
            if path == "/":
                payload = (
                    "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
                    "<title>NextRelay</title><h1>NextRelay · T04</h1>"
                    "<p>本地合成数据开发基础已启动。</p>"
                    "<p>T04 候选、审查和正式提交服务已实现；HTTP 仅供读取。仅限合成资料。</p>"
                    "<p>受限身份和存储状态请通过带 Bearer 凭据的 API 检查。</p></html>"
                )
                content_type = "text/html; charset=utf-8"
            elif path == "/health/live":
                payload = {"status": "alive"}
            else:
                principal = authenticate(environ, settings)
                with connect(settings.database) as connection:
                    if path == "/api/foundation":
                        verify_schema(connection)
                        connection.execute("SELECT 1").fetchone()
                        payload = {
                            "stage": "T04",
                            "identity": {"subject": principal.subject, "method": principal.method},
                            "storage": {"engine": "sqlite", "schema_version": SCHEMA_VERSION},
                            "model": {"enabled": False},
                            "data": "synthetic-only",
                        }
                    elif path.startswith("/api/foundation/scopes/"):
                        scope_id = path.removeprefix("/api/foundation/scopes/")
                        payload = require_owned_scope(connection, principal, scope_id)
                    elif path == "/api/projects":
                        with unit_of_work(settings.database, principal) as store:
                            payload = {"projects": store.projects(), "data": "synthetic-only"}
                    elif path.startswith('/api/projects/') and len(path.split('/')) == 5 and path.split('/')[4] in ('formal','history','candidates'):
                        with unit_of_work(settings.database, principal) as store:
                            project_id, resource = path.split('/')[3:5]
                            if resource == 'formal':
                                payload = store.formal_state(project_id)
                            elif resource == 'candidates':
                                payload = {'candidates': store.records(project_id, 'candidate_specs'),
                                           'reviews': store.records(project_id, 'change_reviews'),
                                           'supersessions': store.records(project_id, 'candidate_supersessions')}
                            else:
                                payload = {kind: store.records(project_id, kind) for kind in
                                           ('change_commits', 'applied_changes', 'baseline_history')}
                    elif path.startswith("/api/projects/") and len(path.split("/")) == 4:
                        with unit_of_work(settings.database, principal) as store:
                            payload = store.project(path.split("/")[3])
                    else:
                        raise AccessError(404, "route_not_found")
        except AccessError as error:
            status, payload = error.status, {"error": error.code}
            if status == 401:
                extra_headers.append(("WWW-Authenticate", 'Bearer realm="NextRelay-development"'))
            if status == 405:
                extra_headers.append(("Allow", "GET"))
        except (sqlite3.Error, RuntimeError):
            # No exception text, paths, query strings, credentials or content in logs.
            logger.error("storage_unavailable")
            status, payload = 503, {"error": "storage_unavailable"}

        body = (
            payload.encode("utf-8") if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )
        headers = [
            ("Content-Type", content_type),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
            ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"),
        ]
        start_response(f"{status} {HTTPStatus(status).phrase}", headers + extra_headers)
        return [body]

    return application
