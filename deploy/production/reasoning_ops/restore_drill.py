"""Logical backup of the canonical Reasoning V3 schema, and the **isolated** restore drill (Phase 20-B).

    python deploy/production/reasoning_ops/restore_drill.py drill --source-url URL --target-url URL [--release release.json] [--out DIR]
    python deploy/production/reasoning_ops/restore_drill.py backup --source-url URL --out DIR [--release release.json]
    python deploy/production/reasoning_ops/restore_drill.py restore --backup DIR --target-url URL

What it is: the procedure ``docs/REASONING-V3-RECOVERY.md`` §2 prescribes, executable against **disposable test databases only**. A drill
result proves that this repository's backup format restores into a healthy, fully migrated Reasoning V3 schema with every canonical row
intact. It is *not* evidence that a production backup or restore works: the production backup is taken and restored by an approved
operator on the approved hosts, under live-rollout approval.

Backup (``backup``):

* ``pg_dump --format=custom --schema=atlas_reasoning`` — the whole canonical schema: every table (results, versions, history, lifecycle,
  ExecutiveBrief history, human context, audit, ``schema_migrations``), schema and data. The deterministic Atlas data root and secrets are
  separate backups (``docs/PRODUCTION-RUNBOOK.md`` §10) and are never in this artifact.
* ``manifest.json`` beside it: the artifact's sha256 and size, the server and ``pg_dump`` versions, the applied migrations (version, name,
  checksum), per-table canonical fingerprints (row count + sha256 of the rows' text in a total order) and the non-secret release record
  supplied by the operator. Never a URL, password or key.
* Files are created ``0600`` in a ``0700`` directory. Encryption at rest is the approved backup store's (the procedure requires it).

Restore (``restore``): the target must be a disposable test database (the Phase 19 evaluation guard: libpq-resolved name with the word
``test``, never ``ATLAS_REASONING_DATABASE_URL``). The schema is dropped and the artifact restored with ``pg_restore --exit-on-error``,
after its sha256 matches the manifest. Then it verifies: ``database_health`` ok; the restored ``schema_migrations`` equals the manifest and
the code's migrations (no pending, no changed checksum); ``apply_migrations`` applies nothing (replay is idempotent); every table's
fingerprint equals the manifest.

Exit: 0 drill/restore verified, 1 verification failed, 2 refused (configuration, guard, missing tools), 3 an error (tool timeout, malformed
manifest, driver error; only the error class is printed). Output is one JSON object; it never contains a database URL or credential.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas_reasoning.evaluation_runner import EvaluationConfigurationError, check_disposable
from atlas_reasoning.store.db import SCHEMA, Database, DatabaseError, redact_url
from atlas_reasoning.store.health import database_health
from atlas_reasoning.store.migrate import apply_migrations, available_migrations

DRILL_LABEL = "isolated restore drill: disposable test databases and synthetic data only; not a production backup or restore test"
MANIFEST_SCHEMA = "reasoning-backup-manifest-v1"
DUMP_NAME = "atlas_reasoning.dump"
MANIFEST_NAME = "manifest.json"
# Release-record values are identifiers only (SHA, digests, versions): a value that looks like a URL with credentials or a key is refused.
_RELEASE_VALUE = re.compile(r"^[A-Za-z0-9._:/@+=-]{1,200}$")
_SECRET_LIKE = re.compile(r"(?i)(://[^/\s]*:[^@/\s]*@|sk-or-|bearer\s|password|secret|token|api[_-]?key)")


class DrillRefused(Exception):
    """The drill/backup/restore cannot run safely (guard, tools, configuration). Exit 2."""


@dataclass(frozen=True)
class Tools:
    pg_dump: str
    pg_restore: str


def find_tools(env: Mapping[str, str]) -> Tools:
    """``pg_dump`` / ``pg_restore`` from ``ATLAS_RESTORE_DRILL_PG_BIN`` (a directory) or PATH."""
    directory = env.get("ATLAS_RESTORE_DRILL_PG_BIN", "").strip()
    found = []
    for name in ("pg_dump", "pg_restore"):
        path = shutil.which(name, path=directory or None) if directory else shutil.which(name)
        if not path:
            raise DrillRefused(f"{name} not found (set ATLAS_RESTORE_DRILL_PG_BIN to a PostgreSQL client bin directory)")
        found.append(path)
    return Tools(*found)


def _major(text: str) -> int:
    match = re.search(r"(\d+)(?:\.\d+)?", text)
    if not match:
        raise DrillRefused("cannot read a PostgreSQL version")
    return int(match.group(1))


def tool_version(path: str) -> str:
    output = subprocess.run([path, "--version"], check=True, capture_output=True, text=True, timeout=30).stdout.strip()
    match = re.search(r"\b(\d+(?:\.\d+)+|\d+)\b", output.split(")", 1)[-1] if ")" in output else output)    # "pg_dump (PostgreSQL) 17.11 (Homebrew)"
    return match.group(1) if match else ""


def server_version(db: Database) -> str:
    with db.transaction() as conn:
        row = conn.execute("SELECT current_setting('server_version') AS version").fetchone()
    return str((row or {}).get("version", ""))


def check_tools(tools: Tools, db: Database) -> dict[str, str]:
    """pg_dump refuses a newer server; refuse early with a clear message instead of a partial artifact."""
    versions = {"pg_dump": tool_version(tools.pg_dump), "pg_restore": tool_version(tools.pg_restore), "server": server_version(db)}
    if _major(versions["pg_dump"]) < _major(versions["server"]) or _major(versions["pg_restore"]) < _major(versions["server"]):
        raise DrillRefused(f"PostgreSQL client tools {versions['pg_dump']} are older than the server {versions['server']}")
    return versions


def guard(url: str, env: Mapping[str, str], role: str) -> str:
    """The Phase 19 disposable-database guard, plus: the URL states its host, port and database itself (libpq would otherwise fill them
    from ``PG*`` variables, so the tool's own connections and pg_dump/pg_restore could reach different servers), and carries no
    ``sslpassword`` (it would land on a command line)."""
    try:
        check_disposable(url, env)
    except EvaluationConfigurationError as error:
        raise DrillRefused(f"{role}: {error}") from None
    from atlas_reasoning.store.evaluation_scenario import connection_target

    target = connection_target(url)
    if not (target.get("host") or target.get("hostaddr")) or not target.get("port") or not target.get("dbname"):
        raise DrillRefused(f"{role}: the URL must state its host, port and database explicitly")
    if "sslpassword" in target:
        raise DrillRefused(f"{role}: sslpassword is not supported in drill URLs")
    return url


def _connection(url: str) -> tuple[str, dict[str, str]]:
    """``--dbname`` conninfo **without** the password, and the child environment carrying it as ``PGPASSWORD``: the password never appears
    on a command line (``ps``). No inherited ``PG*`` variable may redirect the tools to another database."""
    from atlas_reasoning.store.evaluation_scenario import connection_target

    target = connection_target(url)
    password = target.pop("password", None)
    conninfo = " ".join(f"{key}='{value.replace(chr(92), chr(92) * 2).replace(chr(39), chr(92) + chr(39))}'" for key, value in sorted(target.items()))
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")} | {"PGCONNECT_TIMEOUT": "10"}
    if password:
        env["PGPASSWORD"] = password
    return conninfo, env


def _run(command: Sequence[str], url: str, *, timeout: int = 900) -> None:
    conninfo, env = _connection(url)
    argv = [part.replace("{dbname}", conninfo) for part in command]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env, check=False)   # exit status reported below
    if result.returncode != 0:
        # The tools' stderr can echo connection details: report only the tool and its exit status.
        raise DrillRefused(f"{Path(command[0]).name} exited {result.returncode}")


# --- canonical fingerprints (read-only) ----------------------------------------------------------------------------------------------


def canonical_tables(db: Database) -> list[str]:
    with db.transaction() as conn:
        rows = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_type = 'BASE TABLE' "
                            "ORDER BY table_name", (SCHEMA,)).fetchall()
    return [str(row["table_name"]) for row in rows]


def fingerprints(db: Database) -> dict[str, dict[str, Any]]:
    """Per table: row count and sha256 of every row's text in a total order. Equal fingerprints = equal canonical content."""
    out: dict[str, dict[str, Any]] = {}
    with db.transaction() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        # A fixed text form, whatever the server's defaults: a restore onto another server must fingerprint identically.
        for setting in ("SET LOCAL TimeZone = 'UTC'", "SET LOCAL DateStyle = 'ISO, YMD'", "SET LOCAL IntervalStyle = 'postgres'",
                        "SET LOCAL extra_float_digits = 3", "SET LOCAL bytea_output = 'hex'"):
            conn.execute(setting)
        for table in [str(r["table_name"]) for r in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY table_name",
                (SCHEMA,)).fetchall()]:
            digest, count = hashlib.sha256(), 0
            for row in conn.execute(f'SELECT t::text AS row FROM "{SCHEMA}"."{table}" t ORDER BY t::text COLLATE "C"'):
                digest.update(str(row["row"]).encode())
                digest.update(b"\n")
                count += 1
            out[table] = {"rows": count, "sha256": digest.hexdigest()}
    return out


