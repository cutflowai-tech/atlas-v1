"""Manager interpretation notes on reasoning results (``REV/12``).

A note is management's interpretation of one result: attributed, revisable, and never evidence. Its source type is always
``manager_interpretation``. Every create or edit is committed to PostgreSQL first (``manager_notes`` plus an append-only row in
``manager_note_revisions``), and only then copied to the result's memory session (``result:<result_id>``); a Honcho failure is
reported in the outcome and never loses the note. Edits use optimistic concurrency: an edit names the revision it was made
from, and a concurrent edit gets ``NoteConflict`` instead of silently overwriting.

Future reasoning sees a note only as attributed management context (``NoteContextSource`` → ``ReasoningCase.manager_context``),
for the case of the result it was written on.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from atlas_reasoning.enums import NoteSource
from atlas_reasoning.memory import MemoryRecord, RetrievedMemory, result_session
from atlas_reasoning.memory_context import CaseScope, ContextCandidate
from atlas_reasoning.memory_sync import MemorySyncService, SyncOutcome
from atlas_reasoning.store import human_context as sql
from atlas_reasoning.store.repository import NotFound, ReasoningStore, StoreError, StoreTransaction
from atlas_reasoning.user_text import clean_identity, clean_text

MAX_NOTE = 8000
SOURCE = NoteSource.MANAGER_INTERPRETATION
LABEL = "Manager interpretation (management context, not evidence)"


class NoteConflict(StoreError):
    """The note changed since the editor read it."""


@dataclass(frozen=True)
class Note:
    note_id: str
    result_id: str
    case_id: str
    author: str | None
    body: str
    revision: int
    created_at: str
    updated_at: str
    source_type: str = SOURCE.value

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Note:
        return cls(row["note_id"], row["result_id"], row["case_id"], row["author"], row["body"], row["revision"], sql.iso(row["created_at"]) or "",
                   sql.iso(row["updated_at"]) or "")

    def to_dict(self) -> dict[str, Any]:
        return {"note_id": self.note_id, "result_id": self.result_id, "case_id": self.case_id, "author": self.author, "body": self.body,
                "revision": self.revision, "source_type": self.source_type, "label": LABEL, "created_at": self.created_at,
                "updated_at": self.updated_at}


@dataclass(frozen=True)
class NoteWrite:
    note: Note
    sync: tuple[SyncOutcome, ...]


def note_record(note: Note) -> MemoryRecord:
    return MemoryRecord(SOURCE, note.note_id, result_session(note.result_id), note.body, author=note.author, recorded_at=note.updated_at,
                        metadata={"case_id": note.case_id, "result_id": note.result_id, "revision": note.revision})


def note_records(tx: StoreTransaction, note_id: str) -> list[MemoryRecord]:
    """Resolver: the current memory copy of a note."""
    try:
        return [note_record(Note.from_row(sql.get_note(tx, note_id)))]
    except NotFound:
        return []


class ManagerNotes:
    def __init__(self, store: ReasoningStore, sync: MemorySyncService) -> None:
        self.store = store
        self.sync = sync

    def create(self, result_id: str, body: str, *, author: str | None) -> NoteWrite:
        text = clean_text(body, field="note", max_length=MAX_NOTE)
        who = clean_identity(author)
        with self.store.transaction() as tx:
            result = sql.result_case(tx, result_id)
            note = Note.from_row(sql.insert_note(tx, result_id=result_id, case_id=result["case_id"], author=who, body=text))
        return NoteWrite(note, tuple(self.sync.sync([note_record(note)])))

    def update(self, note_id: str, body: str, *, author: str | None, expected_revision: int) -> NoteWrite:
        text = clean_text(body, field="note", max_length=MAX_NOTE)
        who = clean_identity(author)
        with self.store.transaction() as tx:
            current = sql.get_note(tx, note_id, lock=True)
            if current["body"] == text and current["revision"] == expected_revision:
                return NoteWrite(Note.from_row(current), ())          # nothing changed: no new revision, nothing to sync
            row = sql.update_note(tx, note_id=note_id, expected_revision=expected_revision, author=who, body=text)
            if row is None:
                raise NoteConflict(f"note {note_id} is at revision {current['revision']}, not {expected_revision}")
            note = Note.from_row(row)
        return NoteWrite(note, tuple(self.sync.sync([note_record(note)])))

    def get(self, note_id: str) -> Note:
        with self.store.transaction() as tx:
            return Note.from_row(sql.get_note(tx, note_id))

    def for_result(self, result_id: str) -> list[Note]:
        with self.store.transaction() as tx:
            sql.result_case(tx, result_id)
            return [Note.from_row(row) for row in sql.notes_for_results(tx, [result_id])]

    def history(self, note_id: str) -> list[dict[str, Any]]:
        with self.store.transaction() as tx:
            sql.get_note(tx, note_id)
            return [{"note_id": row["note_id"], "revision": row["revision"], "body": row["body"], "author": row["author"],
                     "recorded_at": sql.iso(row["recorded_at"])} for row in sql.note_revisions(tx, note_id)]


class NoteContextSource:
    """Notes on any result of the case, as attributed management context (``REV/12`` #8)."""

    source_type = SOURCE

    def candidates(self, tx: StoreTransaction, scope: CaseScope, now: datetime) -> Sequence[ContextCandidate]:
        return [ContextCandidate(SOURCE, row["note_id"], row["body"], sql.iso(row["updated_at"]) or "", "canonical", "result",
                                 session_key=result_session(row["result_id"]), author=row["author"], case_id=row["case_id"])
                for row in sql.notes_for_results(tx, scope.result_ids) if row["case_id"] == scope.case_id]

    def is_current(self, tx: StoreTransaction, memory: RetrievedMemory, scope: CaseScope, now: datetime) -> bool:
        try:
            row = sql.get_note(tx, memory.source_id or "")
        except NotFound:
            return False
        return bool(row["result_id"] in scope.result_ids and row["revision"] == memory.metadata.get("revision"))
