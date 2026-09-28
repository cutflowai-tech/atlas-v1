"""One atomic scheduled cycle: one run-once attempt, then publish that exact attempt.

This is orchestration core, not a scheduler. A caller (future cron/systemd work) invokes
``scheduled_run``. One non-reentrant production lock spans the complete attempt, its
exact publication, and the immutable safe cycle record. No latest-build scan, fallback,
retry loop, alert, or retention behavior exists here.

Exit codes: 0 published; 2 configuration/lock configuration; 3 sync failure;
4 publish rejected/switch failure; 5 switched with inconsistent metadata;
6 cycle-record failure; 75 lock contention.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_commander.ingest import Clock, new_run_id, utc_now
from atlas_monday_probe.raw_store import write_immutable_atomic

from . import publish as publication
from . import run as sync
from .config import ConfigError, SyncConfig, load_sync_config
from .lock import EXIT_LOCKED, LockError, OperationLocked, production_lock

Transport = Callable[[str, dict[str, Any]], bytes]
SCHEDULED_RECORDS_DIR = "scheduled-cycles"
SCHEDULED_VERSION = "atlas-scheduled-cycle-v1"

PUBLISHED = "published"
SYNC_FAILED = "sync_failed"
PUBLISH_FAILED = "publish_failed"
PUBLISH_INCONSISTENT = "publish_inconsistent"
CONFIGURATION_FAILED = "configuration_failed"
LOCKED = "locked"
RECORD_FAILED = "record_failed"

EXIT_OK, EXIT_CONFIG, EXIT_SYNC_FAILED, EXIT_PUBLISH_FAILED, EXIT_INCONSISTENT, EXIT_RECORD_FAILED = 0, 2, 3, 4, 5, 6


@dataclass
class ScheduledResult:
    """Safe, JSON-ready evidence for one requested scheduled cycle."""

    cycle_id: str
    started_at: str
    finished_at: str | None = None
    status: str = "running"
    attempt_id: str | None = None
    source_run_id: str | None = None
    sync_status: str | None = None
    sync_failure_stage: str | None = None
    sync_failure_category: str | None = None
    publication_id: str | None = None
    publish_status: str | None = None
    publish_failure_stage: str | None = None
    publish_failure_category: str | None = None
    failure_stage: str | None = None
    failure_category: str | None = None
    switched: bool = False
    cycle_record: str | None = None
    lock: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(config: SyncConfig, result: ScheduledResult) -> Path:
    document = {"scheduled_cycle_version": SCHEDULED_VERSION, **result.as_dict()}
    document["cycle_record"] = None
    data = json.dumps(document, indent=1, sort_keys=True).encode() + b"\n"
    root = config.build_dir.expanduser().resolve() / SCHEDULED_RECORDS_DIR
    return write_immutable_atomic(root, f"{result.cycle_id}.json", data).path


def _complete(result: ScheduledResult, config: SyncConfig, clock: Clock) -> ScheduledResult:
    result.finished_at = _iso(clock())
    try:
        result.cycle_record = str(_record(config, result))
    except Exception:  # noqa: BLE001 - never leak raw filesystem exception text
        if result.status == PUBLISHED:
            result.status, result.failure_stage, result.failure_category = RECORD_FAILED, "record", "record_write_failed"
    return result


def scheduled_run(environ: Mapping[str, str] | None = None, *, config: SyncConfig | None = None,
                  transport: Transport | None = None, clock: Clock = utc_now,
                  monotonic: Callable[[], float] = time.monotonic,
                  sleep: Callable[[float], None] = time.sleep,
                  cycle_id_factory: Callable[[datetime], str] = new_run_id,
                  attempt_id_factory: Callable[[datetime], str] = new_run_id,
                  publication_id_factory: Callable[[datetime], str] = new_run_id,
                  max_duration_seconds: float | None = None,
                  monday_item_url: str | None = None) -> ScheduledResult:
    """Run and publish one exact attempt while holding the single production lock once."""
    started = clock()
    result = ScheduledResult(cycle_id=cycle_id_factory(started), started_at=_iso(started))
    try:
        cfg = config or load_sync_config(environ, require_token=True, now=started)
    except ConfigError:
        result.status, result.failure_stage, result.failure_category = CONFIGURATION_FAILED, "configuration", "configuration"
        result.finished_at = _iso(clock())
        return result

    try:
        with production_lock(cfg, "scheduled-run", target=result.cycle_id, clock=clock):
            attempt = sync._run_once_locked(
                config=cfg, transport=transport, clock=clock, monotonic=monotonic, sleep=sleep,
                attempt_id_factory=attempt_id_factory, max_duration_seconds=max_duration_seconds,
                monday_item_url=monday_item_url,
            )
            result.attempt_id, result.source_run_id, result.sync_status = attempt.attempt_id, attempt.source_run_id, attempt.status
            result.sync_failure_stage, result.sync_failure_category = attempt.failing_stage, attempt.error_category
            if attempt.status != "success":
                result.status, result.failure_stage = SYNC_FAILED, "sync"
                result.failure_category = attempt.error_category or "sync_failed"
                return _complete(result, cfg, clock)

            promoted = publication._publish_locked(
                attempt.attempt_id, config=cfg, clock=clock, publication_id_factory=publication_id_factory,
            )
            result.publication_id, result.publish_status = promoted.publication_id, promoted.status
            result.publish_failure_stage, result.publish_failure_category = promoted.failure_stage, promoted.failure_category
            result.switched = promoted.switched
            if promoted.status == publication.PUBLISHED:
                result.status = PUBLISHED
            elif promoted.status == publication.INCONSISTENT:
                result.status, result.failure_stage = PUBLISH_INCONSISTENT, "publish"
                result.failure_category = promoted.failure_category or "publication_inconsistent"
            else:
                result.status, result.failure_stage = PUBLISH_FAILED, "publish"
                result.failure_category = promoted.failure_category or "publish_failed"
            return _complete(result, cfg, clock)
    except OperationLocked as locked:
        result.status, result.failure_stage, result.failure_category = LOCKED, "lock", locked.failure_category
        result.lock, result.finished_at = locked.as_dict(), _iso(clock())
        return result
    except LockError as error:
        result.status, result.failure_stage, result.failure_category = CONFIGURATION_FAILED, "lock", error.failure_category
        result.finished_at = _iso(clock())
        return result


def exit_code(result: ScheduledResult) -> int:
    return {
        PUBLISHED: EXIT_OK, CONFIGURATION_FAILED: EXIT_CONFIG, SYNC_FAILED: EXIT_SYNC_FAILED,
        PUBLISH_FAILED: EXIT_PUBLISH_FAILED, PUBLISH_INCONSISTENT: EXIT_INCONSISTENT,
        RECORD_FAILED: EXIT_RECORD_FAILED, LOCKED: EXIT_LOCKED,
    }.get(result.status, EXIT_RECORD_FAILED)


def summary(result: ScheduledResult) -> str:
    if result.status == LOCKED:
        holder = (result.lock or {}).get("holder") or {}
        return (f"SCHEDULED RUN NOT STARTED (LOCKED): cycle {result.cycle_id}\n"
                f"  lock holder: {holder.get('operation', 'unknown')} pid {holder.get('pid', '?')}")
    lines = [f"SCHEDULED RUN {result.status.upper()}: cycle {result.cycle_id}",
             f"  exact attempt: {result.attempt_id or 'none'} [{result.sync_status or 'not started'}]",
             f"  publication:   {result.publication_id or 'none'} [{result.publish_status or 'not started'}]",
             f"  switched:      {'yes' if result.switched else 'no'}",
             f"  cycle record:  {result.cycle_record or 'not written'}"]
    if result.failure_category:
        lines.append(f"  failure:       {result.failure_stage} [{result.failure_category}]")
    return "\n".join(lines)
