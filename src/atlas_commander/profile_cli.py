"""Generate Editor Profiles from a read-only Monday extract.

    PYTHONPATH=src python3 -m atlas_commander.profile_cli list <extract.json>
    PYTHONPATH=src python3 -m atlas_commander.profile_cli build <extract.json> <editor_id> <out_dir> [--monday-item-url URL]
    PYTHONPATH=src python3 -m atlas_commander.profile_cli dashboard <extract.json> <out_dir> [--monday-item-url URL]

The extract is the JSON written by the read-only ingestion (activity logs, items and
ingestion metadata). ``build`` writes ``<editor_id>.json`` (editor-profile 1.4.0; 1.3.0 with ``--contract 1.3.0``) and
``<editor_id>.html``. ``dashboard`` builds the same profile for every Editor with attributed projects, from one
reconstruction of the extract, into ``profiles/``, then the CEO Dashboard (``dashboard.json`` and a self-contained
``dashboard.html``). Nothing is written back to Monday.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_commander.cycles import COMPLETED
from atlas_commander.dashboard import build_dashboard
from atlas_commander.dashboard_html import render_dashboard_html
from atlas_commander.pipeline import CycleReconstruction, reconstruct_cycles
from atlas_commander.profile import build_editor_profile, profiled_editors
from atlas_commander.profile_html import render_profile_html
from atlas_commander.runtime import ACTIVE_CONTRACT_VERSION, load_contract_version


def reconstruct_extract(extract: dict[str, Any], contract: dict[str, Any]) -> CycleReconstruction:
    ingestion = dict(extract.get("ingestion") or {})
    ingestion.setdefault("retrieved_at", extract.get("retrieved_at"))
    return reconstruct_cycles(extract["activity"], contract, items_payload=extract.get("items"), ingestion=ingestion)


EDITOR_EXCLUSIONS = ("UNMAPPED_EDITOR", "MISSING_EDITOR_EVENT", "MISSING_EDITOR", "AMBIGUOUS_EDITOR", "EDITOR_CHANGED_WITHIN_CYCLE")


def attribution_coverage(result: CycleReconstruction) -> dict[str, Any]:
    """Completed projects with and without a verified Editor, counted from the cycles' own exclusion reasons."""
    completed = [cycle for cycle in result.cycles if cycle.state == COMPLETED]
    reasons: dict[str, int] = {}
    for cycle in completed:
        if cycle.editor_id is None:
            reason = next((r for r in cycle.exclusions if r in EDITOR_EXCLUSIONS), "OTHER")
            reasons[reason] = reasons.get(reason, 0) + 1
    return {"completed": len(completed), "attributed": sum(1 for cycle in completed if cycle.editor_id is not None),
            "not_attributed_by_reason": dict(sorted(reasons.items(), key=lambda pair: -pair[1]))}


def build_profiles(result: CycleReconstruction, contract: dict[str, Any], out: Path, generated_at: str,
                   monday_item_url: str | None = None) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """One Editor Profile (JSON and HTML) per Editor with attributed projects, into ``out/profiles``."""
    (out / "profiles").mkdir(parents=True, exist_ok=True)
    profiles, pages = [], {}
    for editor in profiled_editors(result):
        profile = build_editor_profile(result, contract, editor["editor_id"], generated_at)
        page = render_profile_html(profile, monday_item_url)
        (out / "profiles" / f"{editor['editor_id']}.json").write_text(json.dumps(profile, indent=1) + "\n")
        (out / "profiles" / f"{editor['editor_id']}.html").write_text(page)
        profiles.append(profile)
        pages[editor["editor_id"]] = page
    return profiles, pages


def build_dashboard_files(result: CycleReconstruction, contract: dict[str, Any], out: Path, generated_at: str, profiles: list[dict[str, Any]],
                          pages: dict[str, str], monday_item_url: str | None = None) -> dict[str, Any]:
    """The CEO Dashboard (``dashboard.json`` and ``dashboard.html``) built from those profiles."""
    dashboard = build_dashboard(profiles, generated_at, mapped_editors=contract["editor_attribution"]["entries"],
                                attribution_coverage=attribution_coverage(result),
                                profile_refs={editor_id: f"profiles/{editor_id}.json" for editor_id in pages})
    (out / "dashboard.json").write_text(json.dumps(dashboard, indent=1) + "\n")
    (out / "dashboard.html").write_text(render_dashboard_html(dashboard, pages, monday_item_url))
    return dashboard


def build_all(result: CycleReconstruction, contract: dict[str, Any], out: Path, generated_at: str, monday_item_url: str | None = None) -> dict[str, Any]:
    """One Editor Profile per Editor with attributed projects, plus the CEO Dashboard built from those profiles."""
    profiles, pages = build_profiles(result, contract, out, generated_at, monday_item_url)
    return build_dashboard_files(result, contract, out, generated_at, profiles, pages, monday_item_url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas-profile")
    parser.add_argument("--contract", default=ACTIVE_CONTRACT_VERSION)
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("extract")
    build = sub.add_parser("build")
    build.add_argument("extract")
    build.add_argument("editor_id")
    build.add_argument("out_dir")
    build.add_argument("--monday-item-url", default=None, help="URL template with {item_id}")
    build.add_argument("--generated-at", default=None)
    board = sub.add_parser("dashboard")
    board.add_argument("extract")
    board.add_argument("out_dir")
    board.add_argument("--monday-item-url", default=None, help="URL template with {item_id}")
    board.add_argument("--generated-at", default=None)
    args = parser.parse_args(argv)
    contract = load_contract_version(args.contract)
    result = reconstruct_extract(json.loads(Path(args.extract).read_text()), contract)
    if args.command == "list":
        json.dump(profiled_editors(result), sys.stdout, indent=1)
        print()
        return 0
    generated_at = args.generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if args.command == "dashboard":
        dashboard = build_all(result, contract, Path(args.out_dir), generated_at, args.monday_item_url)
        print(json.dumps({"dashboard": str(Path(args.out_dir) / "dashboard.html"),
                          "editors": [{"editor_id": s["editor_id"], "display_name": s["display_name"]} for s in dashboard["editors"]]}))
        return 0
    profile = build_editor_profile(result, contract, args.editor_id, generated_at)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.editor_id}.json").write_text(json.dumps(profile, indent=1) + "\n")
    (out / f"{args.editor_id}.html").write_text(render_profile_html(profile, args.monday_item_url))
    print(json.dumps({"editor_id": args.editor_id, "json": str(out / f"{args.editor_id}.json"), "html": str(out / f"{args.editor_id}.html")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
