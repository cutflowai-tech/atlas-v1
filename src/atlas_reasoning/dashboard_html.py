"""Server-rendered pages of the reasoning-first dashboard (Phase 16), in English and Arabic.

Pages render ``dashboard`` view objects only; nothing here computes a metric, comparison, confidence, lifecycle or evidence identity.
Every stored or model-written value is escaped (``esc``); identifiers in URLs are canonical (``dashboard_routes``) or percent-encoded.
Model text (Atlas reasoning) and management text are shown as written, with ``dir="auto"``, in both locales: the locale changes only the
interface wording (``dashboard_i18n``). Three sources are kept visibly apart on every card: ATLAS REASONING, MANAGEMENT CONTEXT and
DETERMINISTIC EVIDENCE (also as ``data-source-type``).

The only script is the external ``/reasoning/assets/dashboard.js`` (form submission as JSON with the CSRF header, and opening a
collapsed section a link points into); the pages work for reading without it. No credential ever reaches a page.

Phase 17 insertion point: ``home_page(..., lead_html=...)`` places server-rendered HTML above ``<section id="reasoning-results">``.
It is inserted as HTML, so it must be built only from escaped content (``esc``, ``dashboard_i18n.t``, ``dashboard_routes`` addresses);
model-written text is never trusted HTML. Phase 16 never passes it.
"""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape
from typing import Any

from atlas_reasoning import dashboard_routes as routes
from atlas_reasoning.dashboard import (
    CURRENT_STATUSES,
    EVIDENCE_REF,
    CardSummary,
    EvidenceTrace,
    History,
    Home,
    HumanContext,
    ResultCard,
)
from atlas_reasoning.dashboard_i18n import DIRECTION, t, text
from atlas_reasoning.human_context_html import note_panel, question_panel, teach_atlas_page
from atlas_reasoning.teach_atlas import Teaching

ASSET_CSS = f"{routes.BASE}/assets/dashboard.css"
ASSET_JS = f"{routes.BASE}/assets/dashboard.js"
LIFECYCLE_MARK = {"new": "✦", "active": "●", "updated": "↻", "cooling": "◌", "resolved": "✓", "superseded": "⇢"}
KNOWN_LIFECYCLE = tuple(LIFECYCLE_MARK)
KNOWN_CONFIDENCE = ("weak", "moderate", "strong")
DELTA_KEYS = ("added_findings", "removed_findings", "added_evidence", "removed_evidence", "changed_values", "changed_confidence",
              "added_contradictions", "removed_contradictions")


def esc(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


@dataclass(frozen=True)
class PageContext:
    """What every page needs besides its view object. ``diagnostics_url`` and ``monday_item_url`` are operator configuration,
    validated by ``web_app`` (relative path or https; ``{item_id}`` placeholder)."""

    locale: str
    csrf_token: str = ""
    diagnostics_url: str = "/{locale}/dashboard.html"
    monday_item_url: str | None = None
    switch_path: str | None = None
    rollout_banner: str = ""             # Phase 20-A: "internal" (internal review) or "beta" (management beta); "" when primary
    human_context: bool = True           # Phase 20-A: notes / answers / Teach Atlas interactions enabled

    @property
    def dir(self) -> str:
        return DIRECTION[self.locale]

    @property
    def other(self) -> str:
        return "ar" if self.locale == "en" else "en"

    def t(self, key: str, **params: Any) -> str:
        return t(self.locale, key, **params)

    def label(self, prefix: str, value: object, known: Sequence[str] | None = None) -> str:
        """The localized name of an enum value; an unknown value is shown escaped as stored."""
        value = "" if value is None else str(value)
        if known is not None and value not in known:
            return esc(value)
        key = f"{prefix}.{value}"
        return self.t(key) if text(self.locale, key) != key else esc(value)

    def plain(self, prefix: str, value: object) -> str:
        """The localized name of an enum value as plain text (for use inside a ``t`` parameter, which escapes it)."""
        value = "" if value is None else str(value)
        key = f"{prefix}.{value}"
        localized = text(self.locale, key)
        return localized if localized != key else value

    def diagnostics(self, subject_type: str | None = None, subject_id: str | None = None) -> str:
        url = self.diagnostics_url.replace("{locale}", self.locale)
        if subject_type == "editor" and subject_id:
            url += "#/editor/" + urllib.parse.quote(subject_id, safe="")
        return url

    def monday_link(self, item_id: str) -> str | None:
        if not self.monday_item_url or not item_id:
            return None
        return self.monday_item_url.replace("{item_id}", urllib.parse.quote(item_id, safe=""))


# --- small parts ---------------------------------------------------------------------------------------------------------------


def _auto(value: object, tag: str = "p", cls: str = "") -> str:
    """Stored text (model or management) in its own direction."""
    klass = f' class="{cls}"' if cls else ""
    lines = "<br>".join(esc(line) for line in ("" if value is None else str(value)).split("\n"))
    return f'<{tag} dir="auto"{klass}>{lines}</{tag}>'


def _code(value: object) -> str:
    return f'<code dir="ltr">{esc(value)}</code>'


def _json(value: object) -> str:
    """A canonical value exactly as stored (no rounding, no reformatting of numbers)."""
    return _code(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(", ", ": "), default=str))


