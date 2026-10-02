"""The reasoning engine: turns Change Gate work items into persisted reasoning (``REV/07``–``REV/09``).

    engine = ReasoningEngine(store, gateway)
    report = engine.process_run(run_id)          # every pending LLM work item, each isolated from the others

For each pending LLM work item:

1. **claim** (own transaction): ``pending → in_progress``; the exact case comes from ``change_gate.case_for_work``;
2. **reason**: one gateway call per item, all items concurrently through ``ReasoningGateway.call_many`` (bounded concurrency,
   retries, ``llm_calls`` records); the model's answer is validated inside the call;
3. **persist** (own transaction): the result is created (or, Phase 08, patched) together with the work item's ``done`` status —
   all or nothing. Any failure rolls the transaction back, so the stored result is exactly what it was, and the item is marked
   ``failed`` with a short error (``provider:<error class>``, ``contract:<codes>``, ``store:<error>``) in a separate transaction.

A failure — provider error, invalid output, store conflict — affects only its own work item. The model never sets identity,
provenance or lifecycle (``analyst``), and the answering model must be the configured one (``MODEL_SUBSTITUTED`` otherwise).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from atlas_reasoning import analyst
from atlas_reasoning.change_gate import case_for_work
from atlas_reasoning.contracts import ContractViolation, ReasoningCase, new_result_id
from atlas_reasoning.enums import ResultChangeKind, WorkKind, WorkStatus
from atlas_reasoning.gateway import CallOutcome, ReasoningGateway
from atlas_reasoning.provider import ProviderError, ProviderRequest, ProviderResponse
from atlas_reasoning.store.db import DatabaseError
from atlas_reasoning.store.repository import ReasoningStore, WorkItemRow, WorkTransitionError

LOG = logging.getLogger("atlas_reasoning.engine")
ENGINE_VERSION = "reasoning-engine-v1"


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class WorkError(RuntimeError):
    """A work item cannot be completed; ``code`` is stored as its error."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class WorkOutcome:
    work_item_id: str
    case_id: str
    kind: str
    status: str
    result_id: str | None = None
    version: int | None = None
    change_kind: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class EngineReport:
    run_id: str | None
    outcomes: tuple[WorkOutcome, ...]
    lifecycle: tuple[Any, ...] = field(default_factory=tuple)

    @property
    def failed(self) -> tuple[WorkOutcome, ...]:
        return tuple(row for row in self.outcomes if row.status == WorkStatus.FAILED)

    def to_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for row in self.outcomes:
            key = row.change_kind or row.status
            counts[key] = counts.get(key, 0) + 1
        return {"engine_version": ENGINE_VERSION, "run_id": self.run_id, "counts": counts, "work": [asdict(row) for row in self.outcomes],
                "lifecycle": [row.to_dict() if hasattr(row, "to_dict") else row for row in self.lifecycle]}


@dataclass(frozen=True)
class _Claimed:
    item: WorkItemRow
    case: ReasoningCase
    request: ProviderRequest


def error_code(error: BaseException) -> str:
    """A short, content-free description of a failure for ``reasoning_work_items.last_error``."""
    if isinstance(error, ProviderError):
        return f"provider:{error.error_class}"
    if isinstance(error, ContractViolation):
        return f"contract:{','.join(error.codes)}"
    if isinstance(error, WorkError):
        return f"work:{error.code}"
    if isinstance(error, DatabaseError):
        return f"store:{type(error).__name__}"
    return f"internal:{type(error).__name__}"


