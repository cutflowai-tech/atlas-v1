"""Static, self-contained HTML for the CEO Dashboard document (presentation only).

The page formats values already present in the dashboard document (hours, percentages, month
names). It computes no metric, comparison or conclusion. Each Editor's full Editor Profile page
(``profile_html``) is embedded unchanged and opened from the Editor's card, so the evidence
behind every figure stays one click away.
"""

from __future__ import annotations

import json
from html import escape
from typing import Any

from atlas_commander.management import PENDING_RULES
from atlas_commander.profile_html import CONCLUSION_TEXT, STATUS_TEXT

NOT_APPROVED = "Rule not approved yet"

CSS = """
:root{color-scheme:light;--bg:#f4f4f1;--card:#fcfcfb;--ink:#0b0b0b;--muted:#52514e;--faint:#8a8984;--line:#e3e2dc;--accent:#2a78d6;
--early:#0ca30c;--late:#d03b3b;--ontime:#8a8984;--chip:#efeee9;--warn-ink:#7a5200;--warn-bg:#fff4db}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#121211;--card:#1a1a19;--ink:#fff;--muted:#c3c2b7;
--faint:#8f8e86;--line:#33322d;--accent:#3987e5;--chip:#26261f;--warn-ink:#f3c969;--warn-bg:#2b2413}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#121211;--card:#1a1a19;--ink:#fff;--muted:#c3c2b7;--faint:#8f8e86;--line:#33322d;--accent:#3987e5;
--chip:#26261f;--warn-ink:#f3c969;--warn-bg:#2b2413}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}h1{font-size:26px;margin:0}h2{font-size:18px;margin:0 0 12px}h3{font-size:15px;margin:0}
a{color:var(--accent)}.sub{color:var(--muted);font-size:13px}.faint{color:var(--faint)}code{font-size:12px}
.banner{margin:14px 0 20px;padding:10px 14px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--muted);font-size:13px}
.pending{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 20px}.chip{display:inline-flex;gap:6px;align-items:center;padding:4px 10px;border-radius:99px;
background:var(--chip);font-size:12px;color:var(--muted)}.chip b{color:var(--ink);font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;display:flex;flex-direction:column;gap:10px;min-width:0}
.card header{display:flex;justify-content:space-between;align-items:baseline;gap:8px}.big{font-size:22px;font-weight:650}
.row{display:grid;grid-template-columns:92px 1fr;gap:8px;font-size:13.5px}.row>span:first-child{color:var(--muted)}
.empty{color:var(--faint);font-style:italic}.status{font-size:12px;color:var(--muted)}
.split{display:flex;gap:2px;height:8px;margin:4px 0 2px;border-radius:4px;overflow:hidden;background:var(--line)}
.split i{display:block;height:100%}.split .e{background:var(--early)}.split .o{background:var(--ontime)}.split .l{background:var(--late)}
.key{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:4px;vertical-align:baseline}
.warns{display:flex;flex-direction:column;gap:4px}.warn{font-size:12px;color:var(--warn-ink);background:var(--warn-bg);border-radius:6px;padding:4px 8px}
.open{align-self:flex-start;margin-top:auto;padding:7px 14px;border-radius:8px;border:1px solid var(--accent);color:var(--accent);text-decoration:none;font-size:13.5px;font-weight:600}
section.block{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin:16px 0}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}.scroll{overflow-x:auto}
.qa{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}.qa>div{border:1px solid var(--line);border-radius:10px;padding:12px}
.qa ul{margin:6px 0 0;padding-left:18px;font-size:13.5px}.qa .judgement{font-size:12.5px;margin-top:6px}
.back{display:inline-block;margin-bottom:12px;font-size:13.5px}iframe{width:100%;height:80vh;border:1px solid var(--line);border-radius:12px;background:var(--card)}
.view[hidden]{display:none}.note{color:var(--muted);font-size:12.5px;margin:8px 0 0}
"""

