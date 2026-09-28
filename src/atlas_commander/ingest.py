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
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from atlas_monday_probe.client import MissingAccess, ReadOnlyMondayClient
from atlas_monday_probe.raw_store import RawRecord, write_immutable

INGEST_VERSION = "atlas-ingest-v1"
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


def ingest(client: ReadOnlyMondayClient, board_id: str, columns: list[str], since: str, until: str, raw_dir: Path) -> dict[str, Any]:
    """Run a read-only ingestion; returns the manifest (also written with extract.json to raw_dir)."""
    start, end = _parse(since), _parse(until)
    if end <= start:
        raise IngestError("until must be after since")
    run = IngestRun(_board_id(board_id), list(columns), since, until, raw_dir)
    settings = _store(run, "columns.json", client.query(
        f'query {{ boards(ids: ["{run.board_id}"]) {{ id name columns(ids: {json.dumps(run.columns)}) {{ id title type settings_str }} }} }}', {}))
    run.settings = settings["data"]["boards"][0]

    def keep_update(log: dict[str, Any]) -> None:
        if log.get("event") == "update_column_value":
            run.logs[str(log["id"])] = log

    def keep_creation(log: dict[str, Any]) -> None:
        if log.get("event") == "create_pulse":
            run.creations[str(log["id"])] = log

    for window_start, window_end in _month_windows(start, end):
        _read_window(client, run, "column_logs", window_start, window_end, run.columns, keep_update)
    for window_start, window_end in _week_windows(start, end):
        _read_window(client, run, "all_logs", window_start, window_end, None, keep_creation)
    _read_items(client, run)

    retrieved_at = _iso(datetime.now(timezone.utc))
    complete_windows = all(window.get("complete") or window.get("split") for window in run.windows)
    # An item's history is complete only when it was created on this board inside the window: its create_pulse was read.
    # Items created after `until` (before the items read) or moved in from another board have no create_pulse here.
    created_here = {_pulse_id(log) for log in run.creations.values()}
    complete_items = sorted(str(item["id"]) for item in run.items
                            if complete_windows and start <= _created_at(item) < end and str(item["id"]) in created_here)
    ingestion = {
        "ingest_version": INGEST_VERSION,
        "retrieved_at": retrieved_at,
        "activity_log_window": {"since": since, "until": until},
        "complete_history_item_ids": complete_items,
        "complete_history_basis": ("item created on this board inside the window (its create_pulse was read) and every activity-log window was "
                                   "read to its last page below the API cap; tracked-column changes and create_pulse initial values are therefore all present"),
    }
    extract = {"retrieved_at": retrieved_at, "board_id": run.board_id, "ingestion": ingestion,
               "activity": {"boards": [{"activity_logs": sorted([*run.logs.values(), *run.creations.values()], key=lambda log: (str(log["created_at"]), str(log["id"])))}]},
               "items": {"items": run.items}}
    extract_record = write_immutable(run.raw_dir, "extract.json", json.dumps(extract, sort_keys=True).encode())
    manifest = {
        "ingest_version": INGEST_VERSION,
        "source": "monday",
        "access": "read-only GraphQL queries (ReadOnlyMondayClient); no mutation was issued",
        "board_id": run.board_id,
        "board_name": run.settings.get("name"),
        "tracked_columns": run.columns,
        "window": {"since": since, "until": until},
        "retrieved_at": retrieved_at,
        "windows": run.windows,
        "counts": {"column_logs": len(run.logs), "create_pulse": len(run.creations), "items": len(run.items),
                   "items_with_complete_history": len(complete_items)},
        "raw_files": [{"name": record.name, "sha256": record.sha256, "size_bytes": record.size_bytes} for record in run.records],
        "extract": {"name": extract_record.name, "sha256": extract_record.sha256, "size_bytes": extract_record.size_bytes},
    }
    write_immutable(run.raw_dir, "manifest.json", json.dumps(manifest, indent=1, sort_keys=True).encode())
    return manifest


def main(argv: list[str] | None = None, client: ReadOnlyMondayClient | None = None) -> int:
    from atlas_commander.runtime import load_contract

    board = load_contract()["source_board"]
    default_columns = [board["status_column_id"], board["editor_column_id"], board["video_type_column_id"], board["requested_eta_column_id"],
                       board["performance_issues_column_id"], board["for_bonus_column_id"]]
    parser = argparse.ArgumentParser(prog="atlas-ingest", description="Read-only Monday ingestion into an immutable raw store outside git.")
    parser.add_argument("--board", default=board["board_id"])
    parser.add_argument("--since", required=True, help="UTC start, e.g. 2026-02-01T00:00:00Z")
    parser.add_argument("--until", default=None, help="UTC end (default: now)")
    parser.add_argument("--raw-dir", required=True, help="new directory outside any git worktree")
    parser.add_argument("--columns", nargs="+", default=default_columns)
    args = parser.parse_args(argv)
    until = args.until or _iso(datetime.now(timezone.utc))
    try:
        client = client or ReadOnlyMondayClient.from_env()
        manifest = ingest(client, args.board, args.columns, args.since, until, Path(args.raw_dir))
    except MissingAccess as error:
        print(f"MISSING_ACCESS: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"raw_dir": str(Path(args.raw_dir).expanduser()), "counts": manifest["counts"], "extract": manifest["extract"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
