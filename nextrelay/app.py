"""Minimal WSGI application. Only liveness and a static landing page are public."""
from http import HTTPStatus
import json
import logging
import sqlite3
from pathlib import Path

from .auth import AccessError, authenticate, require_owned_scope
from .db import SCHEMA_VERSION, connect, verify_schema
from .changes import ChangeError
from .formats import ImportFailure
from .http_api import BusinessAPI, cleanup_uploads

logger = logging.getLogger("nextrelay")


def create_app(settings):
    with connect(settings.database) as connection:
        verify_schema(connection)
    cleanup_uploads(settings)

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
            method = environ.get('REQUEST_METHOD','GET')
            path = environ.get("PATH_INFO", "")
            static = {'/':'index.html','/src/style.css':'src/style.css',
                **{'/src/'+f:'src/'+f for f in ('app.js','ux.js','reader-state.js','synthetic-adapter.js','workspace-adapter.js','local-adapter.js','local-ui.js','github-ui.js')}}
            if path in static:
                if method!='GET':raise AccessError(405,'method_not_allowed')
                payload=(Path(__file__).resolve().parents[1]/'frontend'/static[path]).read_bytes()
                if path=='/':payload=payload.replace(b'<head>',b'<head><meta name="nextrelay-mode" content="local">',1)
                content_type={'html':'text/html','css':'text/css','js':'text/javascript'}[static[path].rsplit('.',1)[1]]+'; charset=utf-8'
            elif path == "/health/live":
                if method!='GET':raise AccessError(405,'method_not_allowed')
                payload = {"status": "alive"}
            else:
                principal = authenticate(environ, settings)
                if path=='/api/workspace' or path=='/api/projects' or path.startswith(('/api/projects/','/api/requests/')):
                    payload=BusinessAPI(settings,principal).handle(environ,path,method)
                elif method!='GET':raise AccessError(405,'method_not_allowed')
                else:
                    payload=foundation(settings,principal,path)
        except (ChangeError,ImportFailure) as error:
            status,payload=409,{'error':error.code}
        except (ValueError,TypeError,KeyError,RecursionError):
            status,payload=400,{'error':'invalid_request'}
        except AccessError as error:
            status, payload = error.status, {"error": error.code}
            if status == 401:
                extra_headers.append(("WWW-Authenticate", 'Bearer realm="NextRelay-development"'))
            if status == 405:
                extra_headers.append(("Allow", "GET, POST"))
        except (sqlite3.Error, RuntimeError, OSError):
            logger.error("storage_unavailable")
            status, payload = 503, {"error": "storage_unavailable"}

        body = payload if isinstance(payload,bytes) else (
            payload.encode("utf-8") if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )
        csp="default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        if content_type.startswith(('text/html','text/css','text/javascript')):
            csp="default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        headers = [
            ("Content-Type", content_type), ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"), ("Content-Security-Policy", csp),
        ]
        start_response(f"{status} {HTTPStatus(status).phrase}", headers + extra_headers)
        return [body]

    return application


def foundation(settings,principal,path):
    with connect(settings.database) as connection:
        if path == '/api/foundation':
            verify_schema(connection)
            connection.execute('SELECT 1').fetchone()
            return {'stage':'T11-local-subset',
                    'identity':{'subject':principal.subject,'method':principal.method},
                    'storage':{'engine':'sqlite','schema_version':SCHEMA_VERSION},
                    'model':{'enabled':bool(settings.model and settings.model.provider!='disabled')},'data':'synthetic-only'}
        if path.startswith('/api/foundation/scopes/'):
            return require_owned_scope(connection,principal,path.removeprefix('/api/foundation/scopes/'))
        raise AccessError(404,'route_not_found')