SCHEMA_OBJECTS = {
    "triggers": "SELECT c.relname || '.' || t.tgname AS name, pg_get_triggerdef(t.oid) AS def FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = %s AND NOT t.tgisinternal",
    "functions": "SELECT p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')' AS name, pg_get_functiondef(p.oid) AS def "
                 "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = %s",
    "constraints": "SELECT c.relname || '.' || k.conname AS name, pg_get_constraintdef(k.oid) AS def FROM pg_constraint k "
                   "JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = %s",
    "indexes": "SELECT tablename || '.' || indexname AS name, indexdef AS def FROM pg_indexes WHERE schemaname = %s",
}


def schema_objects(db: Database) -> dict[str, dict[str, Any]]:
    """Count and sha256 of every trigger, function, constraint and index definition of the schema: the append-only triggers and
    integrity constraints the rollback guarantees rely on must survive a restore, not only the rows."""
    out: dict[str, dict[str, Any]] = {}
    with db.transaction() as conn:
        for kind, sql in SCHEMA_OBJECTS.items():
            rows = sorted((str(r["name"]), str(r["def"])) for r in conn.execute(sql, (SCHEMA,)).fetchall())
            out[kind] = {"count": len(rows), "sha256": hashlib.sha256("\n".join(f"{n}\t{d}" for n, d in rows).encode()).hexdigest()}
    return out


