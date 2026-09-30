"""The contract 1.5 Atlas app: Editors → Editor Profile → Evidence, in English or Arabic (presentation only).

Information architecture (HANDOFF-V2 §12, §13, §26):

- **Editors** (``#/``): one scannable card per Editor with the Overall Status, the three component states with one fact each, the
  most frequent positive and issue label, and the sample behind it. Search and a status *filter* (never a ranking); cards are in
  alphabetical order. Team context (timeline, labels, current work, monthly history) sits below, secondary.
- **Editor Profile** (``#/editor/<id>``): summary first (status, why, key figures), then what changed, signals, Quality, Speed,
  Deadlines, Revisions (context), Current work, History and finally Data & evidence. A sticky section bar replaces tabs, so
  nothing is hidden behind a click.
- **Evidence**: every claim has a link that opens its Monday evidence in a drawer; the complete engine report is one click away.
- **Data & rules** (``#/system``): freshness, rules and their approval state, identities, coverage and exclusions.

Rendered from the dashboard document only; the view never computes a metric, comparison or conclusion.
"""

from __future__ import annotations

import calendar
import json
from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from html import escape
from typing import Any

from atlas_commander.dashboard_html import _dedupe_templates, operational_status, pending_label, warning_text
from atlas_commander.i18n import Html, Loc
from atlas_commander.intelligence import CAIRO
from atlas_commander.interpretation_html import window_line
from atlas_commander.management import PENDING_RULES, V15_PENDING_SLOTS, V15_REASONS
from atlas_commander.web import intel
from atlas_commander.web.kit import (
    CLASSIFIED,
    RESULTS,
    VERDICTS,
    Ctx,
    attr,
    avatar,
    code_text,
    component_name,
    deadline_key,
    deadline_stack,
    dl,
    icon,
    item_link,
    meter,
    open_link,
    overall_pill,
    project_list,
    project_templates,
    reason_span,
    section_head,
    stat,
    state_chip,
    status_key,
    table,
    template,
    verdict_chip,
)
from atlas_commander.web.style import CSS, SCRIPT

COMPONENTS = ("quality", "speed", "deadline")
LABEL_CLASSES = ("negative", "positive", "context")
PROFILE_SECTIONS = ("summary", "change", "signals", "quality", "speed", "deadlines", "revisions", "work", "history", "evidence")


# ---------------------------------------------------------------- formatting helpers (presentation only)

def _last_day(value: Mapping[str, Any]) -> str:
    return (date.fromisoformat(value["end_date_exclusive"]) - timedelta(days=1)).isoformat()


def window_range(view: Mapping[str, Any], loc: Loc, which: str = "current") -> Html:
    w = view["window"][which]
    return Html(f'{loc.when(w["start_date"], False)} – {loc.when(_last_day(w), False)}')


