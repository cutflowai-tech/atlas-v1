"""Conservative bounded retention for Atlas-owned operational evidence.

Only strictly named Atlas objects are candidates. Unknown objects, symlinks, incomplete work and
ambiguous/corrupt references are never removed. The public entry point takes the production lock;
scheduled runs use the private already-locked entry point after publish and status succeeded.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from atlas_commander.ingest import RUN_ID_PATTERN, Clock, utc_now

from .config import ConfigError, SyncConfig, load_sync_config
from .lock import LockError, OperationLocked, production_lock
from .publish import CURRENT_METADATA_NAME, HISTORY_DIR, HISTORY_PATTERN, live_attempt
from .run import ATTEMPTS_DIR, BUILD_METADATA_NAME, COMPLETE_NAME, FAILED_NAME

RETENTION_VERSION = "atlas-retention-v1"
KINDS = ("raw_runs", "builds", "attempt_records", "publication_history", "scheduled_cycles")
TERMINAL_ATTEMPT_STATUSES = {"success", "failed"}
TERMINAL_CYCLE_PHASES = {"final", "outcome"}
_CYCLE_FILE = re.compile(r"^(\d{8}T\d{6}Z-[0-9a-f]{12})(?:\.(started|outcome))?\.json$")


@dataclass
class RetentionReport:
    generated_at: str
    cutoff_at: str
    retention_hours: int
    dry_run: bool
    status: str = "completed"
    scanned: dict[str, dict[str, int]] = field(default_factory=dict)
    eligible: dict[str, dict[str, int]] = field(default_factory=dict)
    deleted: dict[str, dict[str, int]] = field(default_factory=dict)
    protected_reasons: dict[str, dict[str, int]] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    retention_version: str = RETENTION_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _Object:
    kind: str
    key: str
    paths: tuple[Path, ...]
    moment: datetime
    size: int


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _id_time(value: str) -> datetime | None:
    if not RUN_ID_PATTERN.fullmatch(value):
        return None
    try:
        return datetime.strptime(value[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _tree_size(path: Path) -> int:
    if path.is_symlink():
        return 0
    if path.is_file():
        try:
            return path.stat(follow_symlinks=False).st_size
        except OSError:
            return 0
    total = 0
    try:
        for root, directories, files in os.walk(path, followlinks=False):
            base = Path(root)
            directories[:] = [name for name in directories if not (base / name).is_symlink()]
            for name in files:
                child = base / name
                if not child.is_symlink():
                    try:
                        total += child.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
    except OSError:
        pass
    return total


def _contains_symlink(path: Path) -> bool:
    if path.is_symlink():
        return True
    if not path.is_dir():
        return False
    try:
        return any(child.is_symlink() for child in path.rglob("*"))
    except OSError:
        return True


def _safe_under(path: Path, root: Path) -> bool:
    try:
        return not path.is_symlink() and path.parent.resolve() == root.resolve()
    except (OSError, RuntimeError):
        return False


def _measure(objects: list[_Object]) -> dict[str, dict[str, int]]:
    result = {kind: {"count": 0, "bytes": 0} for kind in KINDS}
    for item in objects:
        result[item.kind]["count"] += 1
        result[item.kind]["bytes"] += item.size
    return result


def _protect(reasons: dict[tuple[str, str], set[str]], kind: str, key: str, reason: str) -> None:
    reasons[(kind, key)].add(reason)


def _scan(config: SyncConfig, now: datetime) -> tuple[list[_Object], dict[tuple[str, str], set[str]], list[str]]:
    """Return known objects, protection reasons, and fail-closed scan diagnostics."""
    roots = {
        "raw_runs": config.raw_dir.expanduser().resolve(),
        "builds": config.build_dir.expanduser().resolve(),
        "publication_history": config.publish_dir.expanduser().resolve() / HISTORY_DIR,
        "scheduled_cycles": (config.lock_dir.expanduser().resolve() / "scheduled-cycles") if config.lock_dir else None,
    }
    objects: list[_Object] = []
    reasons: dict[tuple[str, str], set[str]] = defaultdict(set)
    failures: list[str] = []
    records: dict[str, dict[str, Any] | None] = {}
    builds: dict[str, dict[str, Any] | None] = {}
    histories: list[tuple[_Object, dict[str, Any] | None, int]] = []

    # Raw runs: a recognized directory must carry a self-identifying manifest. Anything else is unknown.
    raw_root = config.raw_dir.expanduser().resolve()
    if raw_root.is_dir():
        for path in sorted(raw_root.iterdir(), key=lambda item: item.name):
            moment = _id_time(path.name)
            if moment is None or not path.is_dir() or path.is_symlink():
                failures.append("unknown_or_unsafe_raw_object")
                continue
            item = _Object("raw_runs", path.name, (path,), moment, _tree_size(path))
            objects.append(item)
            manifest = _json(path / "manifest.json")
            if manifest is None or (manifest.get("run") or {}).get("run_id") != path.name or _contains_symlink(path):
                _protect(reasons, item.kind, item.key, "corrupt_or_unsafe")

    # Attempt records are independent evidence and may exist without a build.
    attempts_root = config.build_dir.expanduser().resolve() / ATTEMPTS_DIR
    if attempts_root.is_dir():
        for path in sorted(attempts_root.iterdir(), key=lambda item: item.name):
            key = path.stem if path.suffix == ".json" else ""
            moment = _id_time(key)
            if moment is None or not path.is_file() or path.is_symlink():
                failures.append("unknown_or_unsafe_attempt_object")
                continue
            item = _Object("attempt_records", key, (path,), moment, _tree_size(path))
            objects.append(item)
            record = _json(path)
            records[key] = record
            if record is None or record.get("attempt_id") != key or record.get("status") not in TERMINAL_ATTEMPT_STATUSES:
                _protect(reasons, item.kind, item.key, "active_incomplete_or_corrupt")
            elif record.get("source_run_id") is not None:
                source_id = record.get("source_run_id")
                expected = str(config.raw_dir.expanduser().resolve() / str(source_id))
                if not isinstance(source_id, str) or not RUN_ID_PATTERN.fullmatch(source_id) \
                        or record.get("raw_run_dir") != expected:
                    _protect(reasons, item.kind, item.key, "unsafe_source_reference")

    build_root = config.build_dir.expanduser().resolve()
    if build_root.is_dir():
        for path in sorted(build_root.iterdir(), key=lambda item: item.name):
            if path.name == ATTEMPTS_DIR:
                continue
            moment = _id_time(path.name)
            if moment is None or not path.is_dir() or path.is_symlink():
                failures.append("unknown_or_unsafe_build_object")
                continue
            item = _Object("builds", path.name, (path,), moment, _tree_size(path))
            objects.append(item)
            metadata = _json(path / BUILD_METADATA_NAME)
            builds[path.name] = metadata
            complete, failed = (path / COMPLETE_NAME).is_file(), (path / FAILED_NAME).is_file()
            if (complete == failed) or metadata is None or (metadata.get("attempt") or {}).get("attempt_id") != path.name or _contains_symlink(path):
                _protect(reasons, item.kind, item.key, "active_incomplete_or_corrupt")
            elif metadata is not None:
                source = metadata.get("source") or {}
                source_id = source.get("run_id")
                expected = str(config.raw_dir.expanduser().resolve() / str(source_id))
                if not isinstance(source_id, str) or not RUN_ID_PATTERN.fullmatch(source_id) or source.get("raw_run_dir") != expected:
                    _protect(reasons, item.kind, item.key, "unsafe_source_reference")
            if path.name not in records:
                _protect(reasons, item.kind, item.key, "missing_attempt_record")

    history_root = roots["publication_history"]
    if history_root and history_root.is_dir():
        for path in sorted(history_root.iterdir(), key=lambda item: item.name):
            match = HISTORY_PATTERN.fullmatch(path.name)
            if match is None or not path.is_file() or path.is_symlink():
                failures.append("unknown_or_unsafe_publication_object")
                continue
            publication_id = match.group(2)
            moment = _id_time(publication_id)
            if moment is None:
                failures.append("unknown_or_unsafe_publication_object")
                continue
            item = _Object("publication_history", path.name, (path,), moment, _tree_size(path))
            document = _json(path)
            objects.append(item)
            histories.append((item, document, int(match.group(1))))
            if document is None or document.get("publication_id") != publication_id or document.get("sequence") != int(match.group(1)):
                _protect(reasons, item.kind, item.key, "corrupt_or_ambiguous")

    cycle_root = roots["scheduled_cycles"]
    cycle_files: dict[str, list[Path]] = defaultdict(list)
    if cycle_root and cycle_root.is_dir():
        for path in sorted(cycle_root.iterdir(), key=lambda item: item.name):
            match = _CYCLE_FILE.fullmatch(path.name)
            if match is None or not path.is_file() or path.is_symlink():
                failures.append("unknown_or_unsafe_scheduled_object")
                continue
            cycle_files[match.group(1)].append(path)
        for key, paths in sorted(cycle_files.items()):
            moment = _id_time(key)
            if moment is None:
                continue
            item = _Object("scheduled_cycles", key, tuple(sorted(paths)), moment, sum(_tree_size(path) for path in paths))
            objects.append(item)
            docs = [_json(path) for path in paths]
            phases = {doc.get("record_phase") for doc in docs if doc is not None and doc.get("cycle_id") == key}
            if len(docs) != len([doc for doc in docs if doc is not None and doc.get("cycle_id") == key]) or not phases & TERMINAL_CYCLE_PHASES:
                _protect(reasons, item.kind, item.key, "active_incomplete_or_corrupt")

    cutoff = now.astimezone(timezone.utc) - timedelta(hours=config.retention_hours)
    for item in objects:
        if item.moment > cutoff:
            _protect(reasons, item.kind, item.key, "within_retention_window")

    # Pointer and metadata ambiguity fail closed for all recognized publication/build/raw evidence.
    current: str | None
    try:
        current = live_attempt(config)
    except Exception:  # noqa: BLE001 - unsafe pointer; never delete around it
        current = None
        failures.append("current_publication_ambiguous")
        for item in objects:
            if item.kind in {"raw_runs", "builds", "attempt_records", "publication_history"}:
                _protect(reasons, item.kind, item.key, "current_publication_ambiguous")
    current_meta = _json(config.publish_dir.expanduser().resolve() / CURRENT_METADATA_NAME)
    if current is not None:
        _protect(reasons, "builds", current, "current_publication")
        _protect(reasons, "attempt_records", current, "current_publication")
        if current_meta is None or current_meta.get("attempt_id") != current:
            failures.append("current_metadata_ambiguous")
            for item in objects:
                if item.kind in {"raw_runs", "builds", "attempt_records", "publication_history"}:
                    _protect(reasons, item.kind, item.key, "current_metadata_ambiguous")
    elif current_meta is not None:
        failures.append("current_metadata_ambiguous")
        for item in objects:
            if item.kind in {"raw_runs", "builds", "attempt_records", "publication_history"}:
                _protect(reasons, item.kind, item.key, "current_metadata_ambiguous")

    valid_switched = [(item, doc, sequence) for item, doc, sequence in histories
                      if doc is not None and doc.get("switched") is True and isinstance(doc.get("attempt_id"), str)
                      and RUN_ID_PATTERN.fullmatch(doc["attempt_id"])]
    if current is not None and current_meta is not None:
        current_matches = [(item, doc) for item, doc, _ in valid_switched
                           if doc.get("publication_id") == current_meta.get("publication_id")
                           and doc.get("attempt_id") == current]
        if len(current_matches) != 1:
            failures.append("current_history_ambiguous")
            for item in objects:
                if item.kind in {"raw_runs", "builds", "attempt_records", "publication_history"}:
                    _protect(reasons, item.kind, item.key, "current_history_ambiguous")
    switched_newest = sorted(valid_switched, key=lambda row: row[2], reverse=True)
    rollback_attempt = next((doc["attempt_id"] for _, doc, _ in switched_newest
                             if doc["attempt_id"] != current), None)
    if rollback_attempt:
        _protect(reasons, "builds", rollback_attempt, "default_rollback_target")
        _protect(reasons, "attempt_records", rollback_attempt, "default_rollback_target")
        # Keep one history authorization record: the newest record is exactly what default rollback observes first.
        authorization = next(item for item, doc, _ in switched_newest
                             if doc["attempt_id"] == rollback_attempt)
        _protect(reasons, authorization.kind, authorization.key, "default_rollback_target")

    # Explicit rollback accepts every distinct attempt with a successful switched history record.
    # Retain the attempt/source and one newest authorization record per distinct attempt; duplicate
    # old publication records can still age out.
    authorized: set[str] = set()
    for item, document, _ in switched_newest:
        attempt = str(document["attempt_id"])
        _protect(reasons, "builds", attempt, "explicit_rollback_authorized")
        _protect(reasons, "attempt_records", attempt, "explicit_rollback_authorized")
        if attempt not in authorized:
            _protect(reasons, item.kind, item.key, "explicit_rollback_authorized")
            authorized.add(attempt)

    if current_meta is not None and isinstance(current_meta.get("publication_id"), str):
        for item, document, _ in histories:
            if document is not None and document.get("publication_id") == current_meta["publication_id"]:
                _protect(reasons, item.kind, item.key, "current_publication")

    # Every retained publication record retains its referenced attempt. Old records not otherwise protected
    # are deliberately aged out first; explicit rollback then no longer authorizes those older attempts.
    for item, document, _ in histories:
        if reasons.get((item.kind, item.key)) and document is not None:
            referenced_attempt = document.get("attempt_id")
            if isinstance(referenced_attempt, str) and RUN_ID_PATTERN.fullmatch(referenced_attempt):
                _protect(reasons, "builds", referenced_attempt, "retained_publication_reference")
                _protect(reasons, "attempt_records", referenced_attempt, "retained_publication_reference")

    # An attempt record and its build are one evidence unit: a reason to retain either retains both.
    paired = {key for kind, key in reasons if kind in {"builds", "attempt_records"}}
    for attempt in paired:
        _protect(reasons, "builds", attempt, "paired_attempt_evidence")
        _protect(reasons, "attempt_records", attempt, "paired_attempt_evidence")

    # Retained attempts/builds retain all valid source references transitively. Disagreement protects both.
    protected_attempts = {key for kind, key in reasons if kind in {"builds", "attempt_records"}}
    for attempt in protected_attempts:
        source_ids: set[str] = set()
        record = records.get(attempt)
        metadata = builds.get(attempt)
        for value in ((record or {}).get("source_run_id"), ((metadata or {}).get("source") or {}).get("run_id")):
            if isinstance(value, str) and RUN_ID_PATTERN.fullmatch(value):
                source_ids.add(value)
        if len(source_ids) > 1:
            _protect(reasons, "builds", attempt, "ambiguous_source_reference")
            _protect(reasons, "attempt_records", attempt, "ambiguous_source_reference")
        for source_id in source_ids:
            _protect(reasons, "raw_runs", source_id, "retained_attempt_source")

    return objects, reasons, sorted(set(failures))


def _delete(item: _Object, roots: dict[str, Path]) -> None:
    root = roots[item.kind]
    for path in item.paths:
        if not _safe_under(path, root) or _contains_symlink(path):
            raise OSError("unsafe retention candidate")
    for path in item.paths:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def _cleanup_locked(config: SyncConfig, *, dry_run: bool = True, clock: Clock = utc_now) -> RetentionReport:
    now = clock().astimezone(timezone.utc)
    cutoff = now - timedelta(hours=config.retention_hours)
    report = RetentionReport(_iso(now), _iso(cutoff), config.retention_hours, dry_run)
    objects, reasons, diagnostics = _scan(config, now)
    report.scanned = _measure(objects)
    protected = [item for item in objects if reasons.get((item.kind, item.key))]
    eligible = [item for item in objects if not reasons.get((item.kind, item.key))]
    report.eligible = _measure(eligible)
    reason_counts: dict[str, Counter[str]] = {kind: Counter() for kind in KINDS}
    for item in protected:
        for reason in sorted(reasons[(item.kind, item.key)]):
            reason_counts[item.kind][reason] += 1
    report.protected_reasons = {kind: dict(sorted(counts.items())) for kind, counts in reason_counts.items()}
    report.failures.extend(diagnostics)
    deleted: list[_Object] = []
    if not dry_run:
        roots = {
            "raw_runs": config.raw_dir.expanduser().resolve(),
            "builds": config.build_dir.expanduser().resolve(),
            "attempt_records": config.build_dir.expanduser().resolve() / ATTEMPTS_DIR,
            "publication_history": config.publish_dir.expanduser().resolve() / HISTORY_DIR,
            "scheduled_cycles": config.lock_dir.expanduser().resolve() / "scheduled-cycles" if config.lock_dir else Path("/invalid"),
        }
        order = {"publication_history": 0, "scheduled_cycles": 1, "attempt_records": 2, "builds": 3, "raw_runs": 4}
        for item in sorted(eligible, key=lambda value: (order[value.kind], value.key)):
            try:
                _delete(item, roots)
                deleted.append(item)
            except OSError:
                report.failures.append(f"delete_failed:{item.kind}")
    report.deleted = _measure(deleted)
    if report.failures:
        report.status = "completed_with_protected_or_failed_objects"
    return report


def cleanup(environ: dict[str, str] | None = None, *, config: SyncConfig | None = None,
            dry_run: bool = True, clock: Clock = utc_now) -> RetentionReport:
    """Inspect or clean retention candidates while holding the shared production lock."""
    now = clock()
    try:
        cfg = config or load_sync_config(environ, now=now)
    except ConfigError:
        return RetentionReport(_iso(now), _iso(now), 0, dry_run, status="configuration_failed", failures=["configuration"])
    try:
        with production_lock(cfg, "retention", clock=clock):
            return _cleanup_locked(cfg, dry_run=dry_run, clock=clock)
    except OperationLocked:
        return RetentionReport(_iso(now), _iso(now), cfg.retention_hours, dry_run, status="locked", failures=["operation_locked"])
    except LockError:
        return RetentionReport(_iso(now), _iso(now), cfg.retention_hours, dry_run, status="configuration_failed", failures=["lock_configuration"])


def storage_snapshot(config: SyncConfig, *, clock: Clock = utc_now) -> dict[str, Any]:
    """Read-only storage visibility for status; detailed counts appear only for a clean scan."""
    report = _cleanup_locked(config, dry_run=True, clock=clock)
    if report.failures:
        return {"status": "attention_required", "retention_hours": config.retention_hours}
    return {"status": "clean", "retention_hours": config.retention_hours,
            "scanned": report.scanned, "eligible": report.eligible}


def exit_code(report: RetentionReport) -> int:
    if report.status == "locked":
        return 75
    return 0 if report.status == "completed" else 2


def summary(report: RetentionReport) -> str:
    action = "DRY RUN" if report.dry_run else "CLEANUP"
    counts = sum(group["count"] for group in report.deleted.values())
    size = sum(group["bytes"] for group in report.deleted.values())
    eligible = sum(group["count"] for group in report.eligible.values())
    return f"ATLAS RETENTION {action}: {report.status}; eligible={eligible}, deleted={counts}, bytes={size}"
