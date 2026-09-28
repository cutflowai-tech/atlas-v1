from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .adapter import parse_status_changes
from .client import MissingAccess, ReadOnlyMondayClient
from .raw_store import RawRecord, seal_existing, write_immutable
from .report import build_drift_report, build_manifest, load_json

COLUMNS = {"status": "project_status", "editor": "dropdown_mm1emgt8", "video_type": "dropdown_mm062ga0", "eta": "date"}
RAW_FILES = ("activity_logs.json", "items.json", "users_columns.json")


def capture(args: argparse.Namespace) -> list[RawRecord]:
    client = ReadOnlyMondayClient.from_env()
    raw_dir = Path(args.raw_dir)
    activity = client.status_activity(args.board, args.items, COLUMNS["status"], args.since, args.until)
    items = client.items(args.items, list(COLUMNS.values()))
    user_ids = sorted({change.user_id for change in parse_status_changes(json.loads(activity), COLUMNS["status"])})
    users_columns = client.users_and_columns(args.board, user_ids, list(COLUMNS.values()))
    return [write_immutable(raw_dir, name, data) for name, data in zip(RAW_FILES, (activity, items, users_columns))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas_monday_probe", description="Read-only Monday probe (DATA-001).")
    sub = parser.add_subparsers(dest="command", required=True)
    live = sub.add_parser("capture", help="fetch raw payloads with MONDAY_API_TOKEN into an immutable raw dir outside git")
    live.add_argument("--board", required=True)
    live.add_argument("--items", nargs="+", required=True)
    live.add_argument("--since", required=True)
    live.add_argument("--until", required=True)
    live.add_argument("--raw-dir", required=True)
    report = sub.add_parser("report", help="build the redacted manifest and drift report from a sealed raw dir")
    report.add_argument("--raw-dir", required=True)
    report.add_argument("--baseline-snapshot")
    report.add_argument("--access", required=True, help="how the raw payloads were obtained")
    report.add_argument("--scope", required=True, help="JSON describing the probed board/items/editor label")
    report.add_argument("--manifest-out", required=True)
    report.add_argument("--drift-out", required=True)
    args = parser.parse_args(argv)
    if args.command == "capture":
        try:
            records = capture(args)
        except MissingAccess as error:
            print(f"MISSING_ACCESS: {error}", file=sys.stderr)
            return 2
        print(json.dumps([{"name": record.name, "sha256": record.sha256} for record in records], indent=2))
        return 0
    raw_dir = Path(args.raw_dir).expanduser()
    records = [seal_existing(raw_dir, name) for name in RAW_FILES]
    changes = parse_status_changes(load_json(raw_dir / RAW_FILES[0]), COLUMNS["status"])
    baseline = Path(args.baseline_snapshot).read_text() if args.baseline_snapshot else None
    context = {"access": args.access, "scope": json.loads(args.scope), "raw_store": {"location": "local, outside git", "immutable": True}}
    manifest = build_manifest(changes, records, context)
    drift = build_drift_report(changes, load_json(raw_dir / RAW_FILES[1]), load_json(raw_dir / RAW_FILES[2]), baseline, COLUMNS)
    Path(args.manifest_out).write_text(json.dumps(manifest, indent=2) + "\n")
    Path(args.drift_out).write_text(json.dumps(drift, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
