"""Fail-closed bounded retention for Atlas-owned operational evidence.

Only direct children with Atlas' exact names are candidates.  Unknown objects,
symlinks, incomplete work and ambiguous references are retained.  Scheduled
cycles call :func:`_cleanup_locked` while holding the production lock; the public
entry point takes that same lock for operator dry-runs.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from atlas_commander.ingest import RUN_ID_PATTERN, utc_now

from .config import ConfigError, SyncConfig, load_sync_config
from .lock import LockError, OperationLocked, production_lock
from .publish import HISTORY_PATTERN, PublishRejected, live_attempt
from .run import BUILD_METADATA_NAME, COMPLETE_NAME, FAILED_NAME

RETENTION_VERSION = "atlas-retention-v1"
REPORT_DIR = "retention"
REPORT_NAME = "latest.json"
_CYCLE_FILE = re.compile(r"^(\d{8}T\d{6}Z-[0-9a-f]{12})(?:\.(started|outcome))?\.json$")


@dataclass
class Decision:
    kind: str
    name: str
    action: str
    reason: str
    bytes: int


@dataclass
class RetentionReport:
    generated_at: str
    cutoff: str | None
    retention_seconds: int | None
    dry_run: bool
    status: str = "complete"
    decisions: list[Decision] = field(default_factory=list)
    deleted_count: int = 0
    deleted_bytes: int = 0
    retained_count: int = 0
    retained_bytes: int = 0
    would_delete_count: int = 0
    would_delete_bytes: int = 0
    reasons: dict[str, int] = field(default_factory=dict)
    storage: dict[str, dict[str, int]] | None = None
    report_version: str = RETENTION_VERSION
    failure_category: str | None = None
    lock: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _tree_size(path: Path) -> tuple[int, bool]:
    """Return allocated evidence bytes and whether any symlink/unsafe node was seen."""
    try:
        if path.is_symlink():
            return path.lstat().st_size, True
        if path.is_file():
            return path.stat().st_size, False
        if not path.is_dir():
            return path.lstat().st_size, True
        total = path.stat().st_size
        for child in path.iterdir():
            size, unsafe = _tree_size(child)
            total += size
            if unsafe:
                return total, True
        return total, False
    except OSError:
        return 0, True


def _old(path: Path, cutoff: datetime) -> bool:
    try:
        modified = datetime.fromtimestamp(path.lstat().st_mtime, timezone.utc)
    except OSError:
        return False
    # Exact-boundary evidence is retained: deletion requires strictly older.
    return modified < cutoff


def _safe_child(root: Path, path: Path) -> bool:
    try:
        return path.parent == root and root.is_absolute() and path.name not in {"", ".", ".."}
    except OSError:
        return False


def _remove(root: Path, path: Path) -> None:
    if not _safe_child(root, path) or path.is_symlink():
        raise OSError("unsafe retention target")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _source(build: Path, raw_root: Path) -> tuple[str | None, bool]:
    document = _object(build / BUILD_METADATA_NAME)
    source = document.get("source") if document else None
    run_id = source.get("run_id") if isinstance(source, dict) else None
    raw_dir = source.get("raw_run_dir") if isinstance(source, dict) else None
    valid = (isinstance(run_id, str) and RUN_ID_PATTERN.match(run_id) is not None
             and isinstance(raw_dir, str) and raw_dir == str(raw_root / run_id))
    return (run_id if valid else None), valid


def _record(report: RetentionReport, kind: str, path: Path, action: str, reason: str, size: int) -> None:
    report.decisions.append(Decision(kind, path.name, action, reason, size))
    report.reasons[reason] = report.reasons.get(reason, 0) + 1
    if action == "deleted":
        report.deleted_count += 1
        report.deleted_bytes += size
    elif action == "would_delete":
        report.would_delete_count += 1
        report.would_delete_bytes += size
    else:
        report.retained_count += 1
        report.retained_bytes += size


def _write_report(config: SyncConfig, report: RetentionReport) -> None:
    if config.lock_dir is None:
        return
    directory = config.lock_dir.resolve() / REPORT_DIR
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / REPORT_NAME
    temporary = directory / f".{REPORT_NAME}.{os.getpid()}.tmp"
    data = json.dumps(report.as_dict(), indent=1, sort_keys=True).encode() + b"\n"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _cleanup_locked(*, config: SyncConfig, dry_run: bool = False,
                    clock: Callable[[], datetime] = utc_now) -> RetentionReport:
    """Apply retention while the caller holds the production lock."""
    now = clock().astimezone(timezone.utc)
    cutoff = now - timedelta(seconds=config.retention_seconds)
    report = RetentionReport(_iso(now), _iso(cutoff), config.retention_seconds, dry_run)
    configured_roots = (config.raw_dir.expanduser(), config.build_dir.expanduser(), config.publish_dir.expanduser())
    raw_root, build_root, publish_root = (path.resolve() for path in configured_roots)
    cycle_root = config.lock_dir.resolve() / "scheduled-cycles" if config.lock_dir else None
    if any(root.is_symlink() for root in configured_roots) or (config.lock_dir and config.lock_dir.is_symlink()):
        report.status, report.failure_category = "blocked", "unsafe_root"
        report.storage = None
        return report

    ambiguous = False
    protected_attempts: set[str] = set()
    protected_history: set[str] = set()
    try:
        current = live_attempt(config)
    except PublishRejected:
        current, ambiguous = None, True
    if current:
        protected_attempts.add(current)

    history_root = publish_root / "history"
    histories: list[tuple[Path, dict[str, Any]]] = []
    if history_root.is_dir() and not history_root.is_symlink():
        for path in sorted(history_root.iterdir()):
            if path.is_symlink() or not path.is_file() or HISTORY_PATTERN.match(path.name) is None:
                _record(report, "publication_history", path, "retained", "unknown_or_unsafe", _tree_size(path)[0])
                continue
            doc = _object(path)
            if doc is None:
                ambiguous = True
                _record(report, "publication_history", path, "retained", "corrupt_reference", _tree_size(path)[0])
            else:
                histories.append((path, doc))
    elif history_root.exists():
        ambiguous = True

    successful = [(p, d) for p, d in histories if d.get("switched") is True and isinstance(d.get("attempt_id"), str)]
    for path, doc in successful:
        attempt = doc.get("attempt_id")
        if not isinstance(attempt, str) or RUN_ID_PATTERN.match(attempt) is None:
            ambiguous = True
    # Preserve CURRENT's exact record and the actual default rollback target.
    current_doc = _object(publish_root / "CURRENT.json")
    if current_doc is None and current is not None:
        ambiguous = True
    elif current_doc:
        reference = current_doc.get("history_record")
        if isinstance(reference, str):
            candidate = Path(reference)
            if candidate.is_absolute() and candidate.parent == history_root:
                protected_history.add(candidate.name)
            else:
                ambiguous = True
        else:
            ambiguous = True
    if current:
        for path, doc in reversed(successful):
            attempt = doc.get("attempt_id")
            if attempt != current and RUN_ID_PATTERN.match(str(attempt)):
                protected_attempts.add(str(attempt))
                protected_history.add(path.name)
                break

    # Read attempt references before deciding about builds/raw. A corrupt
    # Atlas-named record could refer to either, so ambiguity blocks that graph.
    attempts_root = build_root / "attempts"
    attempt_documents: dict[str, dict[str, Any]] = {}
    attempt_paths: list[Path] = []
    if attempts_root.is_dir() and not attempts_root.is_symlink():
        attempt_paths = sorted(attempts_root.iterdir())
        for path in attempt_paths:
            match = path.suffix == ".json" and RUN_ID_PATTERN.match(path.stem)
            doc = _object(path) if match and not path.is_symlink() and path.is_file() else None
            if match and doc is not None and doc.get("attempt_id") == path.stem:
                attempt_documents[path.stem] = doc
            elif match:
                ambiguous = True
    elif attempts_root.exists() or attempts_root.is_symlink():
        _record(report, "attempt_record", attempts_root, "retained", "unknown_or_unsafe", _tree_size(attempts_root)[0])
        ambiguous = True

    # A corrupt publication reference may name any build, so keep the whole
    # provenance graph.  Clean old, non-required history remains bounded.
    retained_history_attempts: set[str] = set()
    for path, doc in histories:
        size, unsafe = _tree_size(path)
        if unsafe:
            _record(report, "publication_history", path, "retained", "unknown_or_unsafe", size)
        elif ambiguous:
            _record(report, "publication_history", path, "retained", "ambiguous_reference", size)
        elif path.name in protected_history:
            _record(report, "publication_history", path, "retained", "publication_or_rollback_required", size)
            if doc.get("switched") is True and isinstance(doc.get("attempt_id"), str):
                retained_history_attempts.add(doc["attempt_id"])
        elif not _old(path, cutoff):
            _record(report, "publication_history", path, "retained", "within_retention", size)
            if doc.get("switched") is True and isinstance(doc.get("attempt_id"), str):
                retained_history_attempts.add(doc["attempt_id"])
        elif dry_run:
            _record(report, "publication_history", path, "would_delete", "expired", size)
        else:
            try:
                _remove(history_root, path); _record(report, "publication_history", path, "deleted", "expired", size)
            except OSError:
                _record(report, "publication_history", path, "retained", "delete_failed", size); report.status = "partial"
                if doc.get("switched") is True and isinstance(doc.get("attempt_id"), str):
                    retained_history_attempts.add(doc["attempt_id"])

    protected_attempts.update(retained_history_attempts)

    preserved_sources: set[str] = set()
    raw_ambiguous = False
    if build_root.is_dir():
        for path in sorted(build_root.iterdir()):
            if path.name == "attempts":
                continue
            if RUN_ID_PATTERN.match(path.name) is None or path.is_symlink() or not path.is_dir():
                _record(report, "build", path, "retained", "unknown_or_unsafe", _tree_size(path)[0])
                continue
            size, unsafe = _tree_size(path)
            complete = (path / COMPLETE_NAME).is_file() and not (path / FAILED_NAME).exists()
            failed = (path / FAILED_NAME).is_file() and not (path / COMPLETE_NAME).exists()
            source_id, source_valid = _source(path, raw_root)
            if failed and not source_valid:
                fallback = attempt_documents.get(path.name, {}).get("source_run_id")
                if isinstance(fallback, str) and RUN_ID_PATTERN.match(fallback):
                    source_id, source_valid = fallback, True
            if not source_valid:
                raw_ambiguous = True
            protect = ambiguous or path.name in protected_attempts or not (complete or failed) or unsafe or not source_valid
            if protect:
                reason = ("ambiguous_reference" if ambiguous else "publication_or_rollback_required" if path.name in protected_attempts
                          else "active_or_incomplete" if not (complete or failed) else "unknown_or_unsafe" if unsafe else "corrupt_reference")
                _record(report, "build", path, "retained", reason, size)
                protected_attempts.add(path.name)
                if source_id: preserved_sources.add(source_id)
            elif not _old(path, cutoff):
                _record(report, "build", path, "retained", "within_retention", size)
                protected_attempts.add(path.name)
                if source_id: preserved_sources.add(source_id)
            else:
                if dry_run:
                    _record(report, "build", path, "would_delete", "expired", size)
                else:
                    try:
                        _remove(build_root, path); _record(report, "build", path, "deleted", "expired", size)
                    except OSError:
                        _record(report, "build", path, "retained", "delete_failed", size); report.status = "partial"
                        if source_id: preserved_sources.add(source_id)

    if attempts_root.is_dir() and not attempts_root.is_symlink():
        for path in attempt_paths:
            size, unsafe = _tree_size(path)
            match = path.suffix == ".json" and RUN_ID_PATTERN.match(path.stem)
            doc = _object(path) if match and not path.is_symlink() else None
            if not match or unsafe or doc is None or doc.get("attempt_id") != path.stem:
                _record(report, "attempt_record", path, "retained", "unknown_or_unsafe" if not match or unsafe else "corrupt_reference", size)
                continue
            active = doc.get("status") not in {"success", "failed"}
            if ambiguous or path.stem in protected_attempts or active:
                reason = "ambiguous_reference" if ambiguous else "build_evidence_required" if path.stem in protected_attempts else "active_or_incomplete"
                _record(report, "attempt_record", path, "retained", reason, size)
                source_id = doc.get("source_run_id")
                if isinstance(source_id, str) and RUN_ID_PATTERN.match(source_id): preserved_sources.add(source_id)
            elif not _old(path, cutoff):
                _record(report, "attempt_record", path, "retained", "within_retention", size)
                source_id = doc.get("source_run_id")
                if isinstance(source_id, str) and RUN_ID_PATTERN.match(source_id): preserved_sources.add(source_id)
            elif dry_run:
                _record(report, "attempt_record", path, "would_delete", "expired", size)
            else:
                try:
                    _remove(attempts_root, path); _record(report, "attempt_record", path, "deleted", "expired", size)
                except OSError:
                    _record(report, "attempt_record", path, "retained", "delete_failed", size); report.status = "partial"
                    source_id = doc.get("source_run_id")
                    if isinstance(source_id, str) and RUN_ID_PATTERN.match(source_id): preserved_sources.add(source_id)

    if raw_root.is_dir():
        for path in sorted(raw_root.iterdir()):
            size, unsafe = _tree_size(path)
            if RUN_ID_PATTERN.match(path.name) is None or path.is_symlink() or not path.is_dir() or unsafe:
                _record(report, "raw_run", path, "retained", "unknown_or_unsafe", size)
            elif ambiguous or raw_ambiguous or path.name in preserved_sources:
                _record(report, "raw_run", path, "retained", "ambiguous_reference" if ambiguous or raw_ambiguous else "source_evidence_required", size)
            elif not _old(path, cutoff):
                _record(report, "raw_run", path, "retained", "within_retention", size)
            elif dry_run:
                _record(report, "raw_run", path, "would_delete", "expired", size)
            else:
                try:
                    _remove(raw_root, path); _record(report, "raw_run", path, "deleted", "expired", size)
                except OSError:
                    _record(report, "raw_run", path, "retained", "delete_failed", size); report.status = "partial"

    if cycle_root and cycle_root.is_dir() and not cycle_root.is_symlink():
        groups: dict[str, list[Path]] = {}
        for path in sorted(cycle_root.iterdir()):
            match = _CYCLE_FILE.match(path.name)
            if not match or path.is_symlink() or not path.is_file():
                _record(report, "scheduled_cycle", path, "retained", "unknown_or_unsafe", _tree_size(path)[0])
            else:
                groups.setdefault(match.group(1), []).append(path)
        for cycle_id, paths in groups.items():
            docs = [_object(path) for path in paths]
            terminal = any(path.name == f"{cycle_id}.json" or path.name == f"{cycle_id}.outcome.json" for path in paths)
            safe = all(doc is not None and doc.get("cycle_id") == cycle_id for doc in docs)
            old = all(_old(path, cutoff) for path in paths)
            for path in paths:
                size, unsafe = _tree_size(path)
                if unsafe or not safe:
                    _record(report, "scheduled_cycle", path, "retained", "corrupt_reference", size)
                elif not terminal:
                    _record(report, "scheduled_cycle", path, "retained", "active_or_incomplete", size)
                elif not old:
                    _record(report, "scheduled_cycle", path, "retained", "within_retention", size)
                elif dry_run:
                    _record(report, "scheduled_cycle", path, "would_delete", "expired", size)
                else:
                    try:
                        _remove(cycle_root, path); _record(report, "scheduled_cycle", path, "deleted", "expired", size)
                    except OSError:
                        _record(report, "scheduled_cycle", path, "retained", "delete_failed", size); report.status = "partial"
    elif cycle_root and (cycle_root.exists() or cycle_root.is_symlink()):
        _record(report, "scheduled_cycle", cycle_root, "retained", "unknown_or_unsafe", _tree_size(cycle_root)[0])

    unsafe_reasons = {"unknown_or_unsafe", "corrupt_reference", "ambiguous_reference"}
    if (ambiguous or raw_ambiguous or unsafe_reasons.intersection(report.reasons)) and report.status == "complete":
        report.status = "blocked"
    if report.status == "complete":
        storage: dict[str, dict[str, int]] = {}
        for item in report.decisions:
            if item.action == "retained":
                bucket = storage.setdefault(item.kind, {"count": 0, "bytes": 0})
                bucket["count"] += 1; bucket["bytes"] += item.bytes
        report.storage = storage
    if not dry_run:
        try:
            _write_report(config, report)
        except OSError:
            report.status = "partial"
            report.failure_category = "report_write_failed"
            report.storage = None
    return report


def cleanup(environ: Mapping[str, str] | None = None, *, config: SyncConfig | None = None,
            dry_run: bool = False, clock: Callable[[], datetime] = utc_now) -> RetentionReport:
    now = clock()
    try:
        cfg = config or load_sync_config(environ, now=now)
    except ConfigError:
        return RetentionReport(_iso(now), None, None, dry_run, status="failed", failure_category="configuration")
    try:
        with production_lock(cfg, "retention", clock=clock):
            return _cleanup_locked(config=cfg, dry_run=dry_run, clock=clock)
    except OperationLocked as error:
        return RetentionReport(_iso(now), None, cfg.retention_seconds, dry_run, status="locked",
                               failure_category=error.failure_category, lock=error.as_dict())
    except LockError as error:
        return RetentionReport(_iso(now), None, cfg.retention_seconds, dry_run, status="failed",
                               failure_category=error.failure_category)
