"""Read-only operational status derived solely from persisted Atlas evidence.

Freshness is the age of the Monday retrieval that powers ``published/current``:
``fresh`` when age <= sync interval, ``delayed`` when interval < age < stale
threshold, and ``stale`` when age >= the stale threshold.  Publish time is
reported separately and never participates in freshness.

System state is ``failed`` when there is no usable live publication,
``degraded`` when the live build validates but publication metadata disagrees
or the latest sync attempt failed, and ``healthy`` otherwise. ``unknown`` is
reserved for an unreadable configuration/evaluation context.

The evaluator never takes the production lock, calls Monday, or writes files.
Exit codes: 0 healthy+fresh; 1 usable live dashboard with delayed/stale data or
degraded system; 2 failed/unknown system (no trustworthy live publication).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_commander.ingest import RUN_ID_PATTERN, utc_now

from .config import ConfigError, SyncConfig, load_sync_config
from .publish import CURRENT_METADATA_NAME, HISTORY_DIR, PublishRejected, live_attempt, validate_build
from .run import ATTEMPTS_DIR, BUILD_METADATA_NAME

SYSTEM_HEALTHY, SYSTEM_DEGRADED, SYSTEM_FAILED, SYSTEM_UNKNOWN = "healthy", "degraded", "failed", "unknown"
FRESH, DELAYED, STALE, FRESHNESS_UNKNOWN = "fresh", "delayed", "stale", "unknown"
EXIT_OK, EXIT_WARNING, EXIT_FAILURE = 0, 1, 2


@dataclass(frozen=True)
class HealthCheck:
    name: str
    status: str
    category: str | None = None


@dataclass
class StatusSnapshot:
    generated_at: str
    system_state: str
    freshness_state: str
    current_publication: dict[str, Any] | None
    last_attempt: dict[str, Any] | None
    last_successful_attempt: dict[str, Any] | None
    freshness: dict[str, Any]
    checks: list[HealthCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failure_categories: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _json_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _safe_attempt(record: Mapping[str, Any]) -> dict[str, Any]:
    """Allow-list persisted attempt fields; notably excludes exception text/type and paths."""
    return {key: record.get(key) for key in (
        "attempt_id", "started_at", "finished_at", "status", "error_category", "source_run_id"
    )}


def _attempts(config: SyncConfig) -> list[dict[str, Any]]:
    root = config.build_dir.expanduser().resolve() / ATTEMPTS_DIR
    records: list[dict[str, Any]] = []
    try:
        paths = sorted(root.glob("*.json"))
    except OSError:
        return records
    for path in paths:
        if not RUN_ID_PATTERN.match(path.stem):
            continue
        record = _json_object(path)
        if record is not None and record.get("attempt_id") == path.stem:
            records.append(record)
    return records


def _publication_record(config: SyncConfig, attempt_id: str) -> dict[str, Any] | None:
    """Newest successful switch for the live attempt; history is safer than CURRENT on disagreement."""
    root = config.publish_dir.expanduser().resolve() / HISTORY_DIR
    records: list[dict[str, Any]] = []
    try:
        paths = sorted(root.glob("*.json"))
    except OSError:
        return None
    for path in paths:
        record = _json_object(path)
        if record and record.get("attempt_id") == attempt_id and record.get("switched") is True:
            records.append(record)
    return records[-1] if records else None


def _freshness(retrieved_at: object, config: SyncConfig, now: datetime) -> tuple[str, float | None]:
    retrieved = _parse_time(retrieved_at)
    if retrieved is None:
        return FRESHNESS_UNKNOWN, None
    age = max(0.0, (now.astimezone(timezone.utc) - retrieved).total_seconds())
    if age >= config.stale_after_seconds:
        return STALE, age
    if age > config.sync_interval_seconds:
        return DELAYED, age
    return FRESH, age


def evaluate_status(environ: Mapping[str, str] | None = None, *, config: SyncConfig | None = None,
                    clock: Callable[[], datetime] = utc_now) -> StatusSnapshot:
    """Evaluate current status without locks, network access, repair, caching, or any other write."""
    now = clock()
    generated = _iso(now)
    try:
        cfg = config or load_sync_config(environ, now=now)
    except ConfigError:
        return StatusSnapshot(generated, SYSTEM_UNKNOWN, FRESHNESS_UNKNOWN, None, None, None,
                              {"age_seconds": None, "expected_interval_seconds": None, "stale_after_seconds": None},
                              [HealthCheck("configuration", "failed", "configuration")], [], ["configuration"])

    records = _attempts(cfg)
    last_raw = records[-1] if records else None
    successes = [record for record in records if record.get("status") == "success"]
    last_success_raw = successes[-1] if successes else None
    last = _safe_attempt(last_raw) if last_raw else None
    last_success = _safe_attempt(last_success_raw) if last_success_raw else None
    checks: list[HealthCheck] = []
    warnings: list[str] = []
    categories: list[str] = []

    try:
        attempt_id = live_attempt(cfg)
    except PublishRejected as error:
        checks.append(HealthCheck("current_pointer", "failed", error.category))
        categories.append(error.category)
        attempt_id = None
    if attempt_id is None:
        category = categories[0] if categories else "no_current_publication"
        if not checks:
            checks.append(HealthCheck("current_pointer", "failed", category))
            categories.append(category)
        return StatusSnapshot(generated, SYSTEM_FAILED, FRESHNESS_UNKNOWN, None, last, last_success,
                              {"age_seconds": None, "expected_interval_seconds": cfg.sync_interval_seconds,
                               "stale_after_seconds": cfg.stale_after_seconds}, checks, warnings, categories)
    checks.append(HealthCheck("current_pointer", "passed"))

    publish_root = cfg.publish_dir.expanduser().resolve()
    current_meta = _json_object(publish_root / CURRENT_METADATA_NAME)
    metadata_agrees = current_meta is not None and current_meta.get("attempt_id") == attempt_id
    checks.append(HealthCheck("current_metadata", "passed" if metadata_agrees else "warning",
                              None if metadata_agrees else "current_metadata_inconsistent"))
    if not metadata_agrees:
        warnings.append("current_metadata_inconsistent")

    try:
        validated = validate_build(cfg, attempt_id)
    except PublishRejected as error:
        checks.append(HealthCheck("live_build", "failed", error.category))
        categories.append(error.category)
        return StatusSnapshot(generated, SYSTEM_FAILED, FRESHNESS_UNKNOWN,
                              {"attempt_id": attempt_id}, last, last_success,
                              {"age_seconds": None, "expected_interval_seconds": cfg.sync_interval_seconds,
                               "stale_after_seconds": cfg.stale_after_seconds}, checks, warnings, categories)
    checks.append(HealthCheck("live_build", "passed"))

    build = _json_object(validated.site.parent / BUILD_METADATA_NAME) or {}
    raw_source = build.get("source")
    source: dict[str, Any] = raw_source if isinstance(raw_source, dict) else {}
    publication = _publication_record(cfg, attempt_id)
    published_at = publication.get("published_at") if publication else (
        current_meta.get("published_at") if metadata_agrees and current_meta else None
    )
    current = {
        "attempt_id": attempt_id,
        "publication_id": publication.get("publication_id") if publication else (
            current_meta.get("publication_id") if metadata_agrees and current_meta else None
        ),
        "published_at": published_at,
        "source_run_id": validated.source_run_id,
        "monday_retrieved_at": source.get("retrieved_at"),
        "coverage": source.get("coverage"),
        "contract_version": validated.contract_version,
        "board_id": validated.board_id,
    }
    freshness_state, age = _freshness(current["monday_retrieved_at"], cfg, now)
    if freshness_state == FRESHNESS_UNKNOWN:
        categories.append("retrieval_time_invalid")
        checks.append(HealthCheck("retrieval_time", "failed", "retrieval_time_invalid"))
        system = SYSTEM_FAILED
    else:
        checks.append(HealthCheck("retrieval_time", "passed"))
        latest_failed = last is not None and last.get("status") not in {"success", "locked"}
        if latest_failed:
            warnings.append("latest_sync_attempt_failed")
        system = SYSTEM_DEGRADED if (not metadata_agrees or latest_failed) else SYSTEM_HEALTHY

    return StatusSnapshot(generated, system, freshness_state, current, last, last_success,
                          {"age_seconds": age, "expected_interval_seconds": cfg.sync_interval_seconds,
                           "stale_after_seconds": cfg.stale_after_seconds}, checks, warnings, categories)


def exit_code(snapshot: StatusSnapshot) -> int:
    if snapshot.system_state in {SYSTEM_FAILED, SYSTEM_UNKNOWN}:
        return EXIT_FAILURE
    if snapshot.system_state != SYSTEM_HEALTHY or snapshot.freshness_state != FRESH:
        return EXIT_WARNING
    return EXIT_OK


def summary(snapshot: StatusSnapshot) -> str:
    current = snapshot.current_publication or {}
    last = snapshot.last_attempt or {}
    success = snapshot.last_successful_attempt or {}
    coverage = current.get("coverage") or {}
    return "\n".join([
        f"Atlas system: {snapshot.system_state.upper()}",
        f"Data freshness: {snapshot.freshness_state.upper()}" +
        (f" ({snapshot.freshness['age_seconds']:.0f}s old)" if snapshot.freshness.get("age_seconds") is not None else ""),
        f"Live build: {current.get('attempt_id') or 'none'}",
        f"Source run: {current.get('source_run_id') or 'unknown'}",
        f"Monday retrieved: {current.get('monday_retrieved_at') or 'unknown'}",
        f"Published: {current.get('published_at') or 'unknown'}",
        (f"Evidence coverage: {coverage.get('start') or coverage.get('history_start') or 'unknown'} to "
         f"{coverage.get('end') or coverage.get('history_end') or 'unknown'}"),
        f"Last sync attempt: {last.get('attempt_id') or 'none'} [{last.get('status') or 'unknown'}]",
        f"Last successful sync: {success.get('attempt_id') or 'none'}",
    ])
