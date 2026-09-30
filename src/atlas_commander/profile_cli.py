"""Generate Editor Profiles from a read-only Monday extract.

    PYTHONPATH=src python3 -m atlas_commander.profile_cli list <extract.json>
    PYTHONPATH=src python3 -m atlas_commander.profile_cli build <extract.json> <editor_id> <out_dir> [--monday-item-url URL]
    PYTHONPATH=src python3 -m atlas_commander.profile_cli dashboard <extract.json> <out_dir> [--monday-item-url URL]

The extract is the JSON written by the read-only ingestion (activity logs, items and
ingestion metadata). ``build`` writes ``<editor_id>.json`` (editor-profile 1.4.0; 1.3.0 with ``--contract 1.3.0``) and
an English ``<editor_id>.html``. ``dashboard`` builds the same profile for every Editor with attributed projects, from one
reconstruction of the extract, then the CEO Dashboard, as a bilingual site (``atlas_commander.site_layout``): language-neutral
``dashboard.json`` and ``profiles/<editor_id>.json``, and English (``en/``) and Arabic (``ar/``) HTML rendered from those same
documents. Nothing is written back to Monday.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_commander import site_layout
from atlas_commander.cycles import COMPLETED, EDITOR_CHANGED_WITHIN_CYCLE, MISSING_EDITOR_EVENT
from atlas_commander.dashboard import build_dashboard
from atlas_commander.dashboard_html import render_dashboard_html
from atlas_commander.i18n import EN, Loc, locales
from atlas_commander.identity import AMBIGUOUS_EDITOR, EDITOR_LABEL_NAME_MISMATCH, EDITOR_LABEL_NAME_UNVERIFIED, MISSING_EDITOR, UNMAPPED_EDITOR
from atlas_commander.investigation.site import build_site_intelligence, write_document
from atlas_commander.photos import editor_photos
from atlas_commander.pipeline import CycleReconstruction, reconstruct_cycles
from atlas_commander.profile import build_editor_profile, profiled_editors
from atlas_commander.profile_html import render_profile_html
from atlas_commander.publication import site_publication
from atlas_commander.runtime import ACTIVE_CONTRACT_VERSION, load_contract_version
from atlas_commander.verdict.site import build_site_verdicts
from atlas_commander.verdict.site import write_document as write_verdicts


def reconstruct_extract(extract: dict[str, Any], contract: dict[str, Any]) -> CycleReconstruction:
    ingestion = dict(extract.get("ingestion") or {})
    ingestion.setdefault("retrieved_at", extract.get("retrieved_at"))
    return reconstruct_cycles(extract["activity"], contract, items_payload=extract.get("items"), ingestion=ingestion)


# Every reason a completed cycle can lack a verified Editor (identity exceptions plus the cycle-level ones).
EDITOR_EXCLUSIONS = (UNMAPPED_EDITOR, MISSING_EDITOR_EVENT, MISSING_EDITOR, AMBIGUOUS_EDITOR, EDITOR_CHANGED_WITHIN_CYCLE,
                     EDITOR_LABEL_NAME_MISMATCH, EDITOR_LABEL_NAME_UNVERIFIED)


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


def _write(out: Path, relative: str, text: str) -> None:
    path = out / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_profiles(result: CycleReconstruction, contract: dict[str, Any], out: Path, generated_at: str,
                   monday_item_url: str | None = None) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    """One Editor Profile per Editor with attributed projects: ``profiles/<id>.json`` (language-neutral) and its report page in
    every locale (``<locale>/profiles/<id>.html``). Returns the profiles and, per locale, the report HTML embedded in that
    locale's dashboard. Any locale failing to render fails the whole build."""
    (out / "profiles").mkdir(parents=True, exist_ok=True)
    publication = site_publication(result, contract, generated_at)
    if publication is not None:
        (out / site_layout.PUBLICATION_JSON).write_text(json.dumps(publication, indent=1) + "\n")
    profiles = []
    for editor in profiled_editors(result):
        profile = build_editor_profile(result, contract, editor["editor_id"], generated_at)
        (out / site_layout.profile_json(editor["editor_id"])).write_text(json.dumps(profile, indent=1) + "\n")
        profiles.append(profile)
    pages: dict[str, dict[str, str]] = {}
    for loc in locales():
        pages[loc.code] = {}
        for profile in profiles:
            editor_id = profile["editor"]["editor_id"]
            pages[loc.code][editor_id] = render_profile_html(profile, monday_item_url, loc, publication=publication)
            _write(out, site_layout.profile_html(loc.code, editor_id), render_profile_html(
                profile, monday_item_url, loc, dashboard_href=f"../dashboard.html#/editor/{editor_id}",
                switch_href=f"../../{site_layout.profile_html(loc.other().code, editor_id)}", publication=publication))
    return profiles, pages


