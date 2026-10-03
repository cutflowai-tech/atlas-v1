"""The offline model of the Phase 19 evaluation runner: deterministic, no network, no credential (Phase 19-B).

``OfflineModel`` is a ``provider.Transport`` that answers from the request's own case input, exactly as the Phase 19-A golden driver's
``GoldenModel`` does (``tests/reasoning_evaluation_driver.py`` over ``tests/reasoning_fakes.ScriptedAnalyst``): a valid analyst answer
citing only the case's references and numbers, and for an update the well-behaved patch that changes exactly the fields the updater
requires (``fields_requiring_change``), otherwise only the confidence rationale. Faults are queued per case or purpose with ``script``
(a ``ProviderError`` raised, or an answer function of the request input) and always come first.

It is a production module so that ``python -m atlas_reasoning evaluate`` never depends on test code; it is never wired into
``reason`` or any product path. Byte-equal behaviour with the golden driver is tested (the runner's canonical report equals the
driver's).
"""

from __future__ import annotations

import json
import threading
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any

from atlas_reasoning.contracts import PATCHABLE_FIELDS
from atlas_reasoning.provider import ProviderError, ProviderRequest, ProviderResponse
from atlas_reasoning.settings import PINNED_MODEL

MARKER = "(JSON):\n"
OFFLINE_PROVIDER = "fake"
RATIONALES = ("The newest evidence changed the sample.", "The evidence moved again; the level still holds.")

Answer = Mapping[str, Any] | str | ProviderError | Callable[[dict[str, Any]], Any]


def request_input(request: ProviderRequest) -> dict[str, Any]:
    """The case input of a request (its first user message carrying JSON; a corrective re-ask appends messages after it)."""
    text = next(m.content for m in request.messages if m.role == "user" and MARKER in m.content)
    payload: dict[str, Any] = json.loads(text[text.index(MARKER) + len(MARKER):])
    return payload


def _refs(case: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    contradicting_members = {row["member_key"] for row in case["contradicting_findings"]}
    support: list[str] = []
    contra: list[str] = []
    for ref in case["evidence_references"]:
        (contra if ref["role"] == "contradicting" or ref["member_key"] in contradicting_members else support).append(ref["ref_id"])
    return support, contra


def analyst_answer(case: Mapping[str, Any]) -> dict[str, Any]:
    """A valid analyst answer citing only the case's references and using only its numbers."""
    support, contra = _refs(case)
    support = support or contra
    sample = case["supporting_findings"][0]["sample_size"] if case["supporting_findings"] else case["contradicting_findings"][0]["sample_size"]
    subject = f"{case['case']['subject_type']} {case['case']['subject_id']}"
    return {
        "title": f"{case['case']['topic_key'].replace('_', ' ').capitalize()} pattern for {subject}",
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


def update_answer(change: Mapping[str, Any], *, rationale: str = "The evidence moved.") -> dict[str, Any]:
    """An update answer changing exactly ``change`` (field -> new value) and preserving every other patchable field."""
    return {"action": "patch" if change else "no_change", "change_rationale": rationale, "changed_fields": list(change),
            "preserved_fields": [name for name in PATCHABLE_FIELDS if name not in change],
            "patch": {name: change.get(name) for name in PATCHABLE_FIELDS}}


def golden_update(payload: dict[str, Any]) -> dict[str, Any]:
    """The well-behaved update: exactly the fields the updater requires (values built only from the case), otherwise only the confidence
    rationale (to a text different from the previous one)."""
    fresh = analyst_answer(payload)
    required = list(payload.get("fields_requiring_change") or {})
    change = {name: fresh[name] for name in required}
    if not change:
        previous = payload["previous_result"]["fields"]["confidence"]
        change = {"confidence": {"level": previous["level"], "rationale": RATIONALES[1] if previous["rationale"] == RATIONALES[0] else RATIONALES[0]}}
    return update_answer(change)


def overclaim(payload: dict[str, Any]) -> dict[str, Any]:
    """The ``overclaim`` fault: ``strong`` confidence (above any ceiling the golden data has) — an analyst answer, or for an update request
    (it carries ``previous_result``) a patch of the confidence alone."""
    claim = {"level": "strong", "rationale": "Certain."}
    if "previous_result" in payload:
        return update_answer({"confidence": claim})
    answer = analyst_answer(payload)
    answer["confidence"] = claim
    return answer


class ScriptedTransport:
    """Per-key fault queues in front of a model: ``script(key, *answers)`` queues answers for a case ID (else a purpose); a queued answer
    is consumed before the model is asked. ``answer(request, payload)`` is the model; subclasses implement it."""

    provider_name = OFFLINE_PROVIDER
    model = PINNED_MODEL

    def __init__(self) -> None:
        self.requests: list[ProviderRequest] = []
        self._scripts: dict[str, deque[Answer]] = {}
        self._lock = threading.Lock()

    def script(self, key: str, *answers: Answer) -> ScriptedTransport:
        with self._lock:
            self._scripts.setdefault(key, deque()).extend(answers)
        return self

    def scripted(self, request: ProviderRequest) -> Answer | None:
        """Pop the next queued answer for the request (case ID first, then purpose), or None."""
        with self._lock:
            queue = self._scripts.get(request.context.case_id or "") or self._scripts.get(request.context.purpose)
            return queue.popleft() if queue else None

    def response(self, request: ProviderRequest, answer: Answer, payload: dict[str, Any]) -> ProviderResponse:
        if callable(answer) and not isinstance(answer, ProviderError):
            answer = answer(payload)
        if isinstance(answer, ProviderError):
            raise answer
        content = answer if isinstance(answer, str) else json.dumps(answer)
        return ProviderResponse(request_id=request.context.request_id, model=self.model, content=content, input_tokens=1000, output_tokens=400,
                                provider_response_id=f"fake-{len(self.requests)}", provider_status="200", finish_reason="stop")


class OfflineModel(ScriptedTransport):
    """The deterministic offline model (``GoldenModel`` semantics): queued faults first; otherwise ``golden_update`` for an update and
    ``analyst_answer`` for anything else."""

    def complete(self, request: ProviderRequest, *, model: str, timeout: float) -> ProviderResponse:
        payload = request_input(request)
        with self._lock:
            self.requests.append(request)
        answer = self.scripted(request)
        if answer is None:
            answer = golden_update if request.context.purpose == "update" else analyst_answer
        return self.response(request, answer, payload)
