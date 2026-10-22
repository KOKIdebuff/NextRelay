"""Local transactional storage and atomic, explicit schema upgrades."""
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import sqlite3
import re

from .schema import MIGRATIONS

SCHEMA_VERSION = 7


class SchemaError(RuntimeError):
    pass


@contextmanager
def connect(database: Path):
    connection = sqlite3.connect(database, autocommit=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute('PRAGMA synchronous = FULL')
        connection.execute('PRAGMA trusted_schema = OFF')
        yield connection
    finally:
        connection.close()


@contextmanager
def transaction(connection, *, write=True):
    if connection.in_transaction:
        raise RuntimeError('Nested transactions require an explicit future savepoint policy')
    connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
    try:
        yield connection
        connection.execute('COMMIT')
    except BaseException:
        if connection.in_transaction:
            connection.execute('ROLLBACK')
        raise


def _normalize_sql(sql):
    # SQLite ALTER TABLE may quote identifiers even after renaming back.
    return ' '.join(re.sub(r'"([a-z_]+)"', lambda match: match.group(1), sql).split())


def _catalog(connection):
    return tuple(tuple(row) for row in connection.execute(
        "SELECT type, name, sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ))


@lru_cache(maxsize=1)
def _target_catalog():
    return _version_catalog(SCHEMA_VERSION)


@lru_cache(maxsize=4)
def _version_catalog(target_version):
    connection = sqlite3.connect(':memory:', autocommit=True)
    try:
        for version in range(1, target_version + 1):
            for statement in MIGRATIONS[version]:
                connection.execute(statement)
        return _catalog(connection)
    finally:
        connection.close()


def _verify_v1(connection):
    columns = connection.execute('PRAGMA table_info(foundation_scopes)').fetchall()
    if [(row['name'], row['type'], row['pk']) for row in columns] != [
        ('id', 'TEXT', 1), ('owner_subject', 'TEXT', 0), ('label', 'TEXT', 0)
    ]:
        raise SchemaError('Unexpected foundation schema')
    # The original T02 DDL allowed a nullable TEXT primary key; preserve it unchanged.
    actual = connection.execute("SELECT sql FROM sqlite_schema WHERE name = 'foundation_scopes'").fetchone()[0]
    compact = lambda value: _normalize_sql(value).lower()
    if compact(actual) != compact(MIGRATIONS[1][0]):
        raise SchemaError('Unexpected foundation constraints')


def initialize(database: Path):
    database.parent.mkdir(parents=True, exist_ok=True)
    with connect(database) as connection:
        with transaction(connection):
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version > SCHEMA_VERSION:
                raise SchemaError('Database is newer than this application')
            if version == 0 and connection.execute(
                "SELECT 1 FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
            ).fetchone():
                raise SchemaError('Refusing to initialize a nonempty unversioned database')
            if version >= 1:
                _verify_v1(connection)
            if 2 <= version < SCHEMA_VERSION:
                # Rebuilding a table must not silently repair/adopt an unrecognized old constraint.
                actual = {(kind,name):_normalize_sql(sql) for kind,name,sql in _catalog(connection)}
                if any(actual.get((kind,name)) != _normalize_sql(sql) for kind,name,sql in _version_catalog(version)):
                    raise SchemaError('Unexpected source schema; refusing migration')
            for target in range(version + 1, SCHEMA_VERSION + 1):
                for statement in MIGRATIONS[target]:
                    # executescript would implicitly interfere with explicit transaction control.
                    connection.execute(statement)
                connection.execute(f'PRAGMA user_version = {target}')
            verify_schema(connection)
            if connection.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise SchemaError('Foreign key violation in database')
            if version < 4:
                from .auth import Principal
                from .store import Store
                from .lifecycle import Lifecycle
                for project in connection.execute('SELECT * FROM projects').fetchall():
                    Lifecycle(Store(connection,Principal(project['owner_subject']),True)).sync(project['id'],project['revision'])


def verify_schema(connection):
    if connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
        raise SchemaError('Initialize or upgrade the database before starting the server')
    # Validate tables, constraints, indexes AND immutability triggers, not just a version tag.
    # Normalize whitespace to accept the byte-identical T02 schema with its old indentation.
    normalize = lambda rows: tuple((kind, name, _normalize_sql(sql)) for kind, name, sql in rows)
    if normalize(_catalog(connection)) != normalize(_target_catalog()):
        raise SchemaError('Unexpected database structure')


def seed_synthetic(database: Path, subject: str):
    """Opt-in foundation fixtures; never create Project/Task or real user data."""
    with connect(database) as connection:
        with transaction(connection):
            verify_schema(connection)
            if subject == 'dev-other-user':
                raise ValueError('Reserved synthetic fixture subject')
            for scope_id, owner in (('synthetic-owned', subject), ('synthetic-foreign', 'dev-other-user')):
                existing = connection.execute(
                    'SELECT owner_subject FROM foundation_scopes WHERE id = ?', (scope_id,)
                ).fetchone()
                if existing is not None and existing['owner_subject'] != owner:
                    raise SchemaError('Fixture owner differs; use a separate development database')
                connection.execute(
                    'INSERT OR IGNORE INTO foundation_scopes(id, owner_subject, label) VALUES (?, ?, ?)',
                    (scope_id, owner, 'synthetic-access-fixture'),
                )
