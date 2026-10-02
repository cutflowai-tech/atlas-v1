"""Human context around each reasoning call: the seam that connects the engine (Phases 07–09) to the memory layer (Phases 10–14).

For every analyst or update request the engine:

1. **prepares** the case: ``prepare(case)`` asks the scoped ``MemoryContextAssembler`` (``REV/11``) for the case's bounded human
   context — canonical manager notes, management answers and teachings from PostgreSQL, plus remembered context that the canonical
   store proves current — and applies it to a copy of the case (``manager_context`` / ``memory_context`` only). Identity, evidence and
   the evidence fingerprint are untouched, so the Change Gate never sees context and context never becomes evidence;
2. **records** exactly what was injected, under the request ID the call will carry (``memory_injections``), before the call is made;
3. after the result (or result version) is **committed**, ``after_commit`` turns the version's ``questions_for_management`` into
   canonical Atlas questions (``REV/13``; deduplicated, answered/dismissed/evidence-answerable questions suppressed, stale open questions
   superseded) and only then copies the result's management summary to memory (``REV/10``). PostgreSQL always precedes Honcho; a memory
   failure is recorded in ``memory_sync_log`` for ``memory-sync`` to retry and never touches the committed result.

A no-change review (``no_change_review``) changes no visible field, so it asks no question and writes no memory (no churn).

The engine depends only on the ``ContextHooks`` protocol; ``HumanContext`` is the production implementation built from the memory
layer's public services. Honcho itself is reached only through those services (``memory_context``, ``memory_sync``).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from atlas_reasoning import human_context
from atlas_reasoning.atlas_questions import AtlasQuestions
from atlas_reasoning.contracts import ReasoningCase
from atlas_reasoning.enums import ResultChangeKind
from atlas_reasoning.memory import MemoryBackend
from atlas_reasoning.memory_context import AssembledContext
from atlas_reasoning.store.repository import ReasoningStore

LOG = logging.getLogger("atlas_reasoning.context")

# Result changes whose visible content is new: only these produce questions and memory copies.
MATERIAL_CHANGES = (ResultChangeKind.CREATED, ResultChangeKind.PATCHED)


@dataclass(frozen=True)
class PreparedCase:
    case: ReasoningCase                 # the case carrying its human context (evidence and identity unchanged)
    context: AssembledContext


@dataclass(frozen=True)
class FollowUp:
    """What happened after a result version was committed. Never affects the committed result."""

    questions: Mapping[str, int] = field(default_factory=dict)     # outcome -> count (created, repeated, suppressed_*)
    superseded_questions: int = 0
    memory_sync: Mapping[str, int] = field(default_factory=dict)   # sync status -> count (synced, duplicate, failed, skipped, ...)
    errors: tuple[str, ...] = ()
    skipped: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: (dict(value) if isinstance(value, Mapping) else list(value) if isinstance(value, tuple) else value)
                for key, value in asdict(self).items()}


class ContextHooks(Protocol):
    def prepare(self, case: ReasoningCase) -> PreparedCase: ...

    def record(self, prepared: PreparedCase, *, purpose: str, request_id: str, run_id: str | None, work_item_id: str | None,
               result_id: str | None) -> str: ...

    def after_commit(self, *, result_id: str, version: int, change_kind: ResultChangeKind, run_id: str | None) -> FollowUp: ...


def _count(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


class HumanContext:
    """``ContextHooks`` over the memory layer's public services. ``backend`` is ``honcho_client.backend_from_env()`` (``None`` when
    memory is off: canonical context only, every copy logged ``skipped``)."""

    def __init__(self, store: ReasoningStore, backend: MemoryBackend | None, *, env: Mapping[str, str] | None = None) -> None:
        self.store = store
        self.assembler = human_context.assembler(store, backend, env=env)
        self.sync = human_context.sync_service(store, backend)
        self.questions = AtlasQuestions(store, self.sync)

    def prepare(self, case: ReasoningCase) -> PreparedCase:
        document = case.to_dict()
        context = self.assembler.assemble(document)
        return PreparedCase(ReasoningCase.from_dict(context.apply(document)), context)

    def record(self, prepared: PreparedCase, *, purpose: str, request_id: str, run_id: str | None, work_item_id: str | None,
               result_id: str | None) -> str:
        return self.assembler.record(prepared.context, purpose=purpose, request_id=request_id, run_id=run_id, work_item_id=work_item_id,
                                     result_id=result_id)

    def after_commit(self, *, result_id: str, version: int, change_kind: ResultChangeKind, run_id: str | None) -> FollowUp:
        if change_kind not in MATERIAL_CHANGES:
            return FollowUp(skipped=f"{change_kind.value}: no visible change")
        errors: list[str] = []
        questions: dict[str, int] = {}
        superseded = 0
        try:   # canonical question records first (PostgreSQL), each copied to memory after its own commit
            report = self.questions.record_result_questions(result_id, version=version, run_id=run_id)
            questions, superseded = _count([outcome for _, outcome, _ in report.outcomes]), len(report.superseded)
        except Exception as error:  # noqa: BLE001 - the result is committed; a follow-up failure is reported, never raised
            LOG.error("questions not recorded result_id=%s version=%s error=%s", result_id, version, type(error).__name__)
            errors.append(f"questions:{type(error).__name__}")
        sync: dict[str, int] = {}
        try:   # then the result's management summary (never its evidence) to the result and subject sessions
            sync = _count([outcome.status for outcome in self.sync.sync_result(result_id)])
        except Exception as error:  # noqa: BLE001
            LOG.error("result memory sync failed result_id=%s version=%s error=%s", result_id, version, type(error).__name__)
            errors.append(f"memory:{type(error).__name__}")
        return FollowUp(questions, superseded, sync, tuple(errors))
