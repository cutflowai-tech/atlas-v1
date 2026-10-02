"""HTML fragments for human context on reasoning cards (``REV/12``-``REV/14``): the minimal interaction surface.

These are server-rendered fragments for the reasoning-first dashboard (Phase 16) to place on each card; they carry no script and
no credentials. Every piece of stored text is escaped here (``html.escape`` with quotes), so a note, answer or teaching can never
inject markup. Management context is always labelled as such, visually and in ``data-source-type``, and kept apart from Atlas
reasoning and deterministic evidence. Forms post JSON to ``management_api`` routes; the page supplies the CSRF token.
"""

from __future__ import annotations

from collections.abc import Sequence
from html import escape

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
