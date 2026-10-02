"""Shared fixtures for the Phase 17 executive-core tests: canonical result rows built from the factory result, a valid executive answer
built only from the synthesis input (as the real model would), and an offline executive transport. No network, ever."""

from __future__ import annotations

import copy
import json
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from reasoning_engine_support import first_result, new_case
from reasoning_fakes import request_input

from atlas_reasoning.contracts import ReasoningResult
from atlas_reasoning.enums import LifecycleStatus
from atlas_reasoning.executive import CanonicalResult
from atlas_reasoning.executive_contracts import SECTIONS
from atlas_reasoning.provider import ProviderError, ProviderRequest, ProviderResponse
from atlas_reasoning.settings import PINNED_MODEL

BASE = first_result(new_case()).to_dict()


def rid(n: int) -> str:
    return f"rr1_{n:032x}"


def result(n: int, lifecycle: str = "active", **changes: Any) -> ReasoningResult:
    document = copy.deepcopy(BASE)
    document.update(result_id=rid(n), lifecycle_status=lifecycle, **changes)
    return ReasoningResult.from_dict(document)


def row(n: int, lifecycle: str = "active", *, subject_type: str = "editor", subject_id: str = "editor-label-12", reason: str | None = None,
        questions: tuple[tuple[str, str], ...] = (), patched: tuple[str, ...] = (), editors: tuple[str, ...] | None = None,
        orientation: str = "adverse", topic: str = "deadline", **changes: Any) -> CanonicalResult:
    document = result(n, lifecycle, **changes)
    affected = editors if editors is not None else ((subject_id,) if subject_type == "editor" else ())
    return CanonicalResult(result=document, lifecycle_status=LifecycleStatus(lifecycle), current_version=document.version, case_type=f"{subject_type}_pattern"
                           if subject_type in ("editor", "team") else "workflow_pattern", subject_type=subject_type, subject_id=subject_id, topic_key=topic,
                           dimensions={}, orientation=orientation, affected_editor_ids=affected, lifecycle_reason=reason, patched_fields=patched,
                           open_questions=questions)


QUESTION = ("Did anything change in how this work was assigned?", "assignment_context")


def standard_rows() -> list[CanonicalResult]:
    """A: new (editor-label-12, open question); B: updated (editor-label-12); C: active team result; D: resolved (editor-label-15)."""
    return [row(1, "new", reason="created", questions=(QUESTION,)),
            row(2, "updated", reason="patch_accepted", patched=("interpretation", "confidence")),
            row(3, "active", subject_type="team", subject_id="team", reason="observed_again", editors=("editor-label-12", "editor-label-15")),
            row(4, "resolved", subject_id="editor-label-15", reason="absent_for_configured_runs")]


def statement(text: str, *ids: int) -> dict[str, Any]:
    return {"text": text, "result_ids": [rid(n) for n in ids]}


def valid_answer() -> dict[str, Any]:
    """A valid answer for ``standard_rows()``: every statement grounded in what its cited results say."""
    return {"sections": {
        "what_changed": [statement("A new deadline result for editor-label-12 shows 11 of 16 projects late in the current window.", 1),
                         statement("The deadline result for editor-label-15 is resolved and no longer observed.", 4)],
        "top_concerns": [statement("Late deliveries for editor-label-12: 11 of 16 projects in the current window, against 5 of 10 before.", 1, 2)],
        "important_improvements": [statement("The deadline pattern for editor-label-15 was resolved.", 4)],
        "system_patterns": [statement("Two results describe late deliveries in the current window (69% against 50%).", 1, 3)],
        "editor_context": [{"editor_id": "editor-label-12", "text": "Both results about editor-label-12 concern late deliveries.", "result_ids": [rid(1), rid(2)]}],
        "unresolved_questions": [statement("Did anything change in how this work was assigned?", 1)],
        "uncertainty": [statement("Confidence is weak and only attributed projects are counted.", 1)],
        "inspect_next": [statement("Review the projects behind the supporting records.", 1)],
    }}


def generic_answer(payload: Mapping[str, Any]) -> dict[str, Any]:
    """A valid answer for any synthesis input, built only from it (the DB tests' default model)."""
    sections: dict[str, list[dict[str, Any]]] = {name: [] for name in SECTIONS}
    results = list(payload["results"])
    wording = {"new": "This result is new in the latest reasoning.", "updated": "This result was updated in the latest reasoning.",
               "resolved": "This result is resolved and no longer observed."}
    changed = [r for r in results if r["lifecycle_status"] in wording]
    if changed:
        sections["what_changed"].append({"text": wording[changed[0]["lifecycle_status"]], "result_ids": [changed[0]["result_id"]]})
    open_results = [r for r in results if r["lifecycle_status"] != "resolved"]
    concerns = [r for r in open_results if r["subject"]["orientation"] != "favourable"]
    if concerns:
        sections["top_concerns"].append({"text": "This open result deserves attention first.", "result_ids": [concerns[0]["result_id"]]})
    asked = [r for r in open_results if r["open_questions"]]
    if asked:
        sections["unresolved_questions"].append({"text": asked[0]["open_questions"][0]["text"], "result_ids": [asked[0]["result_id"]]})
    return {"sections": sections}


Answer = Mapping[str, Any] | str | ProviderError | Callable[[dict[str, Any]], Any]


@dataclass
class ScriptedExecutive:
    """A ``Transport`` for the executive purpose: queued answers (a JSON-ready mapping, a raw string, a ``ProviderError`` or a function of
    the synthesis input), else ``default`` (a valid answer built from the input)."""

    provider_name: str = "fake"
    model: str = PINNED_MODEL
    default: Callable[[dict[str, Any]], Any] = generic_answer
    requests: list[ProviderRequest] = field(default_factory=list)
    _queue: deque[Answer] = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def script(self, *answers: Answer) -> ScriptedExecutive:
        with self._lock:
            self._queue.extend(answers)
        return self

    def complete(self, request: ProviderRequest, *, model: str, timeout: float) -> ProviderResponse:
        payload = request_input(request)
        with self._lock:
            self.requests.append(request)
            answer: Answer = self._queue.popleft() if self._queue else self.default
        if callable(answer) and not isinstance(answer, ProviderError):
            answer = answer(payload)
        if isinstance(answer, ProviderError):
            raise answer
        content = answer if isinstance(answer, str) else json.dumps(answer)
        return ProviderResponse(request_id=request.context.request_id, model=self.model, content=content, input_tokens=2000, output_tokens=300,
                                provider_response_id=f"fake-x-{len(self.requests)}", provider_status="200", finish_reason="stop")
