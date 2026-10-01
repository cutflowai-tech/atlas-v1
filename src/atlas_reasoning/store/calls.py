"""Persists gateway call metadata to ``llm_calls`` (``REV/06`` #9), one short transaction per call."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlas_reasoning.store.repository import ReasoningStore

if TYPE_CHECKING:
    from atlas_reasoning.gateway import CallRecord


class StoreCallRecorder:
    def __init__(self, store: ReasoningStore) -> None:
        self.store = store

    def record(self, call: CallRecord) -> None:
        with self.store.transaction() as tx:
            tx.record_llm_call(request_id=call.request_id, provider=call.provider, model=call.model, purpose=call.purpose, status=call.status,
                               attempts=call.attempts, latency_ms=call.latency_ms, started_at=call.started_at, finished_at=call.finished_at,
                               run_id=call.run_id, case_id=call.case_id, work_item_id=call.work_item_id, prompt_version=call.prompt_version,
                               source_snapshot_id=call.source_snapshot_id, evidence_fingerprint=call.evidence_fingerprint,
                               provider_status=call.provider_status, error_class=call.error_class, input_tokens=call.input_tokens,
                               output_tokens=call.output_tokens, provider_response_id=call.provider_response_id)