def _primary_speed(view: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The first Video Type with a classified verdict, else the first one (display order of the profile, largest sample first)."""
    rows = view["components"]["speed"]["video_types"]
    return next((row for row in rows if row["verdict"] != "not_classifiable"), rows[0] if rows else None)


def _top_label(s: Mapping[str, Any], label_class: str) -> Mapping[str, Any] | None:
    block = s["quality"].get(label_class) or {}
    rows = block.get("by_label") or []
    return rows[0] if rows else None


def _speed_fact(row: Mapping[str, Any] | None, loc: Loc) -> Html:
    if row is None:
        return loc.t("speed.none_comparable")
    if row["comparator_projects"]:
        return loc.t("ui.speed.fact", labels=loc.labels(row["cohort_labels"]), editor=loc.hours(row["editor_median_seconds"]),
                     others=loc.hours(row["comparator_median_seconds"]), n=loc.num(row["editor_projects"]))
    return loc.t("ui.speed.fact_alone", labels=loc.labels(row["cohort_labels"]), editor=loc.hours(row["editor_median_seconds"]),
                 n=loc.num(row["editor_projects"]))


def _deadline_fact(facts: Mapping[str, Any], loc: Loc) -> Html:
    if not facts.get("deadline_classifiable_projects"):
        return loc.t("deadline.unavailable")
    return loc.t("ui.deadline.fact", rate=loc.pct(facts["absolute_late_rate"]), late=loc.num(facts["late"]), n=loc.num(facts["deadline_classifiable_projects"]))


def _quality_fact(facts: Mapping[str, Any], loc: Loc) -> Html:
    return loc.t("ui.quality.fact", nrate=loc.pct(facts["negative_rate"]), prate=loc.pct(facts["positive_rate"]), n=loc.num(facts["eligible_completed_projects"]))


# ---------------------------------------------------------------- Editors overview

def editor_card(s: Mapping[str, Any], ctx: Ctx) -> str:
    loc, view = ctx.loc, s["interpretation"]
    overall, components = view["overall"], view["components"]
    rows = [
        ("quality", _quality_fact(components["quality"]["facts"], loc)),
        ("speed", _speed_fact(_primary_speed(view), loc)),
        ("deadline", _deadline_fact(components["deadline"]["facts"], loc)),
    ]
    comp = "".join(f'<div data-component="{name}"><dt>{component_name(name, loc)}</dt><dd>{state_chip(components[name]["state"], loc)}'
                   f'<span class="fact">{fact}</span></dd></div>' for name, fact in rows)
    positive, negative = _top_label(s, "positive"), _top_label(s, "negative")
    signal = lambda row: (f'{loc.src(row["label"])} <b>{loc.t("common.times", n=loc.num(row["occurrences"]))}</b>' if row
                          else f'<span class="muted">{loc.t("common.no_signal")}</span>')
    trend = next((change for change in view["recent_change"] if change["trend"]), None)
    trend_row = (f'<div><span class="k">{loc.t("interp.recent.head.trend")}</span><span>{loc.t("interp.trend." + trend["trend"])} · '
                 f'{loc.t("interp.measure." + trend["measurement"])}</span></div>' if trend else "")
    workload = s["current_workload"]
    search = " ".join([s["display_name"], s["editor_id"], str(s["monday_label"])]).casefold()
    return (f'<article class="ed" data-editor-card data-status="{status_key(overall)}" data-search="{attr(search)}">'
            f'<div class="ed-h">{avatar(s["display_name"])}<div><h3><a href="#/editor/{escape(s["editor_id"])}">{loc.src(s["display_name"])}</a></h3>'
            f'<div class="sub">{loc.t("ui.card.sample", n=loc.count("noun.project", view["coverage"]["current_projects"]), active=loc.num(workload.get("active_work_count", 0)))}</div></div></div>'
            f'{overall_pill(overall, loc)}'
            f'<dl class="comp">{comp}</dl>'
            f'<div class="sig"><div><span class="k">{loc.t("card.positive")}</span><span>{signal(positive)}</span></div>'
            f'<div><span class="k">{loc.t("common.issue_signals")}</span><span>{signal(negative)}</span></div>{trend_row}</div>'
            f'<div class="ed-f"><span>{loc.count("noun.completed_project", s["sample"]["completed_projects"])} · {loc.t("interp.all_history")}</span>'
            f'<span>{loc.t("card.view_profile")} {icon("arrow", 13)}</span></div></article>')


def overview(doc: Mapping[str, Any], ctx: Ctx, month: str | None, intelligence: Mapping[str, Any] | None = None) -> str:
    loc = ctx.loc
    editors = sorted(doc["editors"], key=lambda s: (s["display_name"].casefold(), s["editor_id"]))   # alphabetical: never a ranking
    counts = Counter(status_key(s["interpretation"]["overall"]) for s in editors)
    filters = [("all", loc.t("ui.filter.all"), len(editors))] + [
        (key, loc.t("interp.status." + key), counts[key]) for key in CLASSIFIED if counts[key]] + (
        [("none", loc.t("ui.filter.none"), counts["none"])] if counts["none"] else [])
    chips = "".join(f'<button type="button" class="filter {key}" data-filter="{key}" aria-pressed="{"true" if key == "all" else "false"}">'
                    f'{"" if key == "all" else "<i></i>"}{label} <span class="n">{loc.num(n)}</span></button>' for key, label, n in filters)
    first = editors[0]["interpretation"] if editors else None
    window = f'<p>{window_line(first, loc)}</p>' if first else ""
    cards = "".join(editor_card(s, ctx) for s in editors)
    grid = (f'<div class="cards">{cards}</div><div class="nomatch" id="no-match" hidden>{loc.t("ui.no_match")}</div>' if editors
            else f'<div class="nomatch">{loc.t("home.no_editors")}</div>')
    tools = (f'<div class="tools"><label class="search">{icon("search", 16)}<span class="sr">{loc.t("ui.search_label")}</span>'
             f'<input id="editor-search" type="search" autocomplete="off" placeholder="{attr(loc.text("ui.search_placeholder"))}"></label>'
             f'<div class="filters" role="group" aria-label="{attr(loc.text("ui.filter_label"))}">{chips}</div></div>') if editors else ""
    return (f'<div data-view="team"><div class="ph"><div><h1>{loc.t("ui.nav.editors")}</h1>{window}</div></div>'
            f'<p class="note" style="margin:-8px 0 18px">{loc.t("ui.overview_note")}</p>'
            f'{intel.overview_section(intelligence, ctx)}{tools}{grid}{team_context(doc, ctx, month)}</div>')


# ---------------------------------------------------------------- team context (secondary)

def team_context(doc: Mapping[str, Any], ctx: Ctx, month: str | None) -> str:
    loc = ctx.loc
    editors = sorted(doc["editors"], key=lambda s: (s["display_name"].casefold(), s["editor_id"]))
    tabs = [("pulse", loc.t("home.pulse_title"), f'<p class="note" style="margin:0 0 12px">{loc.t("home.pulse_sub")}</p>'
             + timeline(editors, doc["source"].get("retrieved_at"), "pulse", True, ctx)),
            ("labels", loc.t("ui.team.labels"), label_activity(editors, month, loc)),
            ("work", loc.t("common.current_work"), team_workload(editors, loc)),
            ("history", loc.t("home.history_title"), team_history(editors, loc))]
    buttons = "".join(f'<button type="button" role="tab" data-tab="team-{key}" aria-selected="{"true" if i == 0 else "false"}">{label}</button>'
                      for i, (key, label, _) in enumerate(tabs))
    panels = "".join(f'<div id="team-{key}" role="tabpanel"{"" if i == 0 else " hidden"}>{body}</div>' for i, (key, _, body) in enumerate(tabs))
    return (f'<section class="sec" aria-labelledby="team-h">{section_head(f"<span id=team-h>{loc.t("home.context_label")}</span>", loc.t("ui.team.sub"))}'
            f'<div class="seg" role="tablist" data-tabs>{buttons}</div><div class="card">{panels}</div></section>')


def label_activity(editors: list[Mapping[str, Any]], month: str | None, loc: Loc) -> str:
    kinds = {"issue_label": "negative", "positive_label": "positive", "context_label": "context"}
    counts: dict[str, dict[str, Counter[str]]] = {name: {} for name in LABEL_CLASSES}
    for s in editors:
        for event in s["events"]:
            if event["kind"] in kinds and month and _event_month(event) == month:
                counts[kinds[event["kind"]]].setdefault(event["label"], Counter())[s["display_name"]] += 1
    style = {"negative": "neg", "positive": "pos", "context": "ctx"}
    title = {"negative": "common.issue_signals", "positive": "quality.positive_title", "context": "quality.context_title"}
    blocks = []
    for name in LABEL_CLASSES:
        rows = "".join(f'<li><span>{loc.src(label)}</span><span class="chips">'
                       + "".join(f'<span class="chip {style[name]}">{loc.src(who)} <b>{loc.t("common.times", n=loc.num(n))}</b></span>'
                                 for who, n in sorted(c.items(), key=lambda p: (-p[1], p[0])))
                       + "</span></li>" for label, c in sorted(counts[name].items(), key=lambda p: (-sum(p[1].values()), p[0])))
        blocks.append(f'<div><h3 style="margin-bottom:10px">{loc.t(title[name])}</h3><ul class="facts">'
                      f'{rows or f"<li class=empty>{loc.t("ui.none_this_month")}</li>"}</ul></div>')
    period = escape(loc.month(month)) if month else loc.t("activity.this_period")
    return (f'<p class="note" style="margin:0 0 14px">{loc.t("ui.team.labels_sub", period=Html(period))}</p><div class="grid3">{"".join(blocks)}</div>'
            f'<p class="note">{loc.t("activity.footer")}</p>')


def workload_chips(w: Mapping[str, Any], loc: Loc) -> str:
    items = list(w["by_current_status"].items())
    if not items:
        return f'<span class="muted">{loc.t("workload.none")}</span>'
    return '<div class="chips">' + "".join(f'<span class="chip"><b>{loc.num(n)}</b> {loc.src(status)}</span>' for status, n in items) + "</div>"


def team_workload(editors: list[Mapping[str, Any]], loc: Loc) -> str:
    rows = "".join(f'<tr><td><bdi>{escape(s["display_name"])}</bdi></td><td>{loc.num(s["current_workload"].get("active_work_count"))}</td>'
                   f'<td>{loc.num(s["current_workload"].get("awaiting_approval_count"))}</td><td>{workload_chips(s["current_workload"], loc)}</td></tr>'
                   for s in editors)
    return (table([loc.t("common.editor"), loc.t("workload.active_work"), loc.t("workload.awaiting_approval"), loc.t("workload.sub")], rows,
                  f'<tr><td colspan=4>{loc.t("common.none")}</td></tr>')
            + f'<p class="note">{loc.t("workload.footer")}</p>')


def team_history(editors: list[Mapping[str, Any]], loc: Loc) -> str:
    months = sorted({m["month"] for s in editors for m in s["monthly"]}, reverse=True)
    if not months:
        return f'<p class="muted">{loc.t("history.empty")}</p>'
    buttons = "".join(f'<button type="button" role="tab" data-tab="hist-{m}" aria-selected="{"true" if i == 0 else "false"}">{escape(loc.month(m))}</button>'
                      for i, m in enumerate(months))
    panels = []
    for i, m in enumerate(months):
        rows = []
        for s in editors:
            entry = next((x for x in s["monthly"] if x["month"] == m), None)
            if not entry:
                rows.append(f'<tr><td><bdi>{escape(s["display_name"])}</bdi></td><td colspan=2 class="muted">{loc.t("history.no_figures")}</td></tr>')
                continue
            d = entry["deadline"]
            dl_cell = (f'{deadline_stack(d, loc)}<div class="xs soft" style="margin-top:6px">{loc.t("deadline.counts", early=loc.num(d["early"]), on_time=loc.num(d["on_time"]), late=loc.num(d["late"]))}</div>'
                       if d else f'<span class="muted">{loc.t("history.no_deadlines")}</span>')
            speed = "<br>".join(f'{loc.labels(c["labels"], c["cohort_key"])} <b>{loc.hours(c["median_seconds"])}</b> <span class="muted">{loc.t("common.sample_n", n=loc.num(c["projects"]))}</span>'
                                for c in sorted(entry["speed_by_cohort"], key=lambda c: -c["projects"])) or "—"
            rows.append(f'<tr><td><bdi>{escape(s["display_name"])}</bdi></td><td style="min-width:200px">{dl_cell}</td><td>{speed}</td></tr>')
        partial = next((x["partial"] for s in editors for x in s["monthly"] if x["month"] == m), False)
        caption = f'<p class="xs muted" style="margin:0 0 8px">{escape(loc.month(m))}{" · " + loc.t("common.month_in_progress") if partial else ""}</p>'
        panels.append(f'<div id="hist-{m}" role="tabpanel"{"" if i == 0 else " hidden"}>{caption}'
                      + table([loc.t("common.editor"), loc.t("common.deadlines"), loc.t("history.median_duration")], "".join(rows), "") + "</div>")
    return (f'<div class="seg" role="tablist" data-tabs>{buttons}</div>{"".join(panels)}<p class="note">{loc.t("note.trend_v15")}</p>')


# ---------------------------------------------------------------- timeline (team pulse and the Editor's own history)

def _event_month(event: Mapping[str, Any]) -> str:
    return str(event.get("month") or str(event["at"])[:7])


def _position(at: str, month: str) -> float:
    moment = datetime.fromisoformat(at.replace("Z", "+00:00"))
    days = calendar.monthrange(int(month[:4]), int(month[5:]))[1]
    return ((moment.day - 1) + (moment.hour * 3600 + moment.minute * 60 + moment.second) / 86400) / days * 100


def _event_tid(editor_id: str, index: int) -> str:
    return f"e-{editor_id}-{index}"


def _marker(event: Mapping[str, Any], loc: Loc) -> tuple[str, str]:
    kind = event["kind"]
    if kind == "issue_label":
        return "issue", loc.text("timeline.issue_marker", label=event["label"])
    if kind == "positive_label":
        return "positive", loc.text("ui.timeline.positive_marker", label=event["label"])
    if kind == "context_label":
        return "context", loc.text("ui.timeline.context_marker", label=event["label"])
    result = event["deadline_result"]
    return (result, loc.text(f"timeline.delivery.{result}")) if result else ("unclassified", loc.text("timeline.delivery.unclassified"))


def event_templates(s: Mapping[str, Any], ctx: Ctx) -> str:
    loc, out = ctx.loc, []
    for index, event in enumerate(s["events"]):
        if not event["kind"].endswith("_label"):
            continue
        ids = "".join(f"<dd>{loc.tech(v)}</dd>" for v in event["event_ids"])
        out.append(template(_event_tid(s["editor_id"], index), event["label"], dl([
            (loc.t("field.editor"), loc.src(s["display_name"])), (loc.t("field.label_added"), loc.when(event["at"])),
            (loc.t("field.monday_item"), item_link(event["monday_item_id"], ctx)),
            (loc.t("field.source"), loc.tech(event["column_id"]) if "column_id" in event else loc.t("quality.source_column"))])
            + f"<h4>{loc.t('evidence.monday_events')}</h4><dl><dt>{loc.t('common.evidence')}</dt>{ids}</dl>"
            + f'<p><button type="button" class="btn" data-drawer="p-{escape(s["editor_id"])}-{escape(event["monday_item_id"])}">{loc.t("evidence.open_project")}</button></p>'))
    return "".join(out)


def _lane(s: Mapping[str, Any], month: str, retrieved: str | None, show_name: bool, loc: Loc) -> str:
    markers: list[str] = []
    rows_last: dict[int, float] = {}
    for index, event in ((i, e) for i, e in enumerate(s["events"]) if _event_month(e) == month):
        pos = _position(event.get("local_at") or event["at"], month)
        row = 0
        while row in rows_last and pos - rows_last[row] < 1.3:
            row += 1
        rows_last[row] = pos
        cls, label = _marker(event, loc)
        tid = f'p-{s["editor_id"]}-{event["monday_item_id"]}' if event["kind"] == "delivery" else _event_tid(s["editor_id"], index)
        aria = loc.text("timeline.marker_aria", name=s["display_name"], label=label, date=loc.date(event["at"]), item=event["monday_item_id"])
        markers.append(f'<button type="button" class="mk {cls}" style="left:{pos:.2f}%;top:{14 + row * 16}px" data-drawer="{escape(tid)}" '
                       f'aria-label="{attr(aria)}" title="{attr(aria)}"><i></i></button>')
    height = 28 + (max(rows_last) + 1 if rows_last else 1) * 16
    now = f'<span class="now" style="left:{_position(retrieved, month):.2f}%"></span>' if retrieved and retrieved[:7] == month else ""
    name = (f'<div class="ln">{avatar(s["display_name"])}<span>{loc.src(s["display_name"])}</span></div>' if show_name
            else f'<div class="ln"><span class="muted xs">{loc.t("timeline.events")}</span></div>')
    empty = "" if markers else f'<span class="xs muted" style="position:absolute;left:8px;top:10px">{loc.t("timeline.no_events_month")}</span>'
    return f'<div class="lane">{name}<div class="trk" style="height:{height}px">{now}{empty}{"".join(markers)}</div></div>'


def _axis(month: str, retrieved: str | None, loc: Loc) -> str:
    days = calendar.monthrange(int(month[:4]), int(month[5:]))[1]
    ticks = "".join(f'<span style="left:{(day - 1) / days * 100:.2f}%">{loc.t("timeline.tick", month=loc.month_short(month), day=f"{day:02d}")}</span>'
                    for day in (1, 8, 15, 22) if day <= days)
    if retrieved and retrieved[:7] == month:
        ticks += f'<span class="today" style="left:{_position(retrieved, month):.2f}%">{loc.t("timeline.updated")}</span>'
    return f'<div class="axis">{ticks}</div>'


def timeline(summaries: list[Mapping[str, Any]], retrieved: str | None, prefix: str, show_names: bool, ctx: Ctx) -> str:
    loc = ctx.loc
    if retrieved:
        # Events are placed on their Cairo day (D24); the "updated" marker too.
        retrieved = datetime.fromisoformat(retrieved.replace("Z", "+00:00")).astimezone(CAIRO).isoformat()
    months = sorted({_event_month(e) for s in summaries for e in s["events"]}, reverse=True)
    if not months:
        return f'<p class="muted">{loc.t("timeline.no_events")}</p>'
    buttons = "".join(f'<button type="button" role="tab" data-tab="{prefix}-{m}" aria-selected="{"true" if i == 0 else "false"}">{escape(loc.month(m))}</button>'
                      for i, m in enumerate(months))
    panels = "".join(f'<div id="{prefix}-{m}" role="tabpanel"{"" if i == 0 else " hidden"}><div class="tl" dir="ltr"><div class="tl-in">{_axis(m, retrieved, loc)}'
                     f'{"".join(_lane(s, m, retrieved, show_names, loc) for s in summaries)}</div></div></div>' for i, m in enumerate(months))
    legend_items = [("early", loc.t("result.early")), ("on_time", loc.t("result.on_time")), ("late", loc.t("result.late")),
                    ("unclassified", loc.t("common.not_classified")), ("issue", loc.t("timeline.legend_issue")),
                    ("positive", loc.t("ui.timeline.legend_positive")), ("context", loc.t("ui.timeline.legend_context"))]
    legend = ('<div class="legend">' + "".join(f'<span><span class="mk {cls}"><i></i></span> {text}</span>' for cls, text in legend_items)
              + f'<span>{loc.t("timeline.legend_note")}</span><span>{loc.t("timeline.direction_note")}</span></div>')
    return f'<div class="seg" role="tablist" data-tabs>{buttons}</div>{panels}{legend}'


# ---------------------------------------------------------------- Editor Profile

def _sid(eid: str, key: str) -> str:
    return f"s-{eid}-{key}"


def _component_tid(eid: str, name: str) -> str:
    return f"c-{eid}-{name}"


def component_drawers(s: Mapping[str, Any], ctx: Ctx) -> str:
    """One drawer per component: its state and reason, the rule and its approval, and the projects of its evidence."""
    loc, view, eid = ctx.loc, s["interpretation"], s["editor_id"]
    out = []
    for name in COMPONENTS:
        c = view["components"][name]
        ev = c["evidence"]
        rows = [(loc.t("common.status"), state_chip(c["state"], loc) + (" " + reason_span(c["reason"], loc) if c["reason"] else "")),
                (loc.t("ui.rule"), Html(f'{loc.tech(ev["rule_version"])} · {loc.t("interp.state." + c["rule_status"])}')),
                (loc.t("ui.period"), window_range(view, loc)),
                (loc.t("ui.calculated"), loc.when(ev["calculated_at"])),
                (loc.t("common.projects"), loc.num(ev["records"]))]
        out.append(template(_component_tid(eid, name), loc.text("ui.component_drawer_title", component=loc.text("common." + ("deadlines" if name == "deadline" else name)),
                                                                  name=s["display_name"]),
                            f'<p>{loc.t("ui.component_drawer_intro")}</p>' + dl(rows) + f'<h4>{loc.t("common.projects")}</h4>'
                            + project_list(s, ctx, ev["monday_item_ids"])))
    return "".join(out)


def profile_summary(s: Mapping[str, Any], ctx: Ctx, retrieved: str | None) -> str:
    loc, view, eid = ctx.loc, s["interpretation"], s["editor_id"]
    overall, components = view["overall"], view["components"]
    why = "".join(
        f'<li data-component="{escape(row["component"])}"><b>{component_name(row["component"], loc)}</b>'
        + (state_chip(row["state"], loc) if row["component"] != "overall_lookup" else f'<span class="sc">{loc.t("interp.state." + row["state"])}</span>')
        + (reason_span(row["reason"], loc) if row["reason"] and row["reason"] != row["state"] else '<span class="r"></span>')
        + "</li>" for row in overall["why"])
    overall_reason = (f'<span class="soft sm" data-reason="{escape(overall["reason"])}">'
                      f'{code_text(overall["reason"], loc) if overall["reason"] != "not_enough_classifiable_components" else loc.t("interp.reason.not_enough_classifiable_components", min=loc.num(overall["minimum_classifiable_components"]))}</span>'
                      if overall["reason"] else "")
    workload = s["current_workload"]
    primary = _primary_speed(view)
    q, d = components["quality"]["facts"], components["deadline"]["facts"]

    def kpi(key: str, label: Html, value: Html | str, detail: Html | str, state: str) -> str:
        inner = f'<span class="k">{label}{state}</span><span class="v">{value}</span><span class="d">{detail}</span>'
        if ctx.interactive:   # the app routes on the hash, so in-page jumps are buttons; the static report uses plain anchors
            return f'<button type="button" class="kpi" data-jump="{_sid(eid, key)}">{inner}</button>'
        return f'<a class="kpi" href="#{_sid(eid, key)}">{inner}</a>'

    speed_value = loc.pct_value(primary["editor_vs_comparator_pct"], signed=True) if primary and primary["comparator_projects"] else Html("—")
    kpis = (kpi("quality", loc.t("common.quality"), loc.pct(q["negative_rate"]), loc.t("ui.kpi.quality", pos=loc.pct(q["positive_rate"]), n=loc.num(q["eligible_completed_projects"])),
                state_chip(components["quality"]["state"], loc))
            + kpi("speed", loc.t("common.speed"), speed_value, _speed_fact(primary, loc), state_chip(components["speed"]["state"], loc))
            + kpi("deadlines", loc.t("common.deadlines"), loc.pct(d["absolute_late_rate"]),
                  loc.t("ui.kpi.deadline", late=loc.num(d["late"]), n=loc.num(d["deadline_classifiable_projects"]), others=loc.pct(d["comparator_late_rate"])),
                  state_chip(components["deadline"]["state"], loc))
            + kpi("work", loc.t("workload.active_work"), loc.num(workload.get("active_work_count")),
                  loc.t("ui.kpi.work", n=loc.num(workload.get("awaiting_approval_count"))), ""))
    return (f'<section id="{_sid(eid, "summary")}" data-section="interpretation" class="hero">'
            f'<div class="card" data-overall-status="{escape(overall["status"] or "")}" data-status-state="{escape(overall["status_state"])}">'
            f'<div class="who">{avatar(s["display_name"], "xl")}<div><h1>{loc.src(s["display_name"])}</h1>'
            f'<div class="sub">{loc.t("ui.profile.sub", window=window_range(view, loc), cwindow=window_range(view, loc, "comparison"), updated=Html(loc.when(retrieved, False)))}</div></div></div>'
            f'<div class="status-row"><span class="soft sm">{loc.t("interp.section_title")}</span>{overall_pill(overall, loc, True)}{overall_reason}</div>'
            f'<h2 style="font-size:14px;margin-top:14px">{loc.t("interp.why_title")}</h2><ul class="why">{why}</ul>'
            f'<p class="note">{loc.t("interp.no_score")}</p></div>'
            f'<div class="kpis">{kpis}<p class="note" style="grid-column:1/-1;margin:2px 0 0">'
            f'{loc.t("interp.coverage", current=loc.num(view["coverage"]["current_projects"]), comparison=loc.num(view["coverage"]["comparison_projects"]), excluded=loc.num(view["coverage"]["excluded_projects"]))}</p></div>'
            f'</section>')


def _change_value(measurement: str, value: Any, n: int, loc: Loc) -> Html:
    if value is None:
        return Html("—")
    return loc.hours(value) if measurement == "median_speed_seconds" else loc.pct(value)


def profile_change(s: Mapping[str, Any], ctx: Ctx) -> str:
    loc, view, eid = ctx.loc, s["interpretation"], s["editor_id"]
    cards = []
    for change in view["recent_change"]:
        m = change["measurement"]
        name = loc.t("interp.measure." + m)
        if change["cohort_key"]:
            name = Html(f'{name} · {loc.labels(change["cohort_labels"])}')
        difference = change["difference"]
        delta = ("—" if difference is None else loc.hours(difference, signed=True) if m == "median_speed_seconds"
                 else loc.t("interp.pp", value=loc.ltr(f"{difference * 100:+.1f}")))
        trend = (f'<span class="tr">{loc.t("interp.recent.head.trend")}: <b>{loc.t("interp.trend." + change["trend"])}</b></span>' if change["trend"]
                 else f'<span class="tr" data-reason="{escape(change["trend_reason"])}">{code_text(change["trend_reason"], loc)}</span>')
        cards.append(f'<div class="chg" data-measurement="{escape(m)}"><div class="k">{name}<small>{loc.t("interp.direction." + change["direction"])}</small></div>'
                     f'<div class="row"><b>{_change_value(m, change["current"], change["current_sample"], loc)}</b>'
                     f'<span>{loc.t("common.sample_n", n=loc.num(change["current_sample"]))}</span></div>'
                     f'<div class="row"><span>{loc.t("ui.change.was", value=_change_value(m, change["comparison"], change["comparison_sample"], loc), n=loc.num(change["comparison_sample"]))}</span>'
                     f'<span class="delta">{delta}</span></div>{trend}</div>')
    body = f'<div class="change">{"".join(cards)}</div>' if cards else f'<p class="muted">{loc.t("interp.reason.no_value_in_one_window")}</p>'
    sub = loc.t("ui.change.sub", window=window_range(view, loc), cwindow=window_range(view, loc, "comparison"))
    return (f'<section id="{_sid(eid, "change")}" class="sec" data-section="recent-change">{section_head(loc.t("interp.recent_title"), sub)}{body}'
            f'<p class="note">{loc.t("interp.recent_sub")}</p></section>')


def profile_signals(s: Mapping[str, Any], ctx: Ctx) -> str:
    """Supported facts, grouped by direction. These are not Strength / Attention ratings (no threshold is approved for those)."""
    loc, view, eid = ctx.loc, s["interpretation"], s["editor_id"]
    components = view["components"]
    good: list[str] = []
    review: list[str] = []

    def item(text: Html | str, link: str) -> str:
        return f"<li><span>{text}</span>{link}</li>"

    for row in components["speed"]["video_types"]:
        if row["verdict"] in ("faster", "slower"):
            text = loc.t(f"ui.signal.speed_{row['verdict']}", labels=loc.labels(row["cohort_labels"]),
                         pct=loc.pct_value(abs(row["editor_vs_comparator_pct"] or 0)), n=loc.num(row["editor_projects"]))
            (good if row["verdict"] == "faster" else review).append(item(text, open_link(f"cohort-{eid}-{row['cohort_key']}", loc.t("common.evidence"), ctx)))
    deadline = components["deadline"]
    if deadline["state"] in ("positive", "negative"):
        d = deadline["facts"]
        text = loc.t("ui.signal.deadline", relative=loc.t("interp.deadline.relative." + deadline["state"]), rate=loc.pct(d["absolute_late_rate"]),
                     others=loc.pct(d["comparator_late_rate"]))
        (good if deadline["state"] == "positive" else review).append(item(text, open_link(_component_tid(eid, "deadline"), loc.t("common.evidence"), ctx)))
    quality = components["quality"]
    if quality["state"] in ("positive", "negative"):
        (good if quality["state"] == "positive" else review).append(item(
            loc.t("ui.signal.quality_" + quality["state"]), open_link(_component_tid(eid, "quality"), loc.t("common.evidence"), ctx)))
    for name, target in (("positive", good), ("negative", review)):
        for i, row in enumerate((s["quality"].get(name) or {}).get("by_label") or []):
            text = loc.t("ui.signal.label", label=loc.src(row["label"]), n=loc.num(row["occurrences"]),
                         projects=loc.count("noun.project", len(set(row["monday_item_ids"]))))
            target.append(item(text, open_link(f"ql-{eid}-{name}-{i}", loc.t("common.projects"), ctx)))
    empty = f'<li class="empty">{loc.t("common.no_signal")}</li>'
    return (f'<section id="{_sid(eid, "signals")}" class="sec" data-section="signals">{section_head(loc.t("ui.signals.title"), loc.t("ui.signals.sub"))}'
            f'<div class="grid2"><div class="card"><div class="sig-h pos"><i></i><h3>{loc.t("ui.signals.good")}</h3></div><ul class="facts">{"".join(good) or empty}</ul></div>'
            f'<div class="card"><div class="sig-h neg"><i></i><h3>{loc.t("ui.signals.review")}</h3></div><ul class="facts">{"".join(review) or empty}</ul></div></div>'
            f'<p class="note">{loc.t("pending_v15.positive_signals.reason")} {loc.t("pending.needs_attention.reason")}</p></section>')


def _component_header(name: str, title: Html, view: Mapping[str, Any], loc: Loc) -> str:
    c = view["components"][name]
    return (f'<div class="comp-h" data-component="{name}"><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><h3 style="font-size:16px">{title}</h3>'
            f'{state_chip(c["state"], loc)}{reason_span(c["reason"], loc)}</div></div>')


def _evidence_footer(s: Mapping[str, Any], name: str, ctx: Ctx) -> str:
    loc = ctx.loc
    ev = s["interpretation"]["components"][name]["evidence"]
    summary = loc.t("interp.evidence.summary", n=loc.num(ev["records"]), rule=loc.tech(ev["rule_version"]), at=Html(loc.when(ev["calculated_at"])))
    return f'<div class="ev"><span>{summary}</span>{open_link(_component_tid(s["editor_id"], name), loc.t("ui.open_evidence"), ctx)}</div>'


def profile_quality(s: Mapping[str, Any], ctx: Ctx) -> str:
    loc, view, eid = ctx.loc, s["interpretation"], s["editor_id"]
    c = view["components"]["quality"]
    f = c["facts"]
    q = s["quality"]
    stats = (stat(loc.pct(f["negative_rate"]), loc.t("ui.quality.negative_rate", n=loc.num(f["negative_count"]), total=loc.num(f["eligible_completed_projects"])))
             + stat(loc.pct(f["positive_rate"]), loc.t("ui.quality.positive_rate", n=loc.num(f["positive_count"]), total=loc.num(f["eligible_completed_projects"])))
             + stat(loc.num(q["projects_with_issues"]), loc.t("quality.affected", affected=loc.num(q["projects_with_issues"]), total=loc.num(q["completed_projects_attributed"]))))
    excluded = ""
    if c["scoring_exclusions"]:
        # One reason is already said by the sentence itself; several are listed with their counts.
        detail = ("" if len(c["scoring_exclusions"]) == 1 else " · " + loc.comma().join(
            f'{code_text(reason, loc)} ({loc.num(n)})' for reason, n in c["scoring_exclusions"].items()))
        excluded = f'<p class="note">{loc.t("interp.quality.excluded", n=loc.num(sum(c["scoring_exclusions"].values())))}{detail}</p>'
    style = {"negative": "neg", "positive": "pos", "context": "ctx"}
    title = {"negative": "common.issue_signals", "positive": "quality.positive_title", "context": "quality.context_title"}
    maximum = max([row["occurrences"] for name in LABEL_CLASSES for row in (q.get(name) or {}).get("by_label") or []] or [0])
    groups = []
    for name in LABEL_CLASSES:
        rows = (q.get(name) or {}).get("by_label") or []
        bars = "".join(f'<div class="bar"><span>{loc.src(row["label"])}</span>{meter(row["occurrences"], maximum, style[name])}'
                       f'<span class="sm"><b>{loc.num(row["occurrences"])}</b> '
                       f'{open_link(f"ql-{eid}-{name}-{i}", loc.count("noun.project", len(set(row["monday_item_ids"]))), ctx) or loc.count("noun.project", len(set(row["monday_item_ids"])))}</span></div>'
                       for i, row in enumerate(rows))
        empty = {"negative": loc.t("quality.none_recorded_sentence"), "positive": loc.t("quality.positive_detail_v15"), "context": loc.t("quality.context_none")}[name]
        groups.append(f'<div><h4 class="sm soft" style="margin:18px 0 10px;font-weight:600">{loc.t(title[name])}</h4>'
                      f'{f"<div class=bars>{bars}</div>" if bars else f"<p class=muted sm>{empty}</p>"}</div>')
    return (f'<section id="{_sid(eid, "quality")}" class="sec">{section_head(loc.t("common.quality"), loc.t("ui.quality.sub"))}'
            f'<div class="card">{_component_header("quality", loc.t("ui.quality.component"), view, loc)}<div class="stats">{stats}</div>{excluded}'
            f'{"".join(groups)}<p class="note">{loc.t("note.positive_v15")}</p>{_evidence_footer(s, "quality", ctx)}</div></section>')


def profile_speed(s: Mapping[str, Any], ctx: Ctx) -> str:
    loc, view, eid = ctx.loc, s["interpretation"], s["editor_id"]
    rows = view["components"]["speed"]["video_types"]
    cohorts = {c["cohort_key"]: c for c in s["speed"]["cohorts"]}
    tally = Counter(row["verdict"] for row in rows)
    tally_html = "".join(f'<span class="vd {v}">{loc.t("interp.verdict." + v)} · {loc.num(tally[v])}</span>' for v in VERDICTS if tally[v])
    out = []
    for row in rows:
        maximum = max(row["editor_median_seconds"] or 0, row["comparator_median_seconds"] or 0)
        me = (f'<div><span>{loc.t("interp.speed.head.editor")}</span>{meter(row["editor_median_seconds"] or 0, maximum)}'
              f'<span class="v">{loc.hours(row["editor_median_seconds"])}</span></div>').replace('class="track "', 'class="track me"')
        team = (f'<div><span>{loc.t("interp.speed.head.comparator")}</span>{meter(row["comparator_median_seconds"] or 0, maximum)}'
                f'<span class="v">{loc.hours(row["comparator_median_seconds"])}</span></div>').replace('class="track "', 'class="track team"')
        sample = loc.t("ui.speed.sample", e=loc.num(row["editor_projects"]), t=loc.num(row["comparator_projects"]), editors=loc.num(row["comparator_editor_count"]))
        cohort = cohorts.get(row["cohort_key"])
        link = open_link(f"cohort-{eid}-{row['cohort_key']}", loc.t("common.projects"), ctx) if cohort else ""
        out.append(f'<div class="vt" data-verdict="{escape(row["verdict"])}"><div class="name">{loc.labels(row["cohort_labels"])}<small>{sample}</small></div>'
                   f'<div class="cmp">{me}{team}</div>'
                   f'<div class="res">{verdict_chip(row["verdict"], loc)}<span class="sm num">{loc.pct_value(row["editor_vs_comparator_pct"], signed=True)}</span>'
                   f'{reason_span(row["reason"], loc)}{link}</div></div>')
    body = "".join(out) or f'<p class="muted">{loc.t("speed.no_measurable")}</p>'
    how = open_link(f"speed-{eid}", loc.t("speed.how_compared"), ctx)
    return (f'<section id="{_sid(eid, "speed")}" class="sec">{section_head(loc.t("speed.panel.title"), loc.t("speed.panel.sub"), how)}'
            f'<div class="card">{_component_header("speed", loc.t("ui.speed.component"), view, loc)}<div class="tally">{tally_html}</div>{body}'
            f'<p class="note">{loc.t("speed.benchmark_is_descriptive")} {loc.t("ui.speed.note")}</p>{_evidence_footer(s, "speed", ctx)}</div></section>')


def profile_deadline(s: Mapping[str, Any], ctx: Ctx) -> str:
    loc, view, eid = ctx.loc, s["interpretation"], s["editor_id"]
    d = s["deadline"]
    f = view["components"]["deadline"]["facts"]
    unclassified = (d.get("not_classifiable_insufficient_eta_precision") or 0) + (d.get("not_classifiable_missing_eta") or 0)
    if d["evaluated"]:
        top = (f'{deadline_stack(d, loc)}{deadline_key(loc)}<div class="stats" style="margin-top:18px">'
               + stat(loc.pct(d.get("early_rate")), loc.t("ui.deadline.early", n=loc.num(d["early"])))
               + stat(loc.pct(d.get("on_time_rate")), loc.t("ui.deadline.on_time", n=loc.num(d["on_time"])))
               + stat(loc.pct(d.get("late_rate")), loc.t("ui.deadline.late", n=loc.num(d["late"])))
               + stat(loc.hours(d.get("median_delta_seconds"), signed=True), loc.t("report.tile.median_margin")) + "</div>")
    else:
        top = f'<p class="muted">{loc.t("deadline.unavailable")} — {loc.t("deadline.unavailable_detail")}</p>'
    relative = loc.text("interp.deadline.relative." + view["components"]["deadline"]["state"])
    dual = (f'<div class="facts" style="margin-top:16px"><li><span><b>{loc.t("interp.deadline.dual", relative=relative, rate=loc.pct(f["absolute_late_rate"]), late=loc.num(f["late"]), n=loc.num(f["deadline_classifiable_projects"]))}</b></span></li>'
            f'<li><span>{loc.t("interp.deadline.comparator", rate=loc.pct(f["comparator_late_rate"]), n=loc.num(f["comparator_projects"]), editors=loc.num(f["comparator_editor_count"]))}</span></li></div>')
    groups = " ".join(open_link(f"dl-{eid}-{r}", loc.t(f"deadline.group.{r}") + Html(f" ({loc.num(d[r])})"), ctx) for r in RESULTS if d.get(r))
    coverage = (f'<p class="sm soft" style="margin:14px 0 0">{loc.t("ui.deadline.unclassified", n=loc.num(unclassified), no_time=loc.num(d.get("not_classifiable_insufficient_eta_precision") or 0), no_eta=loc.num(d.get("not_classifiable_missing_eta") or 0))} '
                f'{open_link(f"dq-{eid}", loc.t("deadline.coverage_button"), ctx)}</p>' if unclassified else "")
    return (f'<section id="{_sid(eid, "deadlines")}" class="sec">{section_head(loc.t("deadline.panel_title"), loc.t("deadline.panel_sub"))}'
            f'<div class="card">{_component_header("deadline", loc.t("ui.deadline.component"), view, loc)}{top}{dual}'
            f'<div class="chips" style="margin-top:14px;gap:14px">{groups}</div>{coverage}'
            f'<p class="note">{loc.t("interp.deadline.absolute_note")} {loc.t("deadline.negative_note")}</p>{_evidence_footer(s, "deadline", ctx)}</div></section>')


def profile_revisions(s: Mapping[str, Any], ctx: Ctx) -> str:
    loc, eid = ctx.loc, s["editor_id"]
    r = s["revisions"]
    stats = (stat(loc.num(r["client_revision_events"]), loc.t("revisions.client_events"))
             + stat(loc.num(r["internal_revision_events"]), loc.t("revisions.internal_events"))
             + stat(loc.num(r["projects_with_client_revisions"]), loc.t("ui.revisions.projects", total=loc.num(r["completed_projects"])))
             + stat(loc.pct(r.get("client_revision_rate")), loc.t("report.tile.revision_rate")))
    link = open_link(f"rv-{eid}", loc.t("revisions.projects_with"), ctx) if r["monday_item_ids_with_client_revisions"] else ""
    return (f'<section id="{_sid(eid, "revisions")}" class="sec" data-section="revisions">{section_head(loc.t("revisions.context_heading"), loc.t("revisions.disclaimer"))}'
            f'<div class="card"><div class="stats">{stats}</div><div style="margin-top:14px">{link}</div><p class="note">{loc.t("note.revisions")}</p></div></section>')


def profile_work(s: Mapping[str, Any], ctx: Ctx) -> str:
    loc, eid = ctx.loc, s["editor_id"]
    w = s["current_workload"]
    stats = stat(loc.num(w.get("active_work_count")), loc.t("workload.active_work")) + stat(loc.num(w.get("awaiting_approval_count")), loc.t("workload.awaiting_approval"))
    return (f'<section id="{_sid(eid, "work")}" class="sec">{section_head(loc.t("common.current_work"), loc.t("ui.work.sub", date=Html(loc.when(w["as_of"]))))}'
            f'<div class="card"><div class="stats">{stats}</div><div style="margin-top:14px">{workload_chips(w, loc)}</div>'
            f'<p class="note">{loc.t("note.workload_v15")}</p></div></section>')


def profile_history(s: Mapping[str, Any], ctx: Ctx, retrieved: str | None) -> str:
    loc, eid = ctx.loc, s["editor_id"]
    months = []
    for m in s["monthly"]:
        d = m["deadline"]
        deadline = (f'{deadline_stack(d, loc)}<div class="xs soft" style="margin-top:6px">{loc.t("deadline.counts", early=loc.num(d["early"]), on_time=loc.num(d["on_time"]), late=loc.num(d["late"]))} · '
                    f'{loc.t("deadline.late_rate", pct=loc.pct(d["late_rate"]))}</div>' if d else f'<span class="muted">{loc.t("history.no_deadlines")}</span>')
        speed = "<br>".join(f'{loc.labels(c["labels"], c["cohort_key"])} <b>{loc.hours(c["median_seconds"])}</b> <span class="muted">{loc.t("common.sample_n", n=loc.num(c["projects"]))}</span>'
                            for c in sorted(m["speed_by_cohort"], key=lambda c: -c["projects"])) or "—"
        months.append(f'<tr><td>{escape(loc.month(m["month"]))}{" · " + loc.t("common.month_in_progress") if m["partial"] else ""}</td>'
                      f'<td style="min-width:220px">{deadline}</td><td>{speed}</td></tr>')
    monthly = table([loc.t("report.head.month"), loc.t("common.deadlines"), loc.t("history.median_duration")], "".join(months),
                    f'<tr><td colspan=3>{loc.t("history.empty")}</td></tr>')
    return (f'<section id="{_sid(eid, "history")}" class="sec">{section_head(loc.t("ui.history.title"), loc.t("interp.history_scope"))}'
            + (f'<div class="card"><h3 style="margin-bottom:12px">{loc.t("profile.timeline_title")}</h3>{timeline([s], retrieved, f"pt-{eid}", False, ctx)}</div>'
               if ctx.interactive else "")
            + f'<div class="card"><h3 style="margin-bottom:12px">{loc.t("common.by_month")}</h3>{monthly}<p class="note">{loc.t("note.trend_v15")}</p></div></section>')


def profile_evidence(s: Mapping[str, Any], ctx: Ctx) -> str:
    loc, view, eid = ctx.loc, s["interpretation"], s["editor_id"]
    cov = view["coverage"]
    sample = s["sample"]
    stats = (stat(loc.num(sample["completed_projects"]), loc.t("coverage.completed")) + stat(loc.num(sample["open_projects"]), loc.t("coverage.open"))
             + stat(loc.num(sample["speed_eligible_projects"]), loc.t("coverage.measurable"))
             + stat(loc.num(cov["excluded_projects"]), loc.t("ui.evidence.excluded_window")))
    reasons = dict(sample["exclusions_by_reason"])
    for code, count in cov["exclusion_reasons"].items():   # window-only reasons that the history-wide list does not already name
        reasons.setdefault(code, count)
    reason_rows = "".join(f"<li><span>{code_text(r, loc)}</span><b>{loc.num(n)}</b></li>" for r, n in reasons.items())
    notes = "".join(f"<li><span>{warning_text(w, loc)}</span></li>" for w in s["warnings"])
    report = (f'<button type="button" class="btn" data-drawer="report-{escape(eid)}">{icon("doc", 14)} {loc.t("profile.report_button")}</button>' if ctx.interactive else "")
    return (f'<section id="{_sid(eid, "evidence")}" class="sec">{section_head(loc.t("ui.evidence.title"), loc.t("profile.evidence_sub", name=loc.src(s["display_name"])) + Html(" ") + loc.t("profile.evidence_select"), report)}'
            f'<div class="grid2"><div class="card"><h3 style="margin-bottom:12px">{loc.t("ui.evidence.coverage")}</h3><div class="stats">{stats}</div>'
            f'<h4 class="sm soft" style="margin:16px 0 8px">{loc.t("coverage.excluded")}</h4><ul class="facts">{reason_rows or f"<li class=empty>{loc.t("common.none")}</li>"}</ul>'
            f'<p class="note">{loc.t("note.not_attributed")}</p></div>'
            f'<div class="card"><h3 style="margin-bottom:12px">{loc.t("deadline.data_notes")}</h3><ul class="facts">{notes or f"<li class=empty>{loc.t("common.none")}</li>"}</ul></div></div>'
            f'<div class="card" style="margin-top:12px;padding:8px">{project_list(s, ctx)}</div></section>')


def _drawers(s: Mapping[str, Any], ctx: Ctx) -> str:
    loc, eid, name = ctx.loc, s["editor_id"], s["display_name"]
    out = [project_templates(s, ctx), event_templates(s, ctx), component_drawers(s, ctx)]
    speed = s["speed"]
    intro = loc.t("speed.drawer_intro", stat=loc.t("stat." + speed["benchmark_statistic"]), min=loc.num(speed["minimum_editor_sample_size"]),
                  min_projects=loc.count("noun.project", speed["minimum_editor_sample_size"])) if speed.get("minimum_editor_sample_size") else loc.t("common.not_evaluated")
    rule = view_rule_values(s)
    out.append(template(f"speed-{eid}", loc.text("speed.drawer_title", name=name), f"<p>{intro}</p>{rule}<p>{loc.t('speed.benchmark_is_descriptive')}</p>"))
    for c in speed["cohorts"]:
        rng = c.get("team_typical_range_seconds") or {}
        out.append(template(f"cohort-{eid}-{c['cohort_key']}", " + ".join(c["labels"]) or "—", dl([
            (loc.t("common.editor_median"), loc.t("speed.editor_value", median=loc.hours(c["editor_median_seconds"]), n=loc.num(c["editor_sample_size"]))),
            (loc.t("interp.speed.head.comparator"), loc.hours(c["team_median_seconds"])),
            (loc.t("speed.typical_range"), Html(f'{loc.hours(rng.get("p25"))} – {loc.hours(rng.get("p75"))}') if rng else Html("—")),
            (loc.t("common.status"), code_text(c["comparison_status"], loc))])
            + f'<p class="xs muted">{loc.t("speed.benchmark_is_descriptive")}</p><h4>{loc.t("common.projects")}</h4>' + project_list(s, ctx, c["editor_project_ids"])))
    d = s["deadline"]
    notes = "".join(f"<li>{warning_text(w, loc)}</li>" for w in s["warnings"])
    out.append(template(f"dq-{eid}", loc.text("deadline.drawer_title", name=name), f'<p>{loc.t("deadline.drawer_intro")}</p>' + dl([
        (loc.t("deadline.classified"), loc.num(d["evaluated"])), (loc.t("deadline.eta_without_time"), loc.num(d.get("not_classifiable_insufficient_eta_precision") or 0)),
        (loc.t("deadline.no_eta"), loc.num(d.get("not_classifiable_missing_eta") or 0)), (loc.t("deadline.other_reasons"), loc.num(d.get("not_evaluated_other") or 0))])
        + (f"<h4>{loc.t('deadline.data_notes')}</h4><ul>{notes}</ul>" if notes else "")))
    for r in RESULTS:
        out.append(template(f"dl-{eid}-{r}", loc.text(f"deadline.group_title.{r}", name=name),
                            project_list(s, ctx, [row["monday_item_id"] for row in s["projects"] if row["deadline_result"] == r])))
    for label_class in ("positive", "negative"):
        for i, row in enumerate((s["quality"].get(label_class) or {}).get("by_label") or []):
            out.append(template(f"ql-{eid}-{label_class}-{i}", f"{row['label']} · {name}", project_list(s, ctx, row["monday_item_ids"])))
    for i, row in enumerate((s["quality"].get("context") or {}).get("by_label") or []):
        out.append(template(f"ql-{eid}-context-{i}", f"{row['label']} · {name}", project_list(s, ctx, row["monday_item_ids"])))
    out.append(template(f"rv-{eid}", loc.text("revisions.drawer_title", name=name),
                        f'<p>{loc.t("revisions.drawer_intro")} {loc.t("revisions.disclaimer")}</p>' + project_list(s, ctx, s["revisions"]["monday_item_ids_with_client_revisions"])))
    out.append(template(f"report-{eid}", loc.text("profile.report_title", name=name),
                        f'<p>{loc.t("profile.report_intro")}</p><iframe title="{attr(loc.text("profile.report_button"))}" data-report="{escape(eid)}"></iframe>'))
    return "".join(out)


def view_rule_values(s: Mapping[str, Any]) -> str:
    """The speed rule values exactly as the profile states them (technical, shown as code)."""
    component = s["speed"].get("component") or {}
    values = (component.get("rule") or {}).get("values") or {}
    if not values:
        return ""
    return "<ul>" + "".join(f"<li>{Html(f'<code dir=ltr>{escape(str(k))}</code>')}: {Html(f'<code dir=ltr>{escape(str(v))}</code>')}</li>" for k, v in values.items()) + "</ul>"


def profile_sections(with_intelligence: bool) -> tuple[str, ...]:
    """The profile order (HANDOFF-V2 §13); Intelligence findings follow the signals when a published document exists."""
    if not with_intelligence:
        return PROFILE_SECTIONS
    at = PROFILE_SECTIONS.index("signals") + 1
    return (*PROFILE_SECTIONS[:at], "intelligence", *PROFILE_SECTIONS[at:])


def section_bar(eid: str, labels: Mapping[str, Html], ctx: Ctx, sections: tuple[str, ...] = PROFILE_SECTIONS) -> str:
    if ctx.interactive:
        return "".join(f'<button type="button" data-jump="{_sid(eid, key)}" aria-current="{"true" if key == "summary" else "false"}">{labels[key]}</button>'
                       for key in sections)
    return "".join(f'<a href="#{_sid(eid, key)}">{labels[key]}</a>' for key in sections)


def profile_labels(loc: Loc) -> dict[str, Html]:
    return {"summary": loc.t("tab.overview"), "change": loc.t("ui.change.short"), "signals": loc.t("ui.signals.short"), "quality": loc.t("tab.quality"),
            "speed": loc.t("tab.speed"), "deadlines": loc.t("tab.deadlines"), "revisions": loc.t("tab.revisions"), "work": loc.t("common.current_work"),
            "history": loc.t("ui.history.short"), "evidence": loc.t("tab.evidence"), "intelligence": loc.t("ui.iv2.short")}


def editor_profile(s: Mapping[str, Any], retrieved: str | None, ctx: Ctx, intelligence: Mapping[str, Any] | None = None) -> str:
    loc, eid = ctx.loc, s["editor_id"]
    labels = profile_labels(loc)
    jump = section_bar(eid, labels, ctx, profile_sections(intel.published(intelligence)))
    body = (profile_summary(s, ctx, retrieved)
            + f'<nav class="jump" aria-label="{attr(loc.text("ui.sections_label"))}">{jump}</nav>'
            + profile_change(s, ctx) + profile_signals(s, ctx) + intel.editor_section(intelligence, eid, _sid(eid, "intelligence"), ctx)
            + profile_quality(s, ctx) + profile_speed(s, ctx) + profile_deadline(s, ctx)
            + profile_revisions(s, ctx) + profile_work(s, ctx) + profile_history(s, ctx, retrieved) + profile_evidence(s, ctx))
    return (f'<div data-view="editor:{escape(eid)}" hidden><a class="back" href="#/">{icon("back", 15)} {loc.t("ui.back")}</a>{body}{_drawers(s, ctx)}</div>')


# ---------------------------------------------------------------- Data & rules

def data_rules(doc: Mapping[str, Any], ctx: Ctx, status_snapshot: Mapping[str, Any] | None, intelligence: Mapping[str, Any] | None = None) -> str:
    loc = ctx.loc
    source = doc["source"]
    window = source.get("activity_log_window") or {}
    publication = doc.get("publication") or {}
    snapshot = [(loc.t("system.retrieved"), loc.when(source.get("retrieved_at"))),
                (loc.t("system.window"), Html(f'{loc.when(window.get("since"))} <span dir="ltr">→</span> {loc.when(window.get("until"))}')),
                (loc.t("system.contract"), loc.tech(source.get("executable_contract_version"))),
                (loc.t("system.dashboard_document"), loc.tech(doc["dashboard_version"])), (loc.t("system.generated"), loc.when(doc["generated_at"]))]
    if publication.get("release_id"):
        snapshot.append((loc.t("ui.release"), loc.t("publication.identity", release=loc.tech(publication["release_id"]), snapshot=loc.tech(publication["snapshot_id"]))))
    editors = sorted(doc["editors"], key=lambda s: (s["display_name"].casefold(), s["editor_id"]))
    rules = ""
    if editors:
        first = editors[0]
        view = first["interpretation"]
        rows = [(loc.t("interp.component.overall_lookup"), view["overall"]["rule_status"])] + [
            (component_name(name, loc), view["components"][name]["rule_status"]) for name in COMPONENTS] + [
            (loc.t("interp.recent.head.trend"), view["trend_rule_status"])]
        rules = "".join(f'<li><span>{name}</span><span class="sc {"positive" if status == "approved" else "not_classifiable"}">{loc.t("interp.state." + status)}</span></li>'
                        for name, status in rows)
        speed_minimum = first["speed"].get("minimum_editor_sample_size")
        facts = [("common.speed", loc.t("system.rule.speed", stat=loc.t("stat." + first["speed"]["benchmark_statistic"]), min=loc.num(speed_minimum),
                                         min_projects=loc.count("noun.project", speed_minimum)) if speed_minimum else loc.t("common.not_evaluated")),
                 ("common.deadlines", loc.t("system.rule.deadlines", rule=loc.tech(first["deadline"]["rule_version"]))),
                 ("common.quality", loc.t("system.rule.quality")), ("common.revisions", loc.t("system.rule.revisions"))]
        rules += "".join(f'<li><span>{loc.t(name)}</span><span>{text}</span></li>' for name, text in facts)
    slots = [slot for slot in PENDING_RULES if slot in V15_PENDING_SLOTS]
    pending = "".join(f'<li><span>{pending_label(slot, loc, True)}</span><span>{loc.t(f"pending_v15.{slot}.reason" if slot in V15_REASONS else f"pending.{slot}.reason")}</span></li>'
                      for slot in slots)
    identity = "".join(f'<tr><td>{loc.src(s["display_name"])}</td><td>{loc.tech(s["editor_id"])}</td><td>{loc.src(s["monday_label"])}</td>'
                       f'<td>{loc.tech(s["mapping_version"])}</td><td>{loc.tech(s["profile_contract_version"])}</td><td>{loc.num(s["sample"]["completed_projects"])}</td></tr>'
                       for s in editors)
    notes = "".join(f'<tr><td>{loc.src(s["display_name"])}</td><td>{warning_text(w, loc)}</td><td>{loc.tech(w["source"])}</td></tr>' for s in editors for w in s["warnings"])
    excluded = "".join(f'<tr><td>{loc.src(s["display_name"])}</td><td>{code_text(r, loc)}</td><td>{loc.num(n)}</td></tr>'
                       for s in editors for r, n in s["sample"]["exclusions_by_reason"].items())
    eligibility = "".join(f'<tr><td>{loc.src(s["display_name"])}</td><td>{loc.labels(c["labels"])}</td><td>{loc.num(c["editor_sample_size"])}</td>'
                          f'<td>{loc.num(c["team_sample_size"])}</td><td>{loc.t("common.yes" if c["benchmark_eligible"] else "common.no")}</td>'
                          f'<td>{code_text(c["comparison_status"], loc)}</td></tr>' for s in editors for c in s["speed"]["cohorts"])
    none_row = f'<tr><td colspan=6 class="muted">{loc.t("common.none")}</td></tr>'
    coverage = doc.get("attribution_coverage")
    cov = ""
    if coverage:
        reasons = "".join(f"<tr><td>{code_text(r, loc)}</td><td>{loc.num(n)}</td></tr>" for r, n in coverage["not_attributed_by_reason"].items())
        cov = (f'<div class="card"><h3>{loc.t("system.attribution_title")}</h3><p class="sm soft">'
               f'{loc.t("system.attribution_text", attributed=loc.num(coverage["attributed"]), completed=loc.count("noun.completed_project", coverage["completed"], case="gen"))}</p>'
               + table([loc.t("system.head.reason_not_attributed"), loc.t("common.projects")], reasons, none_row) + "</div>")
    missing = "".join(f'<tr><td>{loc.src(e["display_name"])}</td><td>{loc.tech(e["editor_id"])}</td><td>{loc.src(e["monday_label"])}</td></tr>'
                      for e in doc["editors_without_attributable_data"])
    presentation = "".join(f"<li><span>{loc.t(k)}</span></li>" for k in ("ui.presentation.order", "system.presentation.timeline",
                                                                          "system.presentation.months_v15", "system.presentation.languages"))
    return (f'<div data-view="system" hidden><div class="ph"><div><h1>{loc.t("ui.nav.system")}</h1><p>{loc.t("system.sub")}</p></div></div>'
            f'{operational_status(dict(status_snapshot) if status_snapshot is not None else None, loc)}'
            f'<div class="grid2" style="margin-top:12px"><div class="card"><h3 style="margin-bottom:12px">{loc.t("ui.rules.title")}</h3><ul class="rules">{rules}</ul></div>'
            f'<div class="card"><h3 style="margin-bottom:12px">{loc.t("ui.rules.pending")}</h3><ul class="rules">{pending}</ul></div></div>'
            f'<div class="card" style="margin-top:12px"><h3 style="margin-bottom:12px">{loc.t("system.snapshot")}</h3>{dl(snapshot, "dl")}</div>'
            f'<div class="card"><h3 style="margin-bottom:12px">{loc.t("system.editors_identity")}</h3>'
            + table([loc.t("common.editor"), loc.t("system.head.atlas_id"), loc.t("system.head.monday_label"), loc.t("system.head.mapping"), loc.t("system.head.profile"), loc.t("coverage.completed")], identity, none_row)
            + f'</div><div class="card"><h3 style="margin-bottom:12px">{loc.t("system.data_quality_notes")}</h3>'
            + table([loc.t("common.editor"), loc.t("system.head.note"), loc.t("system.head.profile_field")], notes, none_row)
            + f'</div><div class="card"><h3 style="margin-bottom:12px">{loc.t("system.speed_eligibility")}</h3>'
            + table([loc.t("common.editor"), loc.t("field.video_type"), loc.t("system.head.editor_n"), loc.t("system.head.team_n"), loc.t("system.head.eligible"), loc.t("common.status")], eligibility, none_row)
            + f'</div><div class="card"><h3 style="margin-bottom:12px">{loc.t("system.excluded")}</h3>'
            + table([loc.t("common.editor"), loc.t("common.reason"), loc.t("common.projects")], excluded, none_row)
            + f'</div>{cov}<div class="card"><h3 style="margin-bottom:12px">{loc.t("system.mapped_without")}</h3>'
            + table([loc.t("common.editor"), loc.t("system.head.atlas_id"), loc.t("system.head.monday_label")], missing, none_row)
            + f'</div>{intel.rules_card(intelligence, ctx)}<div class="card"><h3 style="margin-bottom:12px">{loc.t("system.presentation_notes")}</h3><ul class="facts">{presentation}</ul></div></div>')


# ---------------------------------------------------------------- page

def language_switch(loc: Loc, href: str, keep_hash: bool = False) -> str:
    other = loc.other()
    return (f'<a class="lang" href="{escape(href)}" hreflang="{other.code}" lang="{other.code}" dir="{other.dir}"'
            f'{" data-keep-hash" if keep_hash else ""} aria-label="{attr(loc.text("lang.switch_label"))}">{escape(loc.text("lang.other_name"))}</a>')


def page(loc: Loc, title: str, body: str, publication: Mapping[str, Any] | None, *, script: bool = True, extra_class: str = "") -> str:
    release_id, snapshot_id = (publication or {}).get("release_id"), (publication or {}).get("snapshot_id")
    meta = (f'<meta name="atlas-release-id" content="{escape(release_id)}"><meta name="atlas-snapshot-id" content="{escape(snapshot_id)}">'
            if release_id and snapshot_id else "")
    attrs = (f' data-atlas-release-id="{escape(release_id)}" data-atlas-snapshot-id="{escape(snapshot_id)}"' if release_id and snapshot_id else "")
    cls = f' class="{extra_class}"' if extra_class else ""
    return (f'<!doctype html><html lang="{loc.code}" dir="{loc.dir}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'{meta}<title>{escape(title)}</title><style>{CSS}</style></head><body{attrs}{cls}>{body}'
            + (f"<script>{SCRIPT}</script>" if script else "") + "</body></html>")


def render_app(doc: Mapping[str, Any], profile_pages: Mapping[str, str], monday_item_url: str | None = None, loc: Loc | None = None,
               switch_href: str | None = None, status_snapshot: Mapping[str, Any] | None = None, intelligence: Mapping[str, Any] | None = None) -> str:
    """The contract 1.5 dashboard page in ``loc``: Editors, each Editor Profile and Data & rules, as one static app. ``intelligence`` is the
    optional published Intelligence V2 document (``approved_only``); without it the page is exactly the page without Intelligence."""
    assert loc is not None
    loc = loc.isolating()   # Latin terms and dates isolated in Arabic (redesign T1.4)
    ctx = Ctx(loc, monday_item_url)
    source = doc["source"]
    retrieved = source.get("retrieved_at")
    month = datetime.fromisoformat(retrieved.replace("Z", "+00:00")).astimezone(CAIRO).strftime("%Y-%m") if retrieved else None
    editors = doc["editors"]
    views = (overview(doc, ctx, month, intelligence) + "".join(editor_profile(s, retrieved, ctx, intelligence) for s in editors)
             + intel.drawers(intelligence, ctx, intel.project_template_ids(editors)))
    body = _dedupe_templates(views)
    blob = json.dumps(dict(profile_pages)).replace("</", "<\\/")
    switch = language_switch(loc, switch_href, keep_hash=True) if switch_href else ""
    fresh = (f'<a class="fresh" href="#/system" title="{attr(loc.text("ui.data_status"))}"><i></i><span>{loc.t("home.updated", date=Html(loc.when(retrieved, False)))}</span></a>'
             if retrieved else "")
    top = (f'<header class="top"><div class="top-in"><a class="brand" href="#/"><i></i><bdi dir="ltr">Atlas</bdi></a>'
           f'<nav class="nav" aria-label="{attr(loc.text("nav.main_label"))}"><a href="#/" data-nav="team" aria-current="page">{loc.t("ui.nav.editors")}</a>'
           f'<a href="#/system" data-nav="system">{loc.t("ui.nav.system")}</a></nav><div class="top-end">{fresh}{switch}</div></div></header>')
    drawer = ('<div class="scrim"></div><aside class="drawer" id="drawer" role="dialog" aria-modal="true" aria-hidden="true" aria-labelledby="drawer-title">'
              f'<header><h2 id="drawer-title"></h2><button type="button" class="x" aria-label="{attr(loc.text("common.close"))}">{icon("x")}</button></header><div class="body"></div></aside>')
    content = (f'{top}<main class="wrap">{body}{data_rules(doc, ctx, status_snapshot, intelligence)}</main>{drawer}'
               f'<script type="application/json" id="atlas-reports">{blob}</script>')
    return page(loc, loc.text("page.dashboard_title"), content, doc.get("publication"))