def lifecycle_badge(status: str, ctx: PageContext, *, help_text: bool = False) -> str:
    known = status in KNOWN_LIFECYCLE
    mark = LIFECYCLE_MARK.get(status, "?")
    badge = (f'<span class="rv-life" data-lifecycle="{esc(status)}"><span class="rv-mark" aria-hidden="true">{esc(mark)}</span>'
             f'<span class="rv-k">{ctx.t("lifecycle.label")}:</span> {ctx.label("lifecycle", status, KNOWN_LIFECYCLE)}</span>')
    if help_text and known:
        badge += f'<span class="rv-life-help">{ctx.t(f"lifecycle.{status}.help")}</span>'
    return badge


def confidence_badge(level: str, ctx: PageContext) -> str:
    return (f'<span class="rv-conf" data-confidence="{esc(level)}"><span class="rv-k">{ctx.t("confidence.label")}:</span> '
            f'{ctx.label("confidence", level, KNOWN_CONFIDENCE)}</span>')


def version_badge(version: int, ctx: PageContext, total: int | None = None) -> str:
    label = ctx.t("card.version_of", n=version, m=total) if total and total != version else ctx.t("card.version", n=version)
    return f'<span class="rv-ver" data-version="{esc(version)}">{label}</span>'


def notices(codes: Sequence[str], ctx: PageContext) -> str:
    if not codes:
        return ""
    items = "".join(f'<li class="rv-notice" data-notice="{esc(code)}">{ctx.t(f"notice.{code}")}</li>' for code in codes)
    return f'<ul class="rv-notices" aria-label="{ctx.t("notice.label")}">{items}</ul>'


def _subject(summary: CardSummary, ctx: PageContext) -> str:
    return (f'<p class="rv-subject"><span>{ctx.label("subject", summary.subject_type)}</span> {_code(summary.subject_id)} · '
            f'<span>{ctx.label("topic", summary.topic_key)}</span></p>')


def _ref_links(refs: Sequence[str], result_id: str, ctx: PageContext, version: int | None = None, *, same_page: bool = False) -> str:
    """Links from a claim to its evidence records: on the evidence page of the same version (``version`` for a historical card), or
    to anchors on the current page (``same_page``, the evidence page itself)."""
    if not refs:
        return f'<p class="rv-refs rv-norefs">{ctx.t("card.no_refs")}</p>'
    page = "" if same_page else routes.evidence_path(ctx.locale, result_id, version=version)
    links = []
    for ref in refs:
        if EVIDENCE_REF.fullmatch(ref):
            links.append(f'<a class="rv-ref" href="{esc(page)}#ev-{esc(ref)}">{_code(ref)}</a>')
        else:
            links.append(f'<span class="rv-ref rv-ref-broken">{_code(ref)}</span>')
    return f'<p class="rv-refs"><span class="rv-k">{ctx.t("card.cites")}:</span> {" ".join(links)}</p>'


def _claim(claim: Mapping[str, Any], result_id: str, ctx: PageContext, version: int | None = None) -> str:
    return _auto(claim["statement"], "p", "rv-claim") + _ref_links(claim["evidence_refs"], result_id, ctx, version)


def _claims(rows: Sequence[Mapping[str, Any]], result_id: str, ctx: PageContext, empty_key: str, version: int | None = None) -> str:
    if not rows:
        return f'<p class="rv-empty">{ctx.t(empty_key)}</p>'
    return '<ul class="rv-claims">' + "".join(f"<li>{_claim(row, result_id, ctx, version)}</li>" for row in rows) + "</ul>"


def _plain_list(rows: Sequence[object], ctx: PageContext) -> str:
    if not rows:
        return f'<p class="rv-empty">{ctx.t("card.none")}</p>'
    return '<ul class="rv-list">' + "".join(f"<li>{_auto(row, 'span')}</li>" for row in rows) + "</ul>"


def _section(source: str, title_key: str, label_key: str, body: str, ctx: PageContext, heading: str = "h2", section_id: str = "") -> str:
    ident = f' id="{esc(section_id)}"' if section_id else ""
    return (f'<section class="rv-src rv-src-{esc(source)}" data-source-type="{esc(source)}"{ident} aria-label="{ctx.t(title_key)}">'
            f'<{heading} class="rv-src-title">{ctx.t(title_key)}</{heading}><p class="rv-src-label">{ctx.t(label_key)}</p>{body}</section>')


# --- page shell ----------------------------------------------------------------------------------------------------------------