def applied(db: Database) -> list[dict[str, str]]:
    with db.transaction() as conn:
        rows = conn.execute("SELECT version, name, checksum FROM schema_migrations ORDER BY version").fetchall()
    return [{"version": str(row["version"]), "name": str(row["name"]), "checksum": str(row["checksum"])} for row in rows]


# --- release record -----------------------------------------------------------------------------------------------------------------


def load_release(path: Path | None) -> dict[str, str]:
    """The operator's non-secret release record (integration SHA, image digests, model, prompt / contract / migration versions)."""
    if path is None:
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DrillRefused(f"cannot read the release record: {type(error).__name__}") from None
    if not isinstance(document, dict):
        raise DrillRefused("the release record must be a JSON object")
    record = {}
    for key, value in document.items():
        text = str(value)
        if not isinstance(key, str) or not _RELEASE_VALUE.match(text) or _SECRET_LIKE.search(f"{key}={text}"):
            raise DrillRefused(f"release record field {str(key)[:40]!r} is not a plain identifier (no URLs with credentials, keys or secrets)")
        record[key] = text
    return dict(sorted(record.items()))


# --- backup / restore ---------------------------------------------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def backup(source_url: str, out: Path, *, env: Mapping[str, str], release: Mapping[str, str] | None = None) -> dict[str, Any]:
    guard(source_url, env, "source")
    db = Database(source_url)
    health = database_health(db)
    if not health["ok"]:
        raise DrillRefused("the source database is not healthy (pending or changed migrations, or missing tables): refusing to back it up")
    tools = find_tools(env)
    versions = check_tools(tools, db)
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(out, 0o700)
    dump = out / DUMP_NAME
    before = fingerprints(db)
    old_umask = os.umask(0o077)
    try:
        _run([tools.pg_dump, "--format=custom", f"--schema={SCHEMA}", "--no-owner", "--no-privileges", f"--file={dump}", "--dbname={dbname}"],
             source_url)
    finally:
        os.umask(old_umask)
    after = fingerprints(db)
    if before != after:
        raise DrillRefused("the source changed while it was being backed up: stop writers (reasoning, memory sync, web writes) and retry")
    manifest = {"schema": MANIFEST_SCHEMA, "label": DRILL_LABEL, "artifact": {"file": DUMP_NAME, "sha256": _sha256(dump), "bytes": dump.stat().st_size,
                                                                            "format": "pg_dump custom", "pg_schema": SCHEMA},
                "versions": versions, "migrations": applied(db), "tables": after, "schema_objects": schema_objects(db),
                "release": dict(release or {})}
    manifest_path = out / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(manifest_path, 0o600)
    os.chmod(dump, 0o600)
    return manifest


def load_manifest(directory: Path) -> dict[str, Any]:
    try:
        manifest = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DrillRefused(f"cannot read {MANIFEST_NAME}: {type(error).__name__}") from None
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise DrillRefused(f"{MANIFEST_NAME} is not a {MANIFEST_SCHEMA} document")
    return manifest


def restore(directory: Path, target_url: str, *, env: Mapping[str, str]) -> dict[str, Any]:
    """Restore into the disposable target and verify it. Returns the verification report (``ok`` = everything verified)."""
    guard(target_url, env, "target")
    manifest = load_manifest(directory)
    dump = directory / str(manifest["artifact"]["file"])
    if not dump.is_file() or _sha256(dump) != manifest["artifact"]["sha256"]:
        raise DrillRefused("the backup artifact is missing or does not match its manifest sha256")
    db = Database(target_url)
    tools = find_tools(env)
    check_tools(tools, db)
    with db.transaction() as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    _run([tools.pg_restore, "--exit-on-error", "--no-owner", "--no-privileges", "--dbname={dbname}", str(dump)], target_url)
    return verify(db, manifest)


