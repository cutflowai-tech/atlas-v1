"""Print a built site's verdicts for review (redesign T2.16; the owner signs off this table in T6.3).

    PYTHONPATH=src python3 -m atlas_commander.verdict.review <site_dir>

``<site_dir>`` is a local build (``profile_cli dashboard … out/real``) or a published release directory. The script checks that
``verdicts.json`` is publishable (schema, same snapshot and contract as ``dashboard.json``) and holds one verdict for every Editor of
the dashboard, then prints the team verdict, one row per Editor (tier, rank, score, confidence, headline key, overdue projects) and
the decisions. It exits 1 when a check fails. Nothing is written.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from atlas_commander import site_layout
from atlas_commander.verdict.site import VERDICTS_JSON, site_problems
from atlas_commander.verdict.tiers import TIERS


def problems(site: Path) -> list[str]:
    path = site / VERDICTS_JSON
    if not path.is_file():
        return [f"{VERDICTS_JSON} is missing: the build did not run the verdict engine (contract 1.5.0+ and include_in_site_build)"]
    dashboard = json.loads((site / site_layout.DASHBOARD_JSON).read_text(encoding="utf-8"))
    source = dashboard["source"]
    found = site_problems(path, source["executable_contract_version"], source.get("retrieved_at"))
    if found:
        return found
    verdicts = json.loads(path.read_text(encoding="utf-8"))
    expected = {e["editor_id"] for e in dashboard["editors"]}
    actual = [e["editor_id"] for e in verdicts["editors"]]
    out = []
    if sorted(actual) != sorted(expected):
        out.append(f"verdicts for {sorted(set(actual))} but the dashboard has {sorted(expected)}")
    if len(actual) != len(set(actual)):
        out.append("an Editor has more than one verdict")
    return out


def _cell(value: Any) -> str:
    return "—" if value is None else str(value)


def table(verdicts: Mapping[str, Any]) -> str:
    """Team line, then the Editors by tier (Best → Low activity) and rank, then the decisions."""
    team = verdicts.get("team") or {}
    lines = [f"Snapshot {verdicts['source']['retrieved_at']} · verdict {verdicts['verdict_version']} · config {verdicts['config']['version']}",
             f"Team: {team.get('state')} · {team.get('trend')} · confidence {team.get('confidence')} · "
             + " · ".join(f"{k['key']} {k['value']}" for k in team.get("kpis") or []), ""]
    header = ("Editor", "Tier", "Rank", "Score", "Confidence", "Headline", "Overdue")
    order = sorted(verdicts["editors"], key=lambda e: (TIERS.index(e["tier"]), e["rank"] is None, e["rank"] or 0, e["display_name"]))
    rows = [(e["display_name"], e["tier"], f"{e['rank']}/{e['ranked_of']}" if e["rank"] else "—", _cell(e["score"]), e["confidence"],
             e["headline"]["key"].removeprefix("verdict.headline."), str(len(e["overdue"]))) for e in order]
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(len(header))]
    for row in [header, tuple("-" * w for w in widths), *rows]:
        lines.append("  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip())
    names = {e["editor_id"]: e["display_name"] for e in verdicts["editors"]}
    shown = {d["id"] for d in verdicts["decisions"]}
    lines += ["", f"Decisions ({len(verdicts['decisions'])} on the overview, {len(verdicts['decision_candidates'])} in all):"]
    for d in verdicts["decision_candidates"]:
        owners = ", ".join(names.get(i, i) for i in d["owner_editor_ids"]) or d["owner_role"]
        lines.append(f"  {'*' if d['id'] in shown else ' '} {d['priority']} {d['horizon']:<10} {d['type']:<18} {owners} ({d['confidence']})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas-verdict-review")
    parser.add_argument("site", type=Path)
    args = parser.parse_args(argv)
    found = problems(args.site)
    if found:
        for problem in found:
            print(f"verdicts not publishable: {problem}", file=sys.stderr)
        return 1
    print(table(json.loads((args.site / VERDICTS_JSON).read_text(encoding="utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
