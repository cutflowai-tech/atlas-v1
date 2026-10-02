"""HTML fragments for human context on reasoning cards (``REV/12``-``REV/14``): the minimal interaction surface.

These are server-rendered fragments the reasoning-first dashboard (Phase 16, ``dashboard_html``) places on each card; they carry no
script and no credentials. Every piece of stored text is escaped here (``html.escape`` with quotes), so a note, answer or teaching
can never inject markup. Management context is always labelled as such, visually and in ``data-source-type``, and kept apart from
Atlas reasoning and deterministic evidence. Forms post JSON to ``management_api`` routes; the page supplies the CSRF token.

``locale`` (``en`` or ``ar``, Phase 16) changes only the fixed interface wording (``dashboard_i18n``); stored text is shown as
written. The English output is unchanged from Phases 12-14.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape
from typing import Any
from urllib.parse import quote

from atlas_reasoning.atlas_questions import MAX_ANSWER, Question
from atlas_reasoning.dashboard_i18n import t, text
from atlas_reasoning.management_api import PREFIX
from atlas_reasoning.manager_notes import MAX_NOTE, Note
from atlas_reasoning.teach_atlas import MAX_TEACHING, Teaching


def esc(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _seg(identifier: str) -> str:
    """An ID as one URL path segment (percent-encoded, then HTML-escaped): a form can only ever post to its own API route."""
    return esc(quote(str(identifier), safe=""))


def _level(heading: str) -> str:
    """The panel's heading element (``h2``-``h6``), so a page keeps a gap-free heading outline."""
    return heading if heading in ("h2", "h3", "h4", "h5", "h6") else "h4"


def _multiline(text: str) -> str:
    return "<br>".join(esc(line) for line in text.split("\n"))


def _revisions(revisions: Sequence[Mapping[str, Any]], locale: str = "en") -> str:
    """Earlier revisions of a note (audit history), oldest first, each escaped and attributed."""
    rows = [f'<li class="mi-revision" data-revision="{esc(row.get("revision"))}"><p class="mi-body">{_multiline(str(row.get("body", "")))}</p>'
            f'<p class="mi-meta">{esc(row.get("author") or t(locale, "hc.management"))} · <time datetime="{esc(row.get("recorded_at"))}">{esc(row.get("recorded_at"))}</time>'
            f' · {t(locale, "hc.revision", n=row.get("revision"))}</p></li>' for row in revisions]
    return f'<details class="mi-history"><summary>{t(locale, "hc.edit_history")}</summary><ol>{"".join(rows)}</ol></details>' if rows else ""


def note_panel(result_id: str, notes: Sequence[Note], *, csrf_token: str, history: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
               locale: str = "en", heading: str = "h4") -> str:
    """The manager-interpretation box of one reasoning card: existing notes (escaped, attributed), each with an edit control and its
    revision history (``ManagerNotes.history``; earlier revisions only), and a text box for a new note."""
    items = []
    for note in notes:
        author = esc(note.author or t(locale, "hc.management"))
        nid = esc(note.note_id)
        edited = f" · {t(locale, 'hc.revision', n=note.revision)}" if note.revision > 1 else ""
        earlier = [row for row in (history or {}).get(note.note_id, ()) if row.get("revision") != note.revision]
        items.append(
            f'<li class="mi-note" data-note-id="{nid}" data-revision="{note.revision}" data-source-type="manager_interpretation">'
            f'<p class="mi-body">{_multiline(note.body)}</p>'
            f'<p class="mi-meta">{author} · <time datetime="{esc(note.updated_at)}">{esc(note.updated_at)}</time>{edited}</p>'
            f'<form class="mi-edit" method="post" action="{PREFIX}/notes/{_seg(note.note_id)}" data-method="PUT" data-csrf="{esc(csrf_token)}" data-json="true">'
            f'<input type="hidden" name="expected_revision" value="{note.revision}" data-type="integer">'
            f'<label for="mi-edit-{nid}">{t(locale, "hc.note_edit")}</label>'
            f'<textarea id="mi-edit-{nid}" name="body" maxlength="{MAX_NOTE}" rows="3" required>{esc(note.body)}</textarea>'
            f'<button type="submit">{t(locale, "hc.note_save_edit")}</button></form>'
            f"{_revisions(earlier, locale)}</li>")
    listing = f'<ul class="mi-notes">{"".join(items)}</ul>' if items else f'<p class="mi-empty">{t(locale, "hc.note_empty")}</p>'
    action = f"{PREFIX}/results/{_seg(result_id)}/notes"
    return (f'<section class="manager-interpretation" data-source-type="manager_interpretation" data-result-id="{esc(result_id)}" '
            f'aria-label="{t(locale, "hc.note_aria")}">'
            f'<{_level(heading)} class="mi-title">{t(locale, "hc.note_title")}</{_level(heading)}>'
            f'<p class="mi-label">{t(locale, "hc.note_label")}</p>'
            f"{listing}"
            f'<form class="mi-form" method="post" action="{action}" data-csrf="{esc(csrf_token)}" data-json="true">'
            f'<label for="mi-{esc(result_id)}">{t(locale, "hc.note_add")}</label>'
            f'<textarea id="mi-{esc(result_id)}" name="body" maxlength="{MAX_NOTE}" rows="3" required></textarea>'
            f'<button type="submit">{t(locale, "hc.note_save")}</button></form></section>')


