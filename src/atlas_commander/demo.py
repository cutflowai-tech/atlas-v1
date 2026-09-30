"""Local demo of the deterministic Atlas dashboard pipeline (no Docker, no Monday access).

The generated source data is synthetic and deliberately shaped like Monday activity logs.
It exercises identity resolution, work-cycle reconstruction, Video Type benchmarking,
deadline classification, performance labels, revision context, Editor Profiles, and the
presentation-only CEO Dashboard.

    PYTHONPATH=src python3 -m atlas_commander.demo serve [--out out/demo] [--port 8000]
    PYTHONPATH=src python3 -m atlas_commander.demo serve --showcase [--out out/showcase] [--port 8000]

``--showcase`` builds a richer synthetic team under contract 1.5.0 (six attested Editors, two windows, several months of
history, labels, revisions and current work) so the 1.5 interface can be reviewed against varied, realistic states.

Local development only: no Monday token or network access is needed, nothing is written to
Monday, and the production image excludes this module (``deploy/production/Dockerfile.app.dockerignore``).
The production path (sync, staged build, atomic publish) is ``atlas_sync``; this demo exercises the
same profile and dashboard builders on synthetic data.
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
FOR_BONUS = "dropdown_mm3tyvvc"
GENERATED_AT = "2026-09-28T00:00:00Z"

STATUS_INDEX = {"Internal Revisions": 0, "Revisions": 2, "Ready For Approval": 3, "Sent": 7, "In Progress": 9, "Create File": 13}
EDITOR_NAMES = {6: "Will", 12: "Ahmed", 13: "Michael", 14: "Mansour", 15: "Sobhy", 16: "Ezz"}
VIDEO_TYPE_NAMES = {4: "Class A", 5: "Class B", 6: "Simple Short", 22: "Reels Boost Pack"}


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


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _project(item: str, editor: int, hours: float, video_type: int = 4, eta: tuple[str, str | None] | None = None,
             start_at: str = "2026-09-01T10:00:00Z") -> list[dict[str, Any]]:
    """One first-pass project: Editor and Video Type set 1h before In Progress, the ETA 2h before, then Ready For Approval."""
    start = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
    end = start + timedelta(hours=hours)
    logs = [
        _dropdown(f"{item}-editor", item, EDITOR, _iso(start - timedelta(hours=1)), [editor], [EDITOR_NAMES[editor]]),
        _dropdown(f"{item}-type", item, VIDEO_TYPE, _iso(start - timedelta(hours=1) + timedelta(seconds=1)), [video_type], [VIDEO_TYPE_NAMES[video_type]]),
        _status(f"{item}-start", item, _iso(start), "Create File", "In Progress"),
        _status(f"{item}-ready", item, _iso(end), "In Progress", "Ready For Approval"),
    ]
    if eta:
        logs.append(_log(f"{item}-eta", item, ETA, _iso(start - timedelta(hours=2)), None,
                         {"date": eta[0], "time": eta[1], "icon": None}, "date"))
    return logs


def _current_item(item: str, editor: int, status: str) -> dict[str, Any]:
    return {"id": item, "board": {"id": BOARD}, "column_values": [
        {"id": EDITOR, "type": "dropdown", "value": json.dumps({"ids": [editor]}), "text": EDITOR_NAMES[editor]},
        {"id": STATUS, "type": "status", "value": json.dumps({"index": STATUS_INDEX[status]}), "text": status},
    ]}


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

    return {
        "retrieved_at": GENERATED_AT,
        "board_id": BOARD,
        "ingestion": {"retrieved_at": GENERATED_AT, "complete_history_item_ids": []},
        "activity": {"boards": [{"activity_logs": logs}]},
        "items": {"items": [_current_item("30", 6, "In Progress"), _current_item("31", 6, "Revisions")]},
    }


# --------------------------------------------------------------------------------------------------- contract 1.5 showcase

SHOWCASE_CONTRACT = "1.5.0"
# Contract 1.5 Cairo windows for GENERATED_AT: current = 2026-08-29..2026-09-27, comparison = 2026-07-30..2026-08-28.
# Starts are spread inside each range so every first Ready For Approval (Cairo) lands in the intended window.
_SHOWCASE_START_DAYS = {"history": ("2026-06-02", 50), "comparison": ("2026-07-30", 26), "current": ("2026-08-29", 26)}
_DURATION_JITTER = (0.0, -0.08, 0.06, -0.04, 0.1, -0.1, 0.03)

# editor label id -> window -> (Class A hours, Class A projects, Class B hours, Class B projects, late projects among timed ETAs).
# Speed and deadline are judged against the other Editors only (leave-one-out, D36/D45), so the spread is relative:
# Michael fast + punctual (Strong), Will similar/faster + punctual (Good), Ahmed fast but often late (Mixed),
# Mansour similar/slower + average lateness (Good), Sobhy slow + often late (Below Expectations), Ezz too few projects.
_SHOWCASE_PLAN: dict[int, dict[str, tuple[float, int, float, int, int]]] = {
    13: {"history": (9.5, 2, 22.0, 2, 1), "comparison": (9.0, 6, 21.0, 6, 4), "current": (6.5, 10, 19.0, 8, 1)},
    6: {"history": (11.0, 2, 21.0, 2, 1), "comparison": (10.5, 6, 20.0, 6, 3), "current": (10.0, 10, 14.0, 8, 2)},
    12: {"history": (7.5, 2, 16.0, 2, 2), "comparison": (7.0, 6, 15.0, 6, 5), "current": (6.8, 10, 14.5, 8, 11)},
    14: {"history": (11.5, 2, 25.0, 2, 1), "comparison": (11.0, 6, 26.0, 6, 6), "current": (10.5, 10, 28.0, 8, 6)},
    15: {"history": (12.5, 2, 23.0, 2, 1), "comparison": (12.0, 6, 24.0, 6, 5), "current": (15.0, 10, 30.0, 8, 12)},
    16: {"comparison": (9.5, 2, 0.0, 0, 1), "current": (9.0, 3, 0.0, 0, 1)},
}
# Small cohorts, no Requested ETA: Simple Short is benchmark-eligible but too small; Reels Boost Pack is not benchmark-eligible.
_SHOWCASE_EXTRAS: dict[tuple[int, str], list[tuple[int, float]]] = {
    (6, "current"): [(6, 4.0), (6, 4.5), (6, 3.5)],
    (12, "current"): [(6, 3.0), (6, 3.2)],
    (16, "current"): [(22, 7.0)],
}
_ISSUE_NAMES = {1: "Late Delivery", 2: "Poor Communication", 3: "2- Quality Issue", 4: "1- Did Not Follow Instructions",
                5: "3- Technical Issues", 6: "Excessive Revisions", 7: "4- Recurring Mistakes"}
_BONUS_NAMES = {1: "1- Exceptional Quality", 3: "Saved Rush Project", 4: "Client Praise", 5: "On Time Delivery",
                6: "High Workload", 7: "Additional Revisions"}
# (editor, window, project index) -> labels as (column, label id). Performance Issues are negative; For Bonus holds
# positive (1, 3, 4, 5) and context (6, 7) labels.
_SHOWCASE_LABELS: dict[tuple[int, str, int], list[tuple[str, int]]] = {
    (13, "current", 0): [(FOR_BONUS, 1)], (13, "current", 4): [(FOR_BONUS, 4)], (13, "current", 9): [(FOR_BONUS, 1), (FOR_BONUS, 4)],
    (13, "current", 12): [(FOR_BONUS, 5)], (13, "comparison", 2): [(ISSUES, 3)],
    (6, "current", 1): [(FOR_BONUS, 3)], (6, "current", 6): [(FOR_BONUS, 5)], (6, "current", 10): [(FOR_BONUS, 6)],
    (6, "current", 14): [(ISSUES, 2)], (6, "comparison", 5): [(FOR_BONUS, 4)],
    (12, "current", 2): [(ISSUES, 1)], (12, "current", 5): [(ISSUES, 1), (ISSUES, 2)], (12, "current", 11): [(FOR_BONUS, 4)],
    (14, "current", 3): [(FOR_BONUS, 6)], (14, "current", 8): [(FOR_BONUS, 7)], (14, "current", 13): [(ISSUES, 5)],
    (15, "current", 1): [(ISSUES, 3)], (15, "current", 5): [(ISSUES, 4)], (15, "current", 9): [(ISSUES, 7), (ISSUES, 6)],
    (15, "current", 15): [(ISSUES, 1)], (15, "comparison", 3): [(FOR_BONUS, 1)], (15, "comparison", 7): [(ISSUES, 3)],
    (16, "current", 0): [(FOR_BONUS, 4)],
}
# (editor, window, project index) -> rework status entered after the first Ready For Approval (context only, never scored).
_SHOWCASE_REWORK: dict[tuple[int, str, int], str] = {
    (15, "current", 0): "Revisions", (15, "current", 2): "Revisions", (15, "current", 5): "Revisions",
    (15, "current", 4): "Internal Revisions", (12, "current", 1): "Revisions", (12, "current", 3): "Revisions",
    (6, "current", 2): "Revisions", (14, "current", 0): "Internal Revisions", (14, "current", 6): "Internal Revisions",
    (13, "current", 8): "Internal Revisions", (15, "comparison", 1): "Revisions", (6, "comparison", 0): "Revisions",
}
# Current snapshot (items payload): Active Work (In Progress / Revisions / Internal Revisions) and Awaiting Approval.
_SHOWCASE_CURRENT: list[tuple[int, str]] = [
    (6, "In Progress"), (6, "In Progress"), (6, "Revisions"), (6, "Ready For Approval"),
    (12, "In Progress"), (12, "In Progress"), (12, "In Progress"), (12, "Internal Revisions"),
    (13, "In Progress"), (13, "Ready For Approval"), (13, "Ready For Approval"),
    (14, "In Progress"), (14, "Revisions"),
    (15, "In Progress"), (15, "In Progress"), (15, "Revisions"), (15, "Revisions"), (15, "Ready For Approval"),
    (16, "In Progress"),
]


def _spread(total: int, marked: int) -> set[int]:
    """Deterministically spread ``marked`` of ``total`` positions evenly (no randomness)."""
    return {index for index in range(total) if (index + 1) * marked // total > index * marked // total} if total else set()


def _window_projects(editor: int, window: str) -> list[tuple[int, float, bool]]:
    """(video type, hours, has a timed-ETA slot) in a stable interleaved Class A / Class B order, then the small cohorts."""
    a_hours, a_count, b_hours, b_count, _ = _SHOWCASE_PLAN[editor][window]
    order: list[tuple[int, float, bool]] = []
    for index in range(max(a_count, b_count)):
        if index < a_count:
            order.append((4, a_hours, True))
        if index < b_count:
            order.append((5, b_hours, True))
    order.extend((video_type, hours, False) for video_type, hours in _SHOWCASE_EXTRAS.get((editor, window), []))
    return order


def showcase_extract() -> dict[str, Any]:
    """A deterministic, non-production Monday-shaped extract for reviewing the contract 1.5 interface.

    Six attested Editors (label IDs 6, 12, 13, 14, 15, 16) with projects in June--July history, the comparison window and
    the current window; Class A / Class B cohorts plus two small ones; timed, missing and date-only Requested ETAs; negative,
    positive and context labels; client and internal revisions; and a current items snapshot for Active Work."""
    logs: list[dict[str, Any]] = []
    next_item = 1001
    for editor, windows in _SHOWCASE_PLAN.items():
        for window, plan in windows.items():
            projects = _window_projects(editor, window)
            first_day, span = _SHOWCASE_START_DAYS[window]
            main = editor != 16 and window != "history"
            # Two projects per main Editor window lose a timed ETA: one has none, one is date-only (not classifiable).
            missing, date_only = (3, 7) if main else (-1, -1)
            timed = [index for index, (_, _, slot) in enumerate(projects) if slot and index not in (missing, date_only)]
            late = {timed[position] for position in _spread(len(timed), plan[4])}
            on_time = next((index for index in timed if index not in late), None) if editor == 6 and window == "current" else None
            for index, (video_type, base_hours, slot) in enumerate(projects):
                item = str(next_item)
                next_item += 1
                day = datetime.fromisoformat(f"{first_day}T00:00:00+00:00") + timedelta(days=index * span // max(len(projects), 1))
                start = day + timedelta(hours=6 + 2 * (index % 4))
                hours = round(base_hours * (1 + _DURATION_JITTER[(index + editor) % len(_DURATION_JITTER)]) * 60) / 60
                ready = datetime.fromisoformat(_iso(start + timedelta(hours=hours)).replace("Z", "+00:00"))
                eta: tuple[str, str | None] | None = None
                if slot and index == date_only:
                    eta = ((ready + timedelta(days=1)).strftime("%Y-%m-%d"), None)
                elif slot and index != missing:
                    offset = (timedelta(0) if index == on_time else -timedelta(hours=2 + index % 3) if index in late
                              else timedelta(hours=1 + index % 4))
                    moment = ready + offset
                    eta = (moment.strftime("%Y-%m-%d"), moment.strftime("%H:%M:%S"))
                logs.extend(_project(item, editor, hours, video_type=video_type, eta=eta, start_at=_iso(start)))
                labels = _SHOWCASE_LABELS.get((editor, window, index), [])
                for column in (ISSUES, FOR_BONUS):
                    ids = [label for label_column, label in labels if label_column == column]
                    if ids:
                        names = _ISSUE_NAMES if column == ISSUES else _BONUS_NAMES
                        logs.append(_dropdown(f"{item}-{column}", item, column, _iso(ready + timedelta(hours=2)), ids, [names[i] for i in ids]))
                rework = _SHOWCASE_REWORK.get((editor, window, index))
                if rework:
                    logs.append(_status(f"{item}-rework", item, _iso(ready + timedelta(hours=20)), "Ready For Approval", rework))
                    logs.append(_status(f"{item}-reready", item, _iso(ready + timedelta(hours=26)), rework, "Ready For Approval"))
                if window == "history":
                    logs.append(_status(f"{item}-sent", item, _iso(ready + timedelta(days=1)), "Ready For Approval", "Sent"))
    current = [_current_item(str(9001 + index), editor, status) for index, (editor, status) in enumerate(_SHOWCASE_CURRENT)]
    return {
        "retrieved_at": GENERATED_AT,
        "board_id": BOARD,
        "ingestion": {"retrieved_at": GENERATED_AT, "complete_history_item_ids": []},
        "activity": {"boards": [{"activity_logs": logs}]},
        "items": {"items": current},
    }


def build_showcase(out_dir: Path) -> dict[str, Path]:
    """Build the contract 1.5.0 showcase site from ``showcase_extract()`` with the real profile and dashboard builders."""
    out_dir.mkdir(parents=True, exist_ok=True)
    extract = out_dir / "showcase-extract.json"
    extract.write_text(json.dumps(showcase_extract(), indent=2) + "\n")
    result = profile_cli(["--contract", SHOWCASE_CONTRACT, "dashboard", str(extract), str(out_dir), "--generated-at", GENERATED_AT])
    if result != 0:
        raise RuntimeError(f"showcase dashboard generation failed with exit code {result}")
    (out_dir / "healthz").write_text("ok\n")
    return {
        "extract": extract,
        "dashboard": out_dir / "dashboard.json",
        "profile": out_dir / "profiles" / "editor-label-13.json",
        "html": out_dir / "en" / "dashboard.html",
        "arabic_html": out_dir / "ar" / "dashboard.html",
        "index": out_dir / "index.html",
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
    serve = sub.add_parser("serve")
    for command in (build, serve):
        command.add_argument("--out", type=Path, default=None, help="output directory (default out/demo, or out/showcase with --showcase)")
        command.add_argument("--showcase", action="store_true", help=f"build the richer contract {SHOWCASE_CONTRACT} showcase dataset")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if args.out is None:
        args.out = Path("out/showcase" if args.showcase else "out/demo")

    paths = build_showcase(args.out) if args.showcase else build_demo(args.out)
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