def page(title: str, main: str, ctx: PageContext) -> str:
    home, teach = routes.home_path(ctx.locale), routes.teach_path(ctx.locale)
    switch = ctx.switch_path or routes.home_path(ctx.other)
    nav = (f'<header class="rv-top"><nav class="rv-nav" aria-label="{ctx.t("nav.label")}">'
           f'<a class="rv-brand" href="{esc(home)}"><bdi dir="ltr">{ctx.t("brand")}</bdi> · {ctx.t("nav.home")}</a>'
           + (f'<a href="{esc(teach)}">{ctx.t("nav.teach")}</a>' if ctx.human_context else "") +
           f'<a href="{esc(ctx.diagnostics())}">{ctx.t("nav.diagnostics")}</a>'
           f'<a class="rv-lang" href="{esc(switch)}" hreflang="{ctx.other}" lang="{ctx.other}" dir="{DIRECTION[ctx.other]}">'
           f'{t(ctx.other, "lang.name")}</a></nav></header>')
    rollout = (f'<p class="rv-banner" role="note" data-state="rollout_{ctx.rollout_banner}">{ctx.t(f"rollout.{ctx.rollout_banner}")} '
               f'<a href="{esc(ctx.diagnostics())}">{ctx.t("home.diagnostics_link")}</a></p>' if ctx.rollout_banner else "")
    messages = (f' data-msg-saving="{ctx.t("form.saving")}" data-msg-saved="{ctx.t("form.saved")}" data-msg-failed="{ctx.t("form.failed")}"')
    return (f'<!doctype html><html lang="{ctx.locale}" dir="{ctx.dir}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">'
            f'<meta name="referrer" content="no-referrer"><title>{esc(title)}</title><link rel="stylesheet" href="{ASSET_CSS}"></head>'
            f'<body{messages}><a class="rv-skip" href="#main">{ctx.t("skip")}</a>{nav}'
            f'<noscript><p class="rv-banner" data-state="no_script">{ctx.t("noscript")}</p></noscript>{rollout}'
            f'<main id="main" class="rv-main" tabindex="-1">{main}</main><script src="{ASSET_JS}" defer></script></body></html>')


def error_page(key: str, ctx: PageContext) -> str:
    """A plain-language error page: no internal detail, always a way back and to the deterministic dashboard."""
    main = (f'<h1>{ctx.t("error.title")}</h1><p class="rv-error" role="alert" data-error="{esc(key)}">{ctx.t(f"error.{key}")}</p>'
            f'<p><a href="{esc(routes.home_path(ctx.locale))}">{ctx.t("error.home")}</a> · '
            f'<a href="{esc(ctx.diagnostics())}">{ctx.t("home.diagnostics_link")}</a></p>')
    return page(text(ctx.locale, "error.title"), main, ctx)


# --- home ------------------------------------------------------------------------------------------------------------------------


def card_summary(card: CardSummary, ctx: PageContext) -> str:
    rid = card.result_id
    links = (f'<p class="rv-links"><a href="{esc(routes.card_path(ctx.locale, rid))}">{ctx.t("card.open")}</a>'
             f'<a href="{esc(routes.evidence_path(ctx.locale, rid))}">{ctx.t("card.evidence")}</a>'
             f'<a href="{esc(routes.history_path(ctx.locale, rid))}">{ctx.t("card.history")}</a></p>')
    replaced = ""
    if card.superseded_by:
        try:
            replaced = (f'<p class="rv-superseded">{ctx.t("card.superseded_by")} '
                        f'<a href="{esc(routes.card_path(ctx.locale, card.superseded_by["result_id"]))}">{ctx.t("card.superseded_link")}</a></p>')
        except routes.InvalidRoute:
            replaced = ""
    return (f'<li><article class="rv-card" id="{esc(routes.card_anchor(rid))}" data-result-id="{esc(rid)}" data-case-id="{esc(card.case_id)}" '
            f'data-version="{esc(card.version)}" data-lifecycle="{esc(card.lifecycle_status)}" data-confidence="{esc(card.confidence)}">'
            f'{_subject(card, ctx)}<h3 class="rv-title"><a href="{esc(routes.card_path(ctx.locale, rid))}" dir="auto">{esc(card.title)}</a></h3>'
            f'<p class="rv-badges">{lifecycle_badge(card.lifecycle_status, ctx)}{confidence_badge(card.confidence, ctx)}{version_badge(card.version, ctx)}'
            f'<span class="rv-updated"><span class="rv-k">{ctx.t("card.updated")}:</span> <time datetime="{esc(card.updated_at)}" dir="ltr">'
            f'{esc(card.updated_at)}</time></span></p>'
            f'{_auto(card.reasoning_summary, "p", "rv-summary")}{notices(card.notices, ctx)}{replaced}{links}</article></li>')


