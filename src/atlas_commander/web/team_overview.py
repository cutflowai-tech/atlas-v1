"""The judgment-first Team overview (redesign T4.2; `after/01-team-desktop.png`, `after/04-team-mobile.png`).

Composed from the Phase 3 components and filled from ``verdicts.json`` only: the team verdict band, the Editors grouped by tier (Best →
Low activity) and ranked inside each tier, and the "What you need to do" rail with the overview decisions (sticky beside the team from
1000 px, above it on narrower screens). Every sentence is a message key of the engine rendered in the page's language (T4.1).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from atlas_commander.i18n import Html
from atlas_commander.interpretation_html import window_line
from atlas_commander.web import verdict_ui as ui
from atlas_commander.web.kit import Ctx


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


def team_overview(verdicts: Mapping[str, Any], ctx: Ctx) -> str:
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
            f'<div class="v-layout"><div class="v-main">{sections or Html("")}</div>{rail(verdicts, ctx)}</div></div>')
