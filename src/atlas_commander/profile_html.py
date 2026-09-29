"""Static HTML view of an editor-profile 1.3.0 or 1.4.0 document, in English or Arabic.

The page only formats values that are already in the profile (durations as hours, rates as
percentages). It never computes a metric, a comparison or a conclusion. Atlas-owned text comes from
the catalogue (:mod:`atlas_commander.i18n`); Monday values and IDs are shown exactly as recorded.
The profile's own explanatory notes are shown through the catalogue in both languages (the English
catalogue text is the profile's text, checked by the tests).
"""

from __future__ import annotations

from html import escape
from typing import Any

from atlas_commander.capabilities import capabilities
from atlas_commander.dashboard import interpretation_view
from atlas_commander.i18n import EN, Html, Loc
from atlas_commander.interpretation_html import CSS as IA_CSS
from atlas_commander.interpretation_html import interpretation_section, window_caption

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--muted:#5f5f5a;--line:#e3e2dc;--good:#1f7a4d;--warn:#9a6700;--bad:#b3261e;--accent:#2f5bb7}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--card:#1f1f1c;--ink:#ecebe6;--muted:#a8a79f;--line:#34332e;--good:#5fc38f;--warn:#e0b050;--bad:#f08a80;--accent:#8fb0ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
[lang=ar] body{font-family:"Segoe UI","Noto Sans Arabic","Noto Naskh Arabic","Geeza Pro","Tahoma",system-ui,sans-serif;line-height:1.75}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{font-size:26px;margin:0}h2{font-size:18px;margin:0 0 12px}
.top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:16px}.top a{color:var(--accent)}
.sub{color:var(--muted);font-size:13px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px;margin:16px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.tile{border:1px solid var(--line);border-radius:8px;padding:10px}
.tile b{display:block;font-size:22px}.tile span{color:var(--muted);font-size:12px}.note{color:var(--muted);font-size:13px;margin:8px 0 0}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:start;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600}.scroll{overflow-x:auto}.pill{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;border:1px solid var(--line)}
.faster_than_team_median{color:var(--good)}.slower_than_team_median{color:var(--bad)}.insufficient_sample,.not_comparable{color:var(--muted)}
.early{color:var(--good)}.late{color:var(--bad)}code{font-size:12px;unicode-bidi:isolate}bdi{unicode-bidi:isolate}details summary{cursor:pointer;color:var(--accent)}
"""


def _deadline_note(deadline: dict[str, Any], loc: Loc) -> Html:
    return loc.t("report.deadline_note_frozen" if deadline.get("requested_eta_selection") else "report.deadline_note_latest")


def _item(item_id: str, url_template: str | None, loc: Loc) -> str:
    text = loc.tech(item_id)
    return f'<a href="{escape(url_template.format(item_id=item_id))}" rel="noopener">{text}</a>' if url_template else text


def _n(value: Any, loc: Loc) -> Html:
    return loc.num(value) if value is not None else Html("—")


def render_profile_html(profile: dict[str, Any], monday_item_url: str | None = None, loc: Loc = EN, *, dashboard_href: str | None = None,
                        switch_href: str | None = None, publication: dict[str, Any] | None = None) -> str:
    """Render the profile in ``loc``. ``monday_item_url`` may contain ``{item_id}`` to link each project to Monday.

    ``dashboard_href`` and ``switch_href`` add a page header with a link back to the dashboard and to the same profile in the
    other language (standalone pages); without them the page has no navigation (the embedded audit view)."""
    if capabilities(profile["executable_contract_version"]).editor_intelligence:
        # Contract 1.5+: the redesigned report. This module keeps the 1.3/1.4 pages byte for byte (fixtures/golden).
        from atlas_commander.web import render_report
        return render_report(profile, monday_item_url, loc, dashboard_href=dashboard_href, switch_href=switch_href, publication=publication)
    t = loc.t
    editor = profile["editor"]
    speed, deadline, quality, revisions, coverage = profile["speed"], profile["deadline"], profile["quality"], profile["revisions"], profile["coverage"]
    summary = deadline["summary"]
    v15 = capabilities(profile["executable_contract_version"]).editor_intelligence
    publication = publication or profile.get("publication")
    release_meta = (f'<meta name="atlas-release-id" content="{escape(publication["release_id"])}">'
                    f'<meta name="atlas-snapshot-id" content="{escape(publication["snapshot_id"])}">') if publication else ""
    body_identity = (f' data-atlas-release-id="{escape(publication["release_id"])}"'
                     f' data-atlas-snapshot-id="{escape(publication["snapshot_id"])}"') if publication else ""
    parts = [(f'<!doctype html><html lang="{loc.code}" dir="{loc.dir}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
              f'{release_meta}<title>{escape(loc.text("report.page_title", name=editor["display_name"]))}</title><style>{CSS}{IA_CSS if v15 else ""}</style></head>'
              f'<body{body_identity}><main>')]
    if dashboard_href or switch_href:
        other = loc.other()
        back = f'<a href="{escape(dashboard_href)}">{t("report.back")}</a>' if dashboard_href else "<span></span>"
        switch = (f'<a href="{escape(switch_href)}" hreflang="{other.code}" lang="{other.code}" dir="{other.dir}" '
                  f'aria-label="{escape(loc.text("lang.switch_label"))}">{escape(loc.text("lang.other_name"))}</a>' if switch_href else "")
        parts.append(f'<nav class="top" aria-label="{escape(loc.text("nav.main_label"))}">{back}{switch}</nav>')
    parts.append(f"<h1>{loc.src(editor['display_name'])}</h1><div class=\"sub\">"
                 + t("report.identity", editor_id=loc.tech(editor["editor_id"]), label=loc.src(editor["monday_person_id"]),
                     mapping=loc.tech(editor["mapping_version"]), contract=loc.tech(profile["executable_contract_version"]),
                     retrieved=loc.tech(profile["source"].get("retrieved_at")), generated=loc.tech(profile["generated_at"]))
                 + "</div>")
    if publication:
        parts.append(f'<div class="sub">{t("publication.identity", release=loc.tech(publication["release_id"]), snapshot=loc.tech(publication["snapshot_id"]))}</div>')

    def tile(value: Any, label: str) -> str:
        return f'<div class="tile"><b>{value}</b><span>{label}</span></div>'

    view = interpretation_view(profile) if v15 else None
    if view is not None:
        # Contract 1.5: the interpretation layer first; history-wide and window-scoped figures are captioned separately (D24).
        parts.append(interpretation_section(view, loc, profile=profile, item_url=monday_item_url))
        caption = window_caption(view, loc)
        parts.append(f"<section class=\"card\"><h2>{t('report.overall_title')}</h2><p class=\"sub\">{t('interp.history_scope')}</p><div class=\"tiles\">"
                     + tile(loc.num(coverage["completed_projects"]), t("report.tile.completed"))
                     + tile(loc.num(coverage["speed_eligible_projects"]), t("report.tile.measurable"))
                     + f"</div><p class=\"sub\">{caption}</p><div class=\"tiles\">"
                     + tile(loc.pct(summary.get("early_rate")), t("report.tile.early_deliveries", n=loc.num(summary["early"]), total=loc.num(summary["evaluated"])))
                     + tile(loc.pct(summary.get("late_rate")), t("report.tile.late_deliveries", n=loc.num(summary["late"]), total=loc.num(summary["evaluated"])))
                     + tile(loc.num(quality["negative"]["total_occurrences"]), t("report.tile.issue_labels"))
                     + "</div></section>")
    else:
        caption = Html("")
        parts.append(f"<section class=\"card\"><h2>{t('report.overall_title')}</h2><div class=\"tiles\">"
                     + tile(loc.num(coverage["completed_projects"]), t("report.tile.completed"))
                     + tile(loc.num(coverage["speed_eligible_projects"]), t("report.tile.measurable"))
                     + tile(loc.pct(summary.get("early_rate")), t("report.tile.early_deliveries", n=loc.num(summary["early"]), total=loc.num(summary["evaluated"])))
                     + tile(loc.pct(summary.get("late_rate")), t("report.tile.late_deliveries", n=loc.num(summary["late"]), total=loc.num(summary["evaluated"])))
                     + tile(loc.num(quality["negative"]["total_occurrences"]), t("report.tile.issue_labels"))
                     + f"</div><p class=\"note\">{t('note.overall')}</p></section>")
    scoped = f'<p class="sub">{caption}</p>' if v15 else ""

    rows = []
    # Display order only: largest Editor samples first.
    for cohort in sorted(speed["cohorts"], key=lambda c: (-c["editor_sample_size"], c["cohort_key"])):
        # A difference against a "team" that is only this Editor is not shown as a comparison.
        shown_pct = cohort.get("editor_vs_team_median_pct") if cohort["comparison_status"] != "no_other_editors_in_cohort" else None
        conclusion = cohort["conclusion"]
        rng = cohort.get("team_typical_range_seconds") or {}
        row_attrs = (f' data-classification="{escape(conclusion)}" data-comparison-status="{escape(cohort["comparison_status"])}"' if v15 else "")
        rows.append(f"<tr{row_attrs}><td>{loc.labels(cohort['cohort_labels'])}<br>{loc.tech(cohort['cohort_key'])}</td>"
                    f"<td>{loc.hours(cohort['editor_median_seconds'])}<br><span class=\"sub\">{t('common.sample_n', n=loc.num(cohort['editor_sample_size']))}</span></td>"
                    f"<td>{loc.hours(cohort['team_median_seconds'])}<br><span class=\"sub\">{t('common.sample_n', n=_n(cohort['team_sample_size'], loc))}</span></td>"
                    f"<td>{loc.pct_value(shown_pct, signed=True)}</td>"
                    f"<td>{loc.hours(rng.get('p25'))} – {loc.hours(rng.get('p75'))}</td>"
                    f"<td class=\"{escape(conclusion)}\">{t('conclusion.' + conclusion)}<br>"
                    f"<span class=\"sub\">{t('status.' + cohort['comparison_status'])}</span></td></tr>")
    empty = f"<tr><td colspan=6>{t('speed.no_measurable')}</td></tr>"
    speed_note = (t("common.not_evaluated") if speed.get("minimum_editor_sample_size") is None
                  else t("report.speed_note", stat=t("stat." + speed["benchmark_statistic"]),
                         min=loc.num(speed["minimum_editor_sample_size"]),
                         min_projects=loc.count("noun.project", speed["minimum_editor_sample_size"])))
    parts.append(f"<section class=\"card\"><h2>{t('report.speed_title')}</h2>{scoped}<div class=\"scroll\"><table><thead><tr><th scope=col>{t('report.head.cohort')}</th>"
                 f"<th scope=col>{t('common.editor_median')}</th><th scope=col>{t('common.team_median')}</th><th scope=col>{t('report.head.difference')}</th>"
                 f"<th scope=col>{t('report.head.typical_range')}</th><th scope=col>{t('report.head.conclusion')}</th></tr></thead>"
                 f"<tbody>{''.join(rows) or empty}</tbody></table></div>"
                 f"<p class=\"note\">{speed_note}</p></section>")

    parts.append(f"<section class=\"card\"><h2>{t('deadline.panel_title')}</h2>{scoped}<div class=\"tiles\">"
                 f"<div class=\"tile\"><b class=\"early\">{loc.num(summary['early'])}</b><span>{t('report.tile.early_rate', pct=loc.pct(summary.get('early_rate')))}</span></div>"
                 + tile(loc.num(summary["on_time"]), t("report.tile.on_time_rate", pct=loc.pct(summary.get("on_time_rate"))))
                 + f"<div class=\"tile\"><b class=\"late\">{loc.num(summary['late'])}</b><span>{t('report.tile.late_rate', pct=loc.pct(summary.get('late_rate')))}</span></div>"
                 + tile(loc.hours(summary.get("median_delta_seconds"), signed=True), t("report.tile.median_margin"))
                 + tile(loc.num(summary["not_classifiable_insufficient_eta_precision"]), t("report.tile.eta_without_time"))
                 + tile(loc.num(summary.get("not_classifiable_missing_eta", 0)), t("report.tile.no_eta"))
                 + f"</div><p class=\"note\">{_deadline_note(deadline, loc)}</p></section>")

    def quality_rows(name: str) -> str:
        return "".join(
            f"<tr><td>{loc.src(row['label'])}</td><td>{loc.num(row['occurrences'])}</td><td>{loc.comma().join(_item(i, monday_item_url, loc) for i in row['monday_item_ids'])}</td></tr>"
            for row in quality[name]["by_label"]
        )

    labels = quality_rows("negative")
    bonus = quality["for_bonus_context"]
    no_labels = f"<tr><td colspan=3>{t('report.no_issue_labels')}</td></tr>"
    taxonomy_tables = ""
    if v15:
        positive_rows = quality_rows("positive")
        context_rows = quality_rows("context")
        taxonomy_tables = (
            f"<h3>{t('quality.positive_title')}</h3><div class=\"scroll\"><table><thead><tr><th scope=col>{t('report.head.label')}</th>"
            f"<th scope=col>{t('report.head.occurrences')}</th><th scope=col>{t('common.projects')}</th></tr></thead>"
            f"<tbody>{positive_rows or no_labels}</tbody></table></div>"
            f"<h3>{t('quality.context_title')}</h3><div class=\"scroll\"><table><thead><tr><th scope=col>{t('report.head.label')}</th>"
            f"<th scope=col>{t('report.head.occurrences')}</th><th scope=col>{t('common.projects')}</th></tr></thead>"
            f"<tbody>{context_rows or no_labels}</tbody></table></div>"
        )
    parts.append(f"<section class=\"card\"><h2>{t('common.quality')}</h2>{scoped}<div class=\"tiles\">"
                 + tile(loc.num(quality["negative"]["total_occurrences"]), t("report.tile.issue_labels"))
                 + tile(loc.num(quality["negative"]["projects_with_issues"]), t("report.tile.projects_with_issues", total=loc.num(quality["negative"]["completed_projects_attributed"])))
                 + tile(loc.num(quality["positive"]["count"]), t("report.tile.positive"))
                 + (tile(loc.num(quality["context"]["total_occurrences"]), t("quality.context_title")) if v15
                    else tile(loc.num(len(bonus["projects"])), t("report.tile.for_bonus")))
                 + f"</div><div class=\"scroll\"><table><thead><tr><th scope=col>{t('report.head.label')}</th><th scope=col>{t('report.head.occurrences')}</th>"
                 f"<th scope=col>{t('common.projects')}</th></tr></thead><tbody>{labels or no_labels}</tbody></table></div>"
                 f"{taxonomy_tables}"
                 f"<p class=\"note\">{t('report.quality_note')} {t('note.positive_v15' if v15 else 'note.positive')}</p></section>")

    revision_tiles = tile(loc.num(revisions["client_revision_events"]), t("revisions.client_events"))
    if v15:
        revision_tiles += tile(loc.num(revisions["internal"]["events"]), t("revisions.internal_events"))
    revision_tiles += tile(loc.num(revisions["projects_with_client_revisions"]), t("report.tile.projects_with_revisions", total=loc.num(revisions["completed_projects"])))
    revision_tiles += tile(loc.pct(revisions["client_revision_rate"]), t("report.tile.revision_rate"))
    parts.append(f"<section class=\"card\"><h2>{t('report.revisions_title')}</h2><div class=\"tiles\">{revision_tiles}"
                 + f"</div><p class=\"note\">{t('note.revisions')}</p></section>")

    workload = profile["current_workload"]
    workload_rows = "".join(f"<tr><td>{loc.src(status)}</td><td>{loc.num(len(items))}</td><td>{loc.comma().join(_item(i, monday_item_url, loc) for i in items)}</td></tr>"
                            for status, items in sorted(workload["by_current_status"].items(), key=lambda pair: -len(pair[1])))
    none_row = f"<tr><td colspan=3>{t('common.none')}</td></tr>"
    workload_summary = ""
    if v15:
        workload_summary = (f'<div class="tiles">{tile(loc.num(workload["active_work"]["count"]), t("workload.active_work"))}'
                            f'{tile(loc.num(workload["awaiting_approval"]["count"]), t("workload.awaiting_approval"))}</div>')
    parts.append(f"<section class=\"card\"><h2>{t('report.current_title', date=loc.tech(workload['as_of']))}</h2>{workload_summary}<div class=\"scroll\"><table><thead><tr>"
                 f"<th scope=col>{t('report.head.current_status')}</th><th scope=col>{t('report.head.items')}</th><th scope=col>{t('common.projects')}</th></tr></thead>"
                 f"<tbody>{workload_rows or none_row}</tbody></table></div><p class=\"note\">{t('note.workload_v15' if v15 else 'note.workload')}</p></section>")

    trend = profile["trend"]
    speed_rows = "".join(f"<tr><td>{loc.tech(row['cohort_key'])}</td><td>{escape(loc.month(row['month']))}</td><td>{loc.num(row['projects'])}</td><td>{loc.hours(row['median_seconds'])}</td></tr>"
                         for row in trend["speed_by_cohort_month"])
    deadline_rows = "".join(f"<tr><td>{escape(loc.month(row['month']))}</td><td>{loc.num(row['evaluated'])}</td><td class=\"early\">{loc.num(row['early'])}</td><td>{loc.num(row['on_time'])}</td>"
                            f"<td class=\"late\">{loc.num(row['late'])}</td><td>{loc.pct(row['early_rate'])}</td><td>{loc.pct(row['late_rate'])}</td></tr>" for row in trend["deadline_by_month"])
    parts.append(f"<section class=\"card\"><h2>{t('common.by_month')}</h2><details><summary>{t('report.show_monthly')}</summary><div class=\"scroll\"><table><thead><tr>"
                 f"<th scope=col>{t('report.head.cohort_short')}</th><th scope=col>{t('report.head.month')}</th><th scope=col>{t('common.projects')}</th>"
                 f"<th scope=col>{t('report.head.median_duration')}</th></tr></thead><tbody>{speed_rows}</tbody></table></div>"
                 f"<div class=\"scroll\"><table><thead><tr><th scope=col>{t('report.head.month')}</th><th scope=col>{t('report.head.deadlines_evaluated')}</th>"
                 f"<th scope=col>{t('result.early')}</th><th scope=col>{t('result.on_time')}</th><th scope=col>{t('result.late')}</th>"
                 f"<th scope=col>{t('report.head.early_rate')}</th><th scope=col>{t('report.head.late_rate')}</th></tr></thead>"
                 f"<tbody>{deadline_rows}</tbody></table></div></details><p class=\"note\">{t('note.trend_v15' if v15 else 'note.trend')}</p></section>")

    reasons = "".join(f"<li>{loc.tech(reason)}: {loc.num(count)}</li>" for reason, count in coverage["exclusions_by_reason"].items()) or f"<li>{t('common.none')}</li>"
    states = "".join(f"<li>{loc.tech(state)}: {loc.num(count)}</li>" for state, count in coverage["states"].items() if count)
    parts.append(f"<section class=\"card\"><h2>{t('report.coverage_title')}</h2><ul>{reasons}</ul><ul>{states}</ul><p class=\"note\">{t('note.not_attributed')}</p></section>")

    def deadline_attr(result: str | None) -> str:
        return f' data-classification="{escape(result or "not_classifiable")}"' if v15 else ""

    project_rows = []
    for row in profile["projects"]:
        result = row["deadline_result"]
        if result:
            deadline_cell = Html(f"{t('result.' + result)} {loc.hours(row['deadline_delta_seconds'], signed=True)}")
        else:
            deadline_cell = loc.tech(row["requested_eta_issue"]) if row["requested_eta_issue"] else Html("—")
        ids = row["evidence_event_ids"]
        project_rows.append(
            f"<tr><td>{_item(row['monday_item_id'], monday_item_url, loc)}</td><td>{loc.tech(row['ready_for_approval_at'] or '—')}</td>"
            f"<td>{loc.hours(row['duration_seconds'])}</td><td>{loc.labels(row['cohort_labels'])}</td>"
            f"<td class=\"{escape(result or '')}\"{deadline_attr(result)}>{deadline_cell}</td>"
            f"<td>{loc.comma().join(loc.src(label) for label in row['quality_labels']) or '—'}</td><td>{loc.num(row['client_revision_events'])}</td>"
            f"<td>{loc.comma().join(loc.tech(reason) for reason in row['exclusions']) or t('evidence.included_lower')}</td>"
            f"<td>{loc.tech(ids['in_progress'])}<br>{loc.tech(ids['ready_for_approval'])}</td></tr>")
    parts.append(f"<section class=\"card\"><h2>{t('report.projects_title')}</h2><details><summary>{t('report.show_projects', n=loc.num(len(profile['projects'])))}"
                 f"</summary><div class=\"scroll\"><table><thead><tr><th scope=col>{t('report.head.item')}</th>"
                 f"<th scope=col>{t('field.ready_for_approval')}</th><th scope=col>{t('report.head.duration')}</th><th scope=col>{t('field.video_type')}</th>"
                 f"<th scope=col>{t('field.deadline')}</th><th scope=col>{t('common.issue_signals')}</th><th scope=col>{t('report.head.client_revisions')}</th>"
                 f"<th scope=col>{t('evidence.metric_status')}</th><th scope=col>{t('report.head.events')}</th></tr></thead><tbody>{''.join(project_rows)}</tbody></table></div></details></section>")
    parts.append("</main></body></html>")
    return "".join(parts)
