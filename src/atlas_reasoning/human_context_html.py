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
