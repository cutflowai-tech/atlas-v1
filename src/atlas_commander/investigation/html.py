"""Minimal review page for an ``intelligence-v2`` document (Tasks 69-72). This is not the product UI.

It exists so reviewers can read, check and challenge findings before the UI/UX branch designs the real presentation. It is
a single static English page, rendered only from the document (it computes nothing), with no script and no network request.
Evidence sits in native ``<details>`` drawers. Every finding shows, in order:

1. the finding;
2. why Atlas noticed it;
3. its interpretation, labelled as such;
4. contradicting evidence;
5. confidence and the reason for it;
6. limitations;
7. what management may want to investigate;
8. the Monday evidence.

Review-mode documents carry a banner, because they are built on unapproved parameters and must never be published.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape
from typing import Any

SECTIONS = (("needs_attention", "Needs attention"), ("important_improvements", "Important improvements"), ("system_patterns", "System patterns"),
            ("editor_specific_patterns", "Editor-specific patterns"), ("hidden_context", "Hidden context"),
            ("emerging_risk_signals", "Emerging risk signals"), ("data_warnings", "Data warnings"))
CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a64;--line:#e4e1d8;--card:#fff;--accent:#2f4fc4;--high:#c92a2a;--medium:#e67700;--low:#5c7cfa;--info:#2b8a3e;--warn:#fff4e6}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ecebe6;--muted:#a3a29b;--line:#34332f;--card:#1f1f1c;--warn:#3a2a14;--accent:#91a7ff}}
a{color:var(--accent)}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{font-size:24px;margin:0 0 4px}h2{font-size:19px;margin:32px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
h3{font-size:16px;margin:0}.muted{color:var(--muted)}.banner{background:var(--warn);border:1px solid var(--medium);padding:10px 14px;border-radius:8px;margin:12px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
.pill{display:inline-block;border-radius:999px;padding:1px 9px;font-size:12px;border:1px solid var(--line);margin-inline-end:6px;white-space:nowrap}
.sev-high{border-color:var(--high);color:var(--high)}.sev-medium{border-color:var(--medium);color:var(--medium)}.sev-low{border-color:var(--low);color:var(--low)}.sev-info{border-color:var(--info);color:var(--info)}
details{margin:6px 0}summary{cursor:pointer;color:var(--accent)}table{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0}
th,td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:start;vertical-align:top}code{font-size:12px;word-break:break-all}
.label{font-weight:600;margin-top:8px}ul{margin:4px 0;padding-inline-start:20px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px}
"""


def _e(value: Any) -> str:
    return escape("" if value is None else str(value))


def _item(item_id: str, url: str | None) -> str:
    return f'<a href="{_e(url.format(item_id=item_id))}">{_e(item_id)}</a>' if url else _e(item_id)


def _values(values: Mapping[str, Any]) -> str:
    return "; ".join(f"{_e(key)}={_e(value)}" for key, value in values.items())


def _mix(rows: Sequence[Mapping[str, Any]]) -> str:
    return ", ".join(f"{row['labels']} {row['share']:.0%}" for row in rows[:5])


def _evidence(block: Mapping[str, Any], url: str | None) -> str:
    rows = "".join(f"<tr><td>{_item(r['monday_item_id'], url)}</td><td>{_e(r.get('editor_id'))}</td><td>{_e(r.get('cohort_key'))}</td>"
                   f"<td><code>{_e(', '.join(r['event_ids']))}</code></td><td><code>{_e(', '.join(r['source_timestamps']))}</code></td>"
                   f"<td>{_values(r['values'])}</td></tr>" for r in block["records"])
    return (f'<details><summary>{_e(block["role"].capitalize())} evidence · {_e(block["code"])} · {len(block["records"])} Monday records</summary>'
            f'<p><span class="label">Calculation:</span> {_e(block["calculation"])}</p><p><span class="label">Sample:</span> {_values(block["sample"])}'
            + (f' · <span class="label">Compared:</span> <code>{_e(block["comparison"])}</code>' if block["comparison"] else "")
            + f'</p><p class="muted">Board {_e(block["monday_board_id"])} · columns {_e(", ".join(block["column_ids"]))} · window {_e((block.get("time_window") or {}).get("window"))}</p>'
            f"<table><thead><tr><th>Monday item</th><th>Editor</th><th>Video Type</th><th>Event IDs</th><th>Timestamps</th><th>Values used</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></details>")


