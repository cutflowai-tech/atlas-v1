"""Migration bootstrap for the Reasoning V3 schema.

Migrations are SQL files in ``store/migrations`` named ``NNNN_<name>.sql`` and applied in numeric order, each in its own
transaction, under a PostgreSQL advisory lock so concurrent bootstraps apply each migration exactly once. ``schema_migrations``
records every applied file with its SHA-256; an applied file whose content later changes is refused (migrations are immutable:
change the schema with a new file). Running ``apply_migrations`` again is a no-op.

Number ranges keep parallel branches from colliding: ``0001``–``0099`` foundation (Phases 01–06), ``0100``–``0199`` reasoning,
update and lifecycle work (Phases 07–09, 15, 17–18), ``0200``–``0299`` memory, notes, questions, teachings and UI (Phases 10–14, 16).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas_reasoning.store.db import SCHEMA, Database, DatabaseError

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
# Arbitrary, fixed key for pg_advisory_xact_lock: "atlas reasoning migrations".
LOCK_KEY = 0x41746C6152534D47


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode()).hexdigest()


class MigrationError(DatabaseError):
    pass


def available_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    migrations = []
    for path in sorted(directory.glob("*.sql")):
        match = _NAME.match(path.name)
        if not match:
            raise MigrationError(f"migration file {path.name} does not match NNNN_<name>.sql")
        migrations.append(Migration(match.group(1), path.name, path.read_text()))
    versions = [migration.version for migration in migrations]
    if len(versions) != len(set(versions)):
        raise MigrationError(f"duplicate migration numbers in {directory}")
    return migrations


def _bootstrap(conn: Any) -> None:
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    conn.execute(f"SET LOCAL search_path TO {SCHEMA}, public")
    conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                        version    text PRIMARY KEY,
                        name       text NOT NULL,
                        checksum   text NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
                        applied_at timestamptz NOT NULL DEFAULT now())""")


def applied_migrations(db: Database) -> dict[str, dict[str, Any]]:
    with db.transaction() as conn:
        exists = conn.execute("SELECT to_regclass(%s) AS name", (f"{SCHEMA}.schema_migrations",)).fetchone()
        if not exists or exists["name"] is None:
            return {}
        return {row["version"]: row for row in conn.execute("SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version")}


def check_applied(applied: dict[str, dict[str, Any]], migrations: list[Migration]) -> list[str]:
    """Problems with already-applied migrations: changed content, or a recorded migration whose file is gone."""
    files = {migration.version: migration for migration in migrations}
    problems = []
    for version, row in applied.items():
        migration = files.get(version)
        if migration is None:
            problems.append(f"applied migration {row['name']} has no file")
        elif migration.checksum != row["checksum"] or migration.name != row["name"]:
            problems.append(f"applied migration {row['name']} was changed after it was applied")
    return problems


def pending_migrations(db: Database, migrations: list[Migration] | None = None) -> list[Migration]:
    migrations = available_migrations() if migrations is None else migrations
    applied = applied_migrations(db)
    return [migration for migration in migrations if migration.version not in applied]


def apply_migrations(db: Database, migrations: list[Migration] | None = None) -> list[str]:
    """Apply every pending migration in order; returns the names applied (empty when already up to date)."""
    migrations = available_migrations() if migrations is None else migrations
    applied_now: list[str] = []
    for migration in migrations:
        with db.transaction() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
            _bootstrap(conn)
            applied = {row["version"]: row for row in conn.execute("SELECT version, name, checksum FROM schema_migrations")}
            problems = check_applied(applied, migrations)
            if problems:
                raise MigrationError("; ".join(problems))
            if migration.version in applied:
                continue
            conn.execute(migration.sql)
            conn.execute("INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                         (migration.version, migration.name, migration.checksum))
            applied_now.append(migration.name)
    return applied_now
