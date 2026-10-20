"""Authentication and object access hooks; no model/storage/write grants implied."""
from dataclasses import dataclass
import hmac


class AccessError(Exception):
    def __init__(self, status, code):
        self.status = status
        self.code = code


@dataclass(frozen=True)
class Principal:
    subject: str
    method: str = "development-token"


def authenticate(environ, settings):
    header = environ.get("HTTP_AUTHORIZATION", "")
    scheme, _, credential = header.partition(" ")
    if (
        scheme.lower() != "bearer"
        or len(credential) > 256
        or not credential.isascii()
        or not hmac.compare_digest(credential, settings.token)
    ):
        raise AccessError(401, "authentication_required")
    # The server config determines identity; client identity headers have no authority.
    return Principal(settings.subject)


def require_owned_scope(connection, principal, scope_id):
    row = connection.execute(
        "SELECT id, label FROM foundation_scopes WHERE id = ? AND owner_subject = ?",
        (scope_id, principal.subject),
    ).fetchone()
    if row is None:
        # Missing and foreign objects intentionally have the same response.
        raise AccessError(404, "scope_not_found")
    return dict(row)
