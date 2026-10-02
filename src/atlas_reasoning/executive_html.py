"""The executive overview as HTML (Phase 17 UI): the lead of the reasoning-first home, placed through Phase 16's ``home_page(lead_html=)``.

Every executive statement is model-written text: it is always escaped (``dashboard_html.esc`` / ``_auto``), never markup. Every link is
built by Phase 16's route builders from canonical IDs (``dashboard_routes.card_path`` / ``evidence_path`` / ``history_path``): a statement
links to the **version** of each cited card the synthesis saw, and that version's evidence; it never links to an Intelligence V2
finding or a Monday item directly (the lower audit chain is Phase 16's drill-down). An ID that is not canonical never becomes a URL.
When a cited card has moved on, been resolved or been replaced since, the statement says so beside the link; the statement itself is
shown exactly as stored. Interface wording is localized (``dashboard_i18n``); stored text is not.
"""

from __future__ import annotations

from atlas_reasoning import dashboard_routes as routes
from atlas_reasoning.dashboard_html import KNOWN_LIFECYCLE, PageContext, _auto, _code, esc, lifecycle_badge, version_badge
from atlas_reasoning.executive_overview import CitedResult, Overview, StatementView


def _link(href: str, label: str, cls: str = "") -> str:
    klass = f' class="{cls}"' if cls else ""
    return f'<a{klass} href="{esc(href)}">{label}</a>'


def cited_result(row: CitedResult, ctx: PageContext) -> str:
    """One cited card: the pinned version's card and evidence, and its state now."""
    attrs = (f'data-result-id="{esc(row.result_id)}" data-pinned-version="{esc(row.pinned_version)}" '
             f'data-current-version="{esc(row.current_version)}" data-lifecycle="{esc(row.current_lifecycle)}"')
    try:
        card = routes.card_path(ctx.locale, row.result_id, version=row.pinned_version)
        evidence = routes.evidence_path(ctx.locale, row.result_id, version=row.pinned_version)
    except routes.InvalidRoute:
        return f'<li class="rv-exec-ref rv-ref-broken" {attrs}>{_code(row.result_id)}</li>'      # never a URL from a non-canonical ID
    title = esc(row.pinned_title) if row.pinned_title else _code(row.result_id)
    parts = [_link(card, f'<span dir="auto">{title}</span>', "rv-exec-card"), version_badge(row.pinned_version or 0, ctx),
             _link(evidence, ctx.t("exec.evidence"), "rv-exec-evidence")]
    status = []
    if not row.exists:
        status.append(f'<span class="rv-exec-state" data-state="missing">{ctx.t("exec.missing")}</span>')
    else:
        if row.current_lifecycle in KNOWN_LIFECYCLE:
            status.append(lifecycle_badge(str(row.current_lifecycle), ctx))
        if row.moved_on:
            status.append(f'<span class="rv-exec-state" data-state="moved_on">{ctx.t("exec.moved_on", n=row.current_version)}</span> '
                          + _link(routes.card_path(ctx.locale, row.result_id), ctx.t("exec.open_current")))
        if row.current_lifecycle == "resolved":
            status.append(f'<span class="rv-exec-state" data-state="resolved">{ctx.t("exec.resolved")}</span>')
        if row.current_lifecycle == "superseded":
            replacement = ""
            try:
                if row.superseded_by:
                    replacement = " " + _link(routes.card_path(ctx.locale, row.superseded_by), ctx.t("exec.open_replacement"), "rv-exec-replacement")
            except routes.InvalidRoute:
                replacement = ""
            status.append(f'<span class="rv-exec-state" data-state="superseded">{ctx.t("exec.superseded")}</span>{replacement}')
    return (f'<li class="rv-exec-ref" {attrs}>{" ".join(parts)}'
            + (f'<span class="rv-exec-status">{" ".join(status)}</span>' if status else "") + "</li>")


def statement(row: StatementView, ctx: PageContext) -> str:
    editor = (f'<p class="rv-exec-editor"><span class="rv-k">{ctx.t("evidence.editor")}:</span> {_code(row.editor_id)}</p>'
              if row.editor_id else "")
    refs = "".join(cited_result(cited, ctx) for cited in row.cited)
    return (f'<li class="rv-exec-statement" data-statement-id="{esc(row.statement_id)}" data-section="{esc(row.section)}">'
            f'{editor}{_auto(row.text, "p", "rv-exec-text")}'
            f'<p class="rv-k rv-exec-based">{ctx.t("exec.based_on")}</p><ul class="rv-exec-refs">{refs}</ul></li>')


def _provenance(overview: Overview, ctx: PageContext) -> str:
    facts = overview.provenance()
    rows = [("exec.brief_id", _code(facts["brief_id"])), ("history.version", esc(facts["version"])), ("exec.run_id", _code(facts["run_id"])),
            ("exec.generator", esc(ctx.plain("exec.generator", facts["generator"]))), ("card.model", _code(facts["model"] or "—")),
            ("card.prompt", _code(facts["prompt_version"] or "—")), ("exec.validator", _code(facts["validator_version"])),
            ("card.created", f'<time datetime="{esc(facts["created_at"])}" dir="ltr">{esc(facts["created_at"])}</time>'),
            ("exec.inputs", esc(facts["input_results"])), ("exec.omitted", esc(facts["omitted_results"]))]
    items = "".join(f"<div><dt>{ctx.t(key)}</dt><dd>{value}</dd></div>" for key, value in rows)
    return f'<details class="rv-provenance"><summary>{ctx.t("card.provenance")}</summary><dl class="rv-dl">{items}</dl></details>'


def overview_html(overview: Overview, ctx: PageContext) -> str:
    """The lead of the home page. Built only from escaped content and Phase 16 route builders (the ``lead_html`` rule)."""
    head = f'<h2 id="rv-exec-h">{ctx.t("exec.title")}</h2>'
    if overview.state == "none":
        return (f'<section id="executive-brief" class="rv-exec" data-state="executive_none" aria-labelledby="rv-exec-h">{head}'
                f'<p class="rv-empty">{ctx.t("exec.none")}</p></section>')
    if overview.state == "unavailable" or overview.brief is None:
        return (f'<section id="executive-brief" class="rv-exec" data-state="executive_unavailable" aria-labelledby="rv-exec-h">{head}'
                f'<p class="rv-unavailable" role="status">{ctx.t("exec.unavailable")}</p></section>')
    brief = overview.brief
    notice = (f'<p class="rv-banner" role="status" data-state="executive_latest_failed">{ctx.t("exec.latest_failed")}</p>'
              if overview.latest_run_failed else "")
    if overview.sections:
        body = "".join(f'<section class="rv-exec-section" data-section="{esc(name)}" aria-labelledby="rv-exec-{esc(name)}">'
                       f'<h3 id="rv-exec-{esc(name)}">{ctx.t(f"exec.section.{name}")}</h3>'
                       f'<ul class="rv-exec-statements">{"".join(statement(row, ctx) for row in rows)}</ul></section>'
                       for name, rows in overview.sections)
    else:
        body = f'<p class="rv-empty" data-state="executive_empty">{ctx.t("exec.empty")}</p>'
    return (f'<section id="executive-brief" class="rv-exec" data-state="executive_brief" data-source-type="executive_synthesis" '
            f'data-brief-id="{esc(brief.brief_id)}" data-brief-version="{esc(brief.version)}" data-run-id="{esc(brief.run_id)}" '
            f'aria-labelledby="rv-exec-h">{head}<p class="rv-src-label">{ctx.t("exec.label")}</p>{notice}{body}{_provenance(overview, ctx)}</section>')
