"""Presentation primitives shared by the contract 1.5 app and report pages (formatting only, no decisions).

Every value shown here was computed by the metric engine and copied into the language-neutral view model
(``atlas_commander.dashboard``). Nothing below classifies, compares or recomputes anything: a status, state or verdict is shown
exactly as the profile states it, and its CSS class is chosen from that value.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from html import escape, unescape
from typing import Any

from atlas_commander.i18n import Html, Loc
from atlas_commander.interpretation_html import STATUS_KEYS, reason_text, status_text

# Overall Status keys that are a classification (the other keys say why there is none).
CLASSIFIED = ("strong", "good", "mixed", "below_expectations")
VERDICTS = ("faster", "similar", "slower", "not_classifiable")
RESULTS = ("early", "on_time", "late")

ICONS = {
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "back": '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "doc": '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 13h6M10 17h6"/>',
    "layers": '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.1"/>',
}
DIRECTIONAL = {"arrow", "back"}


def icon(name: str, size: int = 16) -> str:
    flip = ' class="flip"' if name in DIRECTIONAL else ""
    return (f'<svg{flip} width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')


def attr(text: str) -> str:
    return escape(text, quote=True)


@dataclass(frozen=True)
class Ctx:
    """Rendering context: locale, Monday item link template, and whether evidence opens in drawers (the app) or is shown
    inline (the standalone report)."""

    loc: Loc
    url: str | None = None
    interactive: bool = True


# ---------------------------------------------------------------- identity

def initials(name: str) -> str:
    words = [w for w in name.replace("(", " ").replace(")", " ").split() if w[:1].isalpha()]
    return "".join(w[0] for w in words[:2]).upper() or "?"


def avatar(name: str, size: str = "") -> str:
    return f'<span class="avatar {size}" aria-hidden="true"><bdi>{escape(initials(name))}</bdi></span>'


def item_link(item_id: str, ctx: Ctx) -> str:
    text = ctx.loc.tech(item_id)
    return f'<a href="{escape(ctx.url.format(item_id=item_id))}" target="_blank" rel="noopener">{text}</a>' if ctx.url else text


# ---------------------------------------------------------------- status, state, verdict

def status_key(overall: Mapping[str, Any]) -> str:
    """The filter / style group of an Overall Status: one of CLASSIFIED, or ``none`` when there is no status."""
    key = STATUS_KEYS[overall["status_label"]]
    return key if key in CLASSIFIED else "none"


def overall_pill(overall: Mapping[str, Any], loc: Loc, large: bool = False) -> str:
    return (f'<span class="st {status_key(overall)}{" lg" if large else ""}" data-overall-status="{escape(overall["status"] or "")}" '
            f'data-status-state="{escape(overall["status_state"])}">{status_text(overall, loc)}</span>')


def state_chip(state: str, loc: Loc) -> str:
    return f'<span class="sc {escape(state)}" data-state="{escape(state)}">{loc.t("interp.state." + state)}</span>'


def verdict_chip(verdict: str, loc: Loc) -> str:
    return f'<span class="vd {escape(verdict)}" data-verdict="{escape(verdict)}">{loc.t("interp.verdict." + verdict)}</span>'


def reason_span(reason: str | None, loc: Loc, **params: Any) -> str:
    if not reason:
        return ""
    return f'<span class="r" data-reason="{escape(reason)}">{reason_text(reason, loc, **params)}</span>'


def component_name(name: str, loc: Loc) -> Html:
    if name == "overall_lookup":
        return loc.t("interp.component.overall_lookup")
    return loc.t("common." + ("deadlines" if name == "deadline" else name))


def code_text(code: str, loc: Loc) -> Html:
    """A technical reason code in words when the catalogue has it, else the code itself (never English prose on an Arabic page)."""
    for prefix in ("interp.reason.", "status.", "ui.code."):
        if loc.has(prefix + code):
            return loc.t(prefix + code)
    return loc.tech(code)


# ---------------------------------------------------------------- small building blocks

def template(tid: str, title: str, content: str) -> str:
    """Drawer content. ``title`` is plain text (the script sets it with textContent)."""
    return f'<template id="{escape(tid)}" data-title="{attr(title)}">{content}</template>'


def dl(rows: Sequence[tuple[str, str]], cls: str = "") -> str:
    return f'<dl{f" class={cls}" if cls else ""}>' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"


def stat(value: Any, label: str) -> str:
    return f'<div class="stat"><b>{value}</b><span>{label}</span></div>'


def open_link(tid: str, text: str, ctx: Ctx) -> str:
    """A link that opens evidence in the drawer (app only; the report shows the evidence inline instead)."""
    if not ctx.interactive:
        return ""
    return f'<button type="button" class="link" data-drawer="{escape(tid)}">{text}</button>'


def section_head(title: str, sub: str = "", extra: str = "") -> str:
    return f'<div class="sec-h"><div><h2>{title}</h2>{f"<p>{sub}</p>" if sub else ""}</div>{extra}</div>'


_TAG = re.compile(r"<[^>]+>")
_CELL = re.compile(r"<td(?=[\s>])([^>]*)>")
_COLSPAN = re.compile(r"colspan=\"?(\d+)")


def _labelled(rows: str, labels: Sequence[str]) -> str:
    """Give every body cell its column header as ``data-label`` so narrow screens can show each row as a stacked record."""
    def row(match: re.Match[str]) -> str:
        column = 0

        def cell(found: re.Match[str]) -> str:
            nonlocal column
            attrs = found.group(1)
            span = int(m.group(1)) if (m := _COLSPAN.search(attrs)) else 1
            label = labels[column] if span == 1 and column < len(labels) else ""
            column += span
            return f'<td{attrs} role="cell"' + (f' data-label="{attr(label)}">' if label else ">")
        return "<tr" + match.group(1) + ' role="row">' + _CELL.sub(cell, match.group(2)) + "</tr>"
    return re.sub(r"<tr([^>]*)>(.*?)</tr>", row, rows, flags=re.DOTALL)


def table(head: Iterable[str], rows: str, empty: str) -> str:
    """A data table. Below 768 px the stylesheet turns each row into a key/value record (ATLAS-MOBILE-001); explicit roles keep
    the table semantics that ``display: block`` would otherwise remove."""
    head = list(head)
    heads = "".join(f'<th scope=col role="columnheader">{h}</th>' for h in head)
    labels = [unescape(_TAG.sub("", str(h))).strip() for h in head]
    return (f'<div class="tbl"><table role="table"><thead><tr role="row">{heads}</tr></thead>'
            f'<tbody>{_labelled(rows or empty, labels)}</tbody></table></div>')


def meter(value: float, maximum: float, cls: str = "") -> str:
    width = 0.0 if not maximum else max(0.0, min(100.0, value / maximum * 100))
    return f'<div class="track {cls}"><i style="width:{width:.1f}%"></i></div>'


def deadline_stack(d: Mapping[str, Any], loc: Loc) -> str:
    total = sum(d.get(r) or 0 for r in RESULTS)
    if not total:
        return ""
    label = attr(loc.text("deadline.strip_label", early=d["early"], on_time=d["on_time"], late=d["late"], total=total))
    parts = "".join(f'<i class="{r}" style="flex:{d[r]}"></i>' for r in RESULTS if d.get(r))
    return f'<div class="stack" role="img" aria-label="{label}" title="{label}">{parts}</div>'


def deadline_key(loc: Loc) -> str:
    return '<div class="key">' + "".join(f'<span><i class="{r}"></i>{loc.t("result." + r)}</span>' for r in RESULTS) + "</div>"


# ---------------------------------------------------------------- projects (the evidence behind every figure)

def project_tid(editor_id: str, item_id: str) -> str:
    return f"p-{editor_id}-{item_id}"


def project_evidence(editor_name: str, row: Mapping[str, Any], ctx: Ctx) -> str:
    loc = ctx.loc
    result = row["deadline_result"]
    if result:
        deadline = loc.t("evidence.deadline_result", result=loc.t(f"result.{result}"), delta=loc.hours(row["deadline_delta_seconds"], signed=True))
    else:
        issue = row["requested_eta_issue"]
        reason = (loc.t(f"eta_issue.{issue}") if loc.has(f"eta_issue.{issue}") else loc.tech(issue)) if issue else loc.t("common.not_classified")
        deadline = loc.t("evidence.deadline_unclassified", reason=reason)
    set_at = (f' <span class="muted">{loc.t("evidence.eta_set_at", date=loc.when(row["requested_eta_observed_at"]))}</span>'
              if row.get("requested_eta_observed_at") else "")
    duration = loc.hours(row["duration_seconds"]) + ("" if row["speed_eligible"] else Html(" · " + loc.t("evidence.not_used_for_speed")))
    content = dl([
        (loc.t("field.editor"), loc.src(editor_name)),
        (loc.t("field.monday_item"), item_link(row["monday_item_id"], ctx)),
        (loc.t("field.video_type"), loc.labels(row["cohort_labels"])),
        (loc.t("field.work_started"), loc.when(row["in_progress_at"])),
        (loc.t("field.ready_for_approval"), loc.when(row["ready_for_approval_at"])),
        (loc.t("field.work_duration"), duration),
        (loc.t("field.requested_eta"), loc.when(row["requested_eta"]) + set_at),
        (loc.t("field.deadline"), deadline),
    ])
    ignored = row.get("requested_eta_changes_ignored_after_ready_for_approval") or 0
    notes = f'<p>{loc.count("noun.later_eta_change", ignored)}</p>' if ignored else ""
    labels = "".join(f'<span class="chip">{loc.src(label)}</span>' for label in row["quality_labels"]) or f'<span class="muted">{loc.t("evidence.none_recorded")}</span>'
    ids = row["evidence_event_ids"] or {}
    events = "".join(f"<dt>{loc.t(f'event.{k}')}</dt><dd>{loc.tech(v)}</dd>" for k, v in ids.items() if v)
    status = loc.comma().join(code_text(reason, loc) for reason in row["exclusions"]) if row["exclusions"] else loc.t("evidence.included")
    flags = (f'<p class="xs muted">{loc.t("evidence.flags", flags=Html(loc.comma().join(loc.tech(f) for f in row["flags"])))}</p>' if row["flags"] else "")
    return (content + notes
            + f'<h4>{loc.t("ui.labels_on_project")}</h4><div class="chips">{labels}</div>'
            + f'<h4>{loc.t("revisions.context_heading")}</h4><p>{loc.t("evidence.revision_context", events=loc.count("noun.client_revision_event", row["client_revision_events"]))}</p>'
            + f'<h4>{loc.t("evidence.metric_status")}</h4><p>{status}</p>{flags}'
            + f"<h4>{loc.t('evidence.monday_events')}</h4><dl>{events}</dl>")


def project_templates(s: Mapping[str, Any], ctx: Ctx) -> str:
    return "".join(template(project_tid(s["editor_id"], row["monday_item_id"]), ctx.loc.text("evidence.project_title", item=row["monday_item_id"]),
                            project_evidence(s["display_name"], row, ctx)) for row in s["projects"])


def project_list(s: Mapping[str, Any], ctx: Ctx, item_ids: Iterable[str] | None = None) -> str:
    """Projects as rows; in the app each opens its Monday evidence in the drawer."""
    loc = ctx.loc
    wanted = None if item_ids is None else set(item_ids)
    rows = [row for row in s["projects"] if wanted is None or row["monday_item_id"] in wanted]
    if not rows:
        return f'<p class="muted">{loc.t("evidence.no_projects")}</p>'
    out = []
    for row in rows:
        result = row["deadline_result"]
        deadline = (f'<span class="res-{result}">{loc.t(f"result.{result}")} {loc.hours(row["deadline_delta_seconds"], signed=True)}</span>' if result
                    else f'<span class="muted">{loc.t("common.not_classified_lower")}</span>')
        cells = (f'<span>{loc.when(row["ready_for_approval_at"], False)}</span><span>{loc.labels(row["cohort_labels"])}</span>'
                 f'<span>{deadline}</span><span class="soft">{loc.comma().join(loc.src(label) for label in row["quality_labels"])}</span>'
                 f'<span class="muted">{loc.hours(row["duration_seconds"])}</span>')
        out.append(f'<button type="button" data-drawer="{escape(project_tid(s["editor_id"], row["monday_item_id"]))}">{cells}</button>')
    head = (f'<div class="plist-h" aria-hidden="true"><span>{loc.t("field.ready_for_approval")}</span><span>{loc.t("field.video_type")}</span>'
            f'<span>{loc.t("field.deadline")}</span><span>{loc.t("ui.labels_on_project")}</span><span>{loc.t("field.work_duration")}</span></div>')
    return f'<div class="plist">{head}{"".join(out)}</div>'