SCRIPT = """
(function(){
  var profiles = JSON.parse(document.getElementById('atlas-profiles').textContent);
  function show(){
    var m = location.hash.match(/^#\\/editor\\/(.+)$/), id = m ? decodeURIComponent(m[1]) : null;
    var views = document.querySelectorAll('.view'), found = false;
    for (var i = 0; i < views.length; i++) {
      var match = id ? views[i].getAttribute('data-editor') === id : views[i].id === 'team';
      views[i].hidden = !match; found = found || match;
      var frame = match && id ? views[i].querySelector('iframe') : null;
      if (frame && !frame.getAttribute('data-loaded') && profiles[id]) { frame.srcdoc = profiles[id]; frame.setAttribute('data-loaded', '1'); }
    }
    if (!found) { document.getElementById('team').hidden = false; }
    window.scrollTo(0, 0);
  }
  window.addEventListener('hashchange', show); show();
})();
"""


def _h(seconds: Any) -> str:
    return "—" if seconds is None else f"{seconds / 3600:.1f} h"


def _signed_h(seconds: Any) -> str:
    return "—" if seconds is None else f"{seconds / 3600:+.1f} h"


def _pct(rate: Any) -> str:
    return "—" if rate is None else f"{rate * 100:.1f}%"


def _empty(text: str) -> str:
    return f'<span class="empty">{escape(text)}</span>'


def _split(early: int, on_time: int, late: int) -> str:
    total = early + on_time + late
    if not total:
        return ""
    title = f"{early} early, {on_time} on time, {late} late of {total}"
    segments = "".join(f'<i class="{cls}" style="flex:{n}"></i>' for cls, n in (("e", early), ("o", on_time), ("l", late)) if n)
    return f'<div class="split" role="img" aria-label="{title}" title="{title}">{segments}</div>'


def _deadline_line(d: dict[str, Any]) -> str:
    if not d.get("evaluated"):
        return _empty("Not enough data: no classified deadlines")
    return (f"{_split(d['early'], d['on_time'], d['late'])}<b>{d['early']}</b> early · <b>{d['on_time']}</b> on time · <b>{d['late']}</b> late "
            f"<span class=\"faint\">of {d['evaluated']} · median margin {_signed_h(d.get('median_delta_seconds'))}</span>")


def _speed_line(speed: dict[str, Any]) -> str:
    compared = speed["compared_cohorts"]
    if not compared:
        counts = ", ".join(f"{n} {STATUS_TEXT.get(status, status).lower()}" for status, n in speed["comparison_status_counts"].items())
        return _empty("No speed comparison available") + (f'<div class="status">{escape(counts)}</div>' if counts else "")
    lines = []
    for c in compared:
        lines.append(f"<div>{escape(' + '.join(c['labels']))}: <b>{_h(c['editor_median_seconds'])}</b> vs team {_h(c['team_median_seconds'])} · "
                     f"{escape(CONCLUSION_TEXT[c['conclusion']])} <span class=\"faint\">(n={c['editor_sample_size']} of {c['team_sample_size']}, "
                     f"{c['team_editor_count']} Editors)</span></div>")
    others = len(speed["cohorts"]) - len(compared)
    return "".join(lines) + (f'<div class="status">{others} other Video Type cohorts not comparable or below the minimum sample</div>' if others else "")


def _issues_line(q: dict[str, Any]) -> str:
    if not q["total_occurrences"]:
        return _empty("No Performance Issue labels")
    labels = " · ".join(f"{escape(row['label'])} {row['occurrences']}" for row in q["by_label"])
    return f"<b>{q['total_occurrences']}</b> labels on {q['projects_with_issues']} projects <div class=\"status\">{labels}</div>"


def _workload_line(w: dict[str, Any]) -> str:
    if not w["by_current_status"]:
        return _empty("No current items")
    return " · ".join(f"{escape(status)} <b>{n}</b>" for status, n in w["by_current_status"].items())


