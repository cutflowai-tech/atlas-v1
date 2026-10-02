"""Scoped memory context for one reasoning case (``REV/11``).

``MemoryContextAssembler.assemble(case_document)`` decides which human context and memory a reasoning call about that case may see:

1. **Scope** (``case_scope``). The case's subject and type decide which memory sessions are in scope. An Editor case sees the global
   teachings, that Editor's session, the sessions of its Video Types and the sessions of its own results. A team case (or any
   non-Editor case) sees no Editor's memory unless the caller explicitly names Editors the case includes
   (``explicit_editor_ids``, which must be among the case's affected Editors). Nothing outside the scope is read.
2. **Canonical context** (``manager_context``). Registered ``ContextSource``s (Phases 12-14: manager notes, management answers,
   teachings) read PostgreSQL. This never depends on Honcho and is available even when memory is off or down.
3. **Remembered context** (``memory_context``). With a memory backend, each in-scope session is read. A remembered item is kept only
   when its canonical provenance proves it current: its metadata names the session it was read from, a live ``memory_sync_log``
   row produced exactly this copy (same backend reference, same content hash, not retired), and its source's ``ContextSource``
   (or the result store, for prior reasoning) says the source is still valid (a disabled or expired teaching is not). Anything
   else is dropped and counted.
4. **Deduplication.** One item per canonical source (canonical beats remembered), and one item per normalized body text.
5. **Deterministic order and budgets.** Items are ordered by scope (this result, this case, subject, team, company), source type,
   newest first, then source ID; then admitted in that order while each source type's token cap, the per-item cap and the total
   cap allow (``MemoryBudget``; tokens are estimated as ``ceil(characters / 4)``). An item longer than the per-item cap is cut at a
   character boundary and marked truncated.
6. **Degraded mode.** If the backend fails, canonical context is still returned, ``memory_context.status`` is ``degraded`` and the
   reason is recorded; reasoning continues.
7. **Audit.** ``record(context, request_id=...)`` persists exactly which items (source, session, memory reference, content hash,
   tokens, truncation) were injected into which call (``memory_injections``).

Human context is never evidence: the assembled context fills ``manager_context`` and ``memory_context`` of a copy of the case
document only; the case's identity, evidence and fingerprint are unchanged (the fingerprint excludes both fields).
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from atlas_reasoning.contracts import ReasoningCase
from atlas_reasoning.enums import MemoryStatus, NoteSource
from atlas_reasoning.memory import (
    GLOBAL_TEACHINGS,
    METADATA_KEYS,
    TEAM_EDITORS,
    MemoryBackend,
    MemoryBackendError,
    MemoryRecord,
    RetrievedMemory,
    editor_session,
    parse_session,
    result_session,
    session_key,
    summary_record,
    video_type_session,
)
from atlas_reasoning.settings import ReasoningConfigError
from atlas_reasoning.store import human_context as sql
from atlas_reasoning.store.repository import NotFound, ReasoningStore, StoreTransaction

ASSEMBLER_VERSION = "memory-context-v1"
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


# --- scope ------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CaseScope:
    """What memory one case may see."""

    case_id: str
    case_type: str
    subject_type: str
    subject_id: str
    topic_key: str
    editor_ids: tuple[str, ...]
    video_type_keys: tuple[str, ...]
    workflow_stages: tuple[str, ...]
    result_ids: tuple[str, ...]
    previous_result_id: str | None
    include_team: bool

    @property
    def sessions(self) -> tuple[str, ...]:
        """In-scope memory sessions, in a stable order."""
        keys = [result_session(rid) for rid in self.result_ids]
        keys += [editor_session(eid) for eid in self.editor_ids]
        keys += [video_type_session(key) for key in self.video_type_keys]
        keys += [session_key("workflow", stage) for stage in self.workflow_stages]
        if self.include_team:
            keys.append(TEAM_EDITORS)
        keys.append(GLOBAL_TEACHINGS)
        return tuple(dict.fromkeys(keys))


def case_scope(case: Mapping[str, Any], result_ids: Sequence[str] = (), *, explicit_editor_ids: Iterable[str] = ()) -> CaseScope:
    """The memory scope of a case document (``REV/11`` #2-4)."""
    subject_type, subject_id = case["subject_type"], case["subject_id"]
    dims = case.get("identity_dimensions") or {}
    affected_editors = set(case["scope"]["affected_editor_ids"])
    explicit = sorted(set(explicit_editor_ids))
    stray = [eid for eid in explicit if eid not in affected_editors]
    if stray:
        raise ValueError(f"explicit Editors {stray} are not part of case {case['case_id']}")
    if subject_type == "editor":
        editors: list[str] = [subject_id]
    else:
        editors = explicit
    video_types = sorted({*case["scope"]["affected_video_type_keys"], *([dims["video_type"]] if dims.get("video_type") else [])})
    if subject_type == "video_type":
        video_types = sorted({*video_types, subject_id})
    stages = sorted({*([dims["workflow_stage"]] if dims.get("workflow_stage") else []), *([subject_id] if subject_type == "workflow_stage" else [])})
    return CaseScope(case["case_id"], case["case_type"], subject_type, subject_id, case["topic_key"], tuple(editors), tuple(video_types),
                     tuple(stages), tuple(dict.fromkeys(result_ids)), case.get("previous_result_id"), include_team=subject_type == "team")


# --- items ------------------------------------------------------------------------------------------------------------------

# Scope rank: closer subjects first.
_SCOPE_RANK = {"result": 0, "case": 1, "editor": 2, "video-type": 3, "workflow": 3, "client": 3, TEAM_EDITORS: 4, GLOBAL_TEACHINGS: 5}
_SOURCE_RANK = {NoteSource.MANAGEMENT_TEACHING: 0, NoteSource.MANAGER_INTERPRETATION: 1, NoteSource.MANAGER_ANSWER: 2,
                NoteSource.PRIOR_REASONING_SUMMARY: 3, NoteSource.ATLAS_QUESTION: 4}


@dataclass(frozen=True)
class ContextCandidate:
    """One attributed piece of human context or memory, with its provenance."""

    source_type: NoteSource
    source_id: str
    body: str
    recorded_at: str
    origin: str                      # "canonical" (PostgreSQL) or "memory" (a validated backend copy)
    scope_kind: str                  # result / case / editor / video-type / workflow / client / team:editors / global:teachings
    session_key: str | None = None
    author: str | None = None
    memory_ref: str | None = None
    content_sha256: str | None = None
    case_id: str | None = None
    truncated: bool = False
    labels: Mapping[str, Any] = field(default_factory=dict)

    def sort_key(self, case_id: str) -> tuple[Any, ...]:
        rank = _SCOPE_RANK.get(self.scope_kind, 6)
        if rank > 1 and self.case_id == case_id:
            rank = 1        # context about this very case outranks other context about the same subject
        # Newest first: invert the timestamp's characters so a plain ascending sort stays deterministic.
        return (rank, _SOURCE_RANK.get(self.source_type, 9), _desc(self.recorded_at), self.source_id, self.origin)

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.body)