def home_page(home: Home, ctx: PageContext, *, lead_html: str = "") -> str:
    """The reasoning-first home. ``lead_html`` is the reserved Phase 17 insertion point (trusted, server-rendered HTML only)."""
    backlog = (f'<p class="rv-banner" role="status" data-state="memory_backlog">{ctx.t("home.memory_backlog", n=home.memory_backlog)}</p>'
               if home.memory_backlog else "")
    if home.first_reasoning_failed:
        backlog += (f'<p class="rv-banner" role="status" data-state="first_reasoning_failed">'
                    f'{ctx.t("home.first_failed", n=home.first_reasoning_failed)}</p>')
    if home.first_reasoning_pending:
        backlog += (f'<p class="rv-banner" role="status" data-state="first_reasoning_pending">'
                    f'{ctx.t("home.first_pending", n=home.first_reasoning_pending)}</p>')
    if not home.current and not home.history:
        waiting = home.first_reasoning_failed or home.first_reasoning_pending
        cards = (f'<p class="rv-empty" data-state="{"empty_unreasoned" if waiting else "empty"}">'
                 f'{ctx.t("home.empty_unreasoned" if waiting else "home.empty")}</p>')
    else:
        current = ('<ol class="rv-cards">' + "".join(card_summary(card, ctx) for card in home.current) + "</ol>" if home.current
                   else f'<p class="rv-empty" data-state="no_current">{ctx.t("home.empty_current")}</p>')
        cards = current
    history = ""
    if home.history:
        history = (f'<section id="reasoning-history" aria-labelledby="rv-history-h"><h2 id="rv-history-h">{ctx.t("home.history")}</h2>'
                   f'<p class="rv-lede">{ctx.t("home.history_lede")}</p><ol class="rv-cards rv-cards-history">'
                   + "".join(card_summary(card, ctx) for card in home.history) + "</ol></section>")
    diagnostics = (f'<section id="deterministic-diagnostics" class="rv-diagnostics" aria-labelledby="rv-diag-h"><h2 id="rv-diag-h">{ctx.t("home.diagnostics")}</h2>'
                   f'<p>{ctx.t("home.diagnostics_lede")}</p><p><a href="{esc(ctx.diagnostics())}">{ctx.t("home.diagnostics_link")}</a></p></section>')
    main = (f'<h1>{ctx.t("home.title")}</h1><p class="rv-lede">{ctx.t("home.lede")}</p>{backlog}{lead_html}'
            f'<section id="reasoning-results" aria-labelledby="rv-current-h"><h2 id="rv-current-h">{ctx.t("home.current")}</h2>{cards}</section>'
            f"{history}{diagnostics}")
    return page(text(ctx.locale, "home.title"), main, ctx)


# --- one card --------------------------------------------------------------------------------------------------------------------


def what_changed(card: ResultCard, ctx: PageContext) -> str:
    what = card.what_changed
    lines = []
    if what.change_kind == "lifecycle":
        lines.append(f"<p>{ctx.t('changed.lifecycle', n=what.version, reason=ctx.plain('reason', what.lifecycle_reason))}</p>")
    elif what.change_kind == "no_change_review":
        lines.append(f"<p>{ctx.t('changed.no_change_review', n=what.version)}</p>")
    if what.content_kind == "patched":
        fields = text(ctx.locale, "list.separator").join(text(ctx.locale, f"field.{name}") for name in what.changed_fields)
        lines.append(f"<p>{ctx.t('changed.patched', n=what.content_version, fields=fields)}</p>")
        if what.change_rationale:
            lines.append(f'<p><span class="rv-k">{ctx.t("changed.rationale")}:</span></p>{_auto(what.change_rationale)}')
        if what.delta:
            items = [f"<li>{esc(what.delta[key])} {ctx.t(f'delta.{key}')}</li>" for key in DELTA_KEYS if what.delta.get(key)]
            if what.delta.get("orientation_changed"):
                items.append(f"<li>{ctx.t('delta.orientation_changed')}</li>")
            if items:
                lines.append(f'<p class="rv-k">{ctx.t("changed.delta")}:</p><ul class="rv-delta">{"".join(items)}</ul>')
    else:
        lines.append(f"<p>{ctx.t('changed.created', n=what.content_version)}</p>")
    if what.content_version != what.version and what.change_kind != "no_change_review":
        lines.append(f"<p>{ctx.t('changed.since', n=what.content_version)}</p>")
    return f'<div class="rv-changed" data-change-kind="{esc(what.change_kind)}">{"".join(lines)}</div>'


