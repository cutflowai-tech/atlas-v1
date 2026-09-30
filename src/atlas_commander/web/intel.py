"""Intelligence V2 in the Atlas app: the Top findings, their evidence drawers, each Editor's findings and the rules (presentation only).

Renders the published ``intelligence-v2.json`` document (``approved_only``) exactly as the engine wrote it. Nothing here ranks,
filters by evidence, clusters or computes: the Top findings are ``sections.top_findings``, clusters are the engine's, confidence is
the engine's level. Sentences come from the same statement codes and params in both languages (``investigation.narrative`` and
``narrative_ar``); their Monday values and numbers arrive as Unicode isolates and are shown as ``<bdi>``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from html import escape
from typing import Any

from atlas_commander.i18n import Html, Loc, isolate_latin
from atlas_commander.investigation import narrative
from atlas_commander.web.kit import Ctx, dl, item_link, open_link, project_tid, section_head, table, template

CATEGORY_ORDER = ("needs_attention", "emerging_risk", "system_pattern", "hidden_context", "editor_specific_pattern", "important_improvement", "data_warning")
ROLES = (("supporting_evidence", "supporting"), ("contradicting_evidence", "contradicting"), ("context_evidence", "context"))
# Contradicting and context evidence blocks the detectors can publish; each has a sentence in the catalogue (others show their code).
BLOCKS = ("execution_speed_competitive", "late_despite_typical_execution", "late_projects_with_adequate_runway", "late_with_short_runway",
          "team_execution_moved_same_way", "team_late_rate_moved_same_way", "team_negative_label_rate_moved_same_way",
          "late_delivery_label_on_on_time_submission", "similar_historical_projects", "workload_by_period")


def marked_html(text: str, isolate: bool = False) -> Html:
    """Narrative text with isolate marks as HTML: Monday values in ``<bdi>``, numbers and IDs in ``<bdi dir="ltr">``. With
    ``isolate`` (Arabic), Latin terms of the narrative itself ("Video Type", "Requested ETA") are isolated too (T1.4)."""
    out, depth = [], 0
    for part in re.split(f"([{narrative.FSI}{narrative.LRI}{narrative.PDI}])", text):
        if part in (narrative.FSI, narrative.LRI):
            out.append("<bdi>" if part == narrative.FSI else '<bdi dir="ltr">')
            depth += 1
        elif part == narrative.PDI:
            out.append("</bdi>")
            depth -= 1
        else:
            escaped = escape(part, quote=False)
            out.append(isolate_latin(escaped) if isolate and depth == 0 else escaped)
    return Html("".join(out))


def finding_scope(doc: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    """How the published findings are shown (ATLAS-DATA-002): the Top findings, the other primary findings listed below them, and
    the duplicates grouped under their cluster's primary finding. The three parts always add up to every published finding."""
    top_ids = doc["sections"]["top_findings"]["finding_ids"]
    top = [f for f in doc["findings"] if f["finding_id"] in top_ids]
    grouped = [f for f in doc["findings"] if f["finding_id"] not in top_ids and (f.get("cluster") or {}).get("suppressed_in_sections")]
    listed = [f for f in doc["findings"] if f["finding_id"] not in top_ids and not (f.get("cluster") or {}).get("suppressed_in_sections")]
    return {"top": top, "listed": listed, "grouped": grouped}


def tid(finding: Mapping[str, Any]) -> str:
    return "iv2-" + finding["finding_id"].replace(".", "-").replace(":", "-")


def published(doc: Mapping[str, Any] | None) -> bool:
    """Only a publishable (approved_only) document is ever shown."""
    return doc is not None and bool(doc.get("publishable")) and doc.get("mode") == "approved_only"