def _latest_line(monthly: list[dict[str, Any]]) -> str:
    rows = [m for m in monthly if m["deadline"]][:2]
    if not rows:
        return _empty("Not enough data")
    out = []
    for m in rows:
        d = m["deadline"]
        partial = ' <span class="faint">(in progress)</span>' if m["partial"] else ""
        out.append(f"<div>{escape(m['month_name'])}{partial}: "
                   f"{d['evaluated']} deadlines · {d['early']} early · {d['late']} late</div>")
    return "".join(out)


def _card(s: dict[str, Any]) -> str:
    sample = s["sample"]
    warns = "".join(f'<div class="warn" title="{escape(w["source"])}">{escape(w["text"])}</div>' for w in s["warnings"])
    revisions = s["revisions"]
    return (f'<article class="card"><header><div><h3 class="big">{escape(s["display_name"])}</h3>'
            f'<div class="sub">Monday Editor label {escape(str(s["monday_label"]))}</div></div>'
            f'<div style="text-align:right"><b class="big">{sample["completed_projects"]}</b><div class="sub">completed projects</div></div></header>'
            f'<div class="row"><span>Overall</span><span>{_empty(NOT_APPROVED)}</span></div>'
            f'<div class="row"><span>Speed</span><span>{_speed_line(s["speed"])}</span></div>'
            f'<div class="row"><span>Deadline</span><span>{_deadline_line(s["deadline"])}</span></div>'
            f'<div class="row"><span>Perf. issues</span><span>{_issues_line(s["quality"])}</span></div>'
            f'<div class="row"><span>Positive</span><span>{_empty("No signal available · " + NOT_APPROVED.lower())}</span></div>'
            f'<div class="row"><span>Workload</span><span>{_workload_line(s["current_workload"])}</span></div>'
            f'<div class="row"><span>Recent</span><span>{_latest_line(s["monthly"])}</span></div>'
            f'<div class="row"><span>Revisions</span><span class="faint">{revisions["client_revision_events"]} client revision events on '
            f'{revisions["projects_with_client_revisions"]} projects · context only</span></div>'
            f'{f"<div class=warns>{warns}</div>" if warns else ""}'
            f'<a class="open" href="#/editor/{escape(s["editor_id"])}">Open Editor profile →</a></article>')


