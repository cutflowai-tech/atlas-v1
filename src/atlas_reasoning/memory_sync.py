"""Copies committed canonical context into contextual memory (``REV/10`` #7-9).

Order is fixed: a service commits its canonical row (note, answer, question, teaching) to PostgreSQL in its own transaction, and
only then calls ``MemorySyncService.sync``. Sync bookkeeping lives in ``memory_sync_log``, in separate short transactions, so:

- a Honcho outage, a rejection or a bug in the backend never rolls back, changes or loses the canonical row; the copy is logged
  ``failed`` (with its error class) and ``retry`` sends it later;
- the same content to the same session is sent once: the log is unique on (source, session, operation, content hash), a synced row
  is a duplicate and is not sent again, and a row being sent by another worker is skipped (row lock);
- when a canonical row changes, the new content is a new copy and older live copies of that source in that session are retired;
  ``retire_source`` retires every copy (a disabled or archived teaching, for example);
- with memory off (no backend) the row is logged ``skipped``: canonical state is complete without Honcho.

``retry`` never re-sends stale content: it rebuilds the current records of each unsynced source from the canonical store through
the registered resolvers, marks a superseded row ``skipped`` and syncs what the source holds now.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from atlas_reasoning.enums import MemorySyncStatus, NoteSource
from atlas_reasoning.memory import MemoryBackend, MemoryBackendError, MemoryPolicyError, MemoryRecord, check_record
from atlas_reasoning.store import memory_log
from atlas_reasoning.store.repository import ReasoningStore, StoreTransaction

log = logging.getLogger("atlas_reasoning.memory")

# Rebuilds the current memory records of one canonical source from PostgreSQL (empty when the source should have no live copy).
Resolver = Callable[[StoreTransaction, str], Sequence[MemoryRecord]]


@dataclass(frozen=True)
class SyncOutcome:
    source_type: str
    source_id: str
    session_key: str
    status: str             # synced / duplicate / failed / skipped / busy / refused
    sync_id: str | None = None
    external_ref: str | None = None
    error_class: str | None = None


class MemorySyncService:
    def __init__(self, store: ReasoningStore, backend: MemoryBackend | None, *, resolvers: Mapping[NoteSource, Resolver] | None = None) -> None:
        self.store = store
        self.backend = backend
        self.resolvers: dict[NoteSource, Resolver] = {NoteSource.PRIOR_REASONING_SUMMARY: result_summary_records, **(resolvers or {})}

    @property
    def enabled(self) -> bool:
        return self.backend is not None

    def register(self, source: NoteSource, resolver: Resolver) -> None:
        self.resolvers[source] = resolver

    def sync_result(self, result_id: str) -> list[SyncOutcome]:
        """Copy the current version of a committed result's management summary to its result and subject sessions (Phase 07-09 call
        this after a result version is committed)."""
        with self.store.transaction() as tx:
            records = result_summary_records(tx, result_id)
        return self.sync(records)

    def sync(self, records: Iterable[MemoryRecord]) -> list[SyncOutcome]:
        """Write each record's copy (after its canonical row was committed). Never raises for a backend failure, nor for a record
        the memory policy refuses (a body that is a JSON document, for example): the canonical row is already committed, so that
        copy is ``refused`` (nothing is logged or sent) and the caller's write still succeeds."""
        outcomes = []
        for record in records:
            try:
                checked = check_record(record)
            except MemoryPolicyError as error:
                log.warning("memory copy refused by policy: source=%s id=%s session=%s reason=%s", record.source_type, record.source_id,
                            record.session_key, error)
                outcomes.append(SyncOutcome(str(getattr(record.source_type, "value", record.source_type)), record.source_id, record.session_key,
                                            status="refused", error_class="memory_policy"))
                continue
            outcomes.append(self._sync_one(checked))
        return outcomes

    def _sync_one(self, record: MemoryRecord) -> SyncOutcome:
        backend_name = self.backend.name if self.backend is not None else None
        base = {"source_type": record.source_type.value, "source_id": record.source_id, "session_key": record.session_key}
        with self.store.transaction() as tx:
            row = memory_log.claim(tx, record, backend_name)
            if row is None:
                return SyncOutcome(**base, status="busy")
            if row["status"] == MemorySyncStatus.SYNCED and row["retired_at"] is None:
                return SyncOutcome(**base, status="duplicate", sync_id=row["sync_id"], external_ref=row["external_ref"])
            # A retired copy of the same content (a teaching disabled, then enabled again) is written again.
            if self.backend is None:
                memory_log.mark(tx, row["sync_id"], MemorySyncStatus.SKIPPED, backend=None, attempted=False)
                return SyncOutcome(**base, status="skipped", sync_id=row["sync_id"])
            try:
                ref = self.backend.write(record)
            except MemoryBackendError as error:
                memory_log.mark(tx, row["sync_id"], MemorySyncStatus.FAILED, backend=backend_name, error_class=error.error_class)
                log.warning("memory sync failed: source=%s id=%s session=%s error=%s", record.source_type, record.source_id, record.session_key,
                            error.error_class)
                return SyncOutcome(**base, status="failed", sync_id=row["sync_id"], error_class=error.error_class)
            except Exception as error:  # noqa: BLE001 - a backend bug must never break the caller's (already committed) write
                memory_log.mark(tx, row["sync_id"], MemorySyncStatus.FAILED, backend=backend_name, error_class="internal_error")
                log.error("memory sync internal error: source=%s id=%s error=%s", record.source_type, record.source_id, type(error).__name__)
                return SyncOutcome(**base, status="failed", sync_id=row["sync_id"], error_class="internal_error")
            memory_log.mark(tx, row["sync_id"], MemorySyncStatus.SYNCED, backend=backend_name, external_ref=ref)
            sync_id = row["sync_id"]
        self._retire_older(record, keep=sync_id)
        return SyncOutcome(**base, status="synced", sync_id=sync_id, external_ref=ref)

    def _retire_rows(self, rows: Sequence[dict]) -> int:
        retired = 0
        for row in rows:
            if self.backend is None:
                break
            try:
                self.backend.retire(row["session_key"], row["external_ref"])
            except MemoryBackendError as error:
                log.warning("memory retire failed: sync_id=%s error=%s", row["sync_id"], error.error_class)
                continue
            with self.store.transaction() as tx:
                memory_log.mark_retired(tx, row["sync_id"])
            retired += 1
        return retired

    def _retire_older(self, record: MemoryRecord, *, keep: str) -> None:
        with self.store.transaction() as tx:
            rows = [row for row in memory_log.live_copies(tx, record.source_type, record.source_id, record.session_key) if row["sync_id"] != keep]
        self._retire_rows(rows)

    def retire_source(self, source_type: NoteSource, source_id: str, *, keep_sessions: Iterable[str] = ()) -> int:
        """Retire every live copy of a canonical source (except in ``keep_sessions``). Returns the number retired."""
        keep = set(keep_sessions)
        with self.store.transaction() as tx:
            rows = [row for row in memory_log.live_copies(tx, source_type, source_id) if row["session_key"] not in keep]
        return self._retire_rows(rows)

    def retry(self, *, limit: int = 100) -> list[SyncOutcome]:
        """Re-send pending or failed copies, rebuilt from the current canonical rows."""
        outcomes: list[SyncOutcome] = []
        with self.store.transaction() as tx:
            stale = memory_log.unsynced(tx, limit)
            sources = sorted({(row["source_type"], row["source_id"]) for row in stale})
            current: dict[tuple[str, str], list[MemoryRecord]] = {}
            for source_type, source_id in sources:
                resolver = self.resolvers.get(NoteSource(source_type))
                current[(source_type, source_id)] = list(resolver(tx, source_id)) if resolver else []
            for row in stale:
                hashes = {(record.session_key, record.content_sha256) for record in current[(row["source_type"], row["source_id"])]}
                if (row["session_key"], row["content_sha256"]) not in hashes:
                    memory_log.mark(tx, row["sync_id"], MemorySyncStatus.SKIPPED, backend=None, attempted=False)
        for records in current.values():
            outcomes += self.sync(records)
        return outcomes


def subject_session(subject_type: str, subject_id: str) -> str | None:
    """The memory session of a case subject, when it has one (Editors, Video Types, the team)."""
    from atlas_reasoning.memory import TEAM_EDITORS, editor_session, video_type_session

    if subject_type == "editor":
        return editor_session(subject_id)
    if subject_type == "video_type":
        return video_type_session(subject_id)
    if subject_type == "team":
        return TEAM_EDITORS
    return None


def result_summary_records(tx: StoreTransaction, result_id: str) -> list[MemoryRecord]:
    """Resolver for ``prior_reasoning_summary``: the current version of a result, summarized, for its result and subject sessions.

    ``source_id`` is the result ID; the copy of each new version replaces the previous version's copy (it is retired)."""
    from atlas_reasoning.memory import result_session, summary_record
    from atlas_reasoning.store.repository import NotFound

    try:
        result = tx.get_result(result_id).to_dict()
        case = tx.get_case(result["case_id"])
    except NotFound:
        return []
    sessions = [result_session(result_id)]
    subject = subject_session(case.subject_type, case.subject_id)
    if subject is not None:
        sessions.append(subject)
    return [summary_record(result, session) for session in sessions]

