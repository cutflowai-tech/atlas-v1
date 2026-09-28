"""Offline verification of a read-only ingestion run (no Monday access needed).

    PYTHONPATH=src python3 -m atlas_commander.ingest_verify <raw_dir>

Checks the run directory written by ``atlas_commander.ingest`` and prints a JSON report:

- every raw file and ``extract.json`` exists and matches its SHA-256 in ``manifest.json``;
- every read window finished below the API cap (a capped window must have been split);
- the finished windows of each kind tile the declared coverage window exactly (no gap, no overlap);
- the extract has no duplicate activity-log IDs and its counts match the manifest;
- every activity log in the extract lies inside the coverage window;
- every item has a current-value snapshot, and ``create_pulse`` coverage of items created
  inside the window is reported (never assumed);
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

from atlas_commander.ingest import WINDOW_CAP
from atlas_monday_probe.raw_store import sha256_file


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


def verify(raw_dir: Path) -> dict[str, Any]:
    manifest = json.loads((raw_dir / "manifest.json").read_text())
    failures: list[str] = []

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

    extract = json.loads((raw_dir / "extract.json").read_text())
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

    return {
        "raw_dir": str(raw_dir),
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
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python3 -m atlas_commander.ingest_verify <raw_dir>", file=sys.stderr)
        return 2
    report = verify(Path(args[0]).expanduser())
    print(json.dumps(report, indent=1))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