def _content_hash(source_type: NoteSource, source_id: str, session: str, memory: RetrievedMemory) -> str:
    """The content hash of a returned copy, recomputed from what the backend returned (never the hash it claims)."""
    metadata = {k: v for k, v in memory.metadata.items() if k in METADATA_KEYS and v is not None}
    return MemoryRecord(source_type, source_id, session, memory.body, metadata=metadata).content_sha256


def _desc(text: str) -> tuple[int, ...]:
    return tuple(-ord(ch) for ch in text)


def _norm_body(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().casefold()


class ContextSource(Protocol):
    """A canonical source of human context (registered by Phases 12-14)."""

    source_type: NoteSource

    def candidates(self, tx: StoreTransaction, scope: CaseScope, now: datetime) -> Sequence[ContextCandidate]: ...

    def is_current(self, tx: StoreTransaction, memory: RetrievedMemory, scope: CaseScope, now: datetime) -> bool: ...


class PriorReasoningSource:
    """Prior reasoning summaries come only from memory (canonical results reach the analyst through ``case_for_work``); a remembered
    summary is current when its result exists, is neither superseded nor resolved, and the copy says exactly what the result's current
    version would say (so a no-change review, which changes no visible field, needs no new copy)."""

    source_type = NoteSource.PRIOR_REASONING_SUMMARY

    def candidates(self, tx: StoreTransaction, scope: CaseScope, now: datetime) -> Sequence[ContextCandidate]:
        return ()

    def is_current(self, tx: StoreTransaction, memory: RetrievedMemory, scope: CaseScope, now: datetime) -> bool:
        result_id = memory.source_id or ""
        if result_id == scope.previous_result_id:
            return False    # the analyst already receives the previous result itself
        try:
            row = sql.result_case(tx, result_id)
        except NotFound:
            return False
        if row["lifecycle_status"] in ("superseded", "resolved"):
            return False    # a replaced or resolved card is not current reasoning
        if memory.metadata.get("result_version") == row["current_version"]:
            return True
        current = summary_record(tx.get_result(result_id).to_dict(), memory.session_key)
        return current.body == memory.body


# --- budgets ----------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryBudget:
    """Token limits for injected context. Configurable (``budget_from_env``); every value is bounded."""

    total_tokens: int = 3000
    item_tokens: int = 500
    max_items: int = 24
    per_source_tokens: Mapping[str, int] = field(default_factory=lambda: {
        NoteSource.MANAGEMENT_TEACHING.value: 1200, NoteSource.MANAGER_INTERPRETATION.value: 800, NoteSource.MANAGER_ANSWER.value: 800,
        NoteSource.PRIOR_REASONING_SUMMARY.value: 600, NoteSource.ATLAS_QUESTION.value: 0})
    session_read_limit: int = 20

    def to_dict(self) -> dict[str, Any]:
        return {"total_tokens": self.total_tokens, "item_tokens": self.item_tokens, "max_items": self.max_items,
                "per_source_tokens": dict(sorted(self.per_source_tokens.items())), "session_read_limit": self.session_read_limit}


def budget_from_env(env: Mapping[str, str] | None = None) -> MemoryBudget:
    """``ATLAS_REASONING_MEMORY_TOTAL_TOKENS`` (100-20000), ``..._ITEM_TOKENS`` (20-4000), ``..._MAX_ITEMS`` (1-100) and
    ``ATLAS_REASONING_MEMORY_<SOURCE_TYPE>_TOKENS`` (0-20000) override the defaults."""
    env = os.environ if env is None else env
    base = MemoryBudget()

    def number(name: str, default: int, low: int, high: int) -> int:
        raw = env.get(name, "").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            raise ReasoningConfigError(f"{name} must be an integer") from None
        if not low <= value <= high:
            raise ReasoningConfigError(f"{name} must be between {low} and {high}")
        return value

    per_source = {source: number(f"ATLAS_REASONING_MEMORY_{source.upper()}_TOKENS", tokens, 0, 20000)
                  for source, tokens in base.per_source_tokens.items()}
    return MemoryBudget(total_tokens=number("ATLAS_REASONING_MEMORY_TOTAL_TOKENS", base.total_tokens, 100, 20000),
                        item_tokens=number("ATLAS_REASONING_MEMORY_ITEM_TOKENS", base.item_tokens, 20, 4000),
                        max_items=number("ATLAS_REASONING_MEMORY_MAX_ITEMS", base.max_items, 1, 100), per_source_tokens=per_source)


# --- result -----------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AssembledContext:
    case_id: str
    scope: CaseScope
    memory_status: MemoryStatus
    degraded_reason: str | None
    items: tuple[ContextCandidate, ...]           # injected, in serialization order
    dropped: Mapping[str, int]
    budget: MemoryBudget

    @property
    def manager_context(self) -> list[dict[str, Any]]:
        return [{"source_type": item.source_type.value, "source_id": item.source_id, "body": item.body, "author": item.author,
                 "recorded_at": item.recorded_at} for item in self.items if item.origin == "canonical"]

    @property
    def memory_context(self) -> dict[str, Any]:
        return {"status": self.memory_status.value,
                "items": [{"source_type": item.source_type.value, "memory_ref": item.memory_ref, "session_key": item.session_key, "body": item.body,
                           "recorded_at": item.recorded_at or None} for item in self.items if item.origin == "memory"]}

    def audit_rows(self) -> list[dict[str, Any]]:
        return [{"position": index, "source_type": item.source_type.value, "source_id": item.source_id, "origin": item.origin,
                 "scope_kind": item.scope_kind, "session_key": item.session_key, "memory_ref": item.memory_ref,
                 "content_sha256": item.content_sha256 or hashlib.sha256(item.body.encode()).hexdigest(), "tokens": item.tokens,
                 "truncated": item.truncated} for index, item in enumerate(self.items)]

    @property
    def context_sha256(self) -> str:
        payload = {"manager_context": self.manager_context, "memory_context": self.memory_context}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

    def apply(self, case_document: Mapping[str, Any]) -> dict[str, Any]:
        """A copy of the case document carrying this context, validated against reasoning-v1. Evidence and identity are untouched."""
        if case_document["case_id"] != self.case_id:
            raise ValueError("context was assembled for another case")
        document = copy.deepcopy(dict(case_document))
        document["manager_context"] = self.manager_context
        document["memory_context"] = self.memory_context
        return ReasoningCase.from_dict(document).to_dict()


# --- assembler --------------------------------------------------------------------------------------------------------------


class MemoryContextAssembler:
    def __init__(self, store: ReasoningStore, backend: MemoryBackend | None, *, sources: Iterable[ContextSource] = (),
                 budget: MemoryBudget | None = None) -> None:
        self.store = store
        self.backend = backend
        self.budget = budget or MemoryBudget()
        self.sources: dict[NoteSource, ContextSource] = {NoteSource.PRIOR_REASONING_SUMMARY: PriorReasoningSource()}
        for source in sources:
            self.sources[source.source_type] = source

    def assemble(self, case_document: Mapping[str, Any], *, explicit_editor_ids: Iterable[str] = (), now: datetime | None = None) -> AssembledContext:
        now = now or datetime.now(UTC)
        dropped: dict[str, int] = {}

        def drop(reason: str) -> None:
            dropped[reason] = dropped.get(reason, 0) + 1

        with self.store.transaction() as tx:
            scope = case_scope(case_document, sql.case_result_ids(tx, case_document["case_id"]), explicit_editor_ids=explicit_editor_ids)
            canonical: list[ContextCandidate] = []
            for source_type in sorted(self.sources):
                canonical += self.sources[source_type].candidates(tx, scope, now)
        status, reason, remembered = self._remembered(scope, now, drop)
        selected = self._select(scope.case_id, canonical, remembered, drop)
        return AssembledContext(scope.case_id, scope, status, reason, tuple(selected), dict(sorted(dropped.items())), self.budget)

    def _remembered(self, scope: CaseScope, now: datetime, drop: Any) -> tuple[MemoryStatus, str | None, list[ContextCandidate]]:
        if self.backend is None:
            return MemoryStatus.NOT_REQUESTED, None, []
        found: list[tuple[str, RetrievedMemory]] = []
        try:
            for key in scope.sessions:
                found += [(key, memory) for memory in self.backend.read(key, limit=self.budget.session_read_limit)]
        except MemoryBackendError as error:
            return MemoryStatus.DEGRADED, error.error_class, []
        except Exception as error:  # noqa: BLE001 - a memory bug must never stop reasoning
            return MemoryStatus.DEGRADED, f"internal_error:{type(error).__name__}", []
        kept: list[ContextCandidate] = []
        with self.store.transaction() as tx:
            for key, memory in found:
                candidate = self._validate(tx, key, memory, scope, now)
                if isinstance(candidate, str):
                    drop(candidate)
                else:
                    kept.append(candidate)
        return MemoryStatus.AVAILABLE, None, kept

    def _validate(self, tx: StoreTransaction, key: str, memory: RetrievedMemory, scope: CaseScope, now: datetime) -> ContextCandidate | str:
        if memory.metadata.get("session_key") != key or memory.session_key != key:
            return "memory_wrong_session"
        try:
            source_type = NoteSource(memory.source_type or "")
        except ValueError:
            return "memory_unknown_source"
        if not memory.source_id:
            return "memory_without_provenance"
        log_row = sql.live_sync_row(tx, memory.memory_ref, key)
        if (log_row is None or log_row["source_type"] != source_type.value or log_row["source_id"] != memory.source_id
                or log_row["content_sha256"] != memory.metadata.get("content_sha256")
                or log_row["content_sha256"] != _content_hash(source_type, memory.source_id, key, memory)):
            return "memory_not_canonical"     # unknown, retired, or not exactly the copy that was written (body and metadata re-hashed)
        source = self.sources.get(source_type)
        if source is None or not source.is_current(tx, memory, scope, now):
            return "memory_not_current"
        kind, _ = parse_session(key)
        case_id = memory.metadata.get("case_id")
        recorded = memory.metadata.get("recorded_at") or memory.created_at or ""
        return ContextCandidate(source_type, memory.source_id, memory.body, str(recorded), "memory", kind, session_key=key, memory_ref=memory.memory_ref,
                                content_sha256=log_row["content_sha256"], case_id=case_id if isinstance(case_id, str) else None)

    def _select(self, case_id: str, canonical: Sequence[ContextCandidate], remembered: Sequence[ContextCandidate], drop: Any) -> list[ContextCandidate]:
        ordered = sorted(canonical, key=lambda item: item.sort_key(case_id)) + sorted(remembered, key=lambda item: item.sort_key(case_id))
        seen_sources: set[tuple[str, str]] = set()
        seen_bodies: set[str] = set()
        unique: list[ContextCandidate] = []
        for item in ordered:            # canonical first, so a remembered copy of a canonical item is the duplicate
            source = (item.source_type.value, item.source_id)
            body = _norm_body(item.body)
            if source in seen_sources or body in seen_bodies:
                drop("duplicate")
                continue
            seen_sources.add(source)
            seen_bodies.add(body)
            unique.append(item)
        unique.sort(key=lambda item: item.sort_key(case_id))
        budget = self.budget
        used_total = 0
        used: dict[str, int] = {}
        selected: list[ContextCandidate] = []
        limit_chars = budget.item_tokens * CHARS_PER_TOKEN
        for item in unique:
            if len(item.body) > limit_chars:
                item = replace(item, body=item.body[: limit_chars - 1].rstrip() + "…", truncated=True)
            cap = budget.per_source_tokens.get(item.source_type.value, 0)
            if len(selected) >= budget.max_items:
                drop("budget_items")
                continue
            if used.get(item.source_type.value, 0) + item.tokens > cap:
                drop(f"budget_{item.source_type.value}")
                continue
            if used_total + item.tokens > budget.total_tokens:
                drop("budget_total")
                continue
            used[item.source_type.value] = used.get(item.source_type.value, 0) + item.tokens
            used_total += item.tokens
            selected.append(item)
        return selected

    def record(self, context: AssembledContext, *, purpose: str, request_id: str | None = None, run_id: str | None = None,
               work_item_id: str | None = None, result_id: str | None = None) -> str:
        """Persist exactly which items were injected into one call (``REV/11`` #11)."""
        with self.store.transaction() as tx:
            return sql.insert_injection(tx, case_id=context.case_id, result_id=result_id, run_id=run_id, work_item_id=work_item_id, request_id=request_id,
                                        purpose=purpose, assembler_version=ASSEMBLER_VERSION, memory_status=context.memory_status.value,
                                        degraded_reason=context.degraded_reason, sessions=context.scope.sessions, budget=context.budget.to_dict(),
                                        selected=context.audit_rows(), dropped=context.dropped, context_sha256=context.context_sha256)