def _team_sections(doc: dict[str, Any]) -> str:
    names = {s["editor_id"]: s["display_name"] for s in doc["editors"]}
    order = [s["editor_id"] for s in doc["editors"]]
    team = doc["team"]
    head = "".join(f'<th class="num">{escape(names[e])}</th>' for e in order)

    label_rows = "".join(f"<tr><td>{escape(row['label'])}</td>" + "".join(f'<td class="num">{row["editors"].get(e, "—")}</td>' for e in order)
                         + f'<td class="num">{row["editor_count"]}</td></tr>' for row in team["issue_labels_by_editor"])
    labels = (f'<section class="block"><h2>Performance Issue labels across Editors</h2><div class="scroll"><table><thead><tr><th>Label</th>{head}'
              f'<th class="num">Editors with label</th></tr></thead><tbody>{label_rows or "<tr><td colspan=99>No Performance Issue labels.</td></tr>"}'
              '</tbody></table></div><p class="note">Counts of Monday Performance Issues labels, 1 occurrence = 1 label. Whether a label shared by several '
              f'Editors is a team or process pattern: {NOT_APPROVED.lower()}.</p></section>')

    workload = team["workload_by_editor"]
    work_rows = "".join(f"<tr><td>{escape(names[e])}</td>" + "".join(f'<td class="num">{workload["rows"][e].get(st, "—")}</td>' for st in workload["statuses"])
                        + "</tr>" for e in order)
    work_head = "".join(f'<th class="num">{escape(st)}</th>' for st in workload["statuses"])
    work = (f'<section class="block"><h2>Current items by Monday status</h2><div class="scroll"><table><thead><tr><th>Editor</th>{work_head}</tr></thead>'
            f'<tbody>{work_rows}</tbody></table></div><p class="note">Items whose current Editor Name is the Editor, grouped by their current status. '
            f'Which statuses count as active workload, and any capacity judgement: {NOT_APPROVED.lower()} (open decision 5).</p></section>')

    months = team["deadline_by_editor_month"]["months"]
    month_head = "".join(f'<th class="num">{escape(m["month_name"])}</th>' for m in months)
    cells = []
    for e in order:
        row = team["deadline_by_editor_month"]["rows"][e]
        tds = "".join((f'<td class="num">{row[m["month"]]["late"]}/{row[m["month"]]["evaluated"]}</td>' if m["month"] in row else '<td class="num faint">—</td>')
                      for m in months)
        cells.append(f"<tr><td>{escape(names[e])}</td>{tds}</tr>")
    movement = (f'<section class="block"><h2>Monthly deadlines: late / classified</h2><div class="scroll"><table><thead><tr><th>Editor</th>{month_head}</tr></thead>'
                f'<tbody>{"".join(cells)}</tbody></table></div><p class="note">UTC month of Ready For Approval. Each cell is late deliveries over classified '
                f'deadlines for that month. Improving / declining: {NOT_APPROVED.lower()}.</p></section>')

    coverage = doc.get("attribution_coverage")
    cov = ""
    if coverage:
        reasons = "".join(f"<li><code>{escape(r)}</code>: {n}</li>" for r, n in coverage["not_attributed_by_reason"].items())
        cov = (f'<section class="block"><h2>Projects not attributed to any Editor</h2><p>{coverage["attributed"]} of {coverage["completed"]} completed projects '
               f'in this snapshot have a verified Editor. The rest are not shown on any Editor:</p><ul>{reasons}</ul>'
               '<p class="note">Unverified Editor labels stay quarantined until their identity is confirmed (D9, D16, D17).</p></section>')
    missing = "".join(f"<li>{escape(e['display_name'])} <span class=\"faint\">(label {escape(str(e['monday_label']))})</span></li>"
                      for e in doc["editors_without_attributable_data"])
    if missing:
        cov += (f'<section class="block"><h2>Mapped Editors without attributable projects</h2><ul>{missing}</ul>'
                '<p class="note">These Editors are in the verified mapping but no completed or open project in this snapshot is attributed to them, '
                'so they have no profile.</p></section>')
    return labels + work + movement + cov


def _pending_section() -> str:
    rows = "".join(f"<tr><td>{escape(rule['label'])}</td><td>{escape(NOT_APPROVED)}</td><td>{escape(rule['reason'])}</td></tr>" for rule in PENDING_RULES.values())
    return (f'<section class="block"><h2>Not shown yet, and why</h2><div class="scroll"><table><thead><tr><th>Field</th><th>State</th><th>Reason</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></section>')