def finding_card(finding: Mapping[str, Any], names: Mapping[str, str], titles: Mapping[str, str], url: str | None,
                 types: Mapping[str, str] | None = None) -> str:
    text = finding["text"]
    confidence = finding["confidence"]
    factors = "".join(f"<li>{_e(f['factor'].replace('_', ' '))}: {_e(f['assessment'].replace('_', ' '))}"
                      + (f" — {_e(f.get('detail'))}" if f.get("detail") else "") + "</li>" for f in confidence["factors"])
    contradicting = "".join(_evidence(block, url) for block in finding["contradicting_evidence"]) or '<p class="muted">None found.</p>'
    related = "".join(f'<li>{_e(r["relation"].replace("_", " "))}: <a href="#{_e(r["finding_id"])}">{_e(titles.get(r["finding_id"], r["finding_id"]))}</a></li>'
                      for r in finding["related"])
    parameters = "".join(f"<li><code>{_e(p['name'])}</code> = {_e(p['value'])} ({_e(p['status'].replace('_', ' '))}"
                         + (f", {_e(p['decision_id'])}" if p.get("decision_id") else "") + ")</li>" for p in finding["parameters"])
    who = ", ".join(names.get(editor, editor) for editor in finding["affected_editors"][:8])
    return (f'<article class="card" id="{_e(finding["finding_id"])}"><h3>{_e(text["title"])}</h3>'
            f'<p><span class="pill sev-{_e(finding["severity"])}">{_e(finding["severity"])}</span><span class="pill">{_e(confidence["label"])}</span>'
            f'<span class="pill">level: {_e(finding["evidence_level"])}</span><span class="pill">rank {_e(finding["importance"]["rank"])}</span>'
            + ('<span class="pill sev-medium">proposed parameters</span>' if finding["parameter_status"] != "approved" else "")
            + f'</p><p>{_e(text["summary"])}</p>'
            f'<p class="muted">{_e(finding["sample_size"])} projects · Editors: {_e(who) or "—"} · Video Types: {_e(", ".join((types or {}).get(key, key) for key in finding["affected_video_types"][:8])) or "—"}</p>'
            f'<details><summary>Why Atlas noticed it</summary><p>{_e(text["observation"])}</p></details>'
            f'<details><summary>Interpretation (not a fact)</summary><p>{_e(text["interpretation"]) or "—"}</p><p class="muted">{_e(text["hypothesis"])}</p></details>'
            f'<details><summary>Contradicting evidence ({len(finding["contradicting_evidence"])})</summary>{contradicting}</details>'
            f'<details><summary>Confidence: {_e(confidence["label"])}</summary><p>{_e(text["uncertainty"])}</p><ul>{factors}</ul>'
            f'<p class="muted">{_e(confidence["rule"])}</p></details>'
            f'<details><summary>Limitations ({len(text["limitations"])})</summary><ul>{"".join(f"<li>{_e(x)}</li>" for x in text["limitations"])}</ul></details>'
            f'<details open><summary>What management may want to investigate</summary><p><b>{_e(text["investigation_question"])}</b></p>'
            f'<p>{_e(text["suggested_investigation"])}</p><p class="muted">{_e(text["management_significance"])}</p></details>'
            + "".join(_evidence(block, url) for block in [*finding["supporting_evidence"], *finding["context_evidence"]])
            + (f'<details><summary>Related findings ({len(finding["related"])})</summary><ul>{related}</ul></details>' if related else "")
            + f'<details><summary>Parameters</summary><ul>{parameters or "<li>none</li>"}</ul></details></article>')


