"""Local Docker demo for the deterministic Atlas dashboard pipeline.

The generated source data is synthetic and deliberately shaped like Monday activity logs.
It exercises identity resolution, work-cycle reconstruction, Video Type benchmarking,
deadline classification, performance labels, revision context, Editor Profiles, and the
presentation-only CEO Dashboard.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from atlas_commander.profile_cli import main as profile_cli

BOARD = "5091110326"
SHARED_ACCOUNT = "99154021"
STATUS = "project_status"
EDITOR = "dropdown_mm1emgt8"
VIDEO_TYPE = "dropdown_mm062ga0"
ETA = "date"
ISSUES = "dropdown_mm3tyk8g"
GENERATED_AT = "2026-09-28T00:00:00Z"

STATUS_INDEX = {"Revisions": 2, "Ready For Approval": 3, "Sent": 7, "In Progress": 9, "Create File": 13}
EDITOR_NAMES = {6: "Will", 12: "Ahmed"}
VIDEO_TYPE_NAMES = {4: "Class A", 5: "Class B", 22: "Reels Boost Pack"}


def _ticks(moment: str) -> str:
    parsed = datetime.fromisoformat(moment.replace("Z", "+00:00")).astimezone(timezone.utc)
    return str(int(parsed.timestamp()) * 10_000_000 + parsed.microsecond * 10)


def _log(log_id: str, item: str, column: str, moment: str, previous: Any, value: Any, column_type: str = "color") -> dict[str, Any]:
    data = {
        "pulse_id": int(item),
        "board_id": int(BOARD),
        "column_id": column,
        "column_type": column_type,
        "previous_value": previous,
        "value": value,
        "is_undo_action": None,
        "pulse_name": f"Synthetic project {item}",
    }
    return {
        "id": log_id,
        "event": "update_column_value",
        "entity": "pulse",
        "user_id": SHARED_ACCOUNT,
        "account_id": "1",
        "created_at": _ticks(moment),
        "data": json.dumps(data),
    }


def _dropdown(log_id: str, item: str, column: str, moment: str, ids: list[int], names: list[str]) -> dict[str, Any]:
    value = {"chosenValues": [{"id": identifier, "name": name} for identifier, name in zip(ids, names)]} if ids else None
    return _log(log_id, item, column, moment, None, value, "dropdown")


def _status(log_id: str, item: str, moment: str, before: str, after: str) -> dict[str, Any]:
    label = lambda text: {"label": {"text": text, "index": STATUS_INDEX[text]}}
    return _log(log_id, item, STATUS, moment, label(before), label(after))


def _project(item: str, editor: int, hours: float, video_type: int = 4, eta: tuple[str, str | None] | None = None) -> list[dict[str, Any]]:
    start = datetime.fromisoformat("2026-09-01T10:00:00+00:00")
    end = start + timedelta(hours=hours)
    logs = [
        _dropdown(f"{item}-editor", item, EDITOR, "2026-09-01T09:00:00Z", [editor], [EDITOR_NAMES[editor]]),
        _dropdown(f"{item}-type", item, VIDEO_TYPE, "2026-09-01T09:00:01Z", [video_type], [VIDEO_TYPE_NAMES[video_type]]),
        _status(f"{item}-start", item, "2026-09-01T10:00:00Z", "Create File", "In Progress"),
        _status(f"{item}-ready", item, end.strftime("%Y-%m-%dT%H:%M:%SZ"), "In Progress", "Ready For Approval"),
    ]
    if eta:
        logs.append(_log(f"{item}-eta", item, ETA, "2026-09-01T08:00:00Z", None,
                         {"date": eta[0], "time": eta[1], "icon": None}, "date"))
    return logs


def synthetic_extract() -> dict[str, Any]:
    """Return a deterministic, non-production Monday-shaped extract."""
    logs: list[dict[str, Any]] = []
    for number, hours in enumerate((8, 9, 10, 11, 12), start=1):
        logs.extend(_project(str(number), 6, hours, eta=("2026-09-01", "20:00:00")))
    for number, hours in enumerate((18, 19, 20, 21, 22), start=11):
        logs.extend(_project(str(number), 12, hours))
    logs.extend(_project("21", 6, 30, video_type=5, eta=("2026-09-02", None)))
    logs.extend(_project("23", 6, 7, video_type=22))
    logs.extend([
        _dropdown("quality-1", "1", ISSUES, "2026-09-03T00:00:00Z", [1], ["Late Delivery"]),
        _dropdown("quality-2", "2", ISSUES, "2026-09-03T00:00:00Z", [1, 2], ["Late Delivery", "Poor Communication"]),
        _status("revision-sent", "4", "2026-09-04T00:00:00Z", "Ready For Approval", "Sent"),
        _status("revision-client", "4", "2026-09-05T00:00:00Z", "Sent", "Revisions"),
    ])

    def current_item(item: str, editor: int, status: str) -> dict[str, Any]:
        return {"id": item, "board": {"id": BOARD}, "column_values": [
            {"id": EDITOR, "type": "dropdown", "value": json.dumps({"ids": [editor]}), "text": EDITOR_NAMES[editor]},
            {"id": STATUS, "type": "status", "value": json.dumps({"index": STATUS_INDEX[status]}), "text": status},
        ]}

    return {
        "retrieved_at": GENERATED_AT,
        "board_id": BOARD,
        "ingestion": {"retrieved_at": GENERATED_AT, "complete_history_item_ids": []},
        "activity": {"boards": [{"activity_logs": logs}]},
        "items": {"items": [current_item("30", 6, "In Progress"), current_item("31", 6, "Revisions")]},
    }


def build_demo(out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    extract = out_dir / "demo-extract.json"
    extract.write_text(json.dumps(synthetic_extract(), indent=2) + "\n")
    result = profile_cli(["dashboard", str(extract), str(out_dir), "--generated-at", GENERATED_AT])
    if result != 0:
        raise RuntimeError(f"dashboard generation failed with exit code {result}")
    index = out_dir / "index.html"
    html = out_dir / "en" / "dashboard.html"
    (out_dir / "healthz").write_text("ok\n")
    return {
        "extract": extract,
        "dashboard": out_dir / "dashboard.json",
        "profile": out_dir / "profiles" / "editor-label-6.json",
        "html": html,
        "arabic_html": out_dir / "ar" / "dashboard.html",
        "index": index,
    }


class DemoHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas-demo")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--out", type=Path, default=Path("out"))
    serve = sub.add_parser("serve")
    serve.add_argument("--out", type=Path, default=Path("out"))
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    paths = build_demo(args.out)
    if args.command == "build":
        print(json.dumps({name: str(path) for name, path in paths.items()}))
        return 0

    handler = partial(DemoHandler, directory=str(args.out))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Atlas demo available at http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