def _editor_view(s: dict[str, Any]) -> str:
    qa = []
    for block in s["snapshot"]:
        facts = "".join(f"<li>{escape(f)}</li>" for f in block["facts"]) or f'<li>{_empty("No signal available")}</li>'
        judgement = block["judgement"]
        judgement_html = (f'<div class="judgement">{escape(judgement["label"])}: {_empty(NOT_APPROVED)}</div>' if judgement else "")
        qa.append(f"<div><h3>{escape(block['question'])}</h3>{judgement_html}<ul>{facts}</ul></div>")

    month_rows = []
    for m in s["monthly"]:
        d = m["deadline"]
        speed = "<br>".join(f"{escape(' + '.join(c['labels']) or c['cohort_key'])}: {_h(c['median_seconds'])} <span class=\"faint\">(n={c['projects']})</span>"
                            for c in sorted(m["speed_by_cohort"], key=lambda c: -c["projects"])) or "—"
        deadline_cells = (f'<td>{_split(d["early"], d["on_time"], d["late"])}</td><td class="num">{d["evaluated"]}</td><td class="num">{d["early"]}</td>'
                          f'<td class="num">{d["on_time"]}</td><td class="num">{d["late"]}</td><td class="num">{_pct(d["late_rate"])}</td>'
                          if d else '<td></td><td class="num faint" colspan=5>no classified deadlines</td>')
        month_rows.append(f"<tr><td>{escape(m['month_name'])}{' <span class=faint>(in progress)</span>' if m['partial'] else ''}</td>{deadline_cells}"
                          f"<td>{speed}</td></tr>")
    monthly = (f'<section class="block"><h2>Monthly history</h2><div class="scroll"><table><thead><tr><th>Month</th><th style="min-width:120px">Deadlines</th>'
               '<th class="num">Classified</th><th class="num">Early</th><th class="num">On time</th><th class="num">Late</th><th class="num">Late rate</th>'
               f'<th>Median work duration per exact Video Type</th></tr></thead><tbody>{"".join(month_rows) or "<tr><td colspan=8>Not enough data.</td></tr>"}'
               '</tbody></table></div><p class="note"><span class="key" style="background:var(--early)"></span>early '
               '<span class="key" style="background:var(--ontime)"></span>on time <span class="key" style="background:var(--late)"></span>late · '
               'Most recent month first. Speed is shown only per exact benchmark-eligible Video Type cohort, never pooled. '
               f'Improving / declining: {NOT_APPROVED.lower()}.</p></section>')

    warns = "".join(f'<div class="warn">{escape(w["text"])}</div>' for w in s["warnings"])
    return (f'<div class="view" id="editor-{escape(s["editor_id"])}" data-editor="{escape(s["editor_id"])}" hidden>'
            f'<a class="back" href="#/">← Team overview</a><h1>{escape(s["display_name"])}</h1>'
            f'<div class="sub">Monday Editor label {escape(str(s["monday_label"]))} · {s["sample"]["completed_projects"]} completed projects · '
            f'Overall status: {escape(NOT_APPROVED)}</div>'
            f'{f"<div class=warns style=margin-top:12px>{warns}</div>" if warns else ""}'
            f'<section class="block"><h2>Management snapshot</h2><div class="qa">{"".join(qa)}</div>'
            '<p class="note">Facts come from the deterministic Atlas engine. Judgements such as needs-attention, positive signals, trend and capacity '
            'have no approved rule yet and are left empty.</p></section>'
            f'{monthly}<section class="block"><h2>Full Editor Profile and evidence</h2>'
            f'<iframe title="Editor Profile: {escape(s["display_name"])}" loading="lazy"></iframe></section></div>')


def render_dashboard_html(doc: dict[str, Any], profile_pages: dict[str, str]) -> str:
    """Render the dashboard. ``profile_pages`` maps editor_id -> that Editor's full profile HTML (embedded unchanged)."""
    source = doc["source"]
    window = source.get("activity_log_window") or {}
    blob = json.dumps(profile_pages).replace("</", "<\\/")
    chips = "".join(f'<span class="chip"><b>{escape(slot["label"])}</b>{escape(NOT_APPROVED)}</span>' for slot in doc["team"]["intelligence"].values())
    cards = "".join(_card(s) for s in doc["editors"]) or f"<p>{_empty('No Editor has attributable projects in this snapshot.')}</p>"
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>Atlas Team Overview</title><style>{CSS}</style></head><body><main>"
            f'<div class="view" id="team"><h1>Editor team overview</h1>'
            f'<div class="sub">Monday data retrieved {escape(str(source.get("retrieved_at")))} · activity from {escape(str(window.get("since")))} · '
            f'contract {escape(str(source.get("executable_contract_version")))} · generated {escape(doc["generated_at"])}</div>'
            '<div class="banner">A summary of each Editor\'s Atlas profile. Every figure comes from Monday evidence through the deterministic engine; '
            'open an Editor to see the projects and Monday events behind it. No overall score or status is approved in V1, and revisions are context only.</div>'
            f'<div class="pending">{chips}</div><div class="grid">{cards}</div>{_team_sections(doc)}{_pending_section()}</div>'
            f'{"".join(_editor_view(s) for s in doc["editors"])}'
            f'<script type="application/json" id="atlas-profiles">{blob}</script><script>{SCRIPT}</script></main></body></html>')
