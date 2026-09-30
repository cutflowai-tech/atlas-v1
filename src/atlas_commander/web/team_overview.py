"""The judgment-first Team overview (redesign T4.2; `after/01-team-desktop.png`, `after/04-team-mobile.png`).

Composed from the Phase 3 components and filled from ``verdicts.json`` only: the team verdict band, the Editors grouped by tier (Best →
Low activity) and ranked inside each tier, and the "What you need to do" rail with the overview decisions (sticky beside the team from
1000 px, above it on narrower screens). Every sentence is a message key of the engine rendered in the page's language (T4.1).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from html import escape
from typing import Any

from atlas_commander.i18n import DASH, Html, Loc
from atlas_commander.intelligence import CAIRO
from atlas_commander.interpretation_html import window_line
from atlas_commander.web import intel
from atlas_commander.web import verdict_ui as ui
from atlas_commander.web.kit import Ctx, dl, project_list, template


def _tier_order(verdict: Mapping[str, Any]) -> tuple[int, int, str, str]:
    """Inside a tier: ranked Editors by rank, then the unranked by name (the engine's order, never alphabetical first)."""
    return (0 if verdict["rank"] is not None else 1, verdict["rank"] or 0, verdict["display_name"].casefold(), verdict["editor_id"])


def rail(verdicts: Mapping[str, Any], ctx: Ctx) -> str:
    loc = ctx.loc
    editors = {e["editor_id"]: e for e in verdicts["editors"]}
    cards = "".join(ui.decision_card(d, ui.message(d["title"], loc), editors, loc) for d in verdicts["decisions"])
    more = len(verdicts["decision_candidates"]) - len(verdicts["decisions"])
    extra = f'<p class="v-rail-more">{loc.counted("ui.v.rail.more", more)}</p>' if more > 0 else ""
    body = cards or f'<p class="v-rail-none">{loc.t("ui.v.rail.none")}</p>'
    return (f'<aside class="v-rail" aria-labelledby="v-rail-h"><h2 id="v-rail-h">{loc.t("ui.v.rail.title")}</h2>'
            f'<p class="v-rail-hint">{loc.t("ui.v.rail.hint")}</p><div class="v-rail-list">{body}</div>{extra}</aside>')


def _window_projects(summary: Mapping[str, Any], window: Mapping[str, Any]) -> list[str]:
    """The Editor's projects completed in the current window: first Ready For Approval on a Cairo date inside it (the definition of
    ``coverage.current_projects``, so the list has exactly the count the verdict shows)."""
    start, end = date.fromisoformat(window["start_date"]), date.fromisoformat(window["end_date_exclusive"])
    out = []
    for row in summary["projects"]:
        at = row.get("ready_for_approval_at")
        if row.get("state") == "completed" and at and start <= datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(CAIRO).date() < end:
            out.append(row["monday_item_id"])
    return out


def _methodology(v: Mapping[str, Any], verdicts: Mapping[str, Any], loc: Loc) -> str:
    """How this verdict was reached, in plain words, with the approved numbers (config/verdict-v1.json, D54)."""
    values = verdicts["config"]["values"]
    dims = loc.comma().join(str(loc.t("ui.v.dimension." + d)) for d in v["based_on"]) or DASH
    lines = [window_line({"window": verdicts["windows"]}, loc), loc.t("ui.v.more.based_on", dimensions=Html(dims))]
    if v["rank"] is not None:
        parts = loc.comma().join(f'{loc.t("ui.v.dimension." + k)} {loc.num(_whole(p))}' for k, p in v["score_parts"].items())
        lines.append(loc.t("ui.v.more.score", score=loc.num(_whole(v["score"])), parts=Html(parts), rank=loc.num(v["rank"]), of=loc.num(v["ranked_of"])))
    else:
        lines.append(loc.t("ui.v.more.unranked", minimum=loc.num(_whole(values["score.minimum_completed"]))))
    reasons = [r for r in v["confidence_reasons"] if not r.startswith("missing_") or r == "missing_dimension"]
    why = loc.comma().join(str(loc.t("ui.v.confidence_reason." + r)) for r in reasons) if reasons else str(loc.t("ui.v.confidence_reason.none"))
    lines.append(loc.t("ui.v.more.confidence", level=loc.t("ui.v.confidence." + v["confidence"]), reasons=Html(why)))
    lines.append(loc.t("ui.v.more.tiers", weakest_pp=loc.num(_whole(values["tier.weakest_late_above_team_pp"])),
                       weakest_speed=loc.ltr(f'{_whole(values["tier.weakest_speed_pct"])}%'), watch_pp=loc.num(_whole(values["tier.watch_late_above_team_pp"])),
                       watch_speed=loc.ltr(f'{_whole(values["tier.watch_speed_pct"])}%'), best_share=loc.ltr(f'{_whole(values["tier.best_top_share"] * 100)}%'),
                       low=loc.num(_whole(values["tier.low_activity_below_completed"]))))
    return "".join(f"<p>{line}</p>" for line in lines)


def _whole(value: float) -> int | float:
    return int(value) if float(value).is_integer() else round(value, 1)


def profile_more(v: Mapping[str, Any], summary: Mapping[str, Any] | None, intelligence: Mapping[str, Any] | None, verdicts: Mapping[str, Any],
                 ctx: Ctx) -> str:
    """T4.5: the drawer's More details: methodology in plain words, this Editor's findings without duplicates (each opens its evidence
    drawer), the evidence list, the full analysis, and the raw identifiers under a nested Technical details."""
    loc, eid = ctx.loc, v["editor_id"]
    by_id = {f["finding_id"]: f for f in (intelligence or {}).get("findings") or []} if intel.published(intelligence) else {}
    duplicates = {row["finding_id"] for row in verdicts["findings"]["hide_from_overview"] if row["reason"] == "duplicate"}
    findings = [by_id[f] for f in v["finding_ids"] if f in by_id and f not in duplicates]
    finding_rows = "".join(f'<li><button type="button" class="v-link" data-drawer="{escape(intel.tid(f), quote=True)}">'
                           f'{intel.marked_html(intel.finding_title(f, loc), loc.isolate)}</button></li>' for f in findings)
    evidence = [(f"c-{eid}-deadline", loc.t("ui.v.more.evidence_deadline")), (f"c-{eid}-speed", loc.t("ui.v.more.evidence_speed")),
                (f"vp-{eid}-projects", loc.t("ui.v.more.evidence_projects")), (f"c-{eid}-quality", loc.t("ui.v.more.evidence_quality"))] if summary else []
    evidence_rows = "".join(f'<li><button type="button" class="v-link" data-drawer="{escape(t, quote=True)}">{label}</button></li>' for t, label in evidence)
    hidden = [row for row in verdicts["findings"]["hide_from_overview"] if row["editor_id"] == eid]
    decisions = [d for d in verdicts["decision_candidates"] if eid in d["owner_editor_ids"]]
    technical = dl([(str(loc.t("ui.v.more.tech_editor")), str(loc.tech(eid))),
                    (str(loc.t("ui.v.more.tech_version")), f'{loc.tech(verdicts["verdict_version"])} · {loc.tech(verdicts["config"]["version"])} · {loc.tech(verdicts["config"]["decision_id"])}'),
                    (str(loc.t("ui.v.more.tech_findings")), " ".join(str(loc.tech(f)) for f in v["finding_ids"]) or DASH),
                    (str(loc.t("ui.v.more.tech_hidden")), " ".join(f'{loc.tech(r["finding_id"])} ({loc.tech(r["reason"])})' for r in hidden) or DASH),
                    (str(loc.t("ui.v.more.tech_decisions")), " ".join(str(loc.tech(d["id"])) for d in decisions) or DASH)])
    none = loc.t("ui.v.more.no_findings")
    return (f'<section class="v-more-s"><h4>{loc.t("ui.v.more.method")}</h4>{_methodology(v, verdicts, loc)}</section>'
            f'<section class="v-more-s"><h4>{loc.t("ui.v.more.findings")}</h4>'
            f'{f"<ul>{finding_rows}</ul>" if finding_rows else f"<p>{none}</p>"}</section>'
            f'<section class="v-more-s"><h4>{loc.t("ui.v.more.evidence")}</h4><ul>{evidence_rows}</ul>'
            f'<p><a class="v-prof-full" href="#/profile/{escape(eid, quote=True)}">{loc.t("ui.v.profile.full")}</a></p></section>'
            f'<details class="v-tech"><summary>{loc.t("ui.v.more.technical")}</summary>{technical}</details>')


def profile_templates(verdicts: Mapping[str, Any], ctx: Ctx, dashboard: Mapping[str, Any] | None = None,
                      intelligence: Mapping[str, Any] | None = None) -> str:
    """One drawer per Editor (T4.4), opened by the route ``#/editor/<id>``, with its More details (T4.5) and the list of the window's
    projects behind "Projects this month"."""
    loc = ctx.loc
    pending = any(d["type"] == "approve_rule" and d["title"]["params"].get("dimension") == "quality" for d in verdicts["decision_candidates"])
    summaries = {s["editor_id"]: s for s in (dashboard or {}).get("editors") or []}
    risk = next((f for f in (intelligence or {}).get("findings") or [] if f["finding_type"] == "risk.open_work"), None) if intel.published(intelligence) else None
    out = []
    for v in verdicts["editors"]:
        eid, summary = v["editor_id"], summaries.get(v["editor_id"])
        evidence = {"late": f"c-{eid}-deadline", "speed": f"c-{eid}-speed", "projects": f"vp-{eid}-projects", "quality": f"c-{eid}-quality"} if summary else {}
        if risk is not None:
            evidence["overdue"] = intel.tid(risk)
        more = profile_more(v, summary, intelligence, verdicts, ctx)
        out.append(f'<template id="vp-{escape(eid, quote=True)}">{ui.profile_panel(v, loc, quality_rule_pending=pending, more=more, evidence=evidence)}</template>')
        if summary:
            ids = _window_projects(summary, verdicts["windows"]["current"])
            out.append(template(f"vp-{eid}-projects", loc.text("ui.v.more.projects_title", name=v["display_name"]), project_list(summary, ctx, ids)))
    return "".join(out)


def team_overview(verdicts: Mapping[str, Any], ctx: Ctx, dashboard: Mapping[str, Any] | None = None,
                  intelligence: Mapping[str, Any] | None = None) -> str:
    """The redesigned first layer of the Editors page."""
    loc = ctx.loc
    team = verdicts["team"]
    band = ui.verdict_band(ui.message(team["headline"], loc), ui.message(team["supporting"], loc),
                           [(k, ui.message(k["label"], loc)) for k in team["kpis"]], loc)
    window = f'<p class="v-window">{window_line({"window": verdicts["windows"]}, loc)}</p>'
    by_tier: dict[str, list[Mapping[str, Any]]] = {tier: [] for tier in ui.TIERS}
    for verdict in verdicts["editors"]:
        by_tier[verdict["tier"]].append(verdict)
    sections = "".join(ui.tier_section(tier, [ui.person_card(v, ui.message(v["headline"], loc), loc) for v in sorted(by_tier[tier], key=_tier_order)], loc)
                       for tier in ui.TIERS)
    return (f'<div class="v-page" data-verdict-version="{verdicts["verdict_version"]}">{band}{window}'
            f'<div class="v-layout"><div class="v-main">{sections or Html("")}</div>{rail(verdicts, ctx)}</div>{profile_templates(verdicts, ctx, dashboard, intelligence)}</div>')
