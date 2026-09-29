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
import secrets
import shutil
import stat
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from atlas_commander.ingest import INGEST_VERSION, RUN_ID_PATTERN, utc_now

from .config import ConfigError, SyncConfig, load_sync_config
from .lock import LockError, OperationLocked, production_lock
from .publish import HISTORY_PATTERN, PUBLICATION_VERSION, PublishRejected, live_attempt
from .run import BUILD_METADATA_NAME, COMPLETE_NAME, FAILED_NAME

RETENTION_VERSION = "atlas-retention-v1"
REPORT_DIR = "retention"
REPORT_NAME = "latest.json"
_CYCLE_FILE = re.compile(r"^(\d{8}T\d{6}Z-[0-9a-f]{12})(?:\.(started|outcome))?\.json$")
_PUBLICATION_STATUSES = {"published", "rejected", "switch_failed", "published_metadata_inconsistent"}
_SCHEDULED_VERSION = "atlas-scheduled-cycle-v1"


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
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return None
            value = json.load(handle)
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


def _id_time(value: str) -> datetime | None:
    try:
        if RUN_ID_PATTERN.fullmatch(value) is None:
            return None
        return datetime.strptime(value[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _old_id(value: str, cutoff: datetime) -> bool:
    moment = _id_time(value)
    # Exact-boundary evidence is retained: deletion requires strictly older.
    return moment is not None and moment < cutoff


def _unsafe_roots(paths: tuple[Path, ...]) -> bool:
    """Reject symlinks at/below the configured roots' common data ancestor.

    Platform ancestors such as macOS ``/var -> /private/var`` are outside Atlas' configured
    namespace and are intentionally canonicalized. A symlink used as the data root or one of its
    managed descendants is rejected.
    """
    if not paths:
        return False
    common = Path(os.path.commonpath([str(path) for path in paths]))
    for target in paths:
        current = common
        candidates = [common]
        try:
            relative = target.relative_to(common)
        except ValueError:
            return True
        for part in relative.parts:
            current /= part
            candidates.append(current)
        try:
            if any(candidate.is_symlink() for candidate in candidates):
                return True
        except OSError:
            return True
    return False


def _safe_child(root: Path, path: Path) -> bool:
    try:
        return (path.parent == root and root.is_absolute() and path.name not in {"", ".", ".."}
                and not root.is_symlink() and not path.is_symlink())
    except OSError:
        return False


def _identity(path: Path) -> tuple[int, int] | None:
    try:
        value = path.stat(follow_symlinks=False)
        return value.st_dev, value.st_ino
    except OSError:
        return None


def _remove(root: Path, path: Path, expected: tuple[int, int] | None) -> None:
    if not _safe_child(root, path) or path.is_symlink():
        raise OSError("unsafe retention target")
    if expected is None:
        raise OSError("missing retention target identity")
    root_before = os.stat(root, follow_symlinks=False)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    candidate_fd: int | None = None
    staged: str | None = None
    try:
        root_open = os.fstat(root_fd)
        if (root_before.st_dev, root_before.st_ino) != (root_open.st_dev, root_open.st_ino):
            raise OSError("retention root changed during deletion")
        candidate_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
        candidate = os.fstat(candidate_fd)
        if expected != (candidate.st_dev, candidate.st_ino):
            raise OSError("retention target changed since validation")
        staged = f".atlas-retention-{os.getpid()}-{secrets.token_hex(12)}"
        os.rename(path.name, staged, src_dir_fd=root_fd, dst_dir_fd=root_fd)
        staged_stat = os.stat(staged, dir_fd=root_fd, follow_symlinks=False)
        if (candidate.st_dev, candidate.st_ino) != (staged_stat.st_dev, staged_stat.st_ino):
            try:
                os.stat(path.name, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                os.rename(staged, path.name, src_dir_fd=root_fd, dst_dir_fd=root_fd)
                staged = None
            raise OSError("retention target changed during deletion")
        if stat.S_ISDIR(candidate.st_mode):
            shutil.rmtree(staged, dir_fd=root_fd)
        elif stat.S_ISREG(candidate.st_mode):
            os.unlink(staged, dir_fd=root_fd)
        else:
            raise OSError("unsafe retention target type")
        staged = None
    finally:
        if candidate_fd is not None:
            os.close(candidate_fd)
        os.close(root_fd)


def _source(build: Path, raw_root: Path) -> tuple[str | None, bool]:
    document = _object(build / BUILD_METADATA_NAME)
    source = document.get("source") if document else None
    run_id = source.get("run_id") if isinstance(source, dict) else None
    raw_dir = source.get("raw_run_dir") if isinstance(source, dict) else None
    valid = (isinstance(run_id, str) and RUN_ID_PATTERN.match(run_id) is not None
             and isinstance(raw_dir, str) and raw_dir == str(raw_root / run_id))
    return (run_id if valid else None), valid


def _valid_attempt(path: Path, raw_root: Path) -> tuple[dict[str, Any] | None, bool]:
    document = _object(path)
    attempt_id = path.stem
    valid = (document is not None and document.get("attempt_id") == attempt_id
             and document.get("status") in {"success", "failed", "running", "locked"})
    source_id = document.get("source_run_id") if document else None
    raw_dir = document.get("raw_run_dir") if document else None
    if source_id is not None:
        valid = (valid and isinstance(source_id, str) and RUN_ID_PATTERN.fullmatch(source_id) is not None
                 and isinstance(raw_dir, str) and raw_dir == str(raw_root / source_id))
    return document, bool(valid)


def _valid_raw_run(path: Path) -> tuple[bool, str]:
    manifest_path, failed_path = path / "manifest.json", path / FAILED_NAME
    manifest, failed = _object(manifest_path), _object(failed_path)
    if manifest_path.exists() == failed_path.exists():
        return False, "corrupt_reference"
    if manifest is not None:
        valid = (manifest.get("ingest_version") == INGEST_VERSION and manifest.get("status") == "complete"
                 and (manifest.get("run") or {}).get("run_id") == path.name)
        return valid, "complete" if valid else "corrupt_reference"
    if failed is not None:
        valid = (failed.get("ingest_version") == INGEST_VERSION and failed.get("status") == "failed"
                 and (failed.get("run") or {}).get("run_id") == path.name)
        return valid, "failed" if valid else "corrupt_reference"
    return False, "corrupt_reference"


def _valid_build(path: Path, raw_root: Path, attempt_doc: dict[str, Any] | None) -> tuple[bool, str | None, str]:
    complete_path, failed_path = path / COMPLETE_NAME, path / FAILED_NAME
    complete, failed = _object(complete_path), _object(failed_path)
    source_id, source_valid = _source(path, raw_root)
    if complete_path.exists() == failed_path.exists():
        return (False, source_id if source_valid else None,
                "active_or_incomplete" if not complete_path.exists() else "corrupt_reference")
    if complete is not None:
        marker_valid = (complete.get("status") == "complete" and complete.get("attempt_id") == path.name
                        and complete.get("source_run_id") == source_id)
        return bool(marker_valid and source_valid), source_id, "complete" if marker_valid and source_valid else "corrupt_reference"
    if failed is not None:
        marker_valid = failed.get("status") == "failed" and failed.get("attempt_id") == path.name
        if not source_valid and attempt_doc is not None:
            fallback = attempt_doc.get("source_run_id")
            fallback_path = attempt_doc.get("raw_run_dir")
            if (isinstance(fallback, str) and RUN_ID_PATTERN.fullmatch(fallback)
                    and fallback_path == str(raw_root / fallback)):
                source_id, source_valid = fallback, True
        # A build can fail before build.json exists. The self-identifying failed marker is terminal;
        # a known source, when present, is still retained transitively.
        return bool(marker_valid), source_id if source_valid else None, "failed" if marker_valid else "corrupt_reference"
    return False, None, "corrupt_reference"


def _valid_history(path: Path) -> tuple[dict[str, Any] | None, bool]:
    match = HISTORY_PATTERN.fullmatch(path.name)
    document = _object(path) if match and path.is_file() and not path.is_symlink() else None
    if match is None or document is None:
        return document, False
    attempt_id = document.get("attempt_id")
    valid_attempt = attempt_id is None or (isinstance(attempt_id, str) and RUN_ID_PATTERN.fullmatch(attempt_id) is not None)
    valid = (document.get("publication_version") == PUBLICATION_VERSION
             and document.get("sequence") == int(match.group(1))
             and document.get("publication_id") == match.group(2)
             and document.get("status") in _PUBLICATION_STATUSES
             and isinstance(document.get("switched"), bool) and valid_attempt)
    return document, bool(valid)


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
    configured_lock_root = config.lock_dir.expanduser().absolute()
    if configured_lock_root.is_symlink():
        raise OSError("unsafe retention lock root")
    lock_root = configured_lock_root.resolve()
    before = os.stat(lock_root, follow_symlinks=False)
    lock_fd = os.open(lock_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    directory_fd: int | None = None
    temporary = f".{REPORT_NAME}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    data = json.dumps(report.as_dict(), indent=1, sort_keys=True).encode() + b"\n"
    try:
        opened = os.fstat(lock_fd)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise OSError("retention lock root changed")
        try:
            os.mkdir(REPORT_DIR, mode=0o700, dir_fd=lock_fd)
        except FileExistsError:
            pass
        directory_fd = os.open(REPORT_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=lock_fd)
        try:
            existing = os.stat(REPORT_NAME, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and not stat.S_ISREG(existing.st_mode):
            raise OSError("unsafe retention report path")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory_fd)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, REPORT_NAME, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        if directory_fd is not None:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            os.close(directory_fd)
        os.close(lock_fd)


def _cleanup_locked(*, config: SyncConfig, dry_run: bool = True,
                    clock: Callable[[], datetime] = utc_now) -> RetentionReport:
    """Apply retention while the caller holds the production lock."""
    now = clock().astimezone(timezone.utc)
    cutoff = now - timedelta(seconds=config.retention_seconds)
    report = RetentionReport(_iso(now), _iso(cutoff), config.retention_seconds, dry_run)
    configured_roots = tuple(path.expanduser().absolute() for path in
                             (config.raw_dir, config.build_dir, config.publish_dir))
    lock_root = config.lock_dir.expanduser().absolute() if config.lock_dir else None
    all_roots = configured_roots + ((lock_root,) if lock_root else ())
    if _unsafe_roots(all_roots):
        report.status, report.failure_category = "blocked", "unsafe_root"
        report.storage = None
        return report
    raw_root, build_root, publish_root = (root.resolve() for root in configured_roots)
    canonical_lock_root = lock_root.resolve() if lock_root else None
    cycle_root = canonical_lock_root / "scheduled-cycles" if canonical_lock_root else None

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
    if history_root.is_symlink():
        ambiguous = True
        _record(report, "publication_history", history_root, "retained", "unknown_or_unsafe", _tree_size(history_root)[0])
    elif history_root.is_dir():
        for path in sorted(history_root.iterdir()):
            doc, valid = _valid_history(path)
            if not valid:
                ambiguous = True
                _record(report, "publication_history", path, "retained", "unknown_or_unsafe", _tree_size(path)[0])
                continue
            assert doc is not None
            histories.append((path, doc))
    elif history_root.exists():
        ambiguous = True

    successful = [(p, d) for p, d in histories if d.get("switched") is True and isinstance(d.get("attempt_id"), str)]
    for path, doc in successful:
        attempt = doc.get("attempt_id")
        if not isinstance(attempt, str) or RUN_ID_PATTERN.match(attempt) is None:
            ambiguous = True
    # Preserve CURRENT's exact record and the actual default rollback target.
    current_path = publish_root / "CURRENT.json"
    current_doc = _object(current_path) if current_path.is_file() and not current_path.is_symlink() else None
    if current_doc is None and (current is not None or current_path.exists() or current_path.is_symlink()):
        ambiguous = True
    elif current_doc:
        reference = current_doc.get("history_record")
        if isinstance(reference, str):
            candidate = Path(reference)
            try:
                canonical_candidate = candidate.resolve(strict=True)
            except (OSError, RuntimeError):
                canonical_candidate = Path("/")
            matching = [(path, doc) for path, doc in histories if path == canonical_candidate]
            if (candidate.is_absolute() and canonical_candidate.parent == history_root and len(matching) == 1
                    and matching[0][1].get("publication_id") == current_doc.get("publication_id")
                    and matching[0][1].get("attempt_id") == current):
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
    if attempts_root.is_symlink():
        _record(report, "attempt_record", attempts_root, "retained", "unknown_or_unsafe", _tree_size(attempts_root)[0])
        ambiguous = True
    elif attempts_root.is_dir():
        attempt_paths = sorted(attempts_root.iterdir())
        for path in attempt_paths:
            match = path.suffix == ".json" and RUN_ID_PATTERN.match(path.stem)
            doc, valid = _valid_attempt(path, raw_root) if match and not path.is_symlink() and path.is_file() else (None, False)
            if match and valid and doc is not None:
                attempt_documents[path.stem] = doc
            else:
                ambiguous = True
    elif attempts_root.exists():
        _record(report, "attempt_record", attempts_root, "retained", "unknown_or_unsafe", _tree_size(attempts_root)[0])
        ambiguous = True

    active_attempts = {attempt_id for attempt_id, document in attempt_documents.items()
                       if document.get("status") not in {"success", "failed"}}
    protected_attempts.update(active_attempts)

    # A corrupt publication reference may name any build, so keep the whole
    # provenance graph.  Clean old, non-required history remains bounded.
    retained_history_attempts: set[str] = set()
    for path, doc in histories:
        size, unsafe = _tree_size(path)
        identity = _identity(path)
        if unsafe:
            _record(report, "publication_history", path, "retained", "unknown_or_unsafe", size)
        elif ambiguous:
            _record(report, "publication_history", path, "retained", "ambiguous_reference", size)
        elif path.name in protected_history:
            _record(report, "publication_history", path, "retained", "publication_or_rollback_required", size)
            if doc.get("switched") is True and isinstance(doc.get("attempt_id"), str):
                retained_history_attempts.add(doc["attempt_id"])
        elif not _old_id(str(doc["publication_id"]), cutoff):
            _record(report, "publication_history", path, "retained", "within_retention", size)
            if doc.get("switched") is True and isinstance(doc.get("attempt_id"), str):
                retained_history_attempts.add(doc["attempt_id"])
        elif dry_run:
            _record(report, "publication_history", path, "would_delete", "expired", size)
        else:
            try:
                _remove(history_root, path, identity)
                _record(report, "publication_history", path, "deleted", "expired", size)
            except OSError:
                _record(report, "publication_history", path, "retained", "delete_failed", size); report.status = "partial"
                if doc.get("switched") is True and isinstance(doc.get("attempt_id"), str):
                    retained_history_attempts.add(doc["attempt_id"])

    protected_attempts.update(retained_history_attempts)

    preserved_sources: set[str] = set()
    raw_paths = sorted(raw_root.iterdir()) if raw_root.is_dir() else []
    raw_validation = {path: (_valid_raw_run(path) if path.is_dir() and not path.is_symlink()
                             and RUN_ID_PATTERN.fullmatch(path.name) else (False, "corrupt_reference"))
                      for path in raw_paths}
    raw_ambiguous = any(RUN_ID_PATTERN.fullmatch(path.name) and not valid
                        for path, (valid, _) in raw_validation.items())
    if build_root.is_dir():
        for path in sorted(build_root.iterdir()):
            if path.name == "attempts":
                continue
            if RUN_ID_PATTERN.match(path.name) is None or path.is_symlink() or not path.is_dir():
                _record(report, "build", path, "retained", "unknown_or_unsafe", _tree_size(path)[0])
                if path.is_dir() and not path.is_symlink():
                    source_id, source_valid = _source(path, raw_root)
                    if source_valid and source_id:
                        preserved_sources.add(source_id)
                    else:
                        raw_ambiguous = True
                continue
            size, unsafe = _tree_size(path)
            identity = _identity(path)
            terminal, source_id, terminal_state = _valid_build(path, raw_root, attempt_documents.get(path.name))
            if terminal and terminal_state == "complete" and source_id is None:
                raw_ambiguous = True
            if not terminal and terminal_state == "corrupt_reference":
                raw_ambiguous = True
            if not terminal and terminal_state == "active_or_incomplete" and source_id is None:
                raw_ambiguous = True
            protect = ambiguous or raw_ambiguous or path.name in protected_attempts or not terminal or unsafe
            if protect:
                reason = ("ambiguous_reference" if ambiguous or raw_ambiguous else "active_or_incomplete" if path.name in active_attempts
                          else "publication_or_rollback_required" if path.name in protected_attempts
                          else "unknown_or_unsafe" if unsafe else terminal_state)
                _record(report, "build", path, "retained", reason, size)
                protected_attempts.add(path.name)
                if source_id: preserved_sources.add(source_id)
            elif not _old_id(path.name, cutoff):
                _record(report, "build", path, "retained", "within_retention", size)
                protected_attempts.add(path.name)
                if source_id: preserved_sources.add(source_id)
            else:
                if dry_run:
                    _record(report, "build", path, "would_delete", "expired", size)
                else:
                    try:
                        _remove(build_root, path, identity)
                        _record(report, "build", path, "deleted", "expired", size)
                    except OSError:
                        _record(report, "build", path, "retained", "delete_failed", size); report.status = "partial"
                        if source_id: preserved_sources.add(source_id)

    if attempts_root.is_dir() and not attempts_root.is_symlink():
        for path in attempt_paths:
            size, unsafe = _tree_size(path)
            identity = _identity(path)
            match = path.suffix == ".json" and RUN_ID_PATTERN.match(path.stem)
            doc, valid = _valid_attempt(path, raw_root) if match and not path.is_symlink() else (None, False)
            if not match or unsafe or not valid or doc is None:
                ambiguous = True
                _record(report, "attempt_record", path, "retained", "unknown_or_unsafe" if not match or unsafe else "corrupt_reference", size)
                continue
            active = doc.get("status") not in {"success", "failed"}
            if ambiguous or raw_ambiguous or path.stem in protected_attempts or active:
                reason = ("ambiguous_reference" if ambiguous or raw_ambiguous else "build_evidence_required"
                          if path.stem in protected_attempts else "active_or_incomplete")
                _record(report, "attempt_record", path, "retained", reason, size)
                source_id = doc.get("source_run_id")
                if isinstance(source_id, str) and RUN_ID_PATTERN.match(source_id): preserved_sources.add(source_id)
            elif not _old_id(path.stem, cutoff):
                _record(report, "attempt_record", path, "retained", "within_retention", size)
                source_id = doc.get("source_run_id")
                if isinstance(source_id, str) and RUN_ID_PATTERN.match(source_id): preserved_sources.add(source_id)
            elif dry_run:
                _record(report, "attempt_record", path, "would_delete", "expired", size)
            else:
                try:
                    _remove(attempts_root, path, identity)
                    _record(report, "attempt_record", path, "deleted", "expired", size)
                except OSError:
                    _record(report, "attempt_record", path, "retained", "delete_failed", size); report.status = "partial"
                    source_id = doc.get("source_run_id")
                    if isinstance(source_id, str) and RUN_ID_PATTERN.match(source_id): preserved_sources.add(source_id)

    if raw_root.is_dir():
        for path in raw_paths:
            size, unsafe = _tree_size(path)
            identity = _identity(path)
            valid_raw, raw_state = raw_validation[path]
            if RUN_ID_PATTERN.match(path.name) is None or path.is_symlink() or not path.is_dir() or unsafe:
                _record(report, "raw_run", path, "retained", "unknown_or_unsafe", size)
            elif not valid_raw:
                _record(report, "raw_run", path, "retained", raw_state, size)
            elif ambiguous or raw_ambiguous or path.name in preserved_sources:
                _record(report, "raw_run", path, "retained", "ambiguous_reference" if ambiguous or raw_ambiguous else "source_evidence_required", size)
            elif not _old_id(path.name, cutoff):
                _record(report, "raw_run", path, "retained", "within_retention", size)
            elif dry_run:
                _record(report, "raw_run", path, "would_delete", "expired", size)
            else:
                try:
                    _remove(raw_root, path, identity)
                    _record(report, "raw_run", path, "deleted", "expired", size)
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
            expected_phases = {path.name: ("started" if path.name.endswith(".started.json") else
                                           "outcome" if path.name.endswith(".outcome.json") else "final") for path in paths}
            safe = all(doc is not None and doc.get("cycle_id") == cycle_id
                       and doc.get("scheduled_cycle_version") == _SCHEDULED_VERSION
                       and doc.get("record_phase") == expected_phases[path.name]
                       for path, doc in zip(paths, docs))
            old = _old_id(cycle_id, cutoff)
            for path in paths:
                size, unsafe = _tree_size(path)
                identity = _identity(path)
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
                        _remove(cycle_root, path, identity)
                        _record(report, "scheduled_cycle", path, "deleted", "expired", size)
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
            dry_run: bool = True, clock: Callable[[], datetime] = utc_now) -> RetentionReport:
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