def _reasoning(card: ResultCard, ctx: PageContext) -> str:
    doc, rid = card.document, card.summary.result_id
    v = None if card.is_current_version else card.shown_version
    if doc["alternative_explanations"]:
        rows = []
        for row in doc["alternative_explanations"]:
            tag = f' <span class="rv-tag">{ctx.t("card.needs_context")}</span>' if row.get("requires_context") else ""
            rows.append(f"<li>{_auto(row['explanation'], 'p', 'rv-claim')}{tag}{_ref_links(row['evidence_refs'], rid, ctx, v)}</li>")
        alternatives = '<ul class="rv-claims">' + "".join(rows) + "</ul>"
    else:
        alternatives = f'<p class="rv-empty">{ctx.t("card.alternatives_none")}</p>'
    investigations = ('<ul class="rv-claims">' + "".join(f"<li>{_auto(row['text'], 'p', 'rv-claim')}{_ref_links(row['evidence_refs'], rid, ctx, v)}</li>"
                                                         for row in doc["suggested_investigations"]) + "</ul>"
                      if doc["suggested_investigations"] else f'<p class="rv-empty">{ctx.t("card.none")}</p>')
    asked = ('<ul class="rv-list">' + "".join(f'<li>{_auto(q["text"], "span")}</li>' for q in doc["questions_for_management"]) + "</ul>"
             if doc["questions_for_management"] else f'<p class="rv-empty">{ctx.t("card.none")}</p>')
    confidence = doc["confidence"]
    parts = [
        ("card.summary", _auto(doc["reasoning_summary"], "p", "rv-summary")),
        ("card.what_changed", what_changed(card, ctx)),
        ("card.observation", _claim(doc["observation"], rid, ctx, v)),
        ("card.supporting", _claims(doc["supporting_evidence"], rid, ctx, "card.none", v)),
        ("card.counter", _claims(doc["counter_evidence"], rid, ctx, "card.counter_none", v)),
        ("card.interpretation", _claim(doc["interpretation"], rid, ctx, v)),
        ("card.alternatives", alternatives),
        ("card.confidence", f'<p>{confidence_badge(confidence["level"], ctx)}</p>{_auto(confidence["rationale"])}'),
        ("card.limitations", _plain_list(doc["limitations"], ctx)),
        ("card.significance", _claim(doc["management_significance"], rid, ctx, v)),
        ("card.investigations", investigations),
        ("card.version_questions", asked),
    ]
    return "".join(f'<div class="rv-part" data-part="{esc(key.split(".", 1)[1])}"><h3>{ctx.t(key)}</h3>{body}</div>' for key, body in parts)


def _management(card: ResultCard, context: HumanContext, ctx: PageContext) -> str:
    if not ctx.human_context:
        return f'<p class="rv-unavailable" role="status" data-state="human_context_disabled">{ctx.t("source.management_disabled")}</p>'
    if not context.available:
        return f'<p class="rv-unavailable" role="status" data-state="human_context_unavailable">{ctx.t("source.management_unavailable")}</p>'
    rid = card.summary.result_id
    return (note_panel(rid, context.notes, csrf_token=ctx.csrf_token, history=context.note_history, locale=ctx.locale, heading="h3")
            + question_panel(rid, context.questions, csrf_token=ctx.csrf_token, locale=ctx.locale, heading="h3"))


def _provenance(card: ResultCard, ctx: PageContext) -> str:
    doc = card.document
    meta = doc.get("model_metadata") or {}
    rows = [("card.result_id", _code(doc["result_id"])), ("card.case_id", _code(doc["case_id"])),
            ("card.model", _code(meta.get("model"))), ("card.prompt", _code(doc.get("prompt_version"))),
            ("card.snapshot", _code(doc.get("source_snapshot_id"))), ("card.fingerprint", _code(doc.get("evidence_fingerprint"))),
            ("card.created", f'<time datetime="{esc(doc.get("created_at"))}" dir="ltr">{esc(doc.get("created_at"))}</time>'),
            ("card.updated", f'<time datetime="{esc(doc.get("updated_at"))}" dir="ltr">{esc(doc.get("updated_at"))}</time>')]
    items = "".join(f"<div><dt>{ctx.t(key)}</dt><dd>{value}</dd></div>" for key, value in rows)
    return f'<details class="rv-provenance"><summary>{ctx.t("card.provenance")}</summary><dl class="rv-dl">{items}</dl></details>'


