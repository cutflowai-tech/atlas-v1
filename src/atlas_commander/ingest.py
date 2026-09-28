"""Read-only Monday ingestion for Atlas (REAL-002).

    MONDAY_API_TOKEN=... PYTHONPATH=src python3 -m atlas_commander.ingest \\
        --board 5091110326 --since 2026-02-01T00:00:00Z --raw-dir ~/.atlas/raw/monday/<run-id>

What it does, using only GraphQL ``query`` operations (``ReadOnlyMondayClient`` rejects any
mutation or subscription before a request leaves the process):

1. Reads the tracked columns' settings (label registries) for evidence.
2. Reads ``update_column_value`` activity logs for the tracked columns in date windows. A
   window that returns the API page cap is split in half until every window is complete.
3. Reads every activity log in the same windows and keeps ``create_pulse`` events (the item's
   initial column values).
4. Reads every item's current tracked column values (paginated ``items_page``).

Every raw response is written unchanged, once, read-only, to a raw store that must be
outside git. The command also writes:

- ``extract.json``: the pipeline input (activity logs, items, ingestion metadata);
- ``manifest.json``: the window, every raw file with its SHA-256, counts, and coverage.

An item's Requested ETA history is declared complete only when the item was created on this board
inside the window (its ``create_pulse`` was read) and every window was read to its last page. Items
moved in from another board, or created after ``until`` but before the items read, are not.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from atlas_commander.runtime import ACTIVE_CONTRACT_VERSION
from atlas_monday_probe.client import InvalidMondaySetting, MissingAccess, MondayError, ReadOnlyMondayClient, ReadOnlyViolation
from atlas_monday_probe.raw_store import RawRecord, RawStoreError, inside_git_worktree, write_immutable, write_immutable_atomic

INGEST_VERSION = "atlas-ingest-v2"
EXTRACT_NAME = "extract.json"
MANIFEST_NAME = "manifest.json"
# Present only in a run that failed. A run is complete only with a manifest whose status is "complete" and no failure record.
FAILURE_NAME = "FAILED.json"
RUN_ID_PATTERN = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{12}$")
Clock = Callable[[], datetime]
PAGE_LIMIT = 1000
# Monday returns at most this many activity logs for one filtered query; a window that reaches
# it may be truncated and is split.
WINDOW_CAP = 10_000
MIN_WINDOW = timedelta(minutes=30)
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class IngestError(RuntimeError):
    pass


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str) -> datetime:
    if not _ISO.match(value):
        raise IngestError(f"timestamps must be UTC RFC 3339 without fractions, got {value!r}")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_utc_timestamp(value: str) -> datetime:
    """Parse a UTC RFC 3339 timestamp without fractions (``2026-02-01T00:00:00Z``); raises IngestError otherwise."""
    return _parse(value)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_run_id(started_at: datetime) -> str:
    """``YYYYMMDDTHHMMSSZ-<12 hex>``: sortable by start time, and unique even for attempts started in the same second."""
    return f"{started_at.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(6)}"


def _board_id(value: str) -> str:
    if not value.isdigit():
        raise IngestError(f"board ID must be numeric, got {value!r}")
    return value


@dataclass
class IngestRun:
    board_id: str
    columns: list[str]
    since: str
    until: str
    raw_dir: Path
    records: list[RawRecord] = field(default_factory=list)
    windows: list[dict[str, Any]] = field(default_factory=list)
    logs: dict[str, dict[str, Any]] = field(default_factory=dict)
    creations: dict[str, dict[str, Any]] = field(default_factory=dict)
    items: list[dict[str, Any]] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    stage: str = "start"
    last_window: dict[str, Any] | None = None


def _store(run: IngestRun, name: str, raw: bytes) -> dict[str, Any]:
    run.records.append(write_immutable(run.raw_dir, name, raw))
    parsed: dict[str, Any] = json.loads(raw)
    return parsed


def _activity_query(board: str, since: str, until: str, page: int, columns: list[str] | None) -> str:
    column_filter = f", column_ids: {json.dumps(columns)}" if columns else ""
    return (f'query {{ boards(ids: ["{board}"]) {{ activity_logs(limit: {PAGE_LIMIT}, page: {page}, from: "{since}", to: "{until}"{column_filter}) '
            "{ id event entity user_id account_id created_at data } } }")


def _read_window(client: ReadOnlyMondayClient, run: IngestRun, kind: str, start: datetime, end: datetime,
                 columns: list[str] | None, keep: Callable[[dict[str, Any]], None]) -> None:
    """Read one window to its last page; split it when it reaches the cap."""
    since, until = _iso(start), _iso(end)
    pages: list[list[dict[str, Any]]] = []
    page = 1
    while True:
        raw = client.query(_activity_query(run.board_id, since, until, page, columns), {})
        logs = json.loads(raw)["data"]["boards"][0]["activity_logs"]
        if not logs:
            break
        run.records.append(write_immutable(run.raw_dir, f"{kind}_{since}_{until}_p{page:03d}.json".replace(":", ""), raw))
        pages.append(logs)
        page += 1
    total = sum(len(logs) for logs in pages)
    if total >= WINDOW_CAP:
        if end - start <= MIN_WINDOW:
            raise IngestError(f"{kind} window {since}..{until} still reaches the {WINDOW_CAP}-log cap")
        middle = start + (end - start) / 2
        run.windows.append({"kind": kind, "since": since, "until": until, "logs": total, "split": True})
        _read_window(client, run, kind, start, middle, columns, keep)
        _read_window(client, run, kind, middle, end, columns, keep)
        return
    run.windows.append({"kind": kind, "since": since, "until": until, "logs": total, "pages": len(pages), "complete": True})
    run.last_window = {"kind": kind, "since": since, "until": until}
    for logs in pages:
        for log in logs:
            keep(log)


def _created_at(item: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(item["created_at"]).replace("Z", "+00:00"))


def _pulse_id(log: dict[str, Any]) -> str:
    data = log.get("data")
    if isinstance(data, str):
        data = json.loads(data)
    return str((data or {}).get("pulse_id"))


def _month_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    windows = []
    cursor = start
    while cursor < end:
        month = (cursor.replace(day=1, hour=0, minute=0, second=0) + timedelta(days=32)).replace(day=1)
        windows.append((cursor, min(month, end)))
        cursor = min(month, end)
    return windows


def _week_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    windows = []
    cursor = start
    while cursor < end:
        windows.append((cursor, min(cursor + timedelta(days=7), end)))
        cursor = min(cursor + timedelta(days=7), end)
    return windows


def _read_items(client: ReadOnlyMondayClient, run: IngestRun) -> None:
    columns = json.dumps(run.columns)
    fields = f"items {{ id created_at board {{ id }} group {{ id }} column_values(ids: {columns}) {{ id type text value }} }}"
    raw = client.query(f'query {{ boards(ids: ["{run.board_id}"]) {{ items_page(limit: 500) {{ cursor {fields} }} }} }}', {})
    page = 1
    run.records.append(write_immutable(run.raw_dir, f"items_p{page:03d}.json", raw))
    body = json.loads(raw)["data"]["boards"][0]["items_page"]
    while True:
        run.items.extend(body["items"])
        cursor = body.get("cursor")
        if not cursor:
            break
        page += 1
        raw = client.query(f"query ($cursor: String!) {{ next_items_page(limit: 500, cursor: $cursor) {{ cursor {fields} }} }}", {"cursor": cursor})
        run.records.append(write_immutable(run.raw_dir, f"items_p{page:03d}.json", raw))
        body = json.loads(raw)["data"]["next_items_page"]


def _stats(client: Any) -> dict[str, Any] | None:
    stats = getattr(client, "stats", None)
    return stats.as_dict() if stats is not None and hasattr(stats, "as_dict") else None


def _stats_delta(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any] | None:
    """This run's share of a (possibly reused) client's counters, so a manifest never reports earlier requests."""
    if before is None or after is None:
        return None
    categories = {key: after["failures_by_category"].get(key, 0) - before["failures_by_category"].get(key, 0)
                  for key in after["failures_by_category"]}
    return {"requests": after["requests"] - before["requests"], "retries": after["retries"] - before["retries"],
            "succeeded": after["succeeded"] - before["succeeded"], "failed": after["failed"] - before["failed"],
            "slept_seconds": round(after["slept_seconds"] - before["slept_seconds"], 3),
            "failures_by_category": {key: n for key, n in sorted(categories.items()) if n}}


def tracked_columns(board: dict[str, Any]) -> list[str]:
    """The Monday columns every ingestion reads, from the contract's ``source_board``."""
    return [board["status_column_id"], board["editor_column_id"], board["video_type_column_id"], board["requested_eta_column_id"],
            board["performance_issues_column_id"], board["for_bonus_column_id"]]


