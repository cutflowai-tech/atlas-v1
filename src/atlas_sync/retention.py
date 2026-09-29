"""Conservative bounded retention for Atlas-owned operational evidence.

Only exact, terminal Atlas objects older than the configured boundary are candidates.  Unknown
objects, symlinks, incomplete objects, and ambiguous references are retained.  Public cleanup holds
the production lock; scheduled cleanup calls the already-locked helper.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from atlas_commander.ingest import RUN_ID_PATTERN, Clock, utc_now

from .config import ConfigError, SyncConfig, load_sync_config
from .lock import LockError, OperationLocked, production_lock
from .publish import HISTORY_PATTERN, PublishRejected, live_attempt
from .run import BUILD_METADATA_NAME, COMPLETE_NAME, FAILED_NAME

RETENTION_VERSION = "atlas-retention-v1"
LATEST_DIR = "retention"
LATEST_NAME = "LATEST.json"
ATTEMPT_PATTERN = re.compile(r"^(\d{8}T\d{6}Z-[0-9a-f]{12})\.json$")
SCHEDULED_PATTERN = re.compile(r"^(\d{8}T\d{6}Z-[0-9a-f]{12})(?:\.(started|outcome))?\.json$")
PUBLICATION_STATUSES = {"published", "rejected", "switch_failed", "published_metadata_inconsistent"}


@dataclass
class RetentionItem:
    kind: str
    name: str
    action: str
    reason: str
    bytes: int


@dataclass
class RetentionReport:
    generated_at: str
    cutoff_at: str
    retention_hours: int
    dry_run: bool
    status: str = "complete"
    items: list[RetentionItem] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    bytes: dict[str, int] = field(default_factory=dict)
    reasons: dict[str, int] = field(default_factory=dict)
    error_category: str | None = None
    lock: dict[str, Any] | None = None

    def finish(self) -> RetentionReport:
        self.counts = dict(sorted(Counter(item.action for item in self.items).items()))
        totals: Counter[str] = Counter()
        for item in self.items:
            totals[item.action] += item.bytes
        self.bytes = dict(sorted(totals.items()))
        self.reasons = dict(sorted(Counter(item.reason for item in self.items).items()))
        return self

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _id_time(value: str) -> datetime | None:
    if not isinstance(value, str) or not RUN_ID_PATTERN.match(value):
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


def _history_record(path: Path, match: re.Match[str]) -> dict[str, Any] | None:
    record = _json(path) if path.is_file() and not path.is_symlink() else None
    attempt = (record or {}).get("attempt_id")
    if (record is None or record.get("publication_id") != match.group(2)
            or record.get("status") not in PUBLICATION_STATUSES
            or not isinstance(record.get("switched"), bool)
            or (attempt is not None and (not isinstance(attempt, str) or not RUN_ID_PATTERN.match(attempt)))):
        return None
    return record


def _tree_bytes(path: Path) -> tuple[int, bool]:
    """Size without following links, and whether the tree consists only of real dirs/files."""
    try:
        if path.is_symlink():
            return path.lstat().st_size, False
        if path.is_file():
            return path.stat().st_size, True
        if not path.is_dir():
            return path.lstat().st_size, False
        total = 0
        for child in path.iterdir():
            size, safe = _tree_bytes(child)
            total += size
            if not safe:
                return total, False
        return total, True
    except OSError:
        return 0, False


def _inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve(strict=False).parent == root.resolve()
    except (OSError, RuntimeError):
        return False


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


class _Plan:
    def __init__(self, config: SyncConfig, now: datetime, dry_run: bool) -> None:
        self.config, self.now, self.dry_run = config, now.astimezone(timezone.utc), dry_run
        self.cutoff = self.now - timedelta(hours=config.retention_hours)
        self.items: list[RetentionItem] = []

    def add(self, kind: str, path: Path, action: str, reason: str, size: int | None = None) -> None:
        if size is None:
            size, _ = _tree_bytes(path)
        self.items.append(RetentionItem(kind, path.name, action, reason, size))

    def candidate(self, kind: str, path: Path, object_id: str, *, terminal: bool, protected: bool = False,
                  protected_reason: str = "referenced") -> None:
        size, safe = _tree_bytes(path)
        when = _id_time(object_id)
        if path.is_symlink() or not safe or not _inside(path, path.parent):
            self.add(kind, path, "retained", "unsafe_filesystem_object", size)
        elif when is None:
            self.add(kind, path, "retained", "invalid_timestamp", size)
        elif protected:
            self.add(kind, path, "retained", protected_reason, size)
        elif not terminal:
            self.add(kind, path, "retained", "active_or_incomplete", size)
        elif when >= self.cutoff:  # exact boundary is retained; deletion requires age > retention.
            self.add(kind, path, "retained", "within_retention", size)
        elif self.dry_run:
            self.add(kind, path, "would_delete", "expired", size)
        else:
            try:
                _remove(path)
            except OSError:
                self.add(kind, path, "error", "delete_failed", size)
            else:
                self.add(kind, path, "deleted", "expired", size)


def _valid_source(config: SyncConfig, attempt_id: str) -> str | None:
    metadata = _json(config.build_dir.resolve() / attempt_id / BUILD_METADATA_NAME)
    source = (metadata or {}).get("source")
    run_id = source.get("run_id") if isinstance(source, dict) else None
    expected = config.raw_dir.resolve() / str(run_id)
    if (not isinstance(source, dict) or not isinstance(run_id, str) or not RUN_ID_PATTERN.match(run_id)
            or source.get("raw_run_dir") != str(expected)):
        return None
    return run_id


def _publication_protection(config: SyncConfig) -> tuple[set[str], set[str], set[str], bool]:
    """Mirror rollback semantics; ambiguity makes build/raw cleanup fail closed.

    Every switched history record permits explicit rollback, so its build remains for this pass.  Only
    current/default-rollback history itself is permanent; after an older record expires, its build can
    expire on the next pass.  That ordering cannot leave a retained rollback record with no build.
    """
    try:
        live = live_attempt(config)
    except PublishRejected:
        return set(), set(), set(), False
    history_root = config.publish_dir.resolve() / "history"
    records: list[dict[str, Any]] = []
    clean = True
    for path in sorted(history_root.iterdir()) if history_root.is_dir() else []:
        match = HISTORY_PATTERN.match(path.name)
        if not match:
            continue
        record = _history_record(path, match)
        if record is None:
            clean = False
            continue
        records.append(record)
    required_history = {live} if live else set()
    for record in reversed(records):
        candidate = record.get("attempt_id")
        if record.get("switched") is True and isinstance(candidate, str) and candidate != live:
            required_history.add(candidate)
            break
    attempts = {
        str(record["attempt_id"]) for record in records
        if record.get("switched") is True and isinstance(record.get("attempt_id"), str)
    }
    if live:
        attempts.add(live)
    sources: set[str] = set()
    for attempt in attempts:
        source = _valid_source(config, attempt)
        if source is None:
            clean = False
        else:
            sources.add(source)
    return attempts, sources, required_history, clean


def _scan(config: SyncConfig, *, now: datetime, dry_run: bool) -> RetentionReport:
    plan = _Plan(config, now, dry_run)
    protected_attempts, protected_sources, protected_history, refs_clean = _publication_protection(config)

    build_root = config.build_dir.resolve()
    for path in sorted(build_root.iterdir()) if build_root.is_dir() else []:
        if path.name == "attempts":
            continue
        if not RUN_ID_PATTERN.match(path.name) or (not path.is_dir() and not path.is_symlink()):
            plan.add("build", path, "retained", "unknown_object")
            continue
        terminal = (path / COMPLETE_NAME).is_file() or (path / FAILED_NAME).is_file()
        protected = not refs_clean or path.name in protected_attempts
        plan.candidate("build", path, path.name, terminal=terminal, protected=protected,
                       protected_reason="ambiguous_reference" if not refs_clean else "publication_or_rollback")

    attempts_root = build_root / "attempts"
    for path in sorted(attempts_root.iterdir()) if attempts_root.is_dir() else []:
        match = ATTEMPT_PATTERN.match(path.name)
        record = _json(path) if match and path.is_file() and not path.is_symlink() else None
        if match is None or record is None or record.get("attempt_id") != (match.group(1) if match else None):
            plan.add("attempt_record", path, "retained", "unknown_or_corrupt_object")
            continue
        terminal = record.get("status") in {"success", "failed"}
        protected = not refs_clean or match.group(1) in protected_attempts
        plan.candidate("attempt_record", path, match.group(1), terminal=terminal, protected=protected,
                       protected_reason="ambiguous_reference" if not refs_clean else "publication_or_rollback")

    raw_root = config.raw_dir.resolve()
    for path in sorted(raw_root.iterdir()) if raw_root.is_dir() else []:
        if not RUN_ID_PATTERN.match(path.name) or (not path.is_dir() and not path.is_symlink()):
            plan.add("raw_run", path, "retained", "unknown_object")
            continue
        terminal = (path / "manifest.json").is_file() or (path / "FAILED.json").is_file()
        protected = not refs_clean or path.name in protected_sources
        plan.candidate("raw_run", path, path.name, terminal=terminal, protected=protected,
                       protected_reason="ambiguous_reference" if not refs_clean else "publication_or_rollback")

    history_root = config.publish_dir.resolve() / "history"
    for path in sorted(history_root.iterdir()) if history_root.is_dir() else []:
        match = HISTORY_PATTERN.match(path.name)
        record = _history_record(path, match) if match else None
        if match is None or record is None:
            plan.add("publication_history", path, "retained", "unknown_or_corrupt_object")
            continue
        attempt = record.get("attempt_id")
        protected = not refs_clean or attempt in protected_history
        plan.candidate("publication_history", path, match.group(2), terminal=record.get("status") != "running",
                       protected=protected, protected_reason="ambiguous_reference" if not refs_clean else "publication_or_rollback")

    cycles_root = config.lock_dir.resolve() / "scheduled-cycles" if config.lock_dir else None
    groups: dict[str, list[Path]] = {}
    if cycles_root and cycles_root.is_dir():
        for path in sorted(cycles_root.iterdir()):
            match = SCHEDULED_PATTERN.match(path.name)
            if match is None:
                plan.add("scheduled_cycle", path, "retained", "unknown_object")
            else:
                groups.setdefault(match.group(1), []).append(path)
    for cycle_id, paths in sorted(groups.items()):
        valid = True
        for path in paths:
            record = _json(path) if not path.is_symlink() and path.is_file() else None
            expected_phase = "started" if path.name.endswith(".started.json") else (
                "outcome" if path.name.endswith(".outcome.json") else "final"
            )
            if (record is None or record.get("cycle_id") != cycle_id
                    or record.get("scheduled_cycle_version") != "atlas-scheduled-cycle-v1"
                    or record.get("record_phase") != expected_phase):
                valid = False
        final = next((path for path in paths if path.name == f"{cycle_id}.json"), None)
        outcome = next((path for path in paths if path.name == f"{cycle_id}.outcome.json"), None)
        terminal = valid and (final is not None or outcome is not None)
        # Delete a cycle journal as one unit. A partial failure is reported and the next run is idempotent.
        old = (_id_time(cycle_id) or now) < plan.cutoff
        if not valid:
            reason, action = "unknown_or_corrupt_object", "retained"
        elif not terminal:
            reason, action = "active_or_incomplete", "retained"
        elif not old:
            reason, action = "within_retention", "retained"
        else:
            reason, action = "expired", "would_delete" if dry_run else "deleted"
        for path in paths:
            size, safe = _tree_bytes(path)
            if not safe:
                plan.add("scheduled_cycle", path, "retained", "unsafe_filesystem_object", size)
            elif action == "deleted":
                try:
                    _remove(path)
                except OSError:
                    plan.add("scheduled_cycle", path, "error", "delete_failed", size)
                else:
                    plan.add("scheduled_cycle", path, action, reason, size)
            else:
                plan.add("scheduled_cycle", path, action, reason, size)

    report = RetentionReport(_iso(now), _iso(plan.cutoff), config.retention_hours, dry_run, items=plan.items).finish()
    if report.counts.get("error"):
        report.status, report.error_category = "completed_with_errors", "cleanup_failed"
    return report


def _write_latest(config: SyncConfig, report: RetentionReport) -> None:
    if config.lock_dir is None:
        return
    root = config.lock_dir.resolve() / LATEST_DIR
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path, temporary = root / LATEST_NAME, root / f".{LATEST_NAME}.{os.getpid()}.tmp"
    summary = {key: value for key, value in report.as_dict().items() if key != "items"}
    data = json.dumps({"retention_version": RETENTION_VERSION, **summary}, indent=1, sort_keys=True).encode() + b"\n"
    with temporary.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _cleanup_locked(config: SyncConfig, *, dry_run: bool = False, clock: Clock = utc_now) -> RetentionReport:
    now = clock()
    try:
        report = _scan(config, now=now, dry_run=dry_run)
        if not dry_run:
            _write_latest(config, report)
        return report
    except Exception:  # noqa: BLE001 - safe category only
        return RetentionReport(_iso(now), _iso(now - timedelta(hours=config.retention_hours)), config.retention_hours,
                               dry_run, status="failed", error_category="cleanup_failed").finish()


def cleanup(environ: Mapping[str, str] | None = None, *, config: SyncConfig | None = None,
            dry_run: bool = False, clock: Clock = utc_now) -> RetentionReport:
    now = clock()
    try:
        cfg = config or load_sync_config(environ, now=now)
    except ConfigError:
        return RetentionReport(_iso(now), _iso(now), 0, dry_run, status="failed", error_category="configuration").finish()
    try:
        with production_lock(cfg, "retention", clock=clock):
            return _cleanup_locked(cfg, dry_run=dry_run, clock=lambda: now)
    except OperationLocked as error:
        return RetentionReport(_iso(now), _iso(now - timedelta(hours=cfg.retention_hours)), cfg.retention_hours,
                               dry_run, status="locked", error_category=error.failure_category, lock=error.as_dict()).finish()
    except LockError as error:
        return RetentionReport(_iso(now), _iso(now - timedelta(hours=cfg.retention_hours)), cfg.retention_hours,
                               dry_run, status="failed", error_category=error.failure_category).finish()


def latest_summary(config: SyncConfig) -> dict[str, Any] | None:
    """Expose only a successfully persisted aggregate; detailed paths/items never enter status."""
    if config.lock_dir is None:
        return None
    value = _json(config.lock_dir.resolve() / LATEST_DIR / LATEST_NAME)
    if value is None or value.get("retention_version") != RETENTION_VERSION or value.get("status") != "complete":
        return None
    return {key: value.get(key) for key in ("generated_at", "cutoff_at", "retention_hours", "counts", "bytes", "reasons")}


def exit_code(report: RetentionReport) -> int:
    if report.status == "complete":
        return 0
    if report.status == "locked":
        return 75
    return 2


def summary(report: RetentionReport) -> str:
    return (f"RETENTION {report.status.upper()} ({'DRY RUN' if report.dry_run else 'APPLIED'})\n"
            f"  cutoff: {report.cutoff_at}\n  counts: {report.counts}\n  bytes: {report.bytes}")