def card_page(card: ResultCard, context: HumanContext, trace: EvidenceTrace, history: History, ctx: PageContext) -> str:
    summary, rid = card.summary, card.summary.result_id
    status = card.lifecycle_status
    banners = []
    if not card.is_current_version:
        banners.append(f'<p class="rv-banner" role="status" data-state="historical_version">{ctx.t("card.historical", n=card.shown_version, m=summary.version)} '
                       f'<a href="{esc(routes.card_path(ctx.locale, rid))}">{ctx.t("card.historical_link")}</a></p>')
    if summary.superseded_by:
        try:
            link = routes.card_path(ctx.locale, summary.superseded_by["result_id"])
            banners.append(f'<p class="rv-banner" data-state="superseded">{ctx.t("card.superseded_by")} <a href="{esc(link)}">{ctx.t("card.superseded_link")}</a></p>')
        except routes.InvalidRoute:
            pass
    if summary.lifecycle_status == "resolved":
        banners.append(f'<p class="rv-banner" data-state="resolved">{ctx.t("card.resolved")}</p>')
    if card.replaces:
        links = " ".join(f'<a href="{esc(routes.card_path(ctx.locale, other))}">{_code(other)}</a>' for other in card.replaces)
        banners.append(f'<p class="rv-banner" data-state="replaces">{ctx.t("card.replaces")} {links}</p>')
    shown_notices = notices(summary.notices, ctx) if card.is_current_version else ""
    header = (f'<header class="rv-card-head">{_subject(summary, ctx)}<h1 class="rv-title" dir="auto">{esc(card.document["title"])}</h1>'
              f'<p class="rv-badges">{lifecycle_badge(status, ctx, help_text=True)}{confidence_badge(card.document["confidence"]["level"], ctx)}'
              f'{version_badge(card.shown_version, ctx, summary.version)}</p></header>')
    evidence = (f'<details class="rv-drill" id="evidence-{esc(rid)}"><summary>{ctx.t("evidence.drilldown", n=_cited_count(trace))}</summary>'
                f"{evidence_body(trace, ctx, anchors=False, level=3)}</details>"
                f'<p><a href="{esc(routes.evidence_path(ctx.locale, rid, version=None if card.is_current_version else card.shown_version))}">'
                f'{ctx.t("evidence.open_page")}</a></p>')
    history_html = (f'<details class="rv-drill" id="history-{esc(rid)}"><summary>{ctx.t("history.title")}</summary>{history_body(history, ctx, level=3)}</details>'
                    f'<p><a href="{esc(routes.history_path(ctx.locale, rid))}">{ctx.t("card.history")}</a></p>')
    article = (f'<article class="rv-card rv-card-full" id="{esc(routes.card_anchor(rid))}" data-result-id="{esc(rid)}" data-case-id="{esc(summary.case_id)}" '
               f'data-version="{esc(card.shown_version)}" data-current-version="{esc(summary.version)}" data-lifecycle="{esc(status)}" '
               f'data-confidence="{esc(card.document["confidence"]["level"])}">{header}{"".join(banners)}{shown_notices}'
               f'{_section("atlas_reasoning", "source.atlas", "source.atlas_label", _reasoning(card, ctx), ctx)}'
               f'{_section("management_context", "source.management", "source.management_label", _management(card, context, ctx), ctx)}'
               f'{_section("deterministic_evidence", "source.evidence", "source.evidence_label", evidence + history_html, ctx)}'
               f"{_provenance(card, ctx)}</article>")
    crumbs = (f'<nav class="rv-crumbs" aria-label="{ctx.t("card.breadcrumb")}"><a href="{esc(routes.home_path(ctx.locale))}">{ctx.t("home.title")}</a></nav>')
    return page(f'{card.document["title"]} · Atlas', crumbs + article, ctx)


def _cited_count(trace: EvidenceTrace) -> int:
    return len({ref for claim in trace.claims for ref in claim.evidence_refs})


# --- evidence drill-down ---------------------------------------------------------------------------------------------------------


