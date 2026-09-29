"""The standalone contract 1.5 Editor Profile report: the audit view of one Editor, printable, with every evidence record inline.

It is rendered from the same language-neutral summary (``dashboard.editor_summary``) and the same section renderers as the app,
so the two can never disagree; the report replaces drawers with inline tables and adds the complete evidence records of each
component and every project with its Monday event IDs.
"""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
from typing import Any

from atlas_commander.dashboard import editor_summary
from atlas_commander.i18n import Html, Loc
from atlas_commander.interpretation_html import _records
from atlas_commander.web.app import (
    COMPONENTS,
    _sid,
    language_switch,
    page,
    profile_change,
    profile_deadline,
    profile_history,
    profile_labels,
    profile_quality,
    profile_revisions,
    profile_signals,
    profile_speed,
    profile_summary,
    profile_work,
    section_bar,
)
from atlas_commander.web.kit import Ctx, attr, code_text, component_name, icon, item_link, section_head, table


def _evidence_section(profile: Mapping[str, Any], s: Mapping[str, Any], ctx: Ctx) -> str:
    loc, eid = ctx.loc, s["editor_id"]
    blocks = "".join(f'<div class="card" data-component="{name}"><h3>{component_name(name, loc)}</h3>'
                     f'{_records(profile[name]["component"]["evidence"], loc, ctx.url) or f"<p class=muted>{loc.t("evidence.no_projects")}</p>"}</div>'
                     for name in COMPONENTS)
    rows = []
    for row in profile["projects"]:
        result = row["deadline_result"]
        deadline = (Html(f"{loc.t('result.' + result)} {loc.hours(row['deadline_delta_seconds'], signed=True)}") if result
                    else code_text(row["requested_eta_issue"], loc) if row["requested_eta_issue"] else Html("—"))
        ids = row["evidence_event_ids"]
        rows.append(f"<tr><td>{item_link(row['monday_item_id'], ctx)}</td><td>{loc.tech(row['ready_for_approval_at'] or '—')}</td>"
                    f"<td>{loc.hours(row['duration_seconds'])}</td><td>{loc.labels(row['cohort_labels'])}</td>"
                    f'<td class="res-{escape(result or "")}" data-classification="{escape(result or "not_classifiable")}">{deadline}</td>'
                    f"<td>{loc.comma().join(loc.src(label) for label in row['quality_labels']) or '—'}</td><td>{loc.num(row['client_revision_events'])}</td>"
                    f"<td>{loc.comma().join(code_text(reason, loc) for reason in row['exclusions']) or loc.t('evidence.included_lower')}</td>"
                    f"<td>{loc.tech(ids['in_progress'])}<br>{loc.tech(ids['ready_for_approval'])}</td></tr>")
    head = [loc.t("report.head.item"), loc.t("field.ready_for_approval"), loc.t("report.head.duration"), loc.t("field.video_type"), loc.t("field.deadline"),
            loc.t("ui.labels_on_project"), loc.t("report.head.client_revisions"), loc.t("evidence.metric_status"), loc.t("report.head.events")]
    coverage = profile["coverage"]
    reasons = "".join(f"<li><span>{code_text(reason, loc)}</span><b>{loc.num(count)}</b></li>" for reason, count in coverage["exclusions_by_reason"].items())
    states = "".join(f"<li><span>{loc.tech(state)}</span><b>{loc.num(count)}</b></li>" for state, count in coverage["states"].items() if count)
    return (f'<section id="{_sid(eid, "evidence")}" class="sec">{section_head(loc.t("ui.evidence.title"), loc.t("profile.report_intro"))}'
            f'<div class="grid3">{blocks}</div>'
            f'<div class="card" style="margin-top:12px"><h3 style="margin-bottom:12px">{loc.t("report.coverage_title")}</h3><div class="grid2">'
            f'<ul class="facts">{reasons or f"<li class=empty>{loc.t("common.none")}</li>"}</ul><ul class="facts">{states}</ul></div>'
            f'<p class="note">{loc.t("note.not_attributed")}</p></div>'
            f'<div class="card"><details class="more" open><summary>{loc.t("report.show_projects", n=loc.num(len(profile["projects"])))}</summary>'
            f'<div style="margin-top:12px">{table(head, "".join(rows), "")}</div></details></div></section>')


def render_report(profile: dict[str, Any], monday_item_url: str | None = None, loc: Loc | None = None, *, dashboard_href: str | None = None,
                  switch_href: str | None = None, publication: dict[str, Any] | None = None) -> str:
    """The contract 1.5 Editor Profile report in ``loc``. With ``dashboard_href``/``switch_href`` it has a top bar (standalone
    page); without them it is the embedded audit view."""
    assert loc is not None
    ctx = Ctx(loc, monday_item_url, interactive=False)
    s = editor_summary(profile)
    editor, retrieved = profile["editor"], profile["source"].get("retrieved_at")
    publication = publication or profile.get("publication")
    top = ""
    if dashboard_href or switch_href:
        back = f'<a class="back" style="margin:0" href="{escape(dashboard_href)}">{icon("back", 15)} {loc.t("report.back")}</a>' if dashboard_href else "<span></span>"
        switch = language_switch(loc, switch_href) if switch_href else ""
        top = (f'<header class="top"><nav class="top-in" aria-label="{attr(loc.text("nav.main_label"))}"><a class="brand" href="{escape(dashboard_href or "#")}"><i></i>Atlas</a>'
               f'{back}<div class="top-end">{switch}</div></nav></header>')
    identity = loc.t("report.identity", editor_id=loc.tech(editor["editor_id"]), label=loc.src(editor["monday_person_id"]), mapping=loc.tech(editor["mapping_version"]),
                     contract=loc.tech(profile["executable_contract_version"]), retrieved=loc.tech(retrieved), generated=loc.tech(profile["generated_at"]))
    release = (f'<br>{loc.t("publication.identity", release=loc.tech(publication["release_id"]), snapshot=loc.tech(publication["snapshot_id"]))}' if publication else "")
    body = (profile_summary(s, ctx, retrieved)
            + f'<p class="note">{identity}{release}</p>'
            + f'<nav class="jump" aria-label="{attr(loc.text("ui.sections_label"))}">{section_bar(s["editor_id"], profile_labels(loc), ctx)}</nav>'
            + profile_change(s, ctx) + profile_signals(s, ctx) + profile_quality(s, ctx) + profile_speed(s, ctx) + profile_deadline(s, ctx)
            + profile_revisions(s, ctx) + profile_work(s, ctx) + profile_history(s, ctx, retrieved) + _evidence_section(profile, s, ctx))
    return page(loc, loc.text("report.page_title", name=editor["display_name"]), f'{top}<main class="wrap">{body}</main>', publication,
                script=False, extra_class="report")
