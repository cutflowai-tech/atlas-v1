"""Offline verification of a read-only ingestion run (no Monday access needed).

    PYTHONPATH=src python3 -m atlas_commander.ingest_verify [--production] <raw_dir>

Checks the run directory written by ``atlas_commander.ingest`` and prints a JSON report:

- every raw file and ``extract.json`` exists and matches its SHA-256 in ``manifest.json``;
- every read window finished below the API cap (a capped window must have been split);
- the finished windows of each kind tile the declared coverage window exactly (no gap, no overlap);
- the extract has no duplicate activity-log IDs and its counts match the manifest;
- every activity log in the extract lies inside the coverage window;
- every item has a current-value snapshot, and ``create_pulse`` coverage of items created
  inside the window is reported (never assumed);
- the run is not marked failed (no ``FAILED.json``), has a manifest, and has no leftover staging files;
- production metadata (``atlas-ingest-v2``), when present, is consistent: status ``complete``, a well-formed run
  ID matching the extract (and the directory name, for runs under a raw root), start before finish, a read
  boundary equal to the coverage window and not after the start, a valid API version, an approved contract whose
  board is the manifest's and the extract's board, and per-run client counters that add up. ``--production``
  (``require_production=True``) also fails a run without that metadata;
- the complete-history item list is exactly the items created on this board inside the window
  (``since`` <= created < ``until``, with a ``create_pulse``), and only when every window was complete.
  Items moved in from another board or created after ``until`` are reported, never declared complete.

Exit status is 0 when every check passes and 1 otherwise. Nothing is modified.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from atlas_commander.ingest import EXTRACT_NAME, FAILURE_NAME, MANIFEST_NAME, RUN_ID_PATTERN, WINDOW_CAP
from atlas_commander.runtime import CONTRACT_PATHS, load_contract_version
from atlas_monday_probe.client import InvalidMondaySetting, validate_api_version
from atlas_monday_probe.raw_store import STAGING_SUFFIX, sha256_file


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _tiles(windows: list[dict[str, Any]], since: str, until: str) -> list[str]:
    problems = []
    cursor = _time(since)
    for window in sorted(windows, key=lambda w: _time(w["since"])):
        start, end = _time(window["since"]), _time(window["until"])
        if start > cursor:
            problems.append(f"gap {cursor.isoformat()}..{start.isoformat()}")
        if start < cursor:
            problems.append(f"overlap at {start.isoformat()}")
        cursor = max(cursor, end)
    if cursor != _time(until):
        problems.append(f"coverage ends at {cursor.isoformat()}, expected {until}")
    return problems


def _creation_item(log: dict[str, Any]) -> str | None:
    data = log.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    value = data.get("pulse_id") or data.get("item_id")
    return str(value) if value is not None else None


def _production_failures(raw_dir: Path, manifest: dict[str, Any], extract: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    run, coverage, monday, client = manifest.get("run") or {}, manifest.get("coverage") or {}, manifest.get("monday") or {}, manifest.get("client")
    if manifest.get("status") != "complete":
        failures.append(f"manifest status is {manifest.get('status')!r}, not 'complete'")
    run_id = str(run.get("run_id") or "")
    if not RUN_ID_PATTERN.match(run_id):
        failures.append(f"run_id {run_id!r} is not a well-formed run ID")
    elif RUN_ID_PATTERN.match(raw_dir.name) and raw_dir.name != run_id:
        failures.append(f"run_id {run_id} does not match its directory {raw_dir.name}")
    if (extract.get("ingestion") or {}).get("run_id") != run_id:
        failures.append("extract run_id differs from the manifest run_id")
    try:
        started, finished = _time(run["started_at"]), _time(run["finished_at"])
        if finished < started:
            failures.append("run finished before it started")
        if coverage.get("history_start") != manifest["window"]["since"] or coverage.get("history_end") != manifest["window"]["until"]:
            failures.append("coverage does not equal the activity-log window")
        elif _time(coverage["history_end"]) > started:
            failures.append("read boundary is after the run start")
    except (KeyError, TypeError, ValueError):
        failures.append("run start/finish or coverage timestamps are missing or malformed")
    try:
        validate_api_version(str(monday.get("api_version")))
    except InvalidMondaySetting:
        failures.append(f"Monday API version {monday.get('api_version')!r} is missing or malformed")
    board = str(monday.get("board_id"))
    if board != str(manifest.get("board_id")) or board != str(extract.get("board_id")):
        failures.append("board ID differs between manifest, Monday metadata and extract")
    version = manifest.get("contract_version")
    if version not in CONTRACT_PATHS:
        failures.append(f"contract version {version!r} is not an approved contract")
    elif str(load_contract_version(version)["source_board"]["board_id"]) != board:
        failures.append(f"board {board} is not the board of contract {version}")
    if not isinstance(client, dict):
        failures.append("client request counters are missing")
    else:
        numbers = [client.get(key) for key in ("requests", "retries", "succeeded", "failed")]
        if not all(isinstance(n, int) and n >= 0 for n in numbers):
            failures.append("client request counters are missing or negative")
        elif client["failed"] or client.get("final_failure_category") is not None:
            failures.append("a completed run reports a failed Monday request")
        elif client["requests"] != client["succeeded"] + client["retries"]:
            failures.append("client counters do not add up (requests != succeeded + retries)")
        elif client["succeeded"] < len(manifest.get("raw_files") or []):
            failures.append("fewer successful Monday requests than stored raw responses")
    return failures


def verify(raw_dir: Path, *, require_production: bool = False) -> dict[str, Any]:
    failures: list[str] = []
    if (raw_dir / FAILURE_NAME).exists():
        failures.append(f"run is marked failed ({FAILURE_NAME} present); it must never be used as build input")
    staging = sorted(path.name for path in raw_dir.glob(f".*{STAGING_SUFFIX}")) if raw_dir.is_dir() else []
    if staging:
        failures.append(f"unfinished staging files present: {staging}")
    if not (raw_dir / MANIFEST_NAME).is_file():
        return {"raw_dir": str(raw_dir), "passed": False, "status": "failed" if (raw_dir / FAILURE_NAME).exists() else "incomplete",
                "failures": [*failures, f"no {MANIFEST_NAME}: the run did not complete"]}
    manifest = json.loads((raw_dir / MANIFEST_NAME).read_text())

    for record in [*manifest["raw_files"], manifest["extract"]]:
        path = raw_dir / record["name"]
        if not path.exists():
            failures.append(f"missing raw file {record['name']}")
        elif sha256_file(path) != record["sha256"]:
            failures.append(f"SHA-256 mismatch for {record['name']}")

    since, until = manifest["window"]["since"], manifest["window"]["until"]
    leaves = [w for w in manifest["windows"] if not w.get("split")]
    for window in leaves:
        if not window.get("complete") or window.get("logs", 0) >= WINDOW_CAP:
            failures.append(f"window {window['kind']} {window['since']}..{window['until']} is not complete below the cap")
    for kind in sorted({w["kind"] for w in manifest["windows"]}):
        failures += [f"{kind}: {problem}" for problem in _tiles([w for w in leaves if w["kind"] == kind], since, until)]

    if not (raw_dir / EXTRACT_NAME).is_file():
        return {"raw_dir": str(raw_dir), "passed": False, "status": "incomplete", "failures": [*failures, f"no {EXTRACT_NAME}"]}
    extract = json.loads((raw_dir / EXTRACT_NAME).read_text())
    logs = extract["activity"]["boards"][0]["activity_logs"]
    ids = Counter(str(log["id"]) for log in logs)
    duplicates = sorted(log_id for log_id, n in ids.items() if n > 1)
    if duplicates:
        failures.append(f"{len(duplicates)} duplicate activity-log IDs in extract")
    events = Counter(log["event"] for log in logs)
    counts = manifest["counts"]
    if events["update_column_value"] != counts["column_logs"] or events["create_pulse"] != counts["create_pulse"]:
        failures.append(f"extract event counts {dict(events)} differ from manifest counts {counts}")
    lo, hi = _time(since).timestamp() * 10**7, _time(until).timestamp() * 10**7
    outside = [log["id"] for log in logs if not lo <= int(log["created_at"]) < hi]
    if outside:
        failures.append(f"{len(outside)} activity logs outside the coverage window")

    items = extract["items"]["items"]
    if len(items) != counts["items"]:
        failures.append(f"extract has {len(items)} items, manifest says {counts['items']}")
    without_snapshot = sorted(str(item["id"]) for item in items if not item.get("column_values"))
    created_inside = sorted(str(item["id"]) for item in items if _time(since) <= _time(str(item["created_at"])) < _time(until))
    created_after = sorted(str(item["id"]) for item in items if _time(str(item["created_at"])) >= _time(until))
    with_creation = {_creation_item(log) for log in logs if log["event"] == "create_pulse"}
    created_without_create_pulse = sorted(set(created_inside) - with_creation)
    all_complete = all(w.get("complete") for w in leaves)
    expected_complete = sorted(set(created_inside) & with_creation) if all_complete else []
    if sorted(extract["ingestion"]["complete_history_item_ids"]) != expected_complete:
        failures.append("complete_history_item_ids does not equal the items created on this board inside a fully read window")

    production = "run" in manifest
    if production:
        failures += _production_failures(raw_dir, manifest, extract)
    elif require_production:
        failures.append("manifest has no production metadata (run, coverage, monday, contract_version, client)")

    return {
        "raw_dir": str(raw_dir),
        "status": manifest.get("status", "complete (legacy manifest)"),
        "run_id": (manifest.get("run") or {}).get("run_id"),
        "production_metadata": production,
        "window": manifest["window"],
        "retrieved_at": manifest["retrieved_at"],
        "passed": not failures,
        "failures": failures,
        "raw_files_checked": len(manifest["raw_files"]) + 1,
        "windows": {"read": len(manifest["windows"]), "split": sum(1 for w in manifest["windows"] if w.get("split")), "max_logs_in_a_window": max((w.get("logs", 0) for w in leaves), default=0), "cap": WINDOW_CAP},
        "activity_logs": dict(events),
        "items": len(items),
        "items_without_snapshot": without_snapshot,
        "items_created_inside_window": len(created_inside),
        "items_created_inside_window_without_create_pulse": created_without_create_pulse,
        "items_created_after_window": created_after,
        "complete_history_items": len(extract["ingestion"]["complete_history_item_ids"]),
    }


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    production = "--production" in args
    args = [arg for arg in args if arg != "--production"]
    if len(args) != 1:
        print("usage: python3 -m atlas_commander.ingest_verify [--production] <raw_dir>", file=sys.stderr)
        return 2
    report = verify(Path(args[0]).expanduser(), require_production=production)
    print(json.dumps(report, indent=1))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