def verify(db: Database, manifest: Mapping[str, Any]) -> dict[str, Any]:
    health = database_health(db)
    restored_migrations = applied(db)
    code_migrations = [{"version": str(m.version), "name": m.name} for m in available_migrations()]
    replay = apply_migrations(db)                                  # must apply nothing: the restored schema is current
    restored = fingerprints(db)
    objects = schema_objects(db)
    expected = manifest["tables"]
    differing = sorted(table for table in set(expected) | set(restored) if expected.get(table) != restored.get(table))
    checks = {
        "database_health_ok": bool(health["ok"]),
        "migrations_match_manifest": restored_migrations == manifest["migrations"],
        "migrations_match_code": [{"version": m["version"], "name": m["name"]} for m in restored_migrations] == code_migrations,
        "migration_replay_applied_nothing": replay == [],
        "canonical_tables_identical": not differing,
        "schema_objects_identical": objects == manifest.get("schema_objects"),
        "release_metadata_inspectable": isinstance(manifest.get("release"), dict),
    }
    return {"ok": all(checks.values()), "label": DRILL_LABEL, "checks": checks, "differing_tables": differing,
            "tables": len(restored), "rows": sum(int(t["rows"]) for t in restored.values()),
            "health": {key: health.get(key) for key in ("ok", "pending", "problems", "missing_tables", "server_version")},
            "release": manifest.get("release", {})}


def drill(source_url: str, target_url: str, *, env: Mapping[str, str], out: Path | None = None,
          release: Mapping[str, str] | None = None) -> dict[str, Any]:
    if _same_target(source_url, target_url):
        raise DrillRefused("source and target must be different disposable databases")
    with tempfile.TemporaryDirectory(prefix="reasoning-restore-drill-") as scratch:
        directory = out or Path(scratch) / "backup"
        manifest = backup(source_url, directory, env=env, release=release)
        report = restore(directory, target_url, env=env)
    report["backup"] = {"sha256": manifest["artifact"]["sha256"], "bytes": manifest["artifact"]["bytes"], "versions": manifest["versions"]}
    return report


def _same_target(a: str, b: str) -> bool:
    """Conservative (the evaluation guard's comparison): same database name and port, hosts equal, unstated or both local."""
    from atlas_reasoning.evaluation_runner import _same_database
    from atlas_reasoning.store.evaluation_scenario import connection_target

    return _same_database(connection_target(a), connection_target(b))


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    environment = dict(os.environ if env is None else env)
    for name in [key for key in os.environ if key.startswith("PG")]:      # libpq defaults never redirect the drill's own connections
        del os.environ[name]
    parser = argparse.ArgumentParser(prog="restore_drill", description=DRILL_LABEL)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("drill", "backup"):
        command = sub.add_parser(name)
        command.add_argument("--source-url", required=True)
        command.add_argument("--release", type=Path)
        command.add_argument("--out", type=Path, required=name == "backup")
        if name == "drill":
            command.add_argument("--target-url", required=True)
    restore_command = sub.add_parser("restore")
    restore_command.add_argument("--backup", type=Path, required=True)
    restore_command.add_argument("--target-url", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    import psycopg

    try:
        if args.action == "backup":
            manifest = backup(args.source_url, args.out, env=environment, release=load_release(args.release))
            result: dict[str, Any] = {"ok": True, "label": DRILL_LABEL, "artifact": manifest["artifact"], "tables": len(manifest["tables"])}
        elif args.action == "restore":
            result = restore(args.backup, args.target_url, env=environment)
        else:
            result = drill(args.source_url, args.target_url, env=environment, out=args.out, release=load_release(args.release))
    except (DrillRefused, DatabaseError) as error:
        print(json.dumps({"ok": False, "label": DRILL_LABEL, "refused": _safe(str(error), args)}, sort_keys=True))
        return 2
    except (subprocess.SubprocessError, OSError, KeyError, TypeError, ValueError, psycopg.Error) as error:
        # A tool timeout, an unreadable or malformed manifest, a driver error: an error (3), distinct from a failed verification (1).
        print(json.dumps({"ok": False, "label": DRILL_LABEL, "error": type(error).__name__}, sort_keys=True))
        return 3
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("ok") else 1


def _safe(message: str, args: argparse.Namespace) -> str:
    for url in (getattr(args, "source_url", None), getattr(args, "target_url", None)):
        if url:
            message = message.replace(url, redact_url(url))
    return message


if __name__ == "__main__":
    sys.exit(main())
