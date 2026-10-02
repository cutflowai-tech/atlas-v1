"""Teach Atlas (``REV/14``): explicit, scoped, expirable management teachings.

A teaching is something management deliberately tells Atlas: a business rule, context, a correction, an interpretation or a
temporary situation, for one scope:

=================  ==================  ============================  =========================================
Scope              ``scope_id``        Memory session                Reaches reasoning about
=================  ==================  ============================  =========================================
company            none                ``global:teachings``          every case
editor             Editor ID           ``editor:<id>``               that Editor's cases (and team cases that
                                                                     explicitly include the Editor)
video_type         Video Type key      ``video-type:<key>``          cases involving that Video Type
workflow           workflow stage      ``workflow:<stage>``          cases of that workflow stage
client             client ID           ``client:<id>``               no case yet: cases carry no client
                                                                     dimension, so client teachings are stored,
                                                                     synced and listed but not injected
specific_result    result ID           ``result:<id>``               that result's case
=================  ==================  ============================  =========================================

Validity: ``until_changed`` (from creation until disabled, archived or edited), ``date_range`` (explicit ``valid_from`` ..
``valid_until``; a date-only ``valid_until`` includes that whole day) or ``current_period`` (the current calendar month, UTC).
A teaching is **effective** while it is active and ``valid_from <= now < valid_until``; only effective teachings are injected into
reasoning context (an expired one is excluded even if its memory copy is still live) and only effective teachings have a live
memory copy (``retire_expired`` retires copies that expired).

Teachings are canonical in PostgreSQL (``teachings`` + append-only ``teaching_revisions`` snapshots) and contextual in Honcho.
``enable`` / ``disable`` / ``archive`` change status (archive is final and keeps the teaching readable for audit). Edits use
optimistic concurrency; the scope never changes (teach a new teaching instead).

A teaching never rewrites Monday evidence, metrics, fingerprints, findings or results: this module writes only ``teachings``,
``teaching_revisions`` and ``engineering_review_flags``. A ``correction`` must say whether it reports bad upstream data
(``affects_source_data``); when it does, an engineering review flag is opened and the teaching reaches reasoning labelled as a
reported data issue under review, with the evidence unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from atlas_reasoning.enums import NoteSource, TeachingScope, TeachingStatus, TeachingType, TeachingValidity
from atlas_reasoning.memory import GLOBAL_TEACHINGS, MemoryRecord, RetrievedMemory, session_key
from atlas_reasoning.memory_context import CaseScope, ContextCandidate
from atlas_reasoning.memory_sync import MemorySyncService, SyncOutcome
from atlas_reasoning.store import human_context as sql
from atlas_reasoning.store.repository import NotFound, ReasoningStore, StoreError, StoreTransaction
from atlas_reasoning.user_text import InvalidText, clean_identity, clean_text

MAX_TEACHING = 8000
SOURCE = NoteSource.MANAGEMENT_TEACHING
DATA_ISSUE_NOTE = ("Management reports that upstream source data may be wrong here; engineering is reviewing it. "
                   "The deterministic evidence has not been changed.")
_SESSION_KIND = {TeachingScope.EDITOR: "editor", TeachingScope.VIDEO_TYPE: "video-type", TeachingScope.WORKFLOW: "workflow",
                 TeachingScope.CLIENT: "client", TeachingScope.SPECIFIC_RESULT: "result"}
_SCOPE_KIND = {TeachingScope.COMPANY: GLOBAL_TEACHINGS, TeachingScope.EDITOR: "editor", TeachingScope.VIDEO_TYPE: "video-type",
               TeachingScope.WORKFLOW: "workflow", TeachingScope.CLIENT: "client", TeachingScope.SPECIFIC_RESULT: "result"}


class TeachingConflict(StoreError):
    """The teaching changed since it was read, or the requested change is not allowed (archived)."""


def teaching_session(scope_type: str, scope_id: str | None) -> str:
    scope = TeachingScope(scope_type)
    if scope == TeachingScope.COMPANY:
        return GLOBAL_TEACHINGS
    assert scope_id is not None
    return session_key(_SESSION_KIND[scope], scope_id)


def _parse_time(value: object, field: str, *, end_of_day: bool) -> datetime:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and len(value.strip()) == 10:
        try:
            day = date.fromisoformat(value.strip())
        except ValueError:
            raise InvalidText("INVALID_DATE", f"{field} must be YYYY-MM-DD or an ISO timestamp") from None
        moment = datetime(day.year, day.month, day.day, tzinfo=UTC) + (timedelta(days=1) if end_of_day else timedelta())
    elif isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            raise InvalidText("INVALID_DATE", f"{field} must be YYYY-MM-DD or an ISO timestamp") from None
    else:
        raise InvalidText("INVALID_DATE", f"{field} must be a date")
    if moment.tzinfo is None:
        raise InvalidText("INVALID_DATE", f"{field} needs a time zone")
    return moment.astimezone(UTC)


def current_period(now: datetime) -> tuple[datetime, datetime]:
    """The calendar month (UTC) containing ``now``."""
    start = datetime(now.year, now.month, 1, tzinfo=UTC)
    end = datetime(now.year + (now.month == 12), now.month % 12 + 1, 1, tzinfo=UTC)
    return start, end


def validity_window(mode: str, valid_from: object, valid_until: object, now: datetime) -> tuple[datetime | None, datetime | None]:
    validity = TeachingValidity(mode)
    if validity == TeachingValidity.UNTIL_CHANGED:
        if valid_until is not None:
            raise InvalidText("INVALID_VALIDITY", "an until-changed teaching has no end date")
        return (_parse_time(valid_from, "valid_from", end_of_day=False) if valid_from is not None else now), None
    if validity == TeachingValidity.CURRENT_PERIOD:
        if valid_from is not None or valid_until is not None:
            raise InvalidText("INVALID_VALIDITY", "a current-period teaching takes no dates")
        return current_period(now)
    if valid_from is None or valid_until is None:
        raise InvalidText("INVALID_VALIDITY", "a date-range teaching needs valid_from and valid_until")
    start = _parse_time(valid_from, "valid_from", end_of_day=False)
    end = _parse_time(valid_until, "valid_until", end_of_day=True)
    if end <= start:
        raise InvalidText("INVALID_VALIDITY", "valid_until must be after valid_from")
    return start, end


def is_effective(row: Mapping[str, Any], now: datetime) -> bool:
    return bool(row["status"] == TeachingStatus.ACTIVE and (row["valid_from"] is None or row["valid_from"] <= now)
                and (row["valid_until"] is None or now < row["valid_until"]))


@dataclass(frozen=True)
class Teaching:
    teaching_id: str
    body: str
    scope_type: str
    scope_id: str | None
    teaching_type: str
    validity_mode: str
    valid_from: str | None
    valid_until: str | None
    status: str
    author: str | None
    revision: int
    affects_source_data: bool
    effective: bool
    created_at: str
    updated_at: str
    source_type: str = SOURCE.value

    @classmethod
    def from_row(cls, row: Mapping[str, Any], now: datetime) -> Teaching:
        return cls(row["teaching_id"], row["body"], row["scope_type"], row["scope_id"], row["teaching_type"], row["validity_mode"],
                   sql.iso(row["valid_from"]), sql.iso(row["valid_until"]), row["status"], row["author"], row["revision"],
                   row["affects_source_data"], is_effective(row, now), sql.iso(row["created_at"]) or "", sql.iso(row["updated_at"]) or "")

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__} | {"session_key": teaching_session(self.scope_type, self.scope_id)}


def context_body(row: Mapping[str, Any]) -> str:
    """How a teaching reads in reasoning context: its type, scope and validity, then the teaching itself."""
    scope = row["scope_type"].replace("_", " ") + (f" {row['scope_id']}" if row["scope_id"] else "")
    until = f", valid until {sql.iso(row['valid_until'])}" if row["valid_until"] else ""
    body = f"Management teaching ({row['teaching_type'].replace('_', ' ')}; scope: {scope}{until}): {row['body']}"
    if row["affects_source_data"]:
        body += f"\n{DATA_ISSUE_NOTE}"
    return body[:8000]


def _record(row: Mapping[str, Any]) -> MemoryRecord:
    return MemoryRecord(SOURCE, row["teaching_id"], teaching_session(row["scope_type"], row["scope_id"]), context_body(row), author=row["author"],
                        recorded_at=sql.iso(row["updated_at"]),
                        metadata={"revision": row["revision"], "scope_type": row["scope_type"], "scope_id": row["scope_id"],
                                  "teaching_type": row["teaching_type"], "validity_mode": row["validity_mode"],
                                  "valid_from": sql.iso(row["valid_from"]), "valid_until": sql.iso(row["valid_until"])})


def teaching_records(tx: StoreTransaction, teaching_id: str, now: datetime | None = None) -> list[MemoryRecord]:
    """Resolver: the memory copy of a teaching while it is effective (none otherwise)."""
    try:
        row = sql.get_teaching(tx, teaching_id)
    except NotFound:
        return []
    return [_record(row)] if is_effective(row, now or datetime.now(UTC)) else []


@dataclass(frozen=True)
class TeachingWrite:
    teaching: Teaching
    review_flag: str | None
    sync: tuple[SyncOutcome, ...]
    retired: int


class TeachAtlas:
    def __init__(self, store: ReasoningStore, sync: MemorySyncService, *, clock: Any = None) -> None:
        self.store = store
        self.sync = sync
        self.clock = clock or (lambda: datetime.now(UTC))

    def _scope(self, tx: StoreTransaction, scope_type: object, scope_id: object) -> tuple[str, str | None]:
        try:
            scope = TeachingScope(str(scope_type))
        except ValueError:
            raise InvalidText("INVALID_SCOPE", f"scope_type must be one of {', '.join(s.value for s in TeachingScope)}") from None
        if scope == TeachingScope.COMPANY:
            if scope_id not in (None, ""):
                raise InvalidText("INVALID_SCOPE", "a company teaching has no scope_id")
            return scope.value, None
        sid = clean_text(scope_id, field="scope_id", max_length=200)
        if "\n" in sid:
            raise InvalidText("INVALID_SCOPE", "scope_id must be a single line")
        if scope == TeachingScope.SPECIFIC_RESULT:
            sql.result_case(tx, sid)        # NotFound for an unknown result
        return scope.value, sid

    @staticmethod
    def _type(teaching_type: object, affects_source_data: object) -> tuple[str, bool]:
        try:
            kind = TeachingType(str(teaching_type))
        except ValueError:
            raise InvalidText("INVALID_TYPE", f"teaching_type must be one of {', '.join(t.value for t in TeachingType)}") from None
        if kind == TeachingType.CORRECTION:
            if not isinstance(affects_source_data, bool):
                raise InvalidText("SOURCE_DATA_QUESTION", "a correction must say whether it reports wrong upstream data (affects_source_data)")
            return kind.value, affects_source_data
        if affects_source_data:
            raise InvalidText("SOURCE_DATA_QUESTION", "only a correction can report wrong upstream data")
        return kind.value, False

    def _after_commit(self, row: Mapping[str, Any], flag: Mapping[str, Any] | None, now: datetime) -> TeachingWrite:
        if is_effective(row, now):
            outcomes = tuple(self.sync.sync([_record(row)]))
            retired = self.sync.retire_source(SOURCE, row["teaching_id"], keep_sessions=[teaching_session(row["scope_type"], row["scope_id"])])
        else:
            outcomes, retired = (), self.sync.retire_source(SOURCE, row["teaching_id"])
        return TeachingWrite(Teaching.from_row(row, now), flag["flag_id"] if flag else None, outcomes, retired)

    def _flag(self, tx: StoreTransaction, row: Mapping[str, Any], by: str | None) -> dict[str, Any] | None:
        if not row["affects_source_data"]:
            return None
        return sql.raise_review_flag(tx, teaching_id=row["teaching_id"], revision=row["revision"], summary=row["body"], raised_by=by)

    def create(self, *, body: object, scope_type: object, scope_id: object, teaching_type: object, validity_mode: object, author: str | None,
               valid_from: object = None, valid_until: object = None, affects_source_data: object = None) -> TeachingWrite:
        """Teach Atlas. Arguments may come straight from a request body: every one is validated here."""
        now = self.clock()
        text = clean_text(body, field="teaching", max_length=MAX_TEACHING)
        who = clean_identity(author)
        kind, flags_data = self._type(teaching_type, affects_source_data)
        try:
            start, end = validity_window(str(validity_mode), valid_from, valid_until, now)
        except ValueError as error:
            if isinstance(error, InvalidText):
                raise
            raise InvalidText("INVALID_VALIDITY", f"validity_mode must be one of {', '.join(v.value for v in TeachingValidity)}") from None
        with self.store.transaction() as tx:
            scope, sid = self._scope(tx, scope_type, scope_id)
            row = sql.insert_teaching(tx, {"body": text, "scope_type": scope, "scope_id": sid, "teaching_type": kind,
                                           "validity_mode": TeachingValidity(str(validity_mode)).value,
                                           "valid_from": start, "valid_until": end, "author": who, "affects_source_data": flags_data})
            flag = self._flag(tx, row, who)
        return self._after_commit(row, flag, now)

    def update(self, teaching_id: str, *, expected_revision: int, author: str | None, body: object = None, teaching_type: object = None,
               validity_mode: object = None, valid_from: object = None, valid_until: object = None, affects_source_data: object = None) -> TeachingWrite:
        """Edit content, type or validity. Fields left ``None`` keep their value (validity is restated as a whole when changed)."""
        now = self.clock()
        who = clean_identity(author)
        with self.store.transaction() as tx:
            current = sql.get_teaching(tx, teaching_id, lock=True)
            if current["status"] == TeachingStatus.ARCHIVED:
                raise TeachingConflict(f"teaching {teaching_id} is archived")
            changes: dict[str, Any] = {}
            if body is not None:
                changes["body"] = clean_text(body, field="teaching", max_length=MAX_TEACHING)
            new_type = teaching_type if teaching_type is not None else current["teaching_type"]
            new_flag = affects_source_data if affects_source_data is not None else (current["affects_source_data"] if new_type == "correction" else False)
            changes["teaching_type"], changes["affects_source_data"] = self._type(new_type, new_flag)
            if validity_mode is not None:
                try:
                    changes["valid_from"], changes["valid_until"] = validity_window(str(validity_mode), valid_from, valid_until, now)
                except ValueError as error:
                    if isinstance(error, InvalidText):
                        raise
                    raise InvalidText("INVALID_VALIDITY", "unknown validity_mode") from None
                changes["validity_mode"] = TeachingValidity(str(validity_mode)).value
            elif valid_from is not None or valid_until is not None:
                raise InvalidText("INVALID_VALIDITY", "restate validity_mode when changing dates")
            changes = {name: value for name, value in changes.items() if value != current[name]}
            if not changes:
                return TeachingWrite(Teaching.from_row(current, now), None, (), 0)
            changes["author"] = who
            row = sql.update_teaching(tx, teaching_id, expected_revision=expected_revision, changes=changes, by=who)
            if row is None:
                raise TeachingConflict(f"teaching {teaching_id} is at revision {current['revision']}, not {expected_revision}")
            flag = self._flag(tx, row, who)
        return self._after_commit(row, flag, now)

    def set_status(self, teaching_id: str, status: str, *, author: str | None, expected_revision: int | None = None) -> TeachingWrite:
        """Enable (``active``), disable or archive. Archive is final."""
        now = self.clock()
        who = clean_identity(author)
        target = TeachingStatus(status)
        with self.store.transaction() as tx:
            current = sql.get_teaching(tx, teaching_id, lock=True)
            if current["status"] == target:
                return TeachingWrite(Teaching.from_row(current, now), None, (), 0)
            if current["status"] == TeachingStatus.ARCHIVED:
                raise TeachingConflict(f"teaching {teaching_id} is archived")
            revision = current["revision"] if expected_revision is None else expected_revision
            row = sql.update_teaching(tx, teaching_id, expected_revision=revision, changes={"status": target.value}, by=who, status_change=True)
            if row is None:
                raise TeachingConflict(f"teaching {teaching_id} is at revision {current['revision']}, not {revision}")
        return self._after_commit(row, None, now)

    def enable(self, teaching_id: str, *, author: str | None) -> TeachingWrite:
        return self.set_status(teaching_id, TeachingStatus.ACTIVE, author=author)

    def disable(self, teaching_id: str, *, author: str | None) -> TeachingWrite:
        return self.set_status(teaching_id, TeachingStatus.DISABLED, author=author)

    def archive(self, teaching_id: str, *, author: str | None) -> TeachingWrite:
        return self.set_status(teaching_id, TeachingStatus.ARCHIVED, author=author)

    def retire_expired(self) -> int:
        """Retire the memory copies of active teachings whose validity ended (canonical rows are unchanged)."""
        now = self.clock()
        with self.store.transaction() as tx:
            expired = [row["teaching_id"] for row in sql.teachings(tx, statuses=[TeachingStatus.ACTIVE.value])
                       if row["valid_until"] is not None and row["valid_until"] <= now]
        return sum(self.sync.retire_source(SOURCE, teaching_id) for teaching_id in expired)

    # --- reads ------------------------------------------------------------------------------------------------------------

    def get(self, teaching_id: str) -> Teaching:
        with self.store.transaction() as tx:
            return Teaching.from_row(sql.get_teaching(tx, teaching_id), self.clock())

    def list_teachings(self, *, statuses: Sequence[str] | None = None, scope_type: str | None = None) -> list[Teaching]:
        if statuses is not None:
            statuses = [TeachingStatus(status).value for status in statuses]
        if scope_type is not None:
            scope_type = TeachingScope(scope_type).value
        now = self.clock()
        with self.store.transaction() as tx:
            return [Teaching.from_row(row, now) for row in sql.teachings(tx, statuses=statuses, scope_type=scope_type)]

    def history(self, teaching_id: str) -> list[dict[str, Any]]:
        with self.store.transaction() as tx:
            sql.get_teaching(tx, teaching_id)
            return [{"revision": row["revision"], "snapshot": row["snapshot"], "author": row["author"], "recorded_at": sql.iso(row["recorded_at"])}
                    for row in sql.teaching_revisions(tx, teaching_id)]

    def review_flags(self, *, open_only: bool = True) -> list[dict[str, Any]]:
        with self.store.transaction() as tx:
            return [{**row, "created_at": sql.iso(row["created_at"]), "updated_at": sql.iso(row["updated_at"])}
                    for row in sql.review_flags(tx, open_only=open_only)]


def _relevant(row: Mapping[str, Any], scope: CaseScope) -> bool:
    kind = TeachingScope(row["scope_type"])
    if kind == TeachingScope.COMPANY:
        return True
    if kind == TeachingScope.EDITOR:
        return row["scope_id"] in scope.editor_ids
    if kind == TeachingScope.VIDEO_TYPE:
        return row["scope_id"] in scope.video_type_keys
    if kind == TeachingScope.WORKFLOW:
        return row["scope_id"] in scope.workflow_stages
    if kind == TeachingScope.SPECIFIC_RESULT:
        return row["scope_id"] in scope.result_ids
    return False        # client: cases carry no client dimension yet


class TeachingContextSource:
    """Effective teachings relevant to the case's scope (``REV/14`` #6-7)."""

    source_type = SOURCE

    def candidates(self, tx: StoreTransaction, scope: CaseScope, now: datetime) -> Sequence[ContextCandidate]:
        return [ContextCandidate(SOURCE, row["teaching_id"], context_body(row), sql.iso(row["updated_at"]) or "", "canonical",
                                 _SCOPE_KIND[TeachingScope(row["scope_type"])], session_key=teaching_session(row["scope_type"], row["scope_id"]),
                                 author=row["author"], labels={"teaching_type": row["teaching_type"], "affects_source_data": row["affects_source_data"]})
                for row in sql.teachings(tx, statuses=[TeachingStatus.ACTIVE.value]) if is_effective(row, now) and _relevant(row, scope)]

    def is_current(self, tx: StoreTransaction, memory: RetrievedMemory, scope: CaseScope, now: datetime) -> bool:
        try:
            row = sql.get_teaching(tx, memory.source_id or "")
        except NotFound:
            return False
        return bool(is_effective(row, now) and _relevant(row, scope) and row["revision"] == memory.metadata.get("revision"))