def failure_category(error: BaseException) -> str:
    """A safe category for a failed run; never the exception text, which could echo request details.

    An error type may declare its own safe category as a ``failure_category`` class attribute (e.g. a sync time budget)."""
    declared = getattr(type(error), "failure_category", None)
    if isinstance(declared, str):
        return declared
    if isinstance(error, (MondayError, InvalidMondaySetting)):
        return error.category
    if isinstance(error, ReadOnlyViolation):
        return "read_only_violation"
    if isinstance(error, RawStoreError):
        return "raw_store"
    if isinstance(error, IngestError):
        return "ingest"
    if isinstance(error, KeyboardInterrupt):
        return "interrupted"
    if isinstance(error, (KeyError, IndexError, TypeError, ValueError)):
        return "unexpected_response"
    return "internal"


def _records(records: list[RawRecord]) -> list[dict[str, Any]]:
    return [{"name": record.name, "sha256": record.sha256, "size_bytes": record.size_bytes} for record in records]


def _prepare_run_dir(raw_dir: Path) -> Path:
    """The attempt's own directory: created here, exclusively, so no two attempts can share one."""
    path = raw_dir.expanduser().resolve()
    if inside_git_worktree(path):
        raise RawStoreError(f"raw Monday payloads must be retained outside git: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir()
    except FileExistsError:
        raise IngestError(f"run directory already exists; every ingestion attempt needs a new one: {path}") from None
    return path


def ingest(client: ReadOnlyMondayClient, board_id: str, columns: list[str], since: str, until: str, raw_dir: Path, *,
           run_id: str | None = None, clock: Clock = utc_now, started_at: datetime | None = None,
           contract_version: str = ACTIVE_CONTRACT_VERSION) -> dict[str, Any]:
    """Run one read-only ingestion attempt of ``since``..``until`` into the new directory ``raw_dir``.

    ``until`` is the attempt's fixed read boundary: every window ends at or before it, so later Monday activity
    belongs to the next run. On success, ``extract.json`` and then ``manifest.json`` (status ``complete``) are
    committed atomically, last. On any failure the captured raw responses are kept, ``FAILED.json`` records
    safe facts about where it stopped, no manifest is written, and the error is re-raised."""
    start, end = _parse(since), _parse(until)
    if end <= start:
        raise IngestError("until must be after since")
    board = _board_id(board_id)
    started = started_at or clock()
    if end > started:
        raise IngestError(f"read boundary {until} is after the attempt's start {_iso(started)}; later Monday activity belongs to a later run")
    run_id = run_id or new_run_id(started)
    if not RUN_ID_PATTERN.match(run_id):
        raise IngestError(f"run_id must look like YYYYMMDDTHHMMSSZ-<12 hex>, got {run_id!r}")
    run = IngestRun(board, list(columns), since, until, _prepare_run_dir(raw_dir))
    before = _stats(client)
    identity = {"run_id": run_id, "started_at": _iso(started)}
    monday = {"api_version": getattr(client, "api_version", None), "board_id": board}
    try:
        return _ingest(client, run, start, end, identity, monday, contract_version, before, clock)
    except BaseException as error:
        record = _record_failure(run, error, identity, monday, contract_version, _stats_delta(before, _stats(client)), clock)
        if record is not None:
            try:
                error.atlas_failure_record = record   # type: ignore[attr-defined]  # lets callers point at this attempt's FAILED.json
            except AttributeError:
                pass
        raise


def ingest_run(client: ReadOnlyMondayClient, board_id: str, columns: list[str], history_start: str, raw_root: Path, *,
               clock: Clock = utc_now, contract_version: str = ACTIVE_CONTRACT_VERSION,
               run_id_factory: Callable[[datetime], str] = new_run_id) -> dict[str, Any]:
    """Full-history ingestion from ``history_start`` up to a boundary captured once, now, into ``raw_root/<run_id>``."""
    started = clock()
    boundary = _iso(started)   # the one read boundary for every window of this attempt (whole seconds, never after the start)
    run_id = run_id_factory(started)
    return ingest(client, board_id, columns, history_start, boundary, Path(raw_root) / run_id, run_id=run_id, clock=clock,
                  started_at=started, contract_version=contract_version)


def _ingest(client: ReadOnlyMondayClient, run: IngestRun, start: datetime, end: datetime, identity: dict[str, str], monday: dict[str, Any],
            contract_version: str, before: dict[str, Any] | None, clock: Clock) -> dict[str, Any]:
    since, until = run.since, run.until
    run.stage = "columns"
    settings = _store(run, "columns.json", client.query(
        f'query {{ boards(ids: ["{run.board_id}"]) {{ id name columns(ids: {json.dumps(run.columns)}) {{ id title type settings_str }} }} }}', {}))
    run.settings = settings["data"]["boards"][0]

    def keep_update(log: dict[str, Any]) -> None:
        if log.get("event") == "update_column_value":
            run.logs[str(log["id"])] = log

    def keep_creation(log: dict[str, Any]) -> None:
        if log.get("event") == "create_pulse":
            run.creations[str(log["id"])] = log

    run.stage = "column_logs"
    for window_start, window_end in _month_windows(start, end):
        _read_window(client, run, "column_logs", window_start, window_end, run.columns, keep_update)
    run.stage = "all_logs"
    for window_start, window_end in _week_windows(start, end):
        _read_window(client, run, "all_logs", window_start, window_end, None, keep_creation)
    run.stage = "items"
    _read_items(client, run)

    run.stage = "extract"
    retrieved_at = _iso(clock())
    complete_windows = all(window.get("complete") or window.get("split") for window in run.windows)
    # An item's history is complete only when it was created on this board inside the window: its create_pulse was read.
    # Items created after `until` (before the items read) or moved in from another board have no create_pulse here.
    created_here = {_pulse_id(log) for log in run.creations.values()}
    complete_items = sorted(str(item["id"]) for item in run.items
                            if complete_windows and start <= _created_at(item) < end and str(item["id"]) in created_here)
    ingestion = {
        "ingest_version": INGEST_VERSION,
        "run_id": identity["run_id"],
        "retrieved_at": retrieved_at,
        "activity_log_window": {"since": since, "until": until},
        "complete_history_item_ids": complete_items,
        "complete_history_basis": ("item created on this board inside the window (its create_pulse was read) and every activity-log window was "
                                   "read to its last page below the API cap; tracked-column changes and create_pulse initial values are therefore all present"),
    }
    extract = {"retrieved_at": retrieved_at, "board_id": run.board_id, "ingestion": ingestion,
               "activity": {"boards": [{"activity_logs": sorted([*run.logs.values(), *run.creations.values()], key=lambda log: (str(log["created_at"]), str(log["id"])))}]},
               "items": {"items": run.items}}
    extract_record = write_immutable_atomic(run.raw_dir, EXTRACT_NAME, json.dumps(extract, sort_keys=True).encode())

    run.stage = "manifest"
    client_stats = _stats_delta(before, _stats(client))
    manifest = {
        "ingest_version": INGEST_VERSION,
        "status": "complete",
        "source": "monday",
        "access": "read-only GraphQL queries (ReadOnlyMondayClient); no mutation was issued",
        "run": {**identity, "finished_at": _iso(clock())},
        "coverage": {"history_start": since, "history_end": until},
        "monday": monday,
        "contract_version": contract_version,
        "client": {**client_stats, "final_failure_category": None} if client_stats is not None else None,
        "board_id": run.board_id,
        "board_name": run.settings.get("name"),
        "tracked_columns": run.columns,
        "window": {"since": since, "until": until},
        "retrieved_at": retrieved_at,
        "windows": run.windows,
        "counts": {"column_logs": len(run.logs), "create_pulse": len(run.creations), "items": len(run.items),
                   "items_with_complete_history": len(complete_items)},
        "raw_files": _records(run.records),
        "extract": {"name": extract_record.name, "sha256": extract_record.sha256, "size_bytes": extract_record.size_bytes},
    }
    # The manifest is the commit point: it is written last, and only when everything before it succeeded.
    write_immutable_atomic(run.raw_dir, MANIFEST_NAME, json.dumps(manifest, indent=1, sort_keys=True).encode())
    return manifest


def _record_failure(run: IngestRun, error: BaseException, identity: dict[str, str], monday: dict[str, Any], contract_version: str,
                    client_stats: dict[str, Any] | None, clock: Clock) -> Path | None:
    """Write FAILED.json with safe operational facts only: categories, stage, counters and file hashes, never exception text."""
    category = failure_category(error)
    record = {
        "ingest_version": INGEST_VERSION,
        "status": "failed",
        "run": {**identity, "failed_at": _iso(clock())},
        "coverage": {"history_start": run.since, "history_end": run.until},
        "monday": monday,
        "contract_version": contract_version,
        "failure": {"category": category, "error_type": type(error).__name__, "stage": run.stage, "last_completed_window": run.last_window,
                    "windows_completed": sum(1 for window in run.windows if window.get("complete")),
                    "extract_written": (run.raw_dir / EXTRACT_NAME).exists()},
        "client": ({**client_stats, "final_failure_category": category if isinstance(error, MondayError) else None}
                   if client_stats is not None else None),
        "raw_files": _records(run.records),
        "note": "Incomplete attempt kept for diagnosis only. It has no manifest and must never be used as build input.",
    }
    try:
        return write_immutable_atomic(run.raw_dir, FAILURE_NAME, json.dumps(record, indent=1, sort_keys=True).encode()).path
    except Exception:  # noqa: BLE001 - never mask the original failure; the missing manifest still marks the run incomplete
        return None


def main(argv: list[str] | None = None, client: ReadOnlyMondayClient | None = None) -> int:
    from atlas_commander.runtime import load_contract

    board = load_contract()["source_board"]
    default_columns = tracked_columns(board)
    parser = argparse.ArgumentParser(prog="atlas-ingest", description="Read-only Monday ingestion into an immutable raw store outside git.")
    parser.add_argument("--board", default=board["board_id"])
    parser.add_argument("--since", required=True, help="UTC start, e.g. 2026-02-01T00:00:00Z")
    parser.add_argument("--until", default=None, help="UTC read boundary with --raw-dir (default: the attempt's start time)")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--raw-dir", help="new run directory outside any git worktree")
    target.add_argument("--raw-root", help="raw evidence root; the attempt is written to <raw-root>/<run_id>")
    parser.add_argument("--columns", nargs="+", default=default_columns)
    args = parser.parse_args(argv)
    if args.raw_root and args.until:
        parser.error("--until applies only to --raw-dir; with --raw-root the boundary is the attempt's start time")
    run_dir: Path | None = None
    try:
        client = client or ReadOnlyMondayClient.from_env()
        if args.raw_root:
            manifest = ingest_run(client, args.board, args.columns, args.since, Path(args.raw_root))
        else:
            started = utc_now()
            run_dir = Path(args.raw_dir)
            manifest = ingest(client, args.board, args.columns, args.since, args.until or _iso(started), run_dir, started_at=started)
        run_dir = Path(args.raw_root) / manifest["run"]["run_id"] if args.raw_root else run_dir
    except (MondayError, InvalidMondaySetting, IngestError, RawStoreError) as error:
        failed = getattr(error, "atlas_failure_record", None)
        if failed:
            print(f"INGESTION_FAILED: run marked failed, partial evidence kept: {failed}", file=sys.stderr)
        if isinstance(error, MissingAccess):
            print(f"MISSING_ACCESS: {error}", file=sys.stderr)
            return 2
        if isinstance(error, InvalidMondaySetting):
            print(f"INVALID_CONFIGURATION: {error}", file=sys.stderr)
            return 2
        if isinstance(error, MondayError):
            print(f"MONDAY_API_ERROR [{error.category}]: {error}", file=sys.stderr)
            return 3
        print(f"INGESTION_ERROR [{failure_category(error)}]: {error}", file=sys.stderr)
        return 3
    print(json.dumps({"raw_dir": str(Path(run_dir or "").expanduser()), "run_id": manifest["run"]["run_id"], "counts": manifest["counts"],
                      "client": manifest["client"], "extract": manifest["extract"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
