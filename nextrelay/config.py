"""Fail-closed configuration for synthetic local development only."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import sqlite3
import sys


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    database: Path
    token: str = field(repr=False)
    subject: str = "dev-synthetic-user"
    host: str = "127.0.0.1"
    port: int = 8000
    environment: str = "development"
    auth_mode: str = "dev-token"
    local_root: Path | None = None
    model: object = None
    github: object = None  # code-only controlled test injection; no env endpoint

    def __post_init__(self):
        if sys.version_info[:2] != (3, 14):
            raise ConfigError("T02 requires Python 3.14.x")
        if sqlite3.sqlite_version_info < (3, 37, 0):
            raise ConfigError("SQLite >= 3.37 is required for STRICT tables")
        if self.environment != "development" or self.auth_mode != "dev-token":
            raise ConfigError("Only explicit development/dev-token mode is implemented")
        if self.host != "127.0.0.1":
            raise ConfigError("Development server must bind to 127.0.0.1")
        if not 1 <= self.port <= 65535:
            raise ConfigError("Port must be between 1 and 65535")
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", self.token):
            raise ConfigError("Set a freshly generated URL-safe dev token (32-256 characters)")
        if self.subject == "dev-other-user" or not re.fullmatch(r"dev-[a-z0-9-]{1,64}", self.subject):
            raise ConfigError("Development subject must use a dev- synthetic identifier")
        if not self.database.is_absolute() or str(self.database).startswith(("\\", "//")):
            raise ConfigError("Database must be an absolute local path")
        project = Path(__file__).resolve().parents[1]
        resolved = self.database.resolve()
        if resolved.is_relative_to(project):
            raise ConfigError("Keep the live database outside the project/sync directory")
        for key in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            sync_root = os.environ.get(key)
            if sync_root and resolved.is_relative_to(Path(sync_root).resolve()):
                raise ConfigError("Live SQLite database must be outside OneDrive")
        if self.local_root is not None:
            from .localfiles import absolute
            from .formats import ImportFailure
            try:
                root = absolute(self.local_root).resolve()
            except ImportFailure:
                raise ConfigError('Storage directory must be an absolute local path') from None
            if root.is_relative_to(project) or any(
                os.environ.get(k) and root.is_relative_to(Path(os.environ[k]).resolve())
                for k in ('OneDrive','OneDriveConsumer','OneDriveCommercial')
            ):
                raise ConfigError('Keep originals outside project/sync directories')
            if not root.is_dir():
                raise ConfigError('Create the explicitly selected local storage directory first')


def load_settings(environ=None):
    env = os.environ if environ is None else environ
    local = Path(env.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
    database = Path(env.get("NEXTRELAY_DB_PATH", str(local / "NextRelay" / "dev.sqlite3")))
    try:
        port = int(env.get("NEXTRELAY_PORT", "8000"))
    except ValueError:
        raise ConfigError("NEXTRELAY_PORT must be an integer") from None
    from .model_provider import ModelConfig
    try:
        model=ModelConfig(provider=env.get('NEXTRELAY_MODEL_PROVIDER','disabled'),
            model=env.get('NEXTRELAY_MODEL_NAME',''),
            api_key=env.get('NEXTRELAY_MODEL_API_KEY',''),
            endpoint=env.get('NEXTRELAY_MODEL_ENDPOINT','https://api.openai.com/v1/responses'))
    except ValueError:
        raise ConfigError('Invalid server model configuration; consult README') from None
    return Settings(
        database=database,
        model=model,
        token=env.get("NEXTRELAY_DEV_TOKEN", ""),
        subject=env.get("NEXTRELAY_DEV_SUBJECT", "dev-synthetic-user"),
        host=env.get("NEXTRELAY_HOST", "127.0.0.1"),
        port=port,
        environment=env.get("NEXTRELAY_ENV", ""),
        auth_mode=env.get("NEXTRELAY_AUTH_MODE", ""),
        local_root=Path(env['NEXTRELAY_LOCAL_ROOT']) if env.get('NEXTRELAY_LOCAL_ROOT') else None,
    )