def _entry_page(loc: Loc, target: str, publication: dict[str, Any] | None, alternate: tuple[Loc, str] | None = None) -> str:
    """A tiny page that sends the visitor to ``target`` (no third dashboard is rendered). Under a contract with publication
    identity it also names the release and source snapshot every route shares."""
    links = f'<a href="{target}">{loc.t("entry.open_dashboard")}</a>'
    if alternate:
        other, href = alternate
        links += f' · <a href="{href}" hreflang="{other.code}" lang="{other.code}" dir="{other.dir}">{other.t("entry.open_dashboard")}</a>'
    head = body = identity = ""
    if publication is not None:
        release_id, snapshot_id = publication["release_id"], publication["snapshot_id"]
        head = f'<meta name="atlas-release-id" content="{release_id}"><meta name="atlas-snapshot-id" content="{snapshot_id}">'
        body = f' data-atlas-release-id="{release_id}" data-atlas-snapshot-id="{snapshot_id}"'
        identity = f'<p>{loc.t("publication.identity", release=loc.tech(release_id), snapshot=loc.tech(snapshot_id))}</p>'
    return (f'{site_layout.document_opening(loc.code)}<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'{head}<meta http-equiv="refresh" content="0; url={target}"><title>Atlas</title></head><body{body}><p>{links}</p>{identity}</body></html>')


def build_dashboard_files(result: CycleReconstruction, contract: dict[str, Any], out: Path, generated_at: str, profiles: list[dict[str, Any]],
                          pages: dict[str, dict[str, str]], monday_item_url: str | None = None,
                          status_snapshot: dict[str, Any] | None = None, intelligence: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the language-neutral dashboard and its localized pages.

    ``status_snapshot`` is optional, language-neutral Task 7 context captured by the caller at
    build time. This function neither derives nor validates it, and both locales receive the
    exact same object. ``intelligence`` is the optional published Intelligence V2 document, shown by both locales. Under contract
    1.5.0+ the verdict document (``verdicts.json``, D54) is built from the dashboard and that Intelligence document.
    """
    editor_ids = [profile["editor"]["editor_id"] for profile in profiles]
    publication = site_publication(result, contract, generated_at)
    dashboard = build_dashboard(profiles, generated_at, mapped_editors=contract["editor_attribution"]["entries"],
                                attribution_coverage=attribution_coverage(result),
                                profile_refs={editor_id: site_layout.profile_json(editor_id) for editor_id in editor_ids}, publication=publication,
                                contract_version=contract["contract_version"])
    (out / site_layout.DASHBOARD_JSON).write_text(json.dumps(dashboard, indent=1) + "\n")
    verdicts = build_site_verdicts(dashboard, intelligence, generated_at, monday_item_url=monday_item_url)   # the redesign's judgment layer (D54), 1.5.0+
    if verdicts is not None:
        write_verdicts(out, verdicts)
    photos = editor_photos(e["editor_id"] for e in dashboard["editors"]) if verdicts is not None else {}   # T5.1: admin-added photo files
    for loc in locales():
        _write(out, site_layout.dashboard_html(loc.code), render_dashboard_html(
            dashboard, pages[loc.code], monday_item_url, loc, switch_href=f"../{site_layout.dashboard_html(loc.other().code)}",
            status_snapshot=status_snapshot, intelligence=intelligence, verdicts=verdicts, photos=photos))
        _write(out, site_layout.locale_index(loc.code), _entry_page(loc, "dashboard.html", publication))
    ar = EN.other()
    _write(out, site_layout.ROOT_ENTRY, _entry_page(EN, site_layout.dashboard_html(EN.code), publication,
                                                    (ar, site_layout.dashboard_html(ar.code))))
    return dashboard


def build_all(result: CycleReconstruction, contract: dict[str, Any], out: Path, generated_at: str, monday_item_url: str | None = None,
              status_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every Editor Profile and the CEO Dashboard, as the bilingual site described in ``atlas_commander.site_layout``."""
    profiles, pages = build_profiles(result, contract, out, generated_at, monday_item_url)
    intelligence = build_site_intelligence(result, contract, generated_at, profiles)   # only when config/intelligence-v2.json enables it
    if intelligence is not None:
        write_document(out, intelligence)
    return build_dashboard_files(result, contract, out, generated_at, profiles, pages, monday_item_url, status_snapshot, intelligence)


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
        print(json.dumps({"dashboard": str(Path(args.out_dir) / site_layout.ROOT_ENTRY),
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
