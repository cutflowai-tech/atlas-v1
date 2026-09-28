"""Read-only operational status derived solely from persisted Atlas evidence.

There are no imports from :mod:`atlas_sync.run`; publication imports are lazy so
the build orchestration may safely import the shared snapshot model. Runtime
evaluation never takes the production lock, calls Monday, or writes files.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_commander.ingest import RUN_ID_PATTERN, utc_now

from .config import ConfigError, SyncConfig, load_sync_config

SYSTEM_HEALTHY, SYSTEM_DEGRADED, SYSTEM_FAILED, SYSTEM_UNKNOWN = "healthy", "degraded", "failed", "unknown"
FRESH, DELAYED, STALE, FRESHNESS_UNKNOWN = "fresh", "delayed", "stale", "unknown"
EXIT_OK, EXIT_WARNING, EXIT_FAILURE = 0, 1, 2
ATTEMPTS_DIR, BUILD_METADATA_NAME = "attempts", "build.json"
CURRENT_METADATA_NAME, HISTORY_DIR = "CURRENT.json", "history"
PUBLICATION_VERSION, POINTER_NAME = "atlas-publication-v1", "current"
STABILITY_ATTEMPTS = 2
GROUPED_BUILD_CHECKS = (
    "build_completion", "build_metadata", "artifact_hashes", "locales",
    "raw_source", "raw_verification", "provenance",
)


@dataclass(frozen=True)
class HealthCheck:
    name: str
    status: str
    category: str | None = None


@dataclass
class StatusSnapshot:
    generated_at: str
    snapshot_scope: str
    system_state: str
    freshness_state: str
    live_usable: bool
    current_publication: dict[str, Any] | None
    last_attempt: dict[str, Any] | None
    last_successful_attempt: dict[str, Any] | None
    freshness: dict[str, Any]
    consecutive_failures: int = 0
    failure_threshold: int | None = None
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
    """Allow-list safe fields; exception text/type and filesystem paths never escape."""
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
        if RUN_ID_PATTERN.match(path.stem):
            record = _json_object(path)
            if record is not None and record.get("attempt_id") == path.stem:
                records.append(record)
    return records


def _consecutive_failures(records: list[dict[str, Any]]) -> int:
    count = 0
    for record in reversed(records):
        if record.get("status") != "failed":
            break
        count += 1
    return count


def _history(config: SyncConfig) -> list[tuple[Path, dict[str, Any]]]:
    root = config.publish_dir.expanduser().resolve() / HISTORY_DIR
    records: list[tuple[Path, dict[str, Any]]] = []
    try:
        paths = sorted(root.glob("*.json"))
    except OSError:
        return records
    for path in paths:
        record = _json_object(path)
        if record is not None:
            records.append((path, record))
    return records


def _freshness_values(retrieved_at: object, interval: int, stale_after: int,
                      now: datetime) -> tuple[str, float | None]:
    retrieved = _parse_time(retrieved_at)
    if retrieved is None:
        return FRESHNESS_UNKNOWN, None
    age = (now.astimezone(timezone.utc) - retrieved).total_seconds()
    if age < 0:
        return FRESHNESS_UNKNOWN, age
    if age >= stale_after:
        return STALE, age
    if age > interval:
        return DELAYED, age
    return FRESH, age


def _freshness(retrieved_at: object, config: SyncConfig, now: datetime) -> tuple[str, float | None]:
    return _freshness_values(retrieved_at, config.sync_interval_seconds, config.stale_after_seconds, now)


def _coverage_valid(coverage: object, retrieved_at: object) -> bool:
    if not isinstance(coverage, dict):
        return False
    start, end, retrieved = (_parse_time(coverage.get("history_start")),
                             _parse_time(coverage.get("history_end")), _parse_time(retrieved_at))
    return start is not None and end is not None and retrieved is not None and start <= end <= retrieved


def _pointer_state(config: SyncConfig) -> tuple[str, str | None]:
    """A comparable lock-free pointer observation: (state/category, attempt)."""
    from .publish import PublishRejected, live_attempt

    try:
        return "ok", live_attempt(config)
    except PublishRejected as error:
        return error.category, None


def _failed_build_checks(category: str) -> list[HealthCheck]:
    mapping = {
        "build_not_complete": "build_completion", "unknown_attempt": "build_completion",
        "build_metadata_invalid": "build_metadata", "build_tampered": "artifact_hashes",
        "build_invalid": "locales", "missing_raw_evidence": "raw_source",
        "raw_evidence_invalid": "raw_verification", "wrong_source_run": "provenance",
        "wrong_contract": "provenance", "wrong_board": "provenance", "wrong_api_version": "provenance",
    }
    failed = mapping.get(category, "build_metadata")
    return [HealthCheck(name, "failed" if name == failed else "unknown", category if name == failed else None)
            for name in GROUPED_BUILD_CHECKS]


def _metadata_consistent(config: SyncConfig, attempt_id: str, validated: Any,
                         current: dict[str, Any] | None) -> tuple[bool, dict[str, Any] | None]:
    """CURRENT and its exact history record must agree with all live build/publication fields."""
    if current is None:
        return False, None
    publication_id = current.get("publication_id")
    candidates = [(path, record) for path, record in _history(config) if record.get("publication_id") == publication_id]
    if len(candidates) != 1:
        return False, None
    history_path, history = candidates[0]
    try:
        link = os.readlink(config.publish_dir.expanduser().resolve() / POINTER_NAME)
    except OSError:
        return False, history
    common = {
        "publication_id": publication_id, "attempt_id": attempt_id, "source_run_id": validated.source_run_id,
        "published_at": current.get("published_at"), "current_target": str(validated.site), "current_link": link,
        "build_metadata_sha256": validated.build_metadata_sha256, "contract_version": validated.contract_version,
        "board_id": validated.board_id,
    }
    current_expected = {**common, "publication_version": PUBLICATION_VERSION, "pointer": POINTER_NAME, "status": "published"}
    history_expected = {**common, "publication_version": PUBLICATION_VERSION, "status": "published", "switched": True}
    current_ok = all(current.get(key) == value for key, value in current_expected.items())
    history_ok = all(history.get(key) == value for key, value in history_expected.items())
    try:
        history_reference_ok = Path(str(current.get("history_record"))).resolve() == history_path.resolve()
    except (OSError, RuntimeError):
        history_reference_ok = False
    return current_ok and history_ok and history_reference_ok and _parse_time(current.get("published_at")) is not None, history


def _base_snapshot(generated: str, config: SyncConfig, records: list[dict[str, Any]], **values: Any) -> StatusSnapshot:
    successes = [record for record in records if record.get("status") == "success"]
    return StatusSnapshot(
        generated_at=generated, snapshot_scope="runtime", last_attempt=_safe_attempt(records[-1]) if records else None,
        last_successful_attempt=_safe_attempt(successes[-1]) if successes else None,
        consecutive_failures=_consecutive_failures(records), failure_threshold=config.max_consecutive_failures, **values,
    )


def _evaluate_observation(config: SyncConfig, now: datetime, pointer: tuple[str, str | None],
                          records: list[dict[str, Any]]) -> StatusSnapshot:
    from .publish import PublishRejected, validate_build

    generated = _iso(now)
    pointer_category, attempt_id = pointer
    freshness_empty = {"age_seconds": None, "expected_interval_seconds": config.sync_interval_seconds,
                       "stale_after_seconds": config.stale_after_seconds}
    if pointer_category != "ok" or attempt_id is None:
        category = pointer_category if pointer_category != "ok" else "no_current_publication"
        return _base_snapshot(generated, config, records, system_state=SYSTEM_FAILED,
                              freshness_state=FRESHNESS_UNKNOWN, live_usable=False, current_publication=None,
                              freshness=freshness_empty, checks=[HealthCheck("current_pointer", "failed", category)],
                              warnings=[], failure_categories=[category])
    checks = [HealthCheck("current_pointer", "passed")]
    try:
        validated = validate_build(config, attempt_id)
    except PublishRejected as error:
        return _base_snapshot(generated, config, records, system_state=SYSTEM_FAILED,
                              freshness_state=FRESHNESS_UNKNOWN, live_usable=False,
                              current_publication={"attempt_id": attempt_id}, freshness=freshness_empty,
                              checks=[*checks, *_failed_build_checks(error.category)], warnings=[],
                              failure_categories=[error.category])
    checks.extend(HealthCheck(name, "passed") for name in GROUPED_BUILD_CHECKS)

    build = _json_object(validated.site.parent / BUILD_METADATA_NAME) or {}
    raw_source = build.get("source")
    source: dict[str, Any] = raw_source if isinstance(raw_source, dict) else {}
    publish_root = config.publish_dir.expanduser().resolve()
    current_meta = _json_object(publish_root / CURRENT_METADATA_NAME)
    metadata_ok, history = _metadata_consistent(config, attempt_id, validated, current_meta)
    checks.extend([
        HealthCheck("current_metadata", "passed" if metadata_ok else "warning",
                    None if metadata_ok else "current_metadata_inconsistent"),
        HealthCheck("publication_history", "passed" if metadata_ok else "warning",
                    None if metadata_ok else "publication_history_inconsistent"),
    ])
    warnings = [] if metadata_ok else ["publication_metadata_inconsistent"]
    # Publication time/ID are metadata, never pointer facts. Do not surface them
    # unless CURRENT and its immutable history record agree completely.
    publication = history if metadata_ok and history is not None else {}
    current = {
        "attempt_id": attempt_id, "publication_id": publication.get("publication_id"),
        "published_at": publication.get("published_at"), "source_run_id": validated.source_run_id,
        "monday_retrieved_at": source.get("retrieved_at"), "coverage": source.get("coverage"),
        "contract_version": validated.contract_version, "board_id": validated.board_id,
    }
    freshness_state, age = _freshness(current["monday_retrieved_at"], config, now)
    chronology_ok = _coverage_valid(current["coverage"], current["monday_retrieved_at"])
    checks.append(HealthCheck("coverage_chronology", "passed" if chronology_ok else "failed",
                              None if chronology_ok else "coverage_chronology_invalid"))
    categories: list[str] = []
    system = SYSTEM_HEALTHY
    if freshness_state == FRESHNESS_UNKNOWN:
        categories.append("retrieval_time_invalid")
        checks.append(HealthCheck("retrieval_time", "failed", "retrieval_time_invalid"))
        system = SYSTEM_FAILED
    else:
        checks.append(HealthCheck("retrieval_time", "passed"))
    if not chronology_ok:
        categories.append("coverage_chronology_invalid")
        system = SYSTEM_FAILED
    failures = _consecutive_failures(records)
    if failures:
        warnings.append("latest_sync_attempt_failed")
        if failures >= config.max_consecutive_failures:
            categories.append("consecutive_sync_failures")
            system = SYSTEM_FAILED
        elif system == SYSTEM_HEALTHY:
            system = SYSTEM_DEGRADED
    if not metadata_ok and system == SYSTEM_HEALTHY:
        system = SYSTEM_DEGRADED
    return _base_snapshot(generated, config, records, system_state=system, freshness_state=freshness_state,
                          live_usable=True, current_publication=current,
                          freshness={**freshness_empty, "age_seconds": age}, checks=checks,
                          warnings=warnings, failure_categories=categories)


def evaluate_status(environ: Mapping[str, str] | None = None, *, config: SyncConfig | None = None,
                    clock: Callable[[], datetime] = utc_now) -> StatusSnapshot:
    """Evaluate a bounded, pointer-stable runtime view without locks, network, cache, or writes."""
    now = clock()
    try:
        cfg = config or load_sync_config(environ, now=now)
    except ConfigError:
        return StatusSnapshot(_iso(now), "runtime", SYSTEM_UNKNOWN, FRESHNESS_UNKNOWN, False, None, None, None,
                              {"age_seconds": None, "expected_interval_seconds": None, "stale_after_seconds": None},
                              checks=[HealthCheck("configuration", "failed", "configuration")],
                              failure_categories=["configuration"])
    records = _attempts(cfg)
    for _ in range(STABILITY_ATTEMPTS):
        before = _pointer_state(cfg)
        snapshot = _evaluate_observation(cfg, now, before, records)
        after = _pointer_state(cfg)
        if before == after:
            return snapshot
    successes = [record for record in records if record.get("status") == "success"]
    return StatusSnapshot(_iso(now), "runtime", SYSTEM_UNKNOWN, FRESHNESS_UNKNOWN, False, None,
                          _safe_attempt(records[-1]) if records else None,
                          _safe_attempt(successes[-1]) if successes else None,
                          {"age_seconds": None, "expected_interval_seconds": cfg.sync_interval_seconds,
                           "stale_after_seconds": cfg.stale_after_seconds}, _consecutive_failures(records),
                          cfg.max_consecutive_failures, [HealthCheck("current_pointer", "unknown", "concurrent_transition")],
                          ["concurrent_transition"], ["concurrent_transition"])


def build_time_snapshot(*, config: SyncConfig, generated_at: str, attempt_id: str, source_run_id: str,
                        retrieved_at: str, coverage: Mapping[str, Any], verified: bool,
                        started_at: str | None = None) -> StatusSnapshot:
    """Build-time form of the model from verified fields plus earlier immutable attempt records."""
    now = _parse_time(generated_at)
    freshness_state, age = _freshness(retrieved_at, config, now) if now else (FRESHNESS_UNKNOWN, None)
    chronology_ok = _coverage_valid(dict(coverage), retrieved_at)
    evidence_valid = verified and chronology_ok and freshness_state != FRESHNESS_UNKNOWN
    categories = [] if evidence_valid else ["build_time_evidence_invalid"]
    earlier_attempts = _attempts(config)
    earlier_successes = [record for record in earlier_attempts if record.get("status") == "success"]
    return StatusSnapshot(
        generated_at=generated_at, snapshot_scope="build_time",
        # A staged page is generated before its build is complete and before it
        # is published. It must never claim the live system is healthy.
        system_state=SYSTEM_UNKNOWN, freshness_state=freshness_state,
        live_usable=False,
        current_publication={"attempt_id": attempt_id, "publication_id": None, "published_at": None,
                             "source_run_id": source_run_id, "monday_retrieved_at": retrieved_at,
                             "coverage": dict(coverage), "contract_version": config.contract_version,
                             "board_id": config.board_id},
        last_attempt={"attempt_id": attempt_id, "started_at": started_at, "finished_at": None,
                      "status": "running", "error_category": None, "source_run_id": source_run_id},
        last_successful_attempt=_safe_attempt(earlier_successes[-1]) if earlier_successes else None,
        freshness={"age_seconds": age, "expected_interval_seconds": config.sync_interval_seconds,
                   "stale_after_seconds": config.stale_after_seconds},
        consecutive_failures=_consecutive_failures(earlier_attempts), failure_threshold=config.max_consecutive_failures,
        checks=[HealthCheck("raw_verification", "passed" if verified else "unknown"),
                HealthCheck("coverage_chronology", "passed" if chronology_ok else "unknown")],
        failure_categories=categories,
    )


def exit_code(snapshot: StatusSnapshot) -> int:
    if snapshot.system_state in {SYSTEM_FAILED, SYSTEM_UNKNOWN}:
        return EXIT_FAILURE
    if snapshot.system_state != SYSTEM_HEALTHY or snapshot.freshness_state != FRESH:
        return EXIT_WARNING
    return EXIT_OK


def summary(snapshot: StatusSnapshot) -> str:
    current, last = snapshot.current_publication or {}, snapshot.last_attempt or {}
    success = snapshot.last_successful_attempt or {}
    coverage = current.get("coverage") or {}
    return "\n".join([
        f"Atlas system: {snapshot.system_state.upper()} (live usable: {'yes' if snapshot.live_usable else 'no'})",
        f"Data freshness: {snapshot.freshness_state.upper()}" +
        (f" ({snapshot.freshness['age_seconds']:.0f}s old)" if snapshot.freshness.get("age_seconds") is not None else ""),
        f"Live build: {current.get('attempt_id') or 'none'}", f"Source run: {current.get('source_run_id') or 'unknown'}",
        f"Monday retrieved: {current.get('monday_retrieved_at') or 'unknown'}",
        f"Published: {current.get('published_at') or 'unknown'}",
        f"Evidence coverage: {coverage.get('history_start') or 'unknown'} to {coverage.get('history_end') or 'unknown'}",
        f"Last sync attempt: {last.get('attempt_id') or 'none'} [{last.get('status') or 'unknown'}]",
        f"Last successful sync: {success.get('attempt_id') or 'none'}",
        f"Consecutive failures: {snapshot.consecutive_failures}/{snapshot.failure_threshold or 'unknown'}",
    ])
