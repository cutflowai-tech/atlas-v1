"""HTML for the contract 1.5 interpretation layer (D23--D47), shared by the Editor Overview and the Editor Profile.

Everything is rendered from one language-neutral view model (``dashboard.interpretation_view``); English and Arabic differ
only in their catalogue strings and number/date formatting. Nothing here decides a state: each state, reason and rule
approval is shown exactly as the profile computed it, and every figure carries its sample and window.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape
from typing import Any

from atlas_commander.i18n import EN, Html, Loc

# Styles used only by contract 1.5 pages (earlier contracts keep their original page bytes).
CSS = """
.ia{display:grid;gap:12px}.ia h2,.ia h3{margin:0}.ia-status{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 16px}
.ia-status b{font-size:22px;font-weight:600}.ia-muted{color:var(--muted,#5f5f5a);font-size:13px}
.ia-grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.ia-state{display:inline-block;padding:1px 8px;border-radius:999px;border:1px solid var(--line,#e3e2dc);font-size:12px}
.ia-state.positive{color:var(--good,#1f7a4d)}.ia-state.negative{color:var(--bad,#b3261e)}.ia-state.not_classifiable{color:var(--muted,#5f5f5a)}
.ia table{border-collapse:collapse;width:100%}.ia th,.ia td{text-align:start;padding:6px 8px;border-bottom:1px solid var(--line,#e3e2dc);vertical-align:top}
.ia details{margin-top:6px}.ia summary{cursor:pointer;font-size:13px}.ia ul{margin:4px 0;padding-inline-start:18px}
.ia-badge{display:grid;gap:2px;text-align:end}.ia-badge b{font-size:15px;font-weight:600}
"""

STATUS_KEYS = {"Strong": "strong", "Good": "good", "Mixed": "mixed", "Below Expectations": "below_expectations",
               "Not enough evidence to classify": "not_enough_evidence", "Not enough approved logic to classify": "not_enough_approved_logic"}


def status_text(overall: Mapping[str, Any], loc: Loc) -> Html:
    return loc.t("interp.status." + STATUS_KEYS[overall["status_label"]])


def reason_text(reason: str | None, loc: Loc, **params: Any) -> Html:
    if reason is None:
        return Html("")
    key = "interp.reason." + reason
    return loc.t(key, **params) if loc.has(key) else loc.tech(reason)


def state_chip(state: str, loc: Loc) -> str:
    return f'<span class="ia-state {escape(state)}" data-state="{escape(state)}">{loc.t("interp.state." + state)}</span>'


def _range(value: Mapping[str, Any], loc: Loc) -> tuple[str, str]:
    # end_date_exclusive is the first day not included; show the last included day.
    from datetime import date, timedelta
    last = date.fromisoformat(value["end_date_exclusive"]) - timedelta(days=1)
    return escape(loc.date(value["start_date"], False)), escape(loc.date(last.isoformat(), False))


def window_line(view: Mapping[str, Any], loc: Loc) -> Html:
    start, end = _range(view["window"]["current"], loc)
    cstart, cend = _range(view["window"]["comparison"], loc)
    return loc.t("interp.window", start=Html(start), end=Html(end), cstart=Html(cstart), cend=Html(cend))


def window_caption(view: Mapping[str, Any], loc: Loc) -> Html:
    start, end = _range(view["window"]["current"], loc)
    return loc.t("interp.window_short", start=Html(start), end=Html(end))


def overall_badge(view: Mapping[str, Any], loc: Loc = EN) -> str:
    """The Overview card / profile header badge: the real Overall Status (or why there is none), never a placeholder."""
    overall = view["overall"]
    states = overall["component_states"]
    compact = loc.t("interp.card.components", **{name: loc.text("interp.state." + states[name]) for name in ("quality", "speed", "deadline")})
    return (f'<div class="overall ia-badge" data-status-state="{escape(overall["status_state"])}" data-overall-status="{escape(overall["status"] or "")}">'
            f'<span>{loc.t("overall.label")}</span><b>{status_text(overall, loc)}</b><span class="ia-muted">{compact}</span></div>')


def _evidence(summary: Mapping[str, Any], loc: Loc) -> str:
    return (f'<p class="ia-muted">{loc.t("interp.evidence.summary", n=loc.num(summary["records"]), rule=loc.tech(summary["rule_version"]),
                                         at=Html(escape(loc.date(summary["calculated_at"]))))}</p>')


def _records(evidence: Mapping[str, Any], loc: Loc, item_url: str | None) -> str:
    """Drill-down of one evidence block: each project with the values used and the Monday events behind them."""
    rows = []
    for record in evidence["records"]:
        item = escape(record["monday_item_id"])
        link = f'<a href="{escape(item_url.format(item_id=record["monday_item_id"]))}">{loc.tech(record["monday_item_id"])}</a>' if item_url else loc.tech(item)
        values = "".join(f"<li>{loc.tech(key)}: {loc.tech(_plain(value))}</li>" for key, value in record["source_values"].items() if key != "labels")
        labels = "".join(f'<li>{loc.src(label["label"])} · {loc.tech(label["label_class"])} · {loc.t("interp.label.scored" if label["scored_quality"] else "interp.label.not_scored")}</li>'
                         for label in record["source_values"].get("labels", []))
        events = "".join(f"<li>{loc.tech(event)}</li>" for event in record["event_ids"])
        rows.append(f'<tr><td>{link}</td><td><ul>{values}{labels}</ul></td><td><ul>{events}</ul></td></tr>')
    if not rows:
        return ""
    return (f'<details><summary>{loc.t("interp.evidence.show")} ({loc.num(len(rows))})</summary><div class="scroll"><table><thead><tr>'
            f'<th scope=col>{loc.t("common.projects")}</th><th scope=col>{loc.t("interp.evidence.head.values")}</th>'
            f'<th scope=col>{loc.t("interp.evidence.head.events")}</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></details>')


def _plain(value: Any) -> str:
    return "—" if value is None else str(value)


def _component_card(name: str, component: Mapping[str, Any], body: str, loc: Loc, evidence: Mapping[str, Any] | None, item_url: str | None) -> str:
    reason = reason_text(component["reason"], loc)
    return (f'<div class="card" data-component="{escape(name)}"><h3>{loc.t("common." + ("deadlines" if name == "deadline" else name))} '
            f'{state_chip(component["state"], loc)}</h3>'
            + (f'<p class="ia-muted" data-reason="{escape(component["reason"])}">{reason}</p>' if component["reason"] else "")
            + body + _evidence(component["evidence"], loc) + (_records(evidence, loc, item_url) if evidence else "") + "</div>")


def _speed_rows(video_types: Sequence[Mapping[str, Any]], loc: Loc) -> str:
    rows = []
    for row in video_types:
        verdict = (f'{loc.t("interp.verdict." + row["verdict"])}'
                   + (f'<br><span class="ia-muted" data-reason="{escape(row["reason"])}">{reason_text(row["reason"], loc)}</span>' if row["reason"] else ""))
        comparator = (loc.t("interp.speed.comparator_value", median=loc.hours(row["comparator_median_seconds"]), n=loc.num(row["comparator_projects"]),
                            editors=loc.num(row["comparator_editor_count"])) if row["comparator_projects"] else Html("—"))
        rows.append(f'<tr data-verdict="{escape(row["verdict"])}"><td>{loc.labels(row["cohort_labels"])}<br>{loc.tech(row["cohort_key"])}</td>'
                    f'<td>{loc.t("interp.speed.value", median=loc.hours(row["editor_median_seconds"]), n=loc.num(row["editor_projects"]))}</td>'
                    f'<td>{comparator}</td><td>{loc.pct_value(row["editor_vs_comparator_pct"], signed=True)}</td><td>{verdict}</td></tr>')
    return (f'<div class="scroll"><table><thead><tr><th scope=col>{loc.t("interp.speed.head.type")}</th><th scope=col>{loc.t("interp.speed.head.editor")}</th>'
            f'<th scope=col>{loc.t("interp.speed.head.comparator")}</th><th scope=col>{loc.t("interp.speed.head.difference")}</th>'
            f'<th scope=col>{loc.t("common.result")}</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def _change_value(measurement: str, value: Any, n: int, loc: Loc) -> Html:
    if value is None:
        return Html("—")
    shown = loc.hours(value) if measurement == "median_speed_seconds" else loc.pct(value)
    return loc.t("interp.value_n", value=shown, n=loc.num(n))


def _change_rows(changes: Sequence[Mapping[str, Any]], loc: Loc) -> str:
    rows = []
    for change in changes:
        measurement = change["measurement"]
        name = loc.t("interp.measure." + measurement)
        if change["cohort_key"]:
            name = Html(f'{name} · {loc.labels(change["cohort_labels"])}')
        difference = change["difference"]
        shown = ("—" if difference is None else loc.hours(difference, signed=True) if measurement == "median_speed_seconds"
                 else loc.t("interp.pp", value=loc.ltr(f"{difference * 100:+.1f}")))
        trend = (loc.t("interp.trend." + change["trend"]) if change["trend"]
                 else Html(f'<span class="ia-muted" data-reason="{escape(change["trend_reason"])}">{reason_text(change["trend_reason"], loc)}</span>'))
        rows.append(f'<tr data-measurement="{escape(measurement)}"><td>{name}<br><span class="ia-muted">{loc.t("interp.direction." + change["direction"])}</span></td>'
                    f'<td>{_change_value(measurement, change["current"], change["current_sample"], loc)}</td>'
                    f'<td>{_change_value(measurement, change["comparison"], change["comparison_sample"], loc)}</td><td>{shown}</td><td>{trend}</td></tr>')
    return (f'<div class="scroll"><table><thead><tr><th scope=col>{loc.t("interp.recent.head.measure")}</th><th scope=col>{loc.t("interp.recent.head.current")}</th>'
            f'<th scope=col>{loc.t("interp.recent.head.comparison")}</th><th scope=col>{loc.t("interp.recent.head.change")}</th>'
            f'<th scope=col>{loc.t("interp.recent.head.trend")}</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def interpretation_section(view: Mapping[str, Any], loc: Loc = EN, *, profile: Mapping[str, Any] | None = None, item_url: str | None = None) -> str:
    """Overall Status, why, the three components (with D45's dual Deadline display), Recent Change and coverage.

    With ``profile`` the full evidence records are listed for drill-down (the Editor Profile report); without it only the
    evidence summaries are shown (the dashboard, whose audit view embeds that report)."""
    overall, components = view["overall"], view["components"]
    why = "".join(
        f'<li data-component="{escape(row["component"])}"><b>{loc.t("interp.component.overall_lookup") if row["component"] == "overall_lookup" else loc.t("common." + ("deadlines" if row["component"] == "deadline" else row["component"]))}</b>: '
        f'{loc.t("interp.state." + row["state"])}'
        + (f' · <span data-reason="{escape(row["reason"])}">{reason_text(row["reason"], loc)}</span>' if row["reason"] and row["reason"] != row["state"] else "")
        + "</li>"
        for row in overall["why"])
    overall_reason = (f' · <span data-reason="{escape(overall["reason"])}">{reason_text(overall["reason"], loc, min=loc.num(overall["minimum_classifiable_components"]))}</span>'
                      if overall["reason"] else "")
    head = (f'<div class="card" data-overall-status="{escape(overall["status"] or "")}" data-status-state="{escape(overall["status_state"])}">'
            f'<h2>{loc.t("interp.section_title")}</h2><div class="ia-status"><b>{status_text(overall, loc)}</b>'
            f'<span class="ia-muted">{window_line(view, loc)}</span></div>'
            f'<h3>{loc.t("interp.why_title")}{overall_reason}</h3><ul>{why}</ul>'
            f'<p class="ia-muted">{loc.t("interp.no_score")} {loc.t("interp.facts_note")}</p>'
            f'<p class="ia-muted">{loc.t("interp.coverage", current=loc.num(view["coverage"]["current_projects"]), comparison=loc.num(view["coverage"]["comparison_projects"]), excluded=loc.num(view["coverage"]["excluded_projects"]))}</p></div>')

    quality = components["quality"]
    facts = quality["facts"]
    quality_body = (f'<p>{loc.t("interp.quality.facts", pos=loc.num(facts["positive_count"]), prate=loc.pct(facts["positive_rate"]), neg=loc.num(facts["negative_count"]), nrate=loc.pct(facts["negative_rate"]), n=loc.num(facts["eligible_completed_projects"]))}</p>'
                    + (f'<p class="ia-muted">{loc.t("interp.quality.excluded", n=loc.num(sum(quality["scoring_exclusions"].values())))}: '
                       + loc.comma().join(f'{reason_text(reason, loc)} ({loc.num(n)})' for reason, n in quality["scoring_exclusions"].items()) + "</p>"
                       if quality["scoring_exclusions"] else ""))
    speed = components["speed"]
    speed_body = f'<p>{loc.t("interp.speed.facts", n=loc.num(speed["facts"]["classifiable_projects"]))}</p>{_speed_rows(speed["video_types"], loc)}'
    deadline = components["deadline"]
    d = deadline["facts"]
    relative = loc.text("interp.deadline.relative." + deadline["state"])
    deadline_body = (f'<p><b>{loc.t("interp.deadline.dual", relative=relative, rate=loc.pct(d["absolute_late_rate"]), late=loc.num(d["late"]), n=loc.num(d["deadline_classifiable_projects"]))}</b></p>'
                     f'<p>{loc.t("interp.deadline.comparator", rate=loc.pct(d["comparator_late_rate"]), n=loc.num(d["comparator_projects"]), editors=loc.num(d["comparator_editor_count"]))}</p>'
                     f'<p class="ia-muted">{loc.t("interp.deadline.absolute_note")}</p>')
    blocks = (profile["quality"]["component"]["evidence"], profile["speed"]["component"]["evidence"], profile["deadline"]["component"]["evidence"]) if profile else (None, None, None)
    cards = (_component_card("quality", quality, quality_body, loc, blocks[0], item_url)
             + _component_card("speed", speed, speed_body, loc, blocks[1], item_url)
             + _component_card("deadline", deadline, deadline_body, loc, blocks[2], item_url))
    recent = (f'<div class="card" data-section="recent-change"><h3>{loc.t("interp.recent_title")}</h3><p class="ia-muted">{loc.t("interp.recent_sub")}</p>'
              f'{_change_rows(view["recent_change"], loc)}</div>')
    return f'<section class="ia" data-section="interpretation">{head}<div class="ia-grid">{cards}</div>{recent}</section>'
