"""Deterministic persisted alert lifecycle derived from Task 7 status snapshots.

This module has no health evaluator of its own.  It maps a *runtime*
:class:`atlas_sync.status.StatusSnapshot` and persisted scheduler cycle records to four
operational alert kinds, then atomically replaces ``ATLAS_DATA_DIR/alerts/state.json``.
It does not send notifications, call Monday, acquire the production lock, or persist free-form
exception text.

Callers serialize calls to :func:`update_alert_state` (normally one scheduler process).  A repeated
active condition updates one incident's ``occurrence_count`` and ``last_observed_at``.  Absence
resolves it.  A later recurrence creates a new incident linked to the resolved predecessor.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .status import HealthCheck, StatusSnapshot

ALERT_VERSION = "atlas-alert-state-v1"
ALERTS_DIR = "alerts"
STATE_FILE = "state.json"
WARNING, CRITICAL = "warning", "critical"
ACTIVE, RESOLVED = "active", "resolved"

DATA_STALE = "data_stale"
SCHEDULED_FAILURES = "consecutive_scheduled_failures"
PUBLICATION_INTEGRITY = "publication_integrity"
METADATA_INCONSISTENCY = "publication_metadata_inconsistent"
ALERT_ORDER = (DATA_STALE, SCHEDULED_FAILURES, PUBLICATION_INTEGRITY, METADATA_INCONSISTENCY)

PUBLICATION_CHECKS = frozenset({
    "current_pointer", "build_completion", "build_metadata", "artifact_hashes", "locales",
    "raw_source", "raw_verification", "provenance",
})
METADATA_CHECKS = frozenset({"current_metadata", "publication_history"})
SAFE_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


class AlertStateError(ValueError):
    """Unsafe input or unreadable persisted alert state; existing state is never overwritten."""


@dataclass(frozen=True)
class AlertSignal:
    kind: str
    severity: str
    evidence: dict[str, Any]


@dataclass(frozen=True)
class AlertUpdate:
    state_path: Path
    consecutive_scheduled_failures: int
    active_incidents: tuple[dict[str, Any], ...]
    emitted_events: tuple[dict[str, Any], ...]


def _utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise AlertStateError("observed_at must be an ISO-8601 timestamp") from None
    if parsed.tzinfo is None:
        raise AlertStateError("observed_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: str) -> str:
    return _utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _code(value: object) -> str | None:
    return value if isinstance(value, str) and SAFE_CODE.fullmatch(value) else None


def _check_values(checks: Iterable[HealthCheck | Mapping[str, Any]]) -> list[tuple[str, str]]:
    values = []
    for check in checks:
        name = check.name if isinstance(check, HealthCheck) else check.get("name")
        state = check.status if isinstance(check, HealthCheck) else check.get("status")
        safe_name, safe_state = _code(name), _code(state)
        if safe_name and safe_state:
            values.append((safe_name, safe_state))
    return values


def scheduled_failure_streak(records: Iterable[Mapping[str, Any]]) -> int:
    """Return the trailing failed scheduled-cycle count.

    Completed records are ordered by ``scheduled_for`` then ``cycle_id``. ``running`` records do
    not end an existing streak; the newest completed success does. Malformed records are ignored.
    This is the stable scheduler integration boundary; records may be loaded from any persisted
    scheduler journal without coupling alerts to its storage layout.
    """
    completed: list[tuple[int, str, str, str]] = []
    for record in records:
        cycle_id = _code(record.get("cycle_id"))
        scheduled_for = record.get("scheduled_for") or record.get("started_at")
        raw_state = record.get("status")
        state = "success" if raw_state in {"success", "published"} else (
            "failed" if raw_state in {
                "failed", "sync_failed", "publish_failed", "publish_inconsistent",
                "status_failed", "alert_state_failed", "record_failed", "interrupted",
            } else None
        )
        if cycle_id is None or not isinstance(scheduled_for, str) or state is None:
            continue
        try:
            ordered_at = _iso(scheduled_for)
        except AlertStateError:
            continue
        sequence = record.get("sequence")
        order = sequence if isinstance(sequence, int) and sequence > 0 else 0
        completed.append((order, ordered_at, cycle_id, state))
    completed.sort(key=lambda item: (item[0], item[1], item[2]))
    count = 0
    for _, _, _, state in reversed(completed):
        if state == "success":
            break
        count += 1
    return count


def derive_alert_signals(snapshot: StatusSnapshot, scheduled_cycles: Iterable[Mapping[str, Any]]) -> tuple[AlertSignal, ...]:
    """Map Task 7 semantics to the four alert kinds without recalculating system health."""
    if snapshot.snapshot_scope != "runtime":
        raise AlertStateError("alerts require a runtime StatusSnapshot")
    signals: dict[str, AlertSignal] = {}
    if snapshot.freshness_state == "stale":
        freshness = snapshot.freshness
        signals[DATA_STALE] = AlertSignal(DATA_STALE, CRITICAL, {
            "age_seconds": freshness.get("age_seconds"),
            "stale_after_seconds": freshness.get("stale_after_seconds"),
        })

    streak = scheduled_failure_streak(scheduled_cycles)
    threshold = snapshot.failure_threshold
    if streak and isinstance(threshold, int) and threshold > 0 and streak >= threshold:
        signals[SCHEDULED_FAILURES] = AlertSignal(SCHEDULED_FAILURES, CRITICAL, {
            "consecutive_failures": streak, "failure_threshold": threshold,
        })

    checks = _check_values(snapshot.checks)
    failed_publication = sorted(name for name, state in checks if name in PUBLICATION_CHECKS and state == "failed")
    if not snapshot.live_usable and failed_publication:
        current = snapshot.current_publication or {}
        signals[PUBLICATION_INTEGRITY] = AlertSignal(PUBLICATION_INTEGRITY, CRITICAL, {
            "failed_checks": failed_publication,
            "current_attempt_id": _code(current.get("attempt_id")),
        })

    inconsistent = sorted(name for name, state in checks if name in METADATA_CHECKS and state != "passed")
    if "publication_metadata_inconsistent" in snapshot.warnings or inconsistent:
        signals[METADATA_INCONSISTENCY] = AlertSignal(METADATA_INCONSISTENCY, WARNING, {
            "affected_checks": inconsistent,
        })
    return tuple(signals[kind] for kind in ALERT_ORDER if kind in signals)


def _empty_state() -> dict[str, Any]:
    return {"alert_version": ALERT_VERSION, "next_sequence": 1, "last_observation": None,
            "incidents": [], "events": []}


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_state()
    if path.is_symlink() or not path.is_file():
        raise AlertStateError("alert state path must be a regular file")
    try:
        state = json.loads(path.read_bytes())
    except (OSError, ValueError):
        raise AlertStateError("persisted alert state is unreadable") from None
    if (not isinstance(state, dict) or state.get("alert_version") != ALERT_VERSION
            or not isinstance(state.get("next_sequence"), int)
            or not isinstance(state.get("incidents"), list) or not isinstance(state.get("events"), list)):
        raise AlertStateError("persisted alert state has an unsupported shape")
    return state


def _next_id(state: dict[str, Any], prefix: str) -> str:
    sequence = state["next_sequence"]
    state["next_sequence"] = sequence + 1
    return f"{prefix}-{sequence:08d}"


def _event(state: dict[str, Any], at: str, action: str, incident: dict[str, Any]) -> dict[str, Any]:
    event = {
        "event_id": _next_id(state, "alert-event"), "observed_at": at, "action": action,
        "incident_id": incident["incident_id"], "kind": incident["kind"],
        "severity": incident["severity"], "occurrence_count": incident["occurrence_count"],
    }
    state["events"].append(event)
    return event


def _apply(state: dict[str, Any], signals: tuple[AlertSignal, ...], observed_at: str) -> tuple[dict[str, Any], ...]:
    emitted: list[dict[str, Any]] = []
    by_kind = {signal.kind: signal for signal in signals}
    active = {incident["kind"]: incident for incident in state["incidents"] if incident.get("state") == ACTIVE}
    for kind in ALERT_ORDER:
        incident, signal = active.get(kind), by_kind.get(kind)
        if signal is not None and incident is not None:
            incident.update(severity=signal.severity, last_observed_at=observed_at,
                            occurrence_count=incident["occurrence_count"] + 1, evidence=signal.evidence)
            emitted.append(_event(state, observed_at, "updated", incident))
        elif signal is not None:
            previous = next((item for item in reversed(state["incidents"])
                             if item.get("kind") == kind and item.get("state") == RESOLVED), None)
            incident = {
                "incident_id": _next_id(state, "alert"), "kind": kind, "severity": signal.severity,
                "state": ACTIVE, "first_observed_at": observed_at, "last_observed_at": observed_at,
                "occurrence_count": 1, "resolved_at": None, "evidence": signal.evidence,
                "previous_incident_id": previous.get("incident_id") if previous else None,
            }
            state["incidents"].append(incident)
            emitted.append(_event(state, observed_at, "reactivated" if previous else "opened", incident))
        elif incident is not None:
            incident.update(state=RESOLVED, resolved_at=observed_at)
            emitted.append(_event(state, observed_at, "resolved", incident))
    return tuple(emitted)


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_atomic(path: Path, state: Mapping[str, Any]) -> None:
    data = json.dumps(state, indent=1, sort_keys=True).encode() + b"\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def update_alert_state(*, snapshot: StatusSnapshot, scheduled_cycles: Iterable[Mapping[str, Any]],
                       data_dir: Path, observed_at: str | None = None) -> AlertUpdate:
    """Persist one observation under ``data_dir/alerts`` and return active incidents/events."""
    at = _iso(observed_at or snapshot.generated_at)
    records = list(scheduled_cycles)
    failure_count = scheduled_failure_streak(records)
    signals = derive_alert_signals(snapshot, records)
    root = data_dir.expanduser().resolve() / ALERTS_DIR
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise AlertStateError("alerts path must be a directory")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = root / STATE_FILE
    state = _load(path)
    emitted = _apply(state, signals, at)
    state["last_observation"] = {
        "observed_at": at, "consecutive_scheduled_failures": failure_count,
        "failure_threshold": snapshot.failure_threshold,
    }
    _write_atomic(path, state)
    active = tuple(dict(incident) for incident in state["incidents"] if incident.get("state") == ACTIVE)
    return AlertUpdate(path, failure_count, active, emitted)


def read_alert_state(data_dir: Path) -> dict[str, Any]:
    """Read persisted operational alert state without mutation."""
    return _load(data_dir.expanduser().resolve() / ALERTS_DIR / STATE_FILE)


def as_dict(update: AlertUpdate) -> dict[str, Any]:
    """Safe JSON-compatible integration result (the local filesystem path is intentionally omitted)."""
    return {"consecutive_scheduled_failures": update.consecutive_scheduled_failures,
            "active_incidents": list(update.active_incidents), "emitted_events": list(update.emitted_events)}