def question_panel(result_id: str, questions: Sequence[Question], *, csrf_token: str, locale: str = "en", heading: str = "h4") -> str:
    """Atlas's questions for management on one card: why each matters, its state, every answer (conflicts flagged), and controls to
    answer or dismiss an open question. Not a chat: only questions Atlas asked can be answered."""
    if not questions:
        return ""
    items = []
    for question in questions:
        qid = esc(question.question_id)
        answers = []
        for answer in question.answers:
            conflict = f'<span class="qa-conflict">{t(locale, "hc.q_conflict")}</span>' if answer.conflicts_with_answer_id else ""
            answers.append(f'<li class="qa-answer" data-source-type="manager_answer" data-answer-id="{esc(answer.answer_id)}">'
                           f'<p class="qa-body">{_multiline(answer.body)}</p>'
                           f'<p class="qa-meta">{esc(answer.author or t(locale, "hc.management"))} · <time datetime="{esc(answer.created_at)}">'
                           f"{esc(answer.created_at)}</time> {conflict}</p></li>")
        history = f'<ul class="qa-answers">{"".join(answers)}</ul>' if answers else ""
        controls = ""
        if question.state in ("open", "answered"):
            label = t(locale, "hc.q_answer" if question.state == "open" else "hc.q_answer_again")
            controls = (f'<form class="qa-form" method="post" action="{PREFIX}/questions/{_seg(question.question_id)}/answers" data-csrf="{esc(csrf_token)}" data-json="true">'
                        f'<label for="qa-{qid}">{label}</label>'
                        f'<textarea id="qa-{qid}" name="body" maxlength="{MAX_ANSWER}" rows="2" required></textarea>'
                        f'<button type="submit">{t(locale, "hc.q_save")}</button></form>')
        if question.state == "open":
            controls += (f'<form class="qa-dismiss" method="post" action="{PREFIX}/questions/{_seg(question.question_id)}/dismiss" data-csrf="{esc(csrf_token)}" data-json="true">'
                         f'<button type="submit">{t(locale, "hc.q_dismiss")}</button></form>')
        state = text(locale, f"hc.state.{question.state}") if question.state in _STATES else question.state.capitalize()
        context = question.expected_context_type
        context_text = text(locale, f"hc.ctx.{context}") if context in _CONTEXT_TYPES else context.replace("_", " ")
        items.append(f'<li class="qa-question" data-question-id="{qid}" data-state="{esc(question.state)}" data-source-type="atlas_question">'
                     f'<p class="qa-text">{esc(question.text)}</p>'
                     f'<p class="qa-why">{t(locale, "hc.q_why", reason=question.reason)}</p>'
                     f'<p class="qa-state">{t(locale, "hc.q_state", state=state, context=context_text)}</p>'
                     f"{history}{controls}</li>")
    return (f'<section class="atlas-questions" data-result-id="{esc(result_id)}" aria-label="{t(locale, "hc.q_aria")}">'
            f'<{_level(heading)} class="qa-title">{t(locale, "hc.q_title")}</{_level(heading)}>'
            f'<p class="qa-label">{t(locale, "hc.q_label")}</p>'
            f'<ol class="qa-list">{"".join(items)}</ol></section>')


_STATES = ("open", "answered", "dismissed", "superseded")
_CONTEXT_TYPES = ("business_rule", "workflow_context", "assignment_context", "client_context", "temporary_situation", "data_correction", "other")
_SCOPES = ("company", "editor", "video_type", "workflow", "client", "specific_result")
_TYPES = ("business_rule", "context", "correction", "interpretation", "temporary_situation")
_VALIDITY = ("until_changed", "date_range", "current_period")


def _label(locale: str, prefix: str, value: str, known: Sequence[str]) -> str:
    return t(locale, f"{prefix}.{value}") if value in known else esc(value)


