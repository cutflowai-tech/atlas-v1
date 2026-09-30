"""Build an Intelligence V2 document and its review page from a read-only Monday extract.

    PYTHONPATH=src python3 -m atlas_commander.investigation <extract.json> <out_dir> [--mode approved_only|review]
        [--contract 1.5.0] [--generated-at ISO] [--monday-item-url URL-with-{item_id}]

Writes ``<out_dir>/intelligence-v2.json`` and ``<out_dir>/intelligence-v2.html``. ``approved_only`` (the default) uses only
approved parameters; ``review`` uses the proposed values and marks every document and finding as not publishable. Nothing is
written back to Monday, and no profile, dashboard or published site is changed.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from atlas_commander.investigation.engine import build_intelligence
from atlas_commander.investigation.html import render_intelligence_html
from atlas_commander.investigation.policy import APPROVED_ONLY, MODES
from atlas_commander.profile_cli import reconstruct_extract
from atlas_commander.runtime import load_contract_version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas-intelligence-v2")
    parser.add_argument("extract")
    parser.add_argument("out_dir")
    parser.add_argument("--mode", choices=MODES, default=APPROVED_ONLY)
    parser.add_argument("--contract", default="1.5.0")
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--monday-item-url", default=None, help="URL template with {item_id}")
    args = parser.parse_args(argv)
    contract = load_contract_version(args.contract)
    result = reconstruct_extract(json.loads(Path(args.extract).read_text()), contract)
    generated_at = args.generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    document = build_intelligence(result, contract, generated_at, mode=args.mode)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "intelligence-v2.json").write_text(json.dumps(document, indent=1) + "\n")
    (out / "intelligence-v2.html").write_text(render_intelligence_html(document, args.monday_item_url), encoding="utf-8")
    print(json.dumps({"json": str(out / "intelligence-v2.json"), "html": str(out / "intelligence-v2.html"), "mode": document["mode"],
                      "publishable": document["publishable"], "findings": len(document["findings"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
