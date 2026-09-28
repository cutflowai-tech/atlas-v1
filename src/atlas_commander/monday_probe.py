"""Read-only Monday activity-log probe (DATA-001).

Fetches raw activity logs for one board/item scope, retains the payload immutably
outside git, and derives a redacted manifest plus a schema drift report. Nothing
here mutates Monday, and no identity, status or quality mapping is guessed:
unmapped labels and actors are reported, never inferred.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_commander.contracts import ROOT, schema_errors

API_URL = "https://api.monday.com/v2"
API_VERSION = "2025-04"
TOKEN_ENV = "MONDAY_API_TOKEN"
PROBE_VERSION = "monday-probe-v1"
STATUS_SCHEMA = "normalized-status-event.schema.json"
CONTRACT_STATUSES = frozenset({"Backlog", "In Progress", "Ready For Approval", "Revision", "Approved", "Delivered"})
EXPECTED_LOG_KEYS = frozenset({"id", "event", "data", "entity", "user_id", "account_id", "created_at"})
EXPECTED_STATUS_DATA_KEYS = frozenset({"board_id", "pulse_id", "column_id", "column_type", "value", "previous_value"})
REDACTED_DATA_KEYS = frozenset({"pulse_name", "column_title", "group_name", "user_name", "email", "text", "textual_value"})

Transport = Callable[[str, dict[str, Any], str], dict[str, Any]]

ACTIVITY_QUERY = """query ($board: [ID!], $limit: Int!, $page: Int!, $from: ISO8601DateTime, $to: ISO8601DateTime, $items: [ID!], $columns: [String]) {
  boards(ids: $board) {
    id
    activity_logs(limit: $limit, page: $page, from: $from, to: $to, item_ids: $items, column_ids: $columns) {
      id event data entity user_id account_id created_at
    }
  }
}"""

COLUMNS_QUERY = """query ($board: [ID!]) {
  boards(ids: $board) { id columns { id type title settings_str } }
}"""


class ReadOnlyViolation(RuntimeError):
    pass


class MissingAccess(RuntimeError):
    pass


def assert_read_only(query: str) -> None:
    stripped = query.lstrip()
    if re.search(r"\bmutation\b", query, re.IGNORECASE) or re.search(r"\bsubscription\b", query, re.IGNORECASE):
        raise ReadOnlyViolation("Monday probe only issues GraphQL queries")
    if not stripped.startswith(("query", "{")):
        raise ReadOnlyViolation("Monday probe only issues GraphQL queries")


def _http_transport(query: str, variables: dict[str, Any], token: str) -> dict[str, Any]:
    body = json.dumps({"query": query, "variables": variables}).encode()
    request = urllib.request.Request(
        API_URL, data=body, method="POST",
        headers={"Authorization": token, "Content-Type": "application/json", "API-Version": API_VERSION},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


class MondayReadOnlyClient:
    def __init__(self, token: str | None = None, transport: Transport | None = None) -> None:
        self._token = token if token is not None else os.environ.get(TOKEN_ENV, "")
        if not self._token:
            raise MissingAccess(f"{TOKEN_ENV} is not set; a Monday API token with boards:read scope is required")
        self._transport = transport or _http_transport

    def query(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        assert_read_only(query)
        response = self._transport(query, variables, self._token)
        if response.get("errors"):
            messages = [str(error.get("message", error)) for error in response["errors"]]
            raise MissingAccess("Monday API error: " + "; ".join(messages))
        return response["data"]

    def columns(self, board_id: str) -> list[dict[str, Any]]:
        boards = self.query(COLUMNS_QUERY, {"board": [board_id]})["boards"]
        return boards[0]["columns"] if boards else []

    def activity_logs(self, board_id: str, item_ids: list[str], column_ids: list[str], date_from: str | None, date_to: str | None,
                      limit: int = 500, max_pages: int = 50) -> list[dict[str, Any]]:
        logs: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            variables = {"board": [board_id], "limit": limit, "page": page, "from": date_from, "to": date_to,
                         "items": item_ids or None, "columns": column_ids or None}
            boards = self.query(ACTIVITY_QUERY, variables)["boards"]
            batch = boards[0]["activity_logs"] if boards else []
            logs.extend(batch)
            if len(batch) < limit:
                return logs
        raise RuntimeError(f"activity_logs exceeded {max_pages} pages; narrow the date range")


def monday_timestamp(raw: str) -> str:
    """Convert Monday's 17-digit activity-log timestamp (100ns ticks since epoch) to RFC 3339 UTC."""
    ticks = int(raw)
    moment = datetime.fromtimestamp(ticks // 10_000_000, tz=timezone.utc).replace(microsecond=(ticks % 10_000_000) // 10)
    return moment.isoformat().replace("+00:00", "Z")


def _label_text(value: Any) -> str | None:
    if isinstance(value, dict) and isinstance(value.get("label"), dict):
        text = value["label"].get("text")
        return text if isinstance(text, str) else None
    return None


def _parse_data(log: dict[str, Any]) -> dict[str, Any] | None:
    data = log.get("data")
    if isinstance(data, dict):
        return data
    try:
        parsed = json.loads(data) if isinstance(data, str) else None
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def normalize(log: dict[str, Any], status_column_id: str, actor_mapping: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, list[str]]:
    """Return (candidate NormalizedStatusEvent, issue codes). Candidate is None when it cannot be built without guessing."""
    data = _parse_data(log)
    if data is None:
        return None, ["UNPARSEABLE_DATA"]
    if log.get("event") != "update_column_value" or str(data.get("column_id")) != status_column_id:
        return None, ["NOT_STATUS_CHANGE"]
    to_status, from_status = _label_text(data.get("value")), _label_text(data.get("previous_value"))
    issues = []
    if to_status not in CONTRACT_STATUSES:
        issues.append("UNMAPPED_TO_STATUS")
    if from_status is not None and from_status not in CONTRACT_STATUSES:
        issues.append("UNMAPPED_FROM_STATUS")
    if issues:
        return None, issues
    actor_monday_id = str(log["user_id"]) if log.get("user_id") not in (None, "") else None
    mapped = (actor_mapping or {}).get("actors", {}).get(actor_monday_id) if actor_monday_id else None
    event: dict[str, Any] = {
        "contract_version": "1.0.0",
        "event_id": str(log["id"]),
        "monday_board_id": str(data["board_id"]),
        "monday_item_id": str(data["pulse_id"]),
        "status_column_id": status_column_id,
        "occurred_at": monday_timestamp(str(log["created_at"])),
        "from_status": from_status,
        "to_status": to_status,
    }
    if mapped and actor_mapping and actor_mapping.get("mapping_version"):
        event.update(actor_resolution="canonical_monday_id", actor_monday_id=actor_monday_id, actor_id=mapped,
                     mapping_version=actor_mapping["mapping_version"])
    else:
        event.update(actor_resolution="unresolved_waset_co", actor_monday_id=actor_monday_id, actor_id=None, mapping_version=None)
        issues.append("UNRESOLVED_ACTOR")
    if schema_errors(event, STATUS_SCHEMA):
        return None, issues + ["SCHEMA_INVALID"]
    return event, issues


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()[:16]


def redact(log: dict[str, Any]) -> dict[str, Any]:
    """Keep identifiers, event types and raw timestamps; hash people; drop free text."""
    data = _parse_data(log) or {}
    kept = {key: value for key, value in data.items() if key not in REDACTED_DATA_KEYS}
    for side in ("value", "previous_value"):
        label = _label_text(data.get(side))
        kept[side] = {"label_text": label} if label is not None else ("<redacted>" if data.get(side) is not None else None)
    return {
        "id": log.get("id"), "event": log.get("event"), "entity": log.get("entity"), "created_at": log.get("created_at"),
        "user_id": _digest(str(log["user_id"])) if log.get("user_id") not in (None, "") else None,
        "data": kept,
    }


def store_raw(envelope: dict[str, Any], raw_dir: Path) -> Path:
    """Write the raw envelope once, content-addressed and read-only, outside the git checkout."""
    raw_dir = raw_dir.resolve()
    if raw_dir == ROOT or ROOT in raw_dir.parents:
        raise ValueError("raw Monday payloads must be stored outside the git checkout")
    raw_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps(envelope, sort_keys=True, indent=2).encode()
    target = raw_dir / f"monday-activity-{envelope['board_id']}-{hashlib.sha256(body).hexdigest()}.json"
    if target.exists():
        if target.read_bytes() != body:
            raise FileExistsError(f"{target} exists with different content")
        return target
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(fd, "wb") as handle:
        handle.write(body)
    return target


def drift_report(logs: list[dict[str, Any]], columns: list[dict[str, Any]] | None, status_column_id: str,
                 results: list[tuple[dict[str, Any] | None, list[str]]]) -> dict[str, Any]:
    observed_log_keys = sorted({key for log in logs for key in log})
    status_data_keys: set[str] = set()
    observed_labels: set[str] = set()
    for log in logs:
        data = _parse_data(log)
        if data and log.get("event") == "update_column_value" and str(data.get("column_id")) == status_column_id:
            status_data_keys.update(data)
            observed_labels.update(label for label in (_label_text(data.get("value")), _label_text(data.get("previous_value"))) if label)
    configured_labels: list[str] | None = None
    status_column_present: bool | None = None
    if columns is not None:
        column = next((c for c in columns if c.get("id") == status_column_id), None)
        status_column_present = column is not None
        if column and column.get("settings_str"):
            labels = json.loads(column["settings_str"]).get("labels", {})
            configured_labels = sorted(str(text) for text in labels.values())
    codes: dict[str, int] = {}
    for _, issues in results:
        for code in issues:
            codes[code] = codes.get(code, 0) + 1
    return {
        "probe_version": PROBE_VERSION,
        "contract": STATUS_SCHEMA,
        "log_keys": {"missing": sorted(EXPECTED_LOG_KEYS - set(observed_log_keys)) if logs else [],
                     "unexpected": sorted(set(observed_log_keys) - EXPECTED_LOG_KEYS)},
        "status_data_keys": {"missing": sorted(EXPECTED_STATUS_DATA_KEYS - status_data_keys) if status_data_keys else [],
                             "unexpected": sorted(status_data_keys - EXPECTED_STATUS_DATA_KEYS - REDACTED_DATA_KEYS)},
        "status_column_present": status_column_present,
        "observed_status_labels_not_in_contract": sorted(observed_labels - CONTRACT_STATUSES),
        "configured_status_labels_not_in_contract": sorted(set(configured_labels) - CONTRACT_STATUSES) if configured_labels is not None else None,
        "contract_statuses_not_configured": sorted(CONTRACT_STATUSES - set(configured_labels)) if configured_labels is not None else None,
        "issue_counts": dict(sorted(codes.items())),
    }


def build_outputs(envelope: dict[str, Any], raw_path: Path | None, actor_mapping: dict[str, Any] | None = None) -> dict[str, Any]:
    logs, status_column_id = envelope["activity_logs"], envelope["status_column_id"]
    results = [normalize(log, status_column_id, actor_mapping) for log in logs]
    events = [event for event, _ in results if event]
    manifest = {
        "probe_version": PROBE_VERSION,
        "mode": envelope.get("mode", "real"),
        "board_id": envelope["board_id"],
        "item_ids": envelope["item_ids"],
        "status_column_id": status_column_id,
        "window": {"from": envelope.get("from"), "to": envelope.get("to")},
        "retrieved_at": envelope["retrieved_at"],
        "raw_payload": {"file": raw_path.name if raw_path else None,
                        "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest() if raw_path else None},
        "actor_mapping_version": (actor_mapping or {}).get("mapping_version"),
        "counts": {"activity_logs": len(logs), "normalized_status_events": len(events)},
        "sample": [redact(log) for log in logs[:20]],
        "normalized_events": [{**event, "actor_monday_id": _digest(event["actor_monday_id"]) if event.get("actor_monday_id") else None}
                              for event in events],
    }
    return {"manifest": manifest, "drift": drift_report(logs, envelope.get("columns"), status_column_id, results), "events": events}


def probe(client: MondayReadOnlyClient, board_id: str, item_ids: list[str], status_column_id: str,
          date_from: str | None, date_to: str | None) -> dict[str, Any]:
    columns = client.columns(board_id)
    logs = client.activity_logs(board_id, item_ids, [status_column_id], date_from, date_to)
    return {"mode": "real", "board_id": board_id, "item_ids": item_ids, "status_column_id": status_column_id,
            "from": date_from, "to": date_to, "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "columns": columns, "activity_logs": logs}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="monday-probe", description="Read-only Monday activity-log probe")
    parser.add_argument("--board-id", required=True)
    parser.add_argument("--item-id", action="append", default=[], required=True)
    parser.add_argument("--status-column-id", required=True, help="Monday column id; never guessed")
    parser.add_argument("--from", dest="date_from")
    parser.add_argument("--to", dest="date_to")
    parser.add_argument("--raw-dir", type=Path, required=True, help="immutable raw store outside git")
    parser.add_argument("--out-dir", type=Path, required=True, help="where manifest.json and drift.json are written")
    parser.add_argument("--actor-mapping", type=Path, help="versioned {mapping_version, actors:{monday_id: actor_id}}")
    parser.add_argument("--from-raw", type=Path, help="rebuild outputs from a stored raw envelope instead of calling Monday")
    args = parser.parse_args(argv)
    mapping = json.loads(args.actor_mapping.read_text()) if args.actor_mapping else None
    if args.from_raw:
        envelope, raw_path = json.loads(args.from_raw.read_text()), args.from_raw
    else:
        try:
            client = MondayReadOnlyClient()
            envelope = probe(client, args.board_id, args.item_id, args.status_column_id, args.date_from, args.date_to)
        except MissingAccess as error:
            print(json.dumps({"status": "missing_access", "detail": str(error)}), file=sys.stderr)
            return 2
        raw_path = store_raw(envelope, args.raw_dir)
    outputs = build_outputs(envelope, raw_path, mapping)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "manifest.json").write_text(json.dumps(outputs["manifest"], indent=2, sort_keys=True) + "\n")
    (args.out_dir / "drift.json").write_text(json.dumps(outputs["drift"], indent=2, sort_keys=True) + "\n")
    print(json.dumps({"raw": str(raw_path), "counts": outputs["manifest"]["counts"], "issues": outputs["drift"]["issue_counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