def _options(locale: str, prefix: str, choices: Sequence[str]) -> str:
    return "".join(f'<option value="{esc(value)}">{t(locale, f"{prefix}.{value}")}</option>' for value in choices)


def _validity_text(teaching: Teaching, locale: str = "en") -> str:
    text = _label(locale, "ta.validity", teaching.validity_mode, _VALIDITY)
    if teaching.validity_mode != "until_changed":
        text += esc(f": {teaching.valid_from or '…'} → {teaching.valid_until or '…'}")
    return text


def teach_atlas_page(teachings: Sequence[Teaching], *, csrf_token: str, locale: str = "en") -> str:
    """The Teach Atlas interface: a form to teach Atlas, and every teaching with its source, scope, type, validity and status."""
    rows = []
    for teaching in teachings:
        tid = esc(teaching.teaching_id)
        scope = _label(locale, "ta.scope", teaching.scope_type, _SCOPES) + (esc(f": {teaching.scope_id}") if teaching.scope_id else "")
        flag = f'<span class="ta-flag">{t(locale, "ta.flag")}</span>' if teaching.affects_source_data else ""
        state = (t(locale, "ta.not_in_effect") if teaching.status == "active" and not teaching.effective
                 else _label(locale, "ta.status", teaching.status, ("active", "disabled", "archived")))
        actions = []
        if teaching.status != "archived":
            for action in ("enable", "disable", "archive"):
                if (action, teaching.status) not in (("enable", "active"), ("disable", "disabled")):
                    actions.append(f'<form method="post" action="{PREFIX}/teachings/{_seg(teaching.teaching_id)}/{action}" data-csrf="{esc(csrf_token)}" data-json="true">'
                                   f'<button type="submit">{t(locale, f"ta.{action}")}</button></form>')
        rows.append(f'<tr data-teaching-id="{tid}" data-source-type="management_teaching" data-status="{esc(teaching.status)}">'
                    f'<td class="ta-body">{_multiline(teaching.body)} {flag}</td>'
                    f"<td>{t(locale, 'ta.source')}</td><td>{scope}</td><td>{_label(locale, 'ta.type', teaching.teaching_type, _TYPES)}</td>"
                    f"<td>{_validity_text(teaching, locale)}</td><td>{state}</td><td>{esc(teaching.author or t(locale, 'hc.management'))} · "
                    f"{t(locale, 'hc.revision', n=teaching.revision)}</td>"
                    f'<td class="ta-actions">{"".join(actions)}</td></tr>')
    heads = "".join(f"<th>{t(locale, f'ta.head.{name}')}</th>" for name in ("teaching", "source", "scope", "type", "validity", "status", "author", "actions"))
    table = (f'<table class="ta-list"><thead><tr>{heads}</tr></thead><tbody>{"".join(rows)}</tbody></table>' if rows
             else f'<p class="ta-empty">{t(locale, "ta.empty")}</p>')
    form = (f'<form class="ta-form" method="post" action="{PREFIX}/teachings" data-csrf="{esc(csrf_token)}" data-json="true">'
            f'<label for="ta-body">{t(locale, "ta.body")}</label><textarea id="ta-body" name="body" maxlength="{MAX_TEACHING}" rows="3" required></textarea>'
            f'<label for="ta-scope">{t(locale, "ta.scope")}</label><select id="ta-scope" name="scope_type">{_options(locale, "ta.scope", _SCOPES)}</select>'
            f'<label for="ta-scope-id">{t(locale, "ta.scope_id")}</label><input id="ta-scope-id" name="scope_id" maxlength="200">'
            f'<label for="ta-type">{t(locale, "ta.type")}</label><select id="ta-type" name="teaching_type">{_options(locale, "ta.type", _TYPES)}</select>'
            f'<label for="ta-validity">{t(locale, "ta.validity")}</label><select id="ta-validity" name="validity_mode">{_options(locale, "ta.validity", _VALIDITY)}</select>'
            f'<label for="ta-from">{t(locale, "ta.from")}</label><input id="ta-from" name="valid_from" type="date">'
            f'<label for="ta-until">{t(locale, "ta.until")}</label><input id="ta-until" name="valid_until" type="date">'
            f'<label><input type="checkbox" name="affects_source_data" value="true"> {t(locale, "ta.data_issue")}</label>'
            f'<button type="submit">{t(locale, "ta.submit")}</button></form>')
    return (f'<section class="teach-atlas" aria-label="{t(locale, "ta.title")}"><h2>{t(locale, "ta.title")}</h2>'
            f'<p class="ta-label">{t(locale, "ta.label")}</p>'
            f"{form}{table}</section>")
