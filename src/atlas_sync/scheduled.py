"""One scheduler-friendly Atlas cycle: exact run, exact publish, status, and alerts.

The future OS scheduler invokes :func:`scheduled_run` once per trigger. This module
contains no sleep loop, retry policy, or alert transport. One existing production
lock spans the run, publication of that exact attempt, Task 7 status evaluation,
alert-state update, and immutable cycle record.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_commander.ingest import RUN_ID_PATTERN, Clock, new_run_id, utc_now
from atlas_monday_probe.raw_store import write_immutable_atomic

from . import alerts
from . import publish as publication
from . import run as sync
from . import status as operational_status
from .config import ConfigError, SyncConfig, load_sync_config
from .lock import EXIT_LOCKED, LockError, OperationLocked, production_lock

Transport = Callable[[str, dict[str, Any]], bytes]
SCHEDULED_RECORDS_DIR = "scheduled-cycles"
SCHEDULED_VERSION = "atlas-scheduled-cycle-v1"

PUBLISHED = "published"
SYNC_FAILED = "sync_failed"
PUBLISH_FAILED = "publish_failed"
PUBLISH_INCONSISTENT = "publish_inconsistent"
STATUS_FAILED = "status_failed"
ALERT_STATE_FAILED = "alert_state_failed"
CONFIGURATION_FAILED = "configuration_failed"
LOCKED = "locked"
RECORD_FAILED = "record_failed"

EXIT_OK, EXIT_CONFIG, EXIT_SYNC_FAILED, EXIT_PUBLISH_FAILED = 0, 2, 3, 4
EXIT_INCONSISTENT, EXIT_OPERATIONAL_STATE, EXIT_RECORD_FAILED = 5, 6, 7


@dataclass
class ScheduledResult:
    """Allow-listed, JSON-ready evidence for one requested scheduled cycle."""

    cycle_id: str
    started_at: str
    sequence: int | None = None
    completed_at: str | None = None
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
    previous_live_attempt: str | None = None
    resulting_live_attempt: str | None = None
    final_system_state: str | None = None
    final_freshness_state: str | None = None
    final_live_usable: bool | None = None
    consecutive_scheduled_failures: int | None = None
    active_alert_types: tuple[str, ...] = ()
    failure_stage: str | None = None
    failure_category: str | None = None
    switched: bool = False
    outcome_record: str | None = None
    cycle_record: str | None = None
    lock: dict[str, Any] | None = None
    retention: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _records_root(config: SyncConfig) -> Path:
    if config.lock_dir is None:
        raise LockError("no operational state directory is configured")
    return config.lock_dir.expanduser().resolve() / SCHEDULED_RECORDS_DIR


def _write_record(config: SyncConfig, result: ScheduledResult, phase: str) -> Path:
    document = {"scheduled_cycle_version": SCHEDULED_VERSION, "record_phase": phase,
                "scheduled_for": result.started_at, **result.as_dict()}
    document["outcome_record"] = None
    document["cycle_record"] = None
    data = json.dumps(document, indent=1, sort_keys=True).encode() + b"\n"
    suffix = "" if phase == "final" else f".{phase}"
    return write_immutable_atomic(_records_root(config), f"{result.cycle_id}{suffix}.json", data).path


def _record_started(config: SyncConfig, result: ScheduledResult) -> Path:
    return _write_record(config, result, "started")


def _record_outcome(config: SyncConfig, result: ScheduledResult) -> Path:
    return _write_record(config, result, "outcome")


def _record_final(config: SyncConfig, result: ScheduledResult) -> Path:
    return _write_record(config, result, "final")


def _read_record(path: Path, expected_id: str) -> dict[str, Any] | None:
    try:
        document = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) and document.get("cycle_id") == expected_id else None


def _cycle_records(config: SyncConfig) -> list[dict[str, Any]]:
    """Terminal records, with orphaned durable starts reconstructed as interrupted failures."""
    records: list[dict[str, Any]] = []
    try:
        root = _records_root(config)
        paths = sorted(root.glob("*.json"))
    except (OSError, LockError):
        return records
    cycle_ids = sorted({path.name.split(".", 1)[0] for path in paths})
    for cycle_id in cycle_ids:
        if not RUN_ID_PATTERN.match(cycle_id):
            continue
        final = _read_record(root / f"{cycle_id}.json", cycle_id)
        outcome = _read_record(root / f"{cycle_id}.outcome.json", cycle_id)
        started = _read_record(root / f"{cycle_id}.started.json", cycle_id)
        if final is not None:
            records.append(final)
        elif outcome is not None:
            records.append(outcome)
        elif started is not None:
            records.append({**started, "status": "interrupted", "failure_stage": "process",
                            "failure_category": "interrupted_before_outcome"})
    return records


def _actual_live(config: SyncConfig) -> str | None:
    try:
        return publication.live_attempt(config)
    except publication.PublishRejected:
        return None


def _next_sequence(config: SyncConfig) -> int:
    sequences = [record.get("sequence") for record in _cycle_records(config)]
    return max((value for value in sequences if isinstance(value, int) and value > 0), default=0) + 1


def _evaluate_status(result: ScheduledResult, config: SyncConfig, clock: Clock) -> operational_status.StatusSnapshot | None:
    """Reuse Task 7 status without introducing a second health implementation."""
    try:
        snapshot = operational_status.evaluate_status(config=config, clock=clock)
    except Exception:  # noqa: BLE001 - category only; never persist exception text
        result.status, result.failure_stage, result.failure_category = STATUS_FAILED, "status", "status_failed"
        return None
    result.final_system_state = snapshot.system_state
    result.final_freshness_state = snapshot.freshness_state
    result.final_live_usable = snapshot.live_usable
    return snapshot


def _complete(result: ScheduledResult, config: SyncConfig, clock: Clock, *, evaluate: bool = True) -> ScheduledResult:
    published_successfully = result.status == PUBLISHED
    result.resulting_live_attempt = _actual_live(config)
    snapshot = _evaluate_status(result, config, clock) if evaluate else None
    result.completed_at = _iso(clock())
    try:
        # The core outcome is durable before mutable alert state changes. Restart
        # reconstruction therefore never observes an alert transition without its cycle.
        result.outcome_record = str(_record_outcome(config, result))
    except Exception:  # noqa: BLE001 - never leak raw filesystem exception text
        if result.status != LOCKED:
            result.status, result.failure_stage, result.failure_category = RECORD_FAILED, "record", "record_write_failed"
        return result
    if snapshot is not None:
        try:
            if config.lock_dir is None:
                raise alerts.AlertStateError("operational state directory unavailable")
            update = alerts.update_alert_state(
                snapshot=snapshot, scheduled_cycles=_cycle_records(config),
                data_dir=config.lock_dir, observed_at=snapshot.generated_at,
            )
            result.consecutive_scheduled_failures = update.consecutive_scheduled_failures
            result.active_alert_types = tuple(sorted(str(item["kind"]) for item in update.active_incidents))
        except Exception:  # noqa: BLE001 - category only; never persist exception text
            result.status, result.failure_stage, result.failure_category = ALERT_STATE_FAILED, "alerts", "alert_state_failed"
    if published_successfully and snapshot is not None:
        try:
            from .retention import _cleanup_locked

            result.retention = _cleanup_locked(config, dry_run=False, clock=clock).as_dict()
        except Exception:  # noqa: BLE001 - publication remains valid; report a safe cleanup-only failure
            result.retention = {"status": "failed", "failures": ["retention_failed"]}
    try:
        result.cycle_record = str(_record_final(config, result))
    except Exception:  # noqa: BLE001 - outcome remains durable and restart-safe
        if result.status != LOCKED:
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
    """Run and publish one exact attempt while holding the shared production lock once."""
    started = clock()
    result = ScheduledResult(cycle_id=cycle_id_factory(started), started_at=_iso(started))
    try:
        cfg = config or load_sync_config(environ, require_token=True, now=started)
    except ConfigError:
        result.status, result.failure_stage, result.failure_category = CONFIGURATION_FAILED, "configuration", "configuration"
        result.completed_at = _iso(clock())
        return result

    try:
        with production_lock(cfg, "scheduled-run", target=result.cycle_id, clock=clock):
            result.sequence = _next_sequence(cfg)
            try:
                _record_started(cfg, result)
            except Exception:  # noqa: BLE001 - no Monday request or build starts without durable STARTED evidence
                result.status, result.failure_stage, result.failure_category = RECORD_FAILED, "record", "record_start_failed"
                result.completed_at = _iso(clock())
                return result
            result.previous_live_attempt = _actual_live(cfg)
            attempt = sync._run_once_locked(
                config=cfg, transport=transport, clock=clock, monotonic=monotonic, sleep=sleep,
                attempt_id_factory=attempt_id_factory, max_duration_seconds=max_duration_seconds,
                monday_item_url=monday_item_url,
            )
            result.attempt_id, result.source_run_id, result.sync_status = attempt.attempt_id, attempt.source_run_id, attempt.status
            result.sync_failure_stage, result.sync_failure_category = attempt.failing_stage, attempt.error_category
            if attempt.status != "success":
                result.status, result.failure_stage, result.failure_category = SYNC_FAILED, "sync", "run_failed"
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
                result.failure_category = "publish_metadata_inconsistent"
            else:
                result.status, result.failure_stage = PUBLISH_FAILED, "publish"
                result.failure_category = "publish_switch_failed" if promoted.status == publication.SWITCH_FAILED else "publish_rejected"
            return _complete(result, cfg, clock)
    except OperationLocked as locked:
        result.status, result.failure_stage, result.failure_category = LOCKED, "lock", locked.failure_category
        result.lock = locked.as_dict()
        # A skipped trigger is recorded, but alert state and failure streak are unchanged.
        return _complete(result, cfg, clock, evaluate=False)
    except LockError as error:
        result.status, result.failure_stage, result.failure_category = CONFIGURATION_FAILED, "lock", error.failure_category
        result.completed_at = _iso(clock())
        return result


def exit_code(result: ScheduledResult) -> int:
    return {
        PUBLISHED: EXIT_OK, CONFIGURATION_FAILED: EXIT_CONFIG, SYNC_FAILED: EXIT_SYNC_FAILED,
        PUBLISH_FAILED: EXIT_PUBLISH_FAILED, PUBLISH_INCONSISTENT: EXIT_INCONSISTENT,
        STATUS_FAILED: EXIT_OPERATIONAL_STATE, ALERT_STATE_FAILED: EXIT_OPERATIONAL_STATE,
        RECORD_FAILED: EXIT_RECORD_FAILED, LOCKED: EXIT_LOCKED,
    }.get(result.status, EXIT_RECORD_FAILED)


def summary(result: ScheduledResult) -> str:
    if result.status == LOCKED:
        holder = (result.lock or {}).get("holder") or {}
        return (f"SCHEDULED RUN SKIPPED (LOCKED): cycle {result.cycle_id}\n"
                f"  lock holder: {holder.get('operation', 'unknown')} pid {holder.get('pid', '?')}\n"
                f"  cycle record: {result.cycle_record or 'not written'}")
    lines = [f"SCHEDULED RUN {result.status.upper()}: cycle {result.cycle_id}",
             f"  exact attempt: {result.attempt_id or 'none'} [{result.sync_status or 'not started'}]",
             f"  publication:   {result.publication_id or 'none'} [{result.publish_status or 'not started'}]",
             f"  live attempt:  {result.resulting_live_attempt or 'none'}",
             f"  final status:  {result.final_system_state or 'unknown'} / {result.final_freshness_state or 'unknown'}",
             f"  active alerts: {', '.join(result.active_alert_types) or 'none'}",
             f"  retention:     {(result.retention or {}).get('status', 'not run')}",
             f"  cycle record:  {result.cycle_record or 'not written'}"]
    if result.failure_category:
        lines.append(f"  failure:       {result.failure_stage} [{result.failure_category}]")
    return "\n".join(lines)
