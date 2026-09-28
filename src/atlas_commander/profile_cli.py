"""Generate Editor Profiles from a read-only Monday extract.

    PYTHONPATH=src python3 -m atlas_commander.profile_cli list <extract.json>
    PYTHONPATH=src python3 -m atlas_commander.profile_cli build <extract.json> <editor_id> <out_dir> [--monday-item-url URL]

The extract is the JSON written by the read-only ingestion (activity logs, items and
ingestion metadata). Output is ``<editor_id>.json`` (editor-profile 1.4.0; 1.3.0 with ``--contract 1.3.0``) and
``<editor_id>.html``. Nothing is written back to Monday.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_commander.pipeline import CycleReconstruction, reconstruct_cycles
from atlas_commander.profile import build_editor_profile, profiled_editors
from atlas_commander.profile_html import render_profile_html
from atlas_commander.runtime import ACTIVE_CONTRACT_VERSION, load_contract_version


def reconstruct_extract(extract: dict[str, Any], contract: dict[str, Any]) -> CycleReconstruction:
    ingestion = dict(extract.get("ingestion") or {})
    ingestion.setdefault("retrieved_at", extract.get("retrieved_at"))
    return reconstruct_cycles(extract["activity"], contract, items_payload=extract.get("items"), ingestion=ingestion)


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
    args = parser.parse_args(argv)
    contract = load_contract_version(args.contract)
    result = reconstruct_extract(json.loads(Path(args.extract).read_text()), contract)
    if args.command == "list":
        json.dump(profiled_editors(result), sys.stdout, indent=1)
        print()
        return 0
    generated_at = args.generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    profile = build_editor_profile(result, contract, args.editor_id, generated_at)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.editor_id}.json").write_text(json.dumps(profile, indent=1) + "\n")
    (out / f"{args.editor_id}.html").write_text(render_profile_html(profile, args.monday_item_url))
    print(json.dumps({"editor_id": args.editor_id, "json": str(out / f"{args.editor_id}.json"), "html": str(out / f"{args.editor_id}.html")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