def _table(heads: Sequence[str], rows: Sequence[Sequence[str]], ctx: PageContext, cls: str = "") -> str:
    head = "".join(f'<th scope="col">{ctx.t(key)}</th>' for key in heads)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="rv-scroll" tabindex="0" role="region" aria-label="{ctx.t(heads[0])}"><table class="rv-table {cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def evidence_body(trace: EvidenceTrace, ctx: PageContext, *, anchors: bool = True, level: int = 2) -> str:
    h, hh = f"h{level}", f"h{min(level + 1, 6)}"
    rid = trace.result_id
    historical = trace.version if trace.version != trace.case.get("current_version") else None
    claim_rows = [[ctx.label("field", claim.field), _auto(claim.text, "span"),
                   _ref_links(claim.evidence_refs, rid, ctx, historical, same_page=anchors)] for claim in trace.claims]
    case = trace.case
    scope = case.get("scope") or {}
    case_rows = [("card.case_id", _code(case.get("case_id"))), ("evidence.case_type", _code(case.get("case_type"))),
                 ("card.subject", f'{ctx.label("subject", case.get("subject_type"))} {_code(case.get("subject_id"))}'),
                 ("card.topic", ctx.label("topic", case.get("topic_key"))), ("evidence.identity_key", _code(case.get("identity_key"))),
                 ("evidence.orientation", _code(case.get("orientation"))), ("evidence.scope", _json(scope)),
                 ("card.snapshot", _code(case.get("source_snapshot_id"))), ("card.fingerprint", _code(case.get("evidence_fingerprint"))),
                 ("evidence.contract", _code(case.get("upstream_contract_version")))]
    newer = ""
    if case.get("current_evidence_fingerprint") and case.get("current_evidence_fingerprint") != case.get("evidence_fingerprint"):
        newer = f'<p class="rv-banner" data-state="evidence_changed">{ctx.t("evidence.newer", fp=case.get("current_evidence_fingerprint"))}</p>'
    resolution = (f'<p class="rv-ok" data-state="resolves">{ctx.t("evidence.resolves")}</p>' if trace.resolves else
                  f'<p class="rv-banner" role="alert" data-state="unresolved">{ctx.t("evidence.unresolved")} '
                  + " ".join(_code(ref) for ref in trace.unresolved) + "</p>")
    findings = []
    for index, finding in enumerate(trace.findings):
        ref = finding.finding
        side_key = "evidence.finding_supporting" if finding.side == "supporting" else "evidence.finding_contradicting"
        facts = [("evidence.finding_id", _code(ref.get("finding_id"))), ("evidence.finding_type", _code(ref.get("finding_type"))),
                 ("evidence.member_key", _code(ref.get("member_key"))), ("evidence.direction", _code(ref.get("direction"))),
                 ("evidence.category", _code(ref.get("category"))), ("evidence.evidence_level", _code(ref.get("evidence_level"))),
                 ("evidence.upstream_confidence", ctx.label("confidence", ref.get("confidence"), KNOWN_CONFIDENCE)),
                 ("evidence.sample_size", _code(ref.get("sample_size"))), ("card.limitations", _json(ref.get("limitations") or []))]
        statements = _table(["evidence.code", "evidence.kind", "evidence.level", "evidence.params"],
                            [[_code(s.get("code")), _code(s.get("kind")), _code(s.get("level")), _json(s.get("params") or {})] for s in finding.statements], ctx)
        blocks = _table(["evidence.code", "evidence.role", "evidence.sample", "evidence.comparison", "evidence.exclusions"],
                        [[_code(b.get("evidence_code")), _code(b.get("role")), _json(b.get("sample")), _json(b.get("comparison")), _json(b.get("exclusions") or [])]
                         for b in finding.blocks], ctx) if finding.blocks else ""
        records = []
        for item in finding.evidence:
            ident = f' id="ev-{esc(item.ref_id)}"' if anchors else ""
            monday = ctx.monday_link(item.monday_item_id)
            item_cell = (f'<a href="{esc(monday)}" rel="noreferrer noopener" target="_blank">{_code(item.monday_item_id)}</a>' if monday
                         else _code(item.monday_item_id))
            cited = text(ctx.locale, "list.separator").join(text(ctx.locale, f"field.{name}") for name in item.cited_in)
            anchor = (f'<span{ident} class="rv-ev" data-ref-id="{esc(item.ref_id)}" data-cited="{"true" if item.cited_in else "false"}" '
                      f'tabindex="-1">{_code(item.ref_id)}</span>')
            records.append([anchor, esc(cited) if cited else f'<span class="rv-muted">{ctx.t("evidence.not_cited")}</span>',
                            _code(item.role), _code(item.evidence_code), item_cell, _code(item.cycle_id), _json(list(item.event_ids)),
                            _json(list(item.source_timestamps)), _code(item.editor_id), _code(item.video_type_key), _json(item.values)])
        record_table = _table(["evidence.ref", "evidence.cited_in", "evidence.role", "evidence.code", "evidence.item", "evidence.cycle", "evidence.events",
                               "evidence.timestamps", "evidence.editor", "evidence.video_type", "evidence.values"], records, ctx, "rv-records")
        fid = f' id="finding-{index + 1}"' if anchors else ""
        open_attr = " open" if anchors else ""
        findings.append(f'<details class="rv-finding" data-side="{esc(finding.side)}" data-finding-id="{esc(ref.get("finding_id"))}"{fid}{open_attr}>'
                        f'<summary><span class="rv-side">{ctx.t(side_key)}</span> {_code(ref.get("finding_type"))}</summary>'
                        f'<dl class="rv-dl">{"".join(f"<div><dt>{ctx.t(k)}</dt><dd>{v}</dd></div>" for k, v in facts)}</dl>'
                        f"<{hh}>{ctx.t('evidence.statements')}</{hh}>{statements}"
                        + (f"<{hh}>{ctx.t('evidence.blocks')}</{hh}>{blocks}" if blocks else "")
                        + f"<{hh}>{ctx.t('evidence.records')}</{hh}>{record_table}</details>")
    return (f'<p class="rv-chain">{ctx.t("evidence.chain")}</p>{resolution}'
            f'<section class="rv-ev-claims"><{h}>{ctx.t("evidence.claims")}</{h}>'
            f'{_table(["evidence.field", "evidence.statement", "evidence.refs"], claim_rows, ctx)}</section>'
            f'<section class="rv-ev-case"><{h}>{ctx.t("evidence.case")}</{h}>{newer}<dl class="rv-dl">'
            + "".join(f"<div><dt>{ctx.t(k)}</dt><dd>{v}</dd></div>" for k, v in case_rows) + "</dl></section>"
            f'<section class="rv-ev-findings"><{h}>{ctx.t("evidence.findings")}</{h}>'
            f'<p class="rv-muted">{ctx.t("evidence.snapshot_note", snapshot=case.get("source_snapshot_id"))}</p>'
            f'{"".join(findings)}'
            f'<p><a href="{esc(ctx.diagnostics(case.get("subject_type"), case.get("subject_id")))}">{ctx.t("evidence.diagnostics_link")}</a></p></section>')


def evidence_page(card: ResultCard, trace: EvidenceTrace, ctx: PageContext) -> str:
    rid = card.summary.result_id
    crumbs = (f'<nav class="rv-crumbs" aria-label="{ctx.t("card.breadcrumb")}"><a href="{esc(routes.home_path(ctx.locale))}">{ctx.t("home.title")}</a> › '
              f'<a href="{esc(routes.card_path(ctx.locale, rid, version=None if card.is_current_version else card.shown_version))}" dir="auto">'
              f'{esc(card.document["title"])}</a></nav>')
    main = (f'{crumbs}<article class="rv-evidence" data-result-id="{esc(rid)}" data-version="{esc(trace.version)}" data-source-type="deterministic_evidence">'
            f'<h1>{ctx.t("evidence.title")}</h1>{_auto(card.document["title"], "p", "rv-title-sub")}'
            f'<p class="rv-badges">{lifecycle_badge(card.lifecycle_status, ctx)}{version_badge(trace.version, ctx, card.summary.version)}</p>'
            f'{notices(card.summary.notices, ctx) if card.is_current_version else ""}'
            f'<p class="rv-src-label">{ctx.t("source.evidence_label")}</p>{evidence_body(trace, ctx)}</article>')
    return page(f'{text(ctx.locale, "evidence.title")} · Atlas', main, ctx)