def _by_id(doc: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {finding["finding_id"]: finding for finding in doc["findings"]}


def _text(finding: Mapping[str, Any], loc: Loc) -> dict[str, Any]:
    return narrative.finding_text(narrative.view(finding), loc.code, marked=True)


def confidence_chip(finding: Mapping[str, Any], loc: Loc) -> str:
    level = (finding.get("confidence") or {}).get("level", "weak")
    return f'<span class="iv-conf {escape(level)}" data-confidence="{escape(level)}">{loc.t("ui.iv2.confidence")}: {loc.t("ui.iv2.level." + level)}</span>'


def category_chip(finding: Mapping[str, Any], loc: Loc) -> str:
    category = finding["category"]
    return f'<span class="iv-cat {escape(category)} {escape(finding["direction"])}" data-category="{escape(category)}">{loc.t("ui.iv2.category." + category)}</span>'


def _evidence_line(finding: Mapping[str, Any], loc: Loc) -> Html:
    return loc.t("ui.iv2.evidence_line", projects=loc.count("noun.project", finding["sample_size"]),
                 editors=loc.count("meta.editors", len(finding["affected_editors"])))


def _block_sentence(block: Mapping[str, Any], loc: Loc) -> Html:
    """A block's description (when the catalogue has one) and its number of Monday projects; the code stays in the drawer's data."""
    projects = loc.count("noun.project", len({record["monday_item_id"] for record in block["records"]}))
    return Html(f'{loc.t("ui.iv2.block." + block["code"])} · {projects}') if block["code"] in BLOCKS else projects


def _mixed(finding: Mapping[str, Any], loc: Loc, ctx: Ctx) -> str:
    """Contradicting evidence is always shown next to the claim it qualifies (D53.12)."""
    blocks = finding.get("contradicting_evidence") or []
    if not blocks:
        return ""
    rows = "".join(f"<li>{_block_sentence(block, loc)}</li>" for block in blocks)
    return (f'<div class="iv-mixed" data-mixed="true"><b>{loc.t("ui.iv2.mixed")}</b><ul>{rows}</ul></div>')


def finding_card(finding: Mapping[str, Any], ctx: Ctx, rank: int | None = None, compact: bool = False) -> str:
    loc = ctx.loc
    text = _text(finding, loc)
    cluster = finding.get("cluster") or {}
    related = len(cluster.get("members") or []) - 1 if cluster.get("members") else 0
    head = (f'<div class="iv-h">{f'<span class="iv-rank">{loc.num(rank)}</span>' if rank else ""}{category_chip(finding, loc)}{confidence_chip(finding, loc)}'
            + (f'<span class="iv-rel">{loc.t("ui.iv2.related", n=loc.num(related))}</span>' if related > 0 else "") + "</div>")
    evidence = (f'<div class="iv-ev"><span>{_evidence_line(finding, loc)}</span>'
                f'{open_link(tid(finding), loc.t("ui.open_evidence"), ctx)}</div>')
    if compact:
        return (f'<article class="iv-card compact" data-finding="{escape(finding["finding_id"])}">{head}<h3>{marked_html(text["title"], loc.isolate)}</h3>'
                f'<p>{marked_html(text["observation"], loc.isolate)}</p>{_mixed(finding, loc, ctx)}{evidence}</article>')
    meaning = f'<dt>{loc.t("ui.iv2.meaning")}</dt><dd>{marked_html(text["interpretation"], loc.isolate)}</dd>' if text["interpretation"] else ""
    return (f'<article class="iv-card" data-finding="{escape(finding["finding_id"])}">{head}<h3>{marked_html(text["title"], loc.isolate)}</h3>'
            f'<dl class="iv-dl"><dt>{loc.t("ui.iv2.noticed")}</dt><dd>{marked_html(text["observation"], loc.isolate)}</dd>{meaning}'
            f'<dt>{loc.t("ui.iv2.matters")}</dt><dd>{marked_html(text["management_significance"], loc.isolate)}</dd>'
            f'<dt>{loc.t("ui.iv2.investigate")}</dt><dd>{marked_html(text["suggested_investigation"], loc.isolate)}</dd></dl>'
            f'{_mixed(finding, loc, ctx)}{evidence}</article>')


def overview_section(doc: Mapping[str, Any] | None, ctx: Ctx) -> str:
    """The management surface: at most the engine's Top findings (D53: five), and every other published finding one click away."""
    if not published(doc):
        return ""
    assert doc is not None
    loc = ctx.loc
    by_id = _by_id(doc)
    top_ids = doc["sections"]["top_findings"]["finding_ids"]
    cards = "".join(finding_card(by_id[i], ctx, rank) for rank, i in enumerate(top_ids, start=1))
    body = f'<div class="iv-grid">{cards}</div>' if cards else f'<p class="muted">{loc.t("ui.iv2.none")}</p>'
    groups = []
    scope = finding_scope(doc)
    primaries = scope["listed"]
    for category in CATEGORY_ORDER:
        rows = [f for f in primaries if f["category"] == category]
        if not rows:
            continue
        items = "".join(f'<li><button type="button" class="iv-row" data-drawer="{escape(tid(f))}">{confidence_chip(f, loc)}'
                        f'<span>{marked_html(_text(f, loc)["title"], loc.isolate)}</span></button></li>' for f in rows)
        groups.append(f'<div class="iv-group"><h4>{loc.t("ui.iv2.category." + category)} <span class="muted">{loc.num(len(rows))}</span></h4><ul>{items}</ul></div>')
    counts = {key: loc.num(len(scope[key])) for key in ("top", "listed", "grouped")}
    reconcile = f'<p class="note" data-scope="published">{loc.t("ui.iv2.scope", total=loc.num(len(doc["findings"])), **counts)}</p>'
    more = (f'<details class="more iv-more"><summary>{loc.t("ui.iv2.all", n=counts["listed"])}</summary>{reconcile}{"".join(groups)}</details>'
            if groups else "")
    withheld = sum("weak_evidence_review_only" in row["reasons"] for row in doc["examined_without_finding"])
    note = loc.t("ui.iv2.method") + (Html(" ") + loc.t("ui.iv2.withheld", n=loc.num(withheld)) if withheld else Html(""))
    return (f'<section class="sec iv" id="intelligence" data-section="intelligence" aria-labelledby="iv-h">'
            f'{section_head(f"<span id=iv-h>{loc.t("ui.iv2.title")}</span>", loc.t("ui.iv2.sub"))}'
            f'<h3 class="iv-top-h">{loc.t("ui.iv2.top")}</h3>{body}{more}<p class="note">{note}</p></section>')


def editor_findings(doc: Mapping[str, Any] | None, editor_id: str, ctx: Ctx) -> list[Mapping[str, Any]]:
    if not published(doc):
        return []
    assert doc is not None
    by_id = _by_id(doc)
    block = next((row for row in doc["editors"] if row["editor_id"] == editor_id), None)
    return [by_id[i] for i in (block or {}).get("finding_ids", []) if i in by_id]


def editor_section(doc: Mapping[str, Any] | None, editor_id: str, section_id: str, ctx: Ctx) -> str:
    """The Editor's own findings, in the engine's rank order (only when the document is published)."""
    if not published(doc):
        return ""
    loc = ctx.loc
    rows = editor_findings(doc, editor_id, ctx)
    body = ("".join(finding_card(f, ctx, compact=True) for f in rows) if rows else f'<p class="muted">{loc.t("ui.iv2.editor_none")}</p>')
    return (f'<section id="{escape(section_id)}" class="sec" data-section="intelligence">{section_head(loc.t("ui.iv2.editor_title"), loc.t("ui.iv2.editor_sub"))}'
            f'<div class="iv-list">{body}</div></section>')


def _records(block: Mapping[str, Any], ctx: Ctx, templates: set[str]) -> str:
    chips = []
    for item in sorted({record["monday_item_id"]: record for record in block["records"]}.values(), key=lambda r: r["monday_item_id"]):
        target = project_tid(item["editor_id"], item["monday_item_id"]) if item.get("editor_id") else None
        if target and target in templates:
            chips.append(f'<button type="button" class="chip" data-drawer="{escape(target)}">{ctx.loc.tech(item["monday_item_id"])}</button>')
        else:
            chips.append(f'<span class="chip">{item_link(item["monday_item_id"], ctx)}</span>')
    return f'<div class="chips iv-items">{"".join(chips)}</div>'


def drawers(doc: Mapping[str, Any] | None, ctx: Ctx, templates: set[str]) -> str:
    """One drawer per published finding: every sentence, the confidence factors, the limitations and every Monday project behind it."""
    if not published(doc):
        return ""
    assert doc is not None
    loc = ctx.loc
    by_id = _by_id(doc)
    out = []
    for finding in doc["findings"]:
        text = _text(finding, loc)
        confidence = finding.get("confidence") or {}
        factors = "".join(f"<li>{escape(narrative.module(loc.code).FACTOR_NAMES.get(f['factor'], f['factor']))}: "
                          f"{escape(narrative.module(loc.code).ASSESSMENTS.get(f['assessment'], f['assessment']))}</li>" for f in confidence.get("factors", []))
        sections = [(loc.t("ui.iv2.noticed"), marked_html(text["observation"], loc.isolate))]
        if text["interpretation"]:
            sections.append((loc.t("ui.iv2.meaning"), marked_html(text["interpretation"], loc.isolate)))
        if text["hypothesis"]:
            sections.append((loc.t("ui.iv2.to_check"), marked_html(text["hypothesis"], loc.isolate)))
        sections += [(loc.t("ui.iv2.matters"), marked_html(text["management_significance"], loc.isolate)),
                     (loc.t("ui.iv2.investigate"), marked_html(text["suggested_investigation"], loc.isolate)),
                     (loc.t("ui.iv2.question"), marked_html(text["investigation_question"], loc.isolate))]
        content = [f'<div class="iv-h">{category_chip(finding, loc)}{confidence_chip(finding, loc)}</div>', dl([(str(k), str(v)) for k, v in sections])]
        content.append(f'<h4>{loc.t("ui.iv2.confidence_basis")}</h4><p>{marked_html(text["uncertainty"], loc.isolate)}</p><ul>{factors}</ul>')
        content.append(_mixed(finding, loc, ctx))
        for key, role in ROLES:
            for block in finding.get(key) or []:
                content.append(f'<h4 data-block="{escape(block["code"])}">{loc.t("ui.iv2.role." + role)} · {_block_sentence(block, loc)}</h4>'
                               f'{_records(block, ctx, templates)}')
        members = [m for m in ((finding.get("cluster") or {}).get("members") or []) if m != finding["finding_id"] and m in by_id]
        if members:
            links = "".join(f'<li><button type="button" class="link" data-drawer="{escape(tid(by_id[m]))}">{marked_html(_text(by_id[m], loc)["title"], loc.isolate)}</button></li>'
                            for m in members)
            content.append(f'<h4>{loc.t("ui.iv2.cluster")}</h4><ul>{links}</ul>')
        limitations = "".join(f"<li>{marked_html(line, loc.isolate)}</li>" for line in text["limitations"])
        content.append(f'<h4>{loc.t("ui.iv2.limitations")}</h4><ul>{limitations}</ul>')
        content.append(f'<p class="xs muted">{loc.t("ui.iv2.detector", detector=loc.tech(finding["finding_type"]), version=loc.tech(finding["detector_version"]))}</p>')
        out.append(template(tid(finding), narrative.plain(text["title"]), "".join(content)))
    return "".join(out)


def rules_card(doc: Mapping[str, Any] | None, ctx: Ctx) -> str:
    """Data & rules: the approved Intelligence V2 parameters (D53, D52) exactly as the document states them."""
    if not published(doc):
        return ""
    assert doc is not None
    loc = ctx.loc
    rows = "".join(f'<tr><td>{loc.tech(p["name"])}</td><td>{loc.tech(p["value"])}</td><td>{loc.tech(p["decision_id"] or "—")}</td></tr>'
                   for p in doc["parameters"]["parameters"])
    scope = finding_scope(doc)
    counts = [(loc.t("ui.iv2.rules.published"), loc.num(len(doc["findings"]))),
              (loc.t("ui.iv2.rules.scope"), loc.t("ui.iv2.rules.scope_value", **{key: loc.num(len(scope[key])) for key in ("top", "listed", "grouped")})),
              (loc.t("ui.iv2.rules.withheld"), loc.num(sum("weak_evidence_review_only" in r["reasons"] for r in doc["examined_without_finding"]))),
              (loc.t("ui.iv2.rules.not_evaluated"), loc.num(sum("weak_evidence_review_only" not in r["reasons"] for r in doc["examined_without_finding"]))),
              (loc.t("ui.iv2.rules.version"), loc.tech(doc["intelligence_version"])), (loc.t("ui.iv2.rules.mode"), loc.tech(doc["mode"]))]
    parameters = table([loc.t("ui.iv2.rules.parameter"), loc.t("ui.iv2.rules.value"), loc.t("ui.iv2.rules.decision")], rows, "")
    return (f'<div class="card" data-section="intelligence-rules"><h3 style="margin-bottom:12px">{loc.t("ui.iv2.rules.title")}</h3>'
            f'<p class="sm soft">{loc.t("ui.iv2.method")}</p>{dl([(str(k), str(v)) for k, v in counts], "dl")}{parameters}</div>')


def project_template_ids(editors: Sequence[Mapping[str, Any]]) -> set[str]:
    return {project_tid(s["editor_id"], row["monday_item_id"]) for s in editors for row in s["projects"]}

