"""Offline model stand-ins for the Reasoning V3 engine tests (Phases 07–09). No network, ever.

``ScriptedAnalyst`` is a ``Transport`` that reads the case input from the request (as the real model would) and answers with
valid analyst or update output built only from that input, so end-to-end tests run the real gate, engine, validation and store.
Tests override answers per case (``answers``) or per purpose to simulate malformed, invalid or failing model output.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from atlas_reasoning.contracts import PATCHABLE_FIELDS
from atlas_reasoning.gateway import MemoryRecorder, ReasoningGateway
from atlas_reasoning.provider import ProviderError, ProviderRequest, ProviderResponse
from atlas_reasoning.settings import PINNED_MODEL, GatewaySettings

MARKER = "(JSON):\n"


def request_input(request: ProviderRequest) -> dict[str, Any]:
    """The case input of a request (its first user message carrying JSON; a corrective re-ask appends messages after it)."""
    text = next(m.content for m in request.messages if m.role == "user" and MARKER in m.content)
    payload: dict[str, Any] = json.loads(text[text.index(MARKER) + len(MARKER):])
    return payload


def _refs(case: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    contradicting_members = {row["member_key"] for row in case["contradicting_findings"]}
    support, contra = [], []
    for ref in case["evidence_references"]:
        (contra if ref["role"] == "contradicting" or ref["member_key"] in contradicting_members else support).append(ref["ref_id"])
    return support, contra


def analyst_answer(case: Mapping[str, Any], *, title: str | None = None) -> dict[str, Any]:
    """A valid analyst answer citing only the case's references and using only its numbers."""
    support, contra = _refs(case)
    support = support or contra
    sample = case["supporting_findings"][0]["sample_size"] if case["supporting_findings"] else case["contradicting_findings"][0]["sample_size"]
    subject = f"{case['case']['subject_type']} {case['case']['subject_id']}"
    return {
        "title": title or f"{case['case']['topic_key'].replace('_', ' ').capitalize()} pattern for {subject}",
        "observation": {"statement": f"The deterministic findings describe a {case['orientation']} {case['case']['topic_key']} pattern over {sample} projects.",
                        "evidence_refs": support[:2]},
        "reasoning_summary": "The supporting findings point the same way; the evidence records show which projects carry the pattern.",
        "supporting_evidence": [{"statement": "The supporting findings and their records.", "evidence_refs": support[:3]}],
        "counter_evidence": [{"statement": "Some findings point the other way.", "evidence_refs": contra[:1]}] if contra else [],
        "interpretation": {"statement": "The pattern is likely real but its cause is not visible in Monday.", "evidence_refs": support[:1]},
        "alternative_explanations": [{"explanation": "Assignments or briefs may have changed.", "evidence_refs": [], "requires_context": True}],
        "confidence": {"level": "weak", "rationale": "Kept weak: the cause is not in the data."},
        "limitations": ["Only attributed projects are counted."],
        "management_significance": {"statement": "Worth a short review with the team lead.", "evidence_refs": support[:1]},
        "questions_for_management": [{"text": "Did anything change in how this work was assigned?", "reason": "Assignment context is not in Monday.",
                                      "expected_context_type": "assignment_context"}],
        "suggested_investigations": [{"text": "Review the projects behind the supporting records.", "evidence_refs": support[:1]}],
    }


def update_answer(payload: Mapping[str, Any], *, change: Mapping[str, Any] | None = None, rationale: str = "The evidence moved.") -> dict[str, Any]:
    """A valid update answer: ``change`` maps fields to new values (default: the fields that must change, plus confidence)."""
    must = list(payload.get("fields_citing_removed_evidence", []))
    if change is None:
        fresh = analyst_answer(payload)
        change = {name: fresh[name] for name in must} or {"confidence": {"level": "weak", "rationale": "The newest evidence changed the sample."}}
    action = "patch" if change else "no_change"
    return {"action": action, "change_rationale": rationale, "changed_fields": list(change),
            "preserved_fields": [name for name in PATCHABLE_FIELDS if name not in change],
            "patch": {name: change.get(name) for name in PATCHABLE_FIELDS}}


Answer = Mapping[str, Any] | str | ProviderError | Callable[[dict[str, Any]], Any]


@dataclass
class ScriptedAnalyst:
    """A ``Transport`` answering from the request's own case input. ``script(case_id, answer, ...)`` queues per-case answers: a
    JSON-ready mapping, a raw string (malformed output), a ``ProviderError`` (raised), or a function of the request input."""

    provider_name: str = "fake"
    model: str = PINNED_MODEL
    requests: list[ProviderRequest] = field(default_factory=list)
    _scripts: dict[str, deque[Answer]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def script(self, key: str, *answers: Answer) -> ScriptedAnalyst:
        with self._lock:
            self._scripts.setdefault(key, deque()).extend(answers)
        return self

    def complete(self, request: ProviderRequest, *, model: str, timeout: float) -> ProviderResponse:
        payload = request_input(request)
        with self._lock:
            self.requests.append(request)
            queue = self._scripts.get(request.context.case_id or "") or self._scripts.get(request.context.purpose)
            answer: Answer | None = queue.popleft() if queue else None
        if answer is None:
            answer = update_answer(payload) if request.context.purpose == "update" else analyst_answer(payload)
        if callable(answer) and not isinstance(answer, ProviderError):
            answer = answer(payload)
        if isinstance(answer, ProviderError):
            raise answer
        content = answer if isinstance(answer, str) else json.dumps(answer)
        return ProviderResponse(request_id=request.context.request_id, model=self.model, content=content,
                                input_tokens=1000, output_tokens=400, provider_response_id=f"fake-{len(self.requests)}", provider_status="200",
                                finish_reason="stop")

    def purposes(self) -> list[str]:
        return [request.context.purpose for request in self.requests]


def gateway(transport: Any, *, recorder: Any = None, retries: int = 1) -> ReasoningGateway:
    return ReasoningGateway(transport, GatewaySettings(max_retries=retries, backoff_seconds=0, max_backoff_seconds=0, concurrency=4),
                            recorder=recorder or MemoryRecorder(), sleep=lambda seconds: None)