# --- history ---------------------------------------------------------------------------------------------------------------------


def history_body(history: History, ctx: PageContext, *, level: int = 2) -> str:
    h = f"h{level}"
    rid = history.summary.result_id
    rows = []
    for row in reversed(history.versions):
        fields = text(ctx.locale, "list.separator").join(text(ctx.locale, f"field.{name}") for name in row.changed_fields)
        current = f' <span class="rv-tag">{ctx.t("history.current")}</span>' if row.version == history.summary.version else ""
        link = f'<a href="{esc(routes.card_path(ctx.locale, rid, version=row.version))}">{ctx.t("history.view_version", n=row.version)}</a>'
        rows.append([f"{esc(row.version)}{current}", ctx.label("kind", row.change_kind), lifecycle_badge(row.lifecycle_status, ctx),
                     f'<time datetime="{esc(row.created_at)}" dir="ltr">{esc(row.created_at)}</time>', esc(fields),
                     _auto(row.change_rationale, "span") if row.change_rationale else "", link])
    versions = _table(["history.version", "history.change", "history.status", "history.date", "history.fields", "history.rationale", "history.view"],
                      rows, ctx, "rv-history")
    moves = [[ctx.label("lifecycle", m["from_status"], KNOWN_LIFECYCLE) if m["from_status"] else "—", ctx.label("lifecycle", m["to_status"], KNOWN_LIFECYCLE),
              ctx.label("reason", m["reason_code"]), esc(m["result_version"]),
              f'<time datetime="{esc(m["created_at"])}" dir="ltr">{esc(m["created_at"])}</time>'] for m in history.transitions]
    transitions = (_table(["history.from", "history.to", "history.reason", "history.version", "history.date"], moves, ctx) if moves
                   else f'<p class="rv-empty">{ctx.t("history.none")}</p>')
    return (f'<section class="rv-versions"><{h}>{ctx.t("history.versions")}</{h}>{versions}</section>'
            f'<section class="rv-transitions"><{h}>{ctx.t("history.transitions")}</{h}>{transitions}</section>')


def history_page(history: History, ctx: PageContext) -> str:
    rid = history.summary.result_id
    crumbs = (f'<nav class="rv-crumbs" aria-label="{ctx.t("card.breadcrumb")}"><a href="{esc(routes.home_path(ctx.locale))}">{ctx.t("home.title")}</a> › '
              f'<a href="{esc(routes.card_path(ctx.locale, rid))}" dir="auto">{esc(history.summary.title)}</a></nav>')
    superseded = ""
    if history.summary.superseded_by:
        try:
            superseded = (f'<p class="rv-banner" data-state="superseded">{ctx.t("card.superseded_by")} '
                          f'<a href="{esc(routes.card_path(ctx.locale, history.summary.superseded_by["result_id"]))}">{ctx.t("card.superseded_link")}</a></p>')
        except routes.InvalidRoute:
            pass
    main = (f'{crumbs}<article class="rv-history-page" data-result-id="{esc(rid)}" data-version="{esc(history.summary.version)}" '
            f'data-lifecycle="{esc(history.summary.lifecycle_status)}"><h1>{ctx.t("history.title")}</h1>{_auto(history.summary.title, "p", "rv-title-sub")}'
            f'<p class="rv-badges">{lifecycle_badge(history.summary.lifecycle_status, ctx, help_text=True)}{version_badge(history.summary.version, ctx)}</p>'
            f"{superseded}{notices(history.summary.notices, ctx)}{history_body(history, ctx)}</article>")
    return page(f'{text(ctx.locale, "history.title")} · Atlas', main, ctx)


# --- Teach Atlas -----------------------------------------------------------------------------------------------------------------


def teach_page(teachings: Sequence[Teaching] | None, ctx: PageContext) -> str:
    if teachings is None:
        body = f'<h1>{ctx.t("ta.title")}</h1><p class="rv-unavailable" role="status" data-state="teach_unavailable">{ctx.t("teach.unavailable")}</p>'
    else:
        body = (f'<h1 class="rv-visually-hidden">{ctx.t("ta.title")}</h1><div data-source-type="management_context">'
                f"{teach_atlas_page(teachings, csrf_token=ctx.csrf_token, locale=ctx.locale)}</div>")
    return page(f'{text(ctx.locale, "ta.title")} · Atlas', body, ctx)


__all__ = ["CURRENT_STATUSES", "PageContext", "card_page", "error_page", "evidence_page", "history_page", "home_page", "teach_page"]
