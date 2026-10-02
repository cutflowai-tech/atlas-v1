"""HTML fragments for human context on reasoning cards (``REV/12``-``REV/14``): the minimal interaction surface.

These are server-rendered fragments for the reasoning-first dashboard (Phase 16) to place on each card; they carry no script and
no credentials. Every piece of stored text is escaped here (``html.escape`` with quotes), so a note, answer or teaching can never
inject markup. Management context is always labelled as such, visually and in ``data-source-type``, and kept apart from Atlas
reasoning and deterministic evidence. Forms post JSON to ``management_api`` routes; the page supplies the CSRF token.
"""

from __future__ import annotations

from collections.abc import Sequence
from html import escape

from atlas_reasoning.atlas_questions import MAX_ANSWER, Question
from atlas_reasoning.management_api import PREFIX
from atlas_reasoning.manager_notes import LABEL as NOTE_LABEL
from atlas_reasoning.manager_notes import MAX_NOTE, Note
from atlas_reasoning.teach_atlas import MAX_TEACHING, Teaching


def esc(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _multiline(text: str) -> str:
    return "<br>".join(esc(line) for line in text.split("\n"))


def note_panel(result_id: str, notes: Sequence[Note], *, csrf_token: str) -> str:
    """The manager-interpretation box of one reasoning card: existing notes (escaped, attributed) and a text box."""
    items = []
    for note in notes:
        author = esc(note.author or "Management")
        edited = f" · revision {note.revision}" if note.revision > 1 else ""
        items.append(
            f'<li class="mi-note" data-note-id="{esc(note.note_id)}" data-revision="{note.revision}" data-source-type="manager_interpretation">'
            f'<p class="mi-body">{_multiline(note.body)}</p>'
            f'<p class="mi-meta">{author} · <time datetime="{esc(note.updated_at)}">{esc(note.updated_at)}</time>{edited}</p></li>')
    listing = f'<ul class="mi-notes">{"".join(items)}</ul>' if items else '<p class="mi-empty">No manager interpretation yet.</p>'
    action = f"{PREFIX}/results/{esc(result_id)}/notes"
    return (f'<section class="manager-interpretation" data-source-type="manager_interpretation" data-result-id="{esc(result_id)}" '
            f'aria-label="{esc(NOTE_LABEL)}">'
            f'<h4 class="mi-title">Manager interpretation</h4>'
            f'<p class="mi-label">Management context, not evidence. Atlas uses it only as attributed context.</p>'
            f"{listing}"
            f'<form class="mi-form" method="post" action="{action}" data-csrf="{esc(csrf_token)}" data-json="true">'
            f'<label for="mi-{esc(result_id)}">Add your interpretation</label>'
            f'<textarea id="mi-{esc(result_id)}" name="body" maxlength="{MAX_NOTE}" rows="3" required></textarea>'
            f'<button type="submit">Save interpretation</button></form></section>')


def question_panel(result_id: str, questions: Sequence[Question], *, csrf_token: str) -> str:
    """Atlas's questions for management on one card: why each matters, its state, every answer (conflicts flagged), and controls to
    answer or dismiss an open question. Not a chat: only questions Atlas asked can be answered."""
    if not questions:
        return ""
    items = []
    for question in questions:
        qid = esc(question.question_id)
        answers = []
        for answer in question.answers:
            conflict = '<span class="qa-conflict">Differs from an earlier answer</span>' if answer.conflicts_with_answer_id else ""
            answers.append(f'<li class="qa-answer" data-source-type="manager_answer" data-answer-id="{esc(answer.answer_id)}">'
                           f'<p class="qa-body">{_multiline(answer.body)}</p>'
                           f'<p class="qa-meta">{esc(answer.author or "Management")} · <time datetime="{esc(answer.created_at)}">'
                           f"{esc(answer.created_at)}</time> {conflict}</p></li>")
        history = f'<ul class="qa-answers">{"".join(answers)}</ul>' if answers else ""
        controls = ""
        if question.state in ("open", "answered"):
            label = "Answer" if question.state == "open" else "Add a newer answer"
            controls = (f'<form class="qa-form" method="post" action="{PREFIX}/questions/{qid}/answers" data-csrf="{esc(csrf_token)}" data-json="true">'
                        f'<label for="qa-{qid}">{label}</label>'
                        f'<textarea id="qa-{qid}" name="body" maxlength="{MAX_ANSWER}" rows="2" required></textarea>'
                        f'<button type="submit">Save answer</button></form>')
        if question.state == "open":
            controls += (f'<form class="qa-dismiss" method="post" action="{PREFIX}/questions/{qid}/dismiss" data-csrf="{esc(csrf_token)}" data-json="true">'
                         f'<button type="submit">Dismiss</button></form>')
        items.append(f'<li class="qa-question" data-question-id="{qid}" data-state="{esc(question.state)}" data-source-type="atlas_question">'
                     f'<p class="qa-text">{esc(question.text)}</p>'
                     f'<p class="qa-why">Why it matters: {esc(question.reason)}</p>'
                     f'<p class="qa-state">{esc(question.state.capitalize())} · expects {esc(question.expected_context_type.replace("_", " "))}</p>'
                     f"{history}{controls}</li>")
    return (f'<section class="atlas-questions" data-result-id="{esc(result_id)}" aria-label="Questions for management">'
            f'<h4 class="qa-title">Questions for management</h4>'
            f'<p class="qa-label">Atlas needs business context it cannot see in Monday. Answers are management context, not evidence.</p>'
            f'<ol class="qa-list">{"".join(items)}</ol></section>')


_SCOPES = (("company", "Company"), ("editor", "Editor"), ("video_type", "Video Type"), ("workflow", "Workflow stage"), ("client", "Client"),
           ("specific_result", "Specific result"))
_TYPES = (("business_rule", "Business rule"), ("context", "Context"), ("correction", "Correction"), ("interpretation", "Interpretation"),
          ("temporary_situation", "Temporary situation"))
_VALIDITY = (("until_changed", "Until changed"), ("date_range", "Date range"), ("current_period", "Current period only"))


def _options(choices: Sequence[tuple[str, str]]) -> str:
    return "".join(f'<option value="{esc(value)}">{esc(label)}</option>' for value, label in choices)


def _validity_text(teaching: Teaching) -> str:
    labels = dict(_VALIDITY)
    text = labels.get(teaching.validity_mode, teaching.validity_mode)
    if teaching.validity_mode != "until_changed":
        text += f": {teaching.valid_from or '…'} → {teaching.valid_until or '…'}"
    return text


def teach_atlas_page(teachings: Sequence[Teaching], *, csrf_token: str) -> str:
    """The Teach Atlas interface: a form to teach Atlas, and every teaching with its source, scope, type, validity and status."""
    rows = []
    for teaching in teachings:
        tid = esc(teaching.teaching_id)
        scope = dict(_SCOPES).get(teaching.scope_type, teaching.scope_type) + (f": {teaching.scope_id}" if teaching.scope_id else "")
        flag = '<span class="ta-flag">Reported data issue: under engineering review; evidence unchanged</span>' if teaching.affects_source_data else ""
        state = teaching.status if teaching.status != "active" or teaching.effective else "active (not in effect now)"
        actions = []
        if teaching.status != "archived":
            for action, label in (("enable", "Enable"), ("disable", "Disable"), ("archive", "Archive")):
                if (action, teaching.status) not in (("enable", "active"), ("disable", "disabled")):
                    actions.append(f'<form method="post" action="{PREFIX}/teachings/{tid}/{action}" data-csrf="{esc(csrf_token)}" data-json="true">'
                                   f'<button type="submit">{label}</button></form>')
        rows.append(f'<tr data-teaching-id="{tid}" data-source-type="management_teaching" data-status="{esc(teaching.status)}">'
                    f'<td class="ta-body">{_multiline(teaching.body)} {flag}</td>'
                    f"<td>Management teaching</td><td>{esc(scope)}</td><td>{esc(dict(_TYPES).get(teaching.teaching_type, teaching.teaching_type))}</td>"
                    f"<td>{esc(_validity_text(teaching))}</td><td>{esc(state)}</td><td>{esc(teaching.author or 'Management')} · revision {teaching.revision}</td>"
                    f'<td class="ta-actions">{"".join(actions)}</td></tr>')
    table = ('<table class="ta-list"><thead><tr><th>Teaching</th><th>Source</th><th>Scope</th><th>Type</th><th>Validity</th><th>Status</th>'
             f'<th>Author</th><th>Actions</th></tr></thead><tbody>{"".join(rows)}</tbody></table>') if rows else '<p class="ta-empty">Nothing taught yet.</p>'
    form = (f'<form class="ta-form" method="post" action="{PREFIX}/teachings" data-csrf="{esc(csrf_token)}" data-json="true">'
            f'<label for="ta-body">What should Atlas know?</label><textarea id="ta-body" name="body" maxlength="{MAX_TEACHING}" rows="3" required></textarea>'
            f'<label for="ta-scope">Scope</label><select id="ta-scope" name="scope_type">{_options(_SCOPES)}</select>'
            f'<label for="ta-scope-id">Editor, Video Type, stage, client or result</label><input id="ta-scope-id" name="scope_id" maxlength="200">'
            f'<label for="ta-type">Type</label><select id="ta-type" name="teaching_type">{_options(_TYPES)}</select>'
            f'<label for="ta-validity">Valid</label><select id="ta-validity" name="validity_mode">{_options(_VALIDITY)}</select>'
            f'<label for="ta-from">From</label><input id="ta-from" name="valid_from" type="date">'
            f'<label for="ta-until">Until (inclusive)</label><input id="ta-until" name="valid_until" type="date">'
            f'<label><input type="checkbox" name="affects_source_data" value="true"> This correction says Monday or pipeline data is wrong '
            f"(engineering reviews it; Atlas never edits evidence)</label>"
            f'<button type="submit">Teach Atlas</button></form>')
    return (f'<section class="teach-atlas" aria-label="Teach Atlas"><h2>Teach Atlas</h2>'
            f'<p class="ta-label">Teachings are management context for Atlas\'s reasoning. They never change Monday data, metrics or evidence.</p>'
            f"{form}{table}</section>")
