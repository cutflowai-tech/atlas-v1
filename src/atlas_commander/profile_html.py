"""Static HTML view of an editor-profile 1.3.0 document.

The page only formats values that are already in the profile (durations as hours, rates as
percentages). It never computes a metric, a comparison or a conclusion.
"""

from __future__ import annotations

from html import escape
from typing import Any

CONCLUSION_TEXT = {
    "faster_than_team_median": "Faster than team median",
    "slower_than_team_median": "Slower than team median",
    "equal_to_team_median": "Equal to team median",
    "insufficient_sample": "Insufficient sample",
    "not_comparable": "Not comparable",
}
STATUS_TEXT = {
    "comparable": "Comparable",
    "insufficient_editor_sample": "Fewer than the minimum Editor projects",
    "cohort_not_benchmark_eligible": "Video Type combination not approved for benchmarking",
    "no_other_editors_in_cohort": "No other Editor in this cohort",
    "minimum_sample_size_not_configured": "Minimum sample not configured",
}

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--muted:#5f5f5a;--line:#e3e2dc;--good:#1f7a4d;--warn:#9a6700;--bad:#b3261e;--accent:#2f5bb7}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--card:#1f1f1c;--ink:#ecebe6;--muted:#a8a79f;--line:#34332e;--good:#5fc38f;--warn:#e0b050;--bad:#f08a80;--accent:#8fb0ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{font-size:26px;margin:0}h2{font-size:18px;margin:0 0 12px}
.sub{color:var(--muted);font-size:13px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px;margin:16px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.tile{border:1px solid var(--line);border-radius:8px;padding:10px}
.tile b{display:block;font-size:22px}.tile span{color:var(--muted);font-size:12px}.note{color:var(--muted);font-size:13px;margin:8px 0 0}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600}.scroll{overflow-x:auto}.pill{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;border:1px solid var(--line)}
.faster_than_team_median{color:var(--good)}.slower_than_team_median{color:var(--bad)}.insufficient_sample,.not_comparable{color:var(--muted)}
.early{color:var(--good)}.late{color:var(--bad)}code{font-size:12px}details summary{cursor:pointer;color:var(--accent)}
"""


def _h(seconds: Any) -> str:
    return "—" if seconds is None else f"{seconds / 3600:.1f} h"


def _pct(rate: Any) -> str:
    return "—" if rate is None else f"{rate * 100:.1f}%"


def _signed_pct(value: Any) -> str:
    return "—" if value is None else f"{value:+.1f}%"


def _signed_h(seconds: Any) -> str:
    return "—" if seconds is None else f"{seconds / 3600:+.1f} h"


def _item(item_id: str, url_template: str | None) -> str:
    text = escape(str(item_id))
    return f'<a href="{escape(url_template.format(item_id=item_id))}" rel="noopener">{text}</a>' if url_template else text


def render_profile_html(profile: dict[str, Any], monday_item_url: str | None = None) -> str:
    """Render the profile. ``monday_item_url`` may contain ``{item_id}`` to link each project to Monday."""
    editor = profile["editor"]
    speed, deadline, quality, revisions, coverage = profile["speed"], profile["deadline"], profile["quality"], profile["revisions"], profile["coverage"]
    summary = deadline["summary"]
    parts = [(f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
              f"<title>Atlas Editor Profile</title><style>{CSS}</style></head><body><main>")]
    parts.append(f"<h1>{escape(editor['display_name'])}</h1><div class=\"sub\">Editor <code>{escape(editor['editor_id'])}</code> · "
                 f"Monday label {escape(editor['monday_person_id'])} · mapping {escape(editor['mapping_version'])} · contract "
                 f"{escape(profile['executable_contract_version'])} · data retrieved {escape(str(profile['source'].get('retrieved_at')))} · "
                 f"generated {escape(profile['generated_at'])}</div>")

    parts.append("<section class=\"card\"><h2>Overall picture</h2><div class=\"tiles\">"
                 f"<div class=\"tile\"><b>{coverage['completed_projects']}</b><span>completed projects</span></div>"
                 f"<div class=\"tile\"><b>{coverage['speed_eligible_projects']}</b><span>measurable for speed</span></div>"
                 f"<div class=\"tile\"><b>{_pct(summary.get('early_rate'))}</b><span>early deliveries ({summary['early']}/{summary['evaluated']})</span></div>"
                 f"<div class=\"tile\"><b>{_pct(summary.get('late_rate'))}</b><span>late deliveries ({summary['late']}/{summary['evaluated']})</span></div>"
                 f"<div class=\"tile\"><b>{quality['negative']['total_occurrences']}</b><span>performance issue labels</span></div>"
                 f"</div><p class=\"note\">{escape(profile['overall']['note'])}</p></section>")

    rows = []
    # Display order only: largest Editor samples first.
    for cohort in sorted(speed["cohorts"], key=lambda c: (-c["editor_sample_size"], c["cohort_key"])):
        # A difference against a "team" that is only this Editor is not shown as a comparison.
        shown_pct = cohort.get("editor_vs_team_median_pct") if cohort["comparison_status"] != "no_other_editors_in_cohort" else None
        conclusion = cohort["conclusion"]
        rows.append(f"<tr><td>{escape(' + '.join(cohort['cohort_labels']))}<br><code>{escape(cohort['cohort_key'])}</code></td>"
                    f"<td>{_h(cohort['editor_median_seconds'])}<br><span class=\"sub\">n={cohort['editor_sample_size']}</span></td>"
                    f"<td>{_h(cohort['team_median_seconds'])}<br><span class=\"sub\">n={cohort['team_sample_size'] if cohort['team_sample_size'] is not None else '—'}</span></td>"
                    f"<td>{_signed_pct(shown_pct)}</td>"
                    f"<td>{_h((cohort.get('team_typical_range_seconds') or {}).get('p25'))} – {_h((cohort.get('team_typical_range_seconds') or {}).get('p75'))}</td>"
                    f"<td class=\"{escape(conclusion)}\">{escape(CONCLUSION_TEXT.get(conclusion, conclusion))}<br>"
                    f"<span class=\"sub\">{escape(STATUS_TEXT.get(cohort['comparison_status'], cohort['comparison_status']))}</span></td></tr>")
    parts.append("<section class=\"card\"><h2>Speed by exact Video Type</h2><div class=\"scroll\"><table><thead><tr><th>Video Type cohort</th>"
                 "<th>Editor median</th><th>Team median</th><th>Difference</th><th>Team typical range (P25–P75)</th><th>Conclusion</th></tr></thead>"
                 f"<tbody>{''.join(rows) or '<tr><td colspan=6>No measurable projects.</td></tr>'}</tbody></table></div>"
                 f"<p class=\"note\">Work duration is elapsed time from the first In Progress to the first Ready For Approval. The team benchmark "
                 f"is the {escape(speed['benchmark_statistic'])} of every eligible Editor in the same exact Video Type cohort, including this Editor. "
                 f"A faster/slower conclusion needs at least {speed['minimum_editor_sample_size']} of this Editor's projects in the cohort and at "
                 "least one other Editor. The typical range is descriptive only.</p></section>")

    parts.append("<section class=\"card\"><h2>Deadline performance</h2><div class=\"tiles\">"
                 f"<div class=\"tile\"><b class=\"early\">{summary['early']}</b><span>early · {_pct(summary.get('early_rate'))}</span></div>"
                 f"<div class=\"tile\"><b>{summary['on_time']}</b><span>on time (exactly at ETA) · {_pct(summary.get('on_time_rate'))}</span></div>"
                 f"<div class=\"tile\"><b class=\"late\">{summary['late']}</b><span>late · {_pct(summary.get('late_rate'))}</span></div>"
                 f"<div class=\"tile\"><b>{_signed_h(summary.get('median_delta_seconds'))}</b><span>median margin (negative = early)</span></div>"
                 f"<div class=\"tile\"><b>{summary['not_classifiable_insufficient_eta_precision']}</b><span>ETA without a time (not classified)</span></div>"
                 f"<div class=\"tile\"><b>{summary.get('not_classifiable_missing_eta', 0)}</b><span>no ETA</span></div>"
                 "</div><p class=\"note\">Ready For Approval compared with the latest Requested ETA. No tolerance: exactly at the ETA is on time.</p></section>")

    labels = "".join(f"<tr><td>{escape(row['label'])}</td><td>{row['occurrences']}</td><td>{', '.join(_item(i, monday_item_url) for i in row['monday_item_ids'])}</td></tr>"
                     for row in quality["negative"]["by_label"])
    bonus = quality["for_bonus_context"]
    parts.append("<section class=\"card\"><h2>Quality</h2><div class=\"tiles\">"
                 f"<div class=\"tile\"><b>{quality['negative']['total_occurrences']}</b><span>performance issue labels</span></div>"
                 f"<div class=\"tile\"><b>{quality['negative']['projects_with_issues']}</b><span>projects with issues of {quality['negative']['completed_projects_attributed']}</span></div>"
                 f"<div class=\"tile\"><b>{quality['positive']['count']}</b><span>positive signals</span></div>"
                 f"<div class=\"tile\"><b>{len(bonus['projects'])}</b><span>projects with For Bonus (context)</span></div>"
                 f"</div><div class=\"scroll\"><table><thead><tr><th>Label</th><th>Occurrences</th><th>Projects</th></tr></thead><tbody>"
                 f"{labels or '<tr><td colspan=3>No performance issue labels.</td></tr>'}</tbody></table></div>"
                 f"<p class=\"note\">Each Monday Performance Issues label counts once, with no severity weights. {escape(quality['positive']['note'])}</p></section>")

    parts.append("<section class=\"card\"><h2>Revisions (context only)</h2><div class=\"tiles\">"
                 f"<div class=\"tile\"><b>{revisions['client_revision_events']}</b><span>client revision events</span></div>"
                 f"<div class=\"tile\"><b>{revisions['projects_with_client_revisions']}</b><span>projects with revisions of {revisions['completed_projects']}</span></div>"
                 f"<div class=\"tile\"><b>{_pct(revisions['client_revision_rate'])}</b><span>revision rate</span></div>"
                 f"</div><p class=\"note\">{escape(revisions['note'])}</p></section>")

    workload = profile["current_workload"]
    workload_rows = "".join(f"<tr><td>{escape(status)}</td><td>{len(items)}</td><td>{', '.join(_item(i, monday_item_url) for i in items)}</td></tr>"
                            for status, items in sorted(workload["by_current_status"].items(), key=lambda pair: -len(pair[1])))
    parts.append(f"<section class=\"card\"><h2>Current items (as of {escape(str(workload['as_of']))})</h2><div class=\"scroll\"><table><thead><tr>"
                 f"<th>Current status</th><th>Items</th><th>Projects</th></tr></thead><tbody>{workload_rows or '<tr><td colspan=3>None.</td></tr>'}"
                 f"</tbody></table></div><p class=\"note\">{escape(workload['note'])}</p></section>")

    trend = profile["trend"]
    speed_rows = "".join(f"<tr><td><code>{escape(row['cohort_key'])}</code></td><td>{escape(row['month'])}</td><td>{row['projects']}</td><td>{_h(row['median_seconds'])}</td></tr>"
                         for row in trend["speed_by_cohort_month"])
    deadline_rows = "".join(f"<tr><td>{escape(row['month'])}</td><td>{row['evaluated']}</td><td class=\"early\">{row['early']}</td><td>{row['on_time']}</td>"
                            f"<td class=\"late\">{row['late']}</td><td>{_pct(row['early_rate'])}</td><td>{_pct(row['late_rate'])}</td></tr>" for row in trend["deadline_by_month"])
    parts.append("<section class=\"card\"><h2>By month</h2><details><summary>Show monthly figures</summary><div class=\"scroll\"><table><thead><tr>"
                 f"<th>Cohort</th><th>Month</th><th>Projects</th><th>Median duration</th></tr></thead><tbody>{speed_rows}</tbody></table></div>"
                 "<div class=\"scroll\"><table><thead><tr><th>Month</th><th>Deadlines evaluated</th><th>Early</th><th>On time</th><th>Late</th><th>Early rate</th><th>Late rate</th></tr></thead>"
                 f"<tbody>{deadline_rows}</tbody></table></div></details><p class=\"note\">{escape(trend['note'])}</p></section>")

    reasons = "".join(f"<li><code>{escape(reason)}</code>: {count}</li>" for reason, count in coverage["exclusions_by_reason"].items()) or "<li>None</li>"
    states = "".join(f"<li><code>{escape(state)}</code>: {count}</li>" for state, count in coverage["states"].items() if count)
    parts.append(f"<section class=\"card\"><h2>Data coverage</h2><ul>{reasons}</ul><ul>{states}</ul><p class=\"note\">{escape(coverage['not_attributed_note'])}</p></section>")

    project_rows = []
    for row in profile["projects"]:
        result = row["deadline_result"]
        project_rows.append(
            f"<tr><td>{_item(row['monday_item_id'], monday_item_url)}</td><td>{escape(str(row['ready_for_approval_at'] or '—'))}</td>"
            f"<td>{_h(row['duration_seconds'])}</td><td>{escape(' + '.join(row['cohort_labels']) or '—')}</td>"
            f"<td class=\"{escape(result or '')}\">{escape(result or (row['requested_eta_issue'] or '—'))} {_signed_h(row['deadline_delta_seconds']) if result else ''}</td>"
            f"<td>{escape(', '.join(row['quality_labels']) or '—')}</td><td>{row['client_revision_events']}</td>"
            f"<td>{escape(', '.join(row['exclusions']) or 'included')}</td>"
            f"<td><code>{escape(str(row['evidence_event_ids']['in_progress']))}</code><br><code>{escape(str(row['evidence_event_ids']['ready_for_approval']))}</code></td></tr>")
    parts.append("<section class=\"card\"><h2>Projects and evidence</h2><details><summary>Show all "
                 f"{len(profile['projects'])} projects with their Monday event IDs</summary><div class=\"scroll\"><table><thead><tr><th>Item</th>"
                 "<th>Ready For Approval</th><th>Duration</th><th>Video Type</th><th>Deadline</th><th>Issue labels</th><th>Client revisions</th>"
                 f"<th>Metric status</th><th>In Progress / RFA events</th></tr></thead><tbody>{''.join(project_rows)}</tbody></table></div></details></section>")
    parts.append("</main></body></html>")
    return "".join(parts)