class ReasoningEngine:
    def __init__(self, store: ReasoningStore, gateway: ReasoningGateway, *, clock: Callable[[], str] = utc_now,
                 result_ids: Callable[[], str] = new_result_id) -> None:
        self.store, self.gateway, self.clock, self.result_ids = store, gateway, clock, result_ids

    # --- public ---------------------------------------------------------------------------------------------------------------

    def process_run(self, run_id: str) -> EngineReport:
        """Every pending LLM work item (of any run: older pending items are never skipped)."""
        return EngineReport(run_id, tuple(self.process_work(self.pending_work())))

    def pending_work(self) -> list[WorkItemRow]:
        items = self.store.work_items(open_only=True)
        return [item for item in items if item.status == WorkStatus.PENDING and item.kind in self.handled_kinds]

    handled_kinds: tuple[WorkKind, ...] = (WorkKind.NEW_RESULT,)

    def process_work(self, items: Sequence[WorkItemRow]) -> list[WorkOutcome]:
        outcomes: list[WorkOutcome] = []
        claimed: list[_Claimed] = []
        for item in items:
            try:
                ready = self._claim(item)
            except WorkTransitionError:
                continue   # another worker took it, or it was superseded or cancelled meanwhile
            except Exception as error:  # noqa: BLE001 - one bad item never stops the others
                outcomes.append(self._fail(item, error))
                continue
            if isinstance(ready, WorkOutcome):
                outcomes.append(ready)
            else:
                claimed.append(ready)
        for ready, call in zip(claimed, self.gateway.call_many([ready.request for ready in claimed])):
            outcomes.append(self._complete(ready, call))
        return outcomes

    # --- steps ----------------------------------------------------------------------------------------------------------------

    def _claim(self, item: WorkItemRow) -> _Claimed | WorkOutcome:
        with self.store.transaction() as tx:
            tx.set_work_item_status(item.work_item_id, WorkStatus.IN_PROGRESS)
        try:
            with self.store.transaction() as tx:
                case = case_for_work(tx, item)
                if item.kind == WorkKind.NEW_RESULT and tx.open_result(item.case_id) is not None:
                    raise WorkError("RESULT_EXISTS", f"case {item.case_id} already has an open result")
            return _Claimed(item, case, analyst.analyst_request(case, run_id=item.run_id, work_item_id=item.work_item_id))
        except Exception as error:  # noqa: BLE001
            return self._fail(item, error)

    def _complete(self, ready: _Claimed, call: CallOutcome) -> WorkOutcome:
        if call.error is not None or call.response is None:
            return self._fail(ready.item, call.error or WorkError("NO_RESPONSE"))
        try:
            self._check_model(call.response)
            return self._persist_new(ready, call.response)
        except Exception as error:  # noqa: BLE001 - rolled back; recorded on the item
            return self._fail(ready.item, error)

    def _check_model(self, response: ProviderResponse) -> None:
        if response.model != self.gateway.model:
            raise WorkError("MODEL_SUBSTITUTED", f"answered by {response.model}, configured {self.gateway.model}")

    def _persist_new(self, ready: _Claimed, response: ProviderResponse) -> WorkOutcome:
        item = ready.item
        result = analyst.result_from_response(ready.case, response, provider=self.gateway.transport.provider_name, result_id=self.result_ids(),
                                              now=self.clock())
        with self.store.transaction() as tx:
            tx.create_result(result, run_id=item.run_id, work_item_id=item.work_item_id)
            tx.set_work_item_status(item.work_item_id, WorkStatus.DONE)
        LOG.info("result created work_item_id=%s case_id=%s result_id=%s", item.work_item_id, item.case_id, result.result_id)
        return WorkOutcome(item.work_item_id, item.case_id, item.kind.value, WorkStatus.DONE.value, result.result_id, 1, ResultChangeKind.CREATED.value)

    def _fail(self, item: WorkItemRow, error: BaseException) -> WorkOutcome:
        code = error_code(error)
        LOG.warning("work item failed work_item_id=%s case_id=%s error=%s", item.work_item_id, item.case_id, code)
        try:
            with self.store.transaction() as tx:
                tx.set_work_item_status(item.work_item_id, WorkStatus.FAILED, error=code)
        except DatabaseError as failure:
            LOG.error("work item status not recorded work_item_id=%s error=%s", item.work_item_id, error_code(failure))
        return WorkOutcome(item.work_item_id, item.case_id, item.kind.value, WorkStatus.FAILED.value, item.result_id, None, None, code)