def render_intelligence_html(document: Mapping[str, Any], monday_item_url: str | None = None) -> str:
    names = {row["editor_id"]: row.get("display_name") or row["editor_id"] for row in document["editors"]}
    findings = {finding["finding_id"]: finding for finding in document["findings"]}
    titles = {key: value["text"]["title"] for key, value in findings.items()}
    sections = document["sections"]

    def cards(ids: Sequence[str]) -> str:
        return "".join(finding_card(findings[i], names, titles, monday_item_url, document["video_types"]) for i in ids) or '<p class="muted">No finding in this section.</p>'

    brief = "".join(f'<div class="card"><h3><a href="#{_e(b["finding_id"])}">{_e(b["title"])}</a></h3><p>{_e(b["what_happened"])}</p>'
                    f'<p><span class="label">Unusual?</span> {_e(b["is_it_unusual"])}</p><p><span class="label">Where:</span> {_e(b["where"])}</p>'
                    f'<p><span class="label">Evidence:</span> {_e(b["evidence"])}</p><p><span class="label">Why it matters:</span> {_e(b["why_it_matters"])}</p>'
                    f'<p><span class="label">Next:</span> {_e(b["next_step"])}</p></div>' for b in document["executive_brief"]) or \
        '<p class="muted">No finding met the evidence and approval rules for this run. Zero findings is a valid result.</p>'
    body = [f"<h1>Atlas Intelligence V2 — {'review' if not document['publishable'] else 'findings'}</h1>",
            (f'<p class="muted">Monday snapshot {_e(document["source"]["retrieved_at"])} · contract {_e(document["executable_contract_version"])} · '
            f'current window {_e(document["windows"]["current"]["start_date"])} to {_e(document["windows"]["current"]["end_date_exclusive"])} (Cairo, end exclusive) · '
             f'generated {_e(document["generated_at"])}</p>')]
    if not document["publishable"]:
        body.append('<div class="banner"><b>Review only — not publishable.</b> Built in review mode: findings marked "proposed parameters" use thresholds '
                    "management has not approved (D25, D53). Nothing here is a management conclusion.</div>")
    body.append(f"<h2>Executive brief</h2>{brief}")
    for key, title in SECTIONS:
        body.append(f"<h2>{_e(title)} ({len(sections[key])})</h2>{cards(sections[key])}")
    suppressed = [finding["finding_id"] for finding in document["findings"] if (finding["cluster"] or {}).get("suppressed_in_sections")]
    if suppressed:
        body.append(f"<h2>Clustered duplicates ({len(suppressed)})</h2><p class=\"muted\">Findings about the same projects, Video Types and direction as a "
                    "higher-ranked finding. They are kept for audit and linked to the primary finding.</p>" + cards(suppressed))
    investigations = "".join(f'<li><a href="#{_e(row["finding_id"])}">{_e(titles.get(row["finding_id"], ""))}</a>: {_e(row["code"].replace("_", " "))}</li>'
                             for row in sections["suggested_investigations"])
    body.append(f"<h2>Suggested investigations</h2><ul>{investigations or '<li>None.</li>'}</ul>")
    insufficient = "".join(f"<tr><td>{_e(row['detector'])}</td><td>{_e(_values(row['reasons']))}</td></tr>" for row in sections["insufficient_evidence"])
    body.append("<h2>Not enough evidence / not approved</h2><p class=\"muted\">Every analysis that ran without producing a finding, with its reason. "
                "rule_not_approved means the threshold it needs has no management approval yet.</p>"
                f"<table><thead><tr><th>Detector</th><th>Reasons (count)</th></tr></thead><tbody>{insufficient}</tbody></table>")
    editors = "".join(f'<div class="card"><h3>{_e(row.get("display_name"))}</h3><p>Strength findings: {len(row["strengths"])} · attention: {len(row["attention"])}'
                      f' · context: {len(row["context"])}</p><details><summary>Fairness context</summary><p>{_e(_values(row["fairness_context"]["sample"]))}</p>'
                      f'<p>Project mix: {_e(_mix(row["fairness_context"]["project_mix"]))}</p>'
                      f'<p>Workload: {_e(_values(row["fairness_context"]["workload"]))}</p><p class="muted">{_e(row["fairness_context"]["note"])}</p></details></div>'
                      for row in document["editors"])
    body.append(f'<h2>Editors</h2><div class="grid">{editors}</div>')
    parameters = "".join(f"<tr><td><code>{_e(p['name'])}</code></td><td>{_e(p['status'])}</td><td>{_e(p['decision_id'])}</td><td>{_e(p['value'])}</td>"
                         f"<td>{_e(p['proposed_value'])}</td><td>{_e(p['meaning'])}</td></tr>" for p in document["parameters"]["parameters"])
    body.append("<h2>Parameters and approval</h2><table><thead><tr><th>Parameter</th><th>Status</th><th>Decision</th><th>Approved value</th>"
                f"<th>Proposed value</th><th>Meaning</th></tr></thead><tbody>{parameters}</tbody></table>")
    return (f'<!doctype html><html lang="en" dir="ltr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>Atlas Intelligence V2</title><style>{CSS}</style></head><body><main>{''.join(body)}</main></body></html>")
