"""Reasoning V3 evaluation metrics (Phase 19, ``REV/19`` #3): exact, explicit, computed from two canonical states.

Every metric is counted per **evaluated step** of a golden case from the canonical state before and after the step
(``evaluation_types.CanonicalState``) and summed over the suite as one exact fraction, never as an average of averages. A setup step is
never measured; a golden case listed in a metric's exclusions (``EvaluationCase.metric_exclusions``, each with a documented reason) does
not contribute to that metric at all. A zero denominator means **no data**: the value is ``None`` (never 0, never 1) and the release
threshold decides (``Threshold.on_no_data``; release thresholds fail on no data).

``METRICS`` holds the definitions (numerator, denominator, exclusions, zero-denominator behaviour, machine-readable field name) that
``docs/REASONING-V3-EVALUATION.md`` repeats; the functions below are their only implementation. Nothing here calls a model, writes a row
or decides a run status: the harness observes what Reasoning V3 did; it never re-implements it.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from atlas_reasoning import guardrails
from atlas_reasoning.contracts import PATCHABLE_FIELDS
from atlas_reasoning.delta import material_delta
from atlas_reasoning.evaluation_types import CanonicalState, MetricCount

OPEN_LIFECYCLE = ("new", "active", "updated", "cooling")
SHOWN_WHILE_PRESENT = ("new", "active", "updated")
CONTENT_KINDS = ("created", "patched", "no_change_review")
REASONING_PURPOSES = ("analyst", "update")
OPEN_WORK = ("pending", "in_progress")
# Phase 15 codes that say a committed conclusion is not traceable to its case's deterministic evidence. Entity codes (UNKNOWN_PERSON /
# PROJECT / ENTITY) and the human-context codes are not re-checked: their vocabulary includes the human context of the call, which the
# canonical case document does not carry; they are covered at call time by ``validation_rejection_rate``.
GROUNDING_CODES = frozenset({guardrails.ValidationCode.UNKNOWN_EVIDENCE, guardrails.ValidationCode.WRONG_EVIDENCE_ROLE,
                             guardrails.ValidationCode.COUNTER_EVIDENCE_MISSING, guardrails.ValidationCode.NO_SUPPORTING_EVIDENCE,
                             guardrails.ValidationCode.UNSUPPORTED_NUMBER, guardrails.ValidationCode.UNSUPPORTED_METRIC,
                             guardrails.ValidationCode.CAUSAL_OVERCLAIM, guardrails.ValidationCode.CONFIDENCE_EXCEEDED})


@dataclass(frozen=True)
class MetricDefinition:
    name: str                     # the machine-readable field name
    title: str
    higher_is_better: bool
    numerator: str
    denominator: str
    exclusions: str
    zero_denominator: str = "no data: value null; the release threshold fails (on_no_data = fail)"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "title": self.title, "higher_is_better": self.higher_is_better, "numerator": self.numerator,
                "denominator": self.denominator, "exclusions": self.exclusions, "zero_denominator": self.zero_denominator}


_COMMON = "setup steps; golden cases that list the metric in metric_exclusions"

METRICS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        "case_identity_stability", "Case identity stability", True,
        "Change Gate observations of the step whose identity key was already known before the step, that resolved to the same case_id and "
        "that were not split (the case disappeared while a never-seen case about the same subject and topic appeared in the same step)",
        "Change Gate observations of the step whose identity key was already known before the step (the same semantic case: Phase 04 identity key)",
        f"cases first seen in the step (no earlier identity); {_COMMON}"),
    MetricDefinition(
        "unnecessary_new_card_rate", "Unnecessary new-card rate", False,
        "cases among the denominator for which the step created a result_id that did not exist before the step",
        "cases that had a reusable (not superseded) result before the step and are present after it — preservation or update was correct",
        f"cases first seen in the step; absent cases; cases whose only earlier results were superseded; {_COMMON}"),
    MetricDefinition(
        "unnecessary_field_rewrite_rate", "Unnecessary field rewrite rate", False,
        "patchable fields whose value changed across the step although the card's evidence fingerprint did not change, or that an accepted "
        "update changed without declaring them in changed_fields",
        "patchable fields (12 per card) of every card that existed before the step",
        f"cards created in the step; {_COMMON}"),
    MetricDefinition(
        "grounding_failure_rate", "Grounding failure rate", False,
        "committed created/patched versions of the step for which the Phase 15 validator, re-run on the stored version and the case document "
        "it was reasoned on, reports a grounding code (UNKNOWN_EVIDENCE, WRONG_EVIDENCE_ROLE, COUNTER_EVIDENCE_MISSING, NO_SUPPORTING_EVIDENCE, "
        "UNSUPPORTED_NUMBER, UNSUPPORTED_METRIC, CAUSAL_OVERCLAIM, CONFIDENCE_EXCEEDED)",
        "created and patched versions committed in the step",
        f"no_change_review and lifecycle versions (they copy content); entity and human-context codes (checked at call time); {_COMMON}"),
    MetricDefinition(
        "validation_rejection_rate", "Validation rejection rate", False,
        "candidates refused by the Phase 15 guardrails (or the optional reviewer) in the step (reasoning_failed_candidates rows)",
        "analyst and update provider calls of the step that returned an answer (succeeded llm_calls rows): every such answer is validated",
        f"failed calls (no answer to validate); executive and reviewer calls; {_COMMON} (a case that injects invalid model output on purpose)"),
    MetricDefinition(
        "lifecycle_churn_rate", "Lifecycle churn rate", False,
        "cards that, in the step, returned through lifecycle-only moves to a state they had left in the same step (flip-flop), moved to cooling or resolved while "
        "their case is present, or — when the card moved or its case's presence changed in the step — ended it shown as current "
        "(new/active/updated) while its case is absent, or cooling while present",
        "cards that exist after the step",
        f"superseded cards; {_COMMON}"),
    MetricDefinition(
        "duplicate_question_rate", "Duplicate-question rate", False,
        "open Atlas questions that duplicate another open question of the same case (same dedup key), plus questions opened in the step that "
        "repeat an answered or dismissed question of the same case",
        "open Atlas questions after the step",
        f"superseded questions; {_COMMON}"),
    MetricDefinition(
        "expectation_failure_rate", "Structural expectation failure rate", False,
        "structural expectations of the golden cases that the observation did not meet",
        "structural expectations evaluated (one per fact named in an evaluated step's expect block)",
        "setup steps (they carry no expectations); never excluded per case"),
)
METRIC_NAMES = tuple(metric.name for metric in METRICS)
STEP_METRICS = tuple(name for name in METRIC_NAMES if name != "expectation_failure_rate")


def definition(name: str) -> MetricDefinition:
    return next(metric for metric in METRICS if metric.name == name)


# --- helpers ------------------------------------------------------------------------------------------------------------------


def field_hashes(document: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """Patchable field -> sha256 of its canonical JSON. The harness compares hashes, never text."""
    return tuple((name, hashlib.sha256(json.dumps(document.get(name), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest())
                 for name in PATCHABLE_FIELDS)


def declared_changes(update_document: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not update_document:
        return ()
    names = [row.get("field") if isinstance(row, Mapping) else row for row in update_document.get("changed_fields") or []]
    return tuple(sorted({str(name) for name in names if name}))


def update_case(case_document: Mapping[str, Any], previous: Mapping[str, Any], evidence_before: Mapping[str, Any] | None,
                evidence_after: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The case a patch was validated against, rebuilt exactly as ``ReasoningEngine._update_case`` builds it: the work item's case
    document with the previous result and the material delta from the previous version's evidence to the patched version's. None when
    either evidence state is unknown (the re-check then reports ``NO_CASE_DOCUMENT``)."""
    if evidence_before is None or evidence_after is None:
        return None
    document = dict(case_document)
    document.update(previous_result_id=previous["result_id"], previous_result_version=previous["version"],
                    material_delta=material_delta(evidence_before, evidence_after, fingerprint_before=previous["evidence_fingerprint"],
                                                  fingerprint_after=document["evidence_fingerprint"]))
    return document


def grounding_codes(document: Mapping[str, Any], case_document: Mapping[str, Any] | None, *, model: str, prompt_version: str,
                    previous: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    """The Phase 15 validator's grounding codes for one stored version, re-run on the case document it was reasoned on. Identity and
    provenance are not re-judged (the version is already committed); a version without its case document cannot be re-checked and
    reports ``NO_CASE_DOCUMENT`` (counted as a failure: grounding that cannot be shown is not shown)."""
    if case_document is None:
        return ("NO_CASE_DOCUMENT",)
    expected = guardrails.Expected(case_id=str(document.get("case_id")), result_id=str(document.get("result_id")), version=int(document.get("version") or 1),
                                   source_snapshot_id=str(document.get("source_snapshot_id")),
                                   evidence_fingerprint=str(document.get("evidence_fingerprint")), prompt_version=prompt_version, model=model,
                                   previous=previous)
    report = guardrails.validate_candidate(document, case_document, expected)
    return tuple(sorted({code for code in report.codes if code in GROUNDING_CODES}))


def _results_by_case(state: CanonicalState) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for result in state.results:
        found.setdefault(result.case_id, set()).add(result.result_id)
    return found


def _version(state: CanonicalState, result_id: str, version: int) -> Any:
    return next((row for row in state.versions if row.result_id == result_id and row.version == version), None)


# --- per-step counts ----------------------------------------------------------------------------------------------------------


def _subject(identity_key: str) -> tuple[str, ...]:
    """(subject type, subject ID, topic): what a case is about, without its identity dimensions."""
    return tuple(identity_key.split("|")[1:4])


def identity_splits(before: CanonicalState, after: CanonicalState) -> set[str]:
    """Known cases that the step split: the case disappeared while a case never seen before, about the same subject and topic, appeared
    in the same step (the same semantic case under a new case_id). ``case_id`` is a hash of the unique identity key, so a lost identity
    shows up only this way."""
    known = {case.case_id for case in before.cases}
    identity = {case.case_id: case.identity_key for case in after.cases}
    seen = {(row.run_id, row.case_id) for row in before.observations}
    step = [row for row in after.observations if (row.run_id, row.case_id) not in seen]
    appeared = {_subject(identity[row.case_id]) for row in step if row.action == "new" and row.case_id not in known and row.case_id in identity}
    return {row.case_id for row in step if row.action == "disappeared" and row.case_id in known
            and row.case_id in identity and _subject(identity[row.case_id]) in appeared}


def case_identity(before: CanonicalState, after: CanonicalState) -> MetricCount:
    known = {case.identity_key: case.case_id for case in before.cases}
    identity = {case.case_id: case.identity_key for case in after.cases}
    seen = {(row.run_id, row.case_id) for row in before.observations}
    splits = identity_splits(before, after)
    stable = total = 0
    for row in after.observations:
        if (row.run_id, row.case_id) in seen or identity.get(row.case_id) not in known:
            continue
        total += 1
        stable += known[identity[row.case_id]] == row.case_id and row.case_id not in splits
    return MetricCount(stable, total)


def unnecessary_new_cards(before: CanonicalState, after: CanonicalState) -> MetricCount:
    reusable = {result.case_id for result in before.results if result.lifecycle_status != "superseded"}
    present = {case.case_id for case in after.cases if case.presence == "present"}
    existing = {result.result_id for result in before.results}
    after_by_case = _results_by_case(after)
    units = sorted(reusable & present)
    return MetricCount(sum(1 for case_id in units if after_by_case.get(case_id, set()) - existing), len(units))


def unnecessary_rewrites(before: CanonicalState, after: CanonicalState) -> MetricCount:
    rewritten = examined = 0
    current = {result.result_id: result.version for result in after.results}
    for result in before.results:
        old, new = _version(before, result.result_id, result.version), _version(after, result.result_id, current.get(result.result_id, result.version))
        if old is None or new is None:
            continue
        examined += len(PATCHABLE_FIELDS)
        declared = {name for row in after.versions if row.result_id == result.result_id and result.version < row.version <= new.version
                    for name in row.declared_changes}
        moved = old.evidence_fingerprint != new.evidence_fingerprint
        old_fields, new_fields = dict(old.fields), dict(new.fields)
        rewritten += sum(1 for name in PATCHABLE_FIELDS if old_fields.get(name) != new_fields.get(name) and (not moved or name not in declared))
    return MetricCount(rewritten, examined)


def _new_versions(before: CanonicalState, after: CanonicalState) -> list[Any]:
    seen = {(row.result_id, row.version) for row in before.versions}
    return [row for row in after.versions if (row.result_id, row.version) not in seen]


def grounding_failures(before: CanonicalState, after: CanonicalState) -> MetricCount:
    written = [row for row in _new_versions(before, after) if row.change_kind in ("created", "patched")]
    return MetricCount(sum(1 for row in written if row.grounding_codes), len(written))


def validation_rejections(before: CanonicalState, after: CanonicalState) -> MetricCount:
    seen_calls, seen_refusals = {row.request_id for row in before.calls}, {row.candidate_id for row in before.refusals}
    answered = sum(1 for row in after.calls if row.request_id not in seen_calls and row.purpose in REASONING_PURPOSES and row.status == "succeeded")
    refused = sum(1 for row in after.refusals if row.candidate_id not in seen_refusals)
    return MetricCount(refused, answered)


def lifecycle_churn(before: CanonicalState, after: CanonicalState) -> MetricCount:
    presence = {case.case_id: case.presence for case in after.cases}
    was_present = {case.case_id: case.presence for case in before.cases}
    kinds = {(row.result_id, row.version): row.change_kind for row in after.versions}
    seen = {row.transition_id for row in before.transitions}
    steps: dict[str, list[Any]] = {}
    for row in after.transitions:
        if row.transition_id not in seen:
            steps.setdefault(row.result_id, []).append(row)
    churned = total = 0
    for result in after.results:
        if result.lifecycle_status == "superseded":
            continue
        total += 1
        moves = sorted(steps.get(result.result_id, []), key=lambda row: row.result_version)
        present = presence.get(result.case_id) == "present"
        # Flip-flop: within a run of lifecycle-only moves (versions of kind ``lifecycle``), a return to a state already left. A created /
        # patched version is a content change that justifies its move and starts a new run (updated -> active settle, patch -> updated).
        flip_flop, visited = False, []
        for row in moves:
            if kinds.get((row.result_id, row.result_version)) != "lifecycle":
                visited = [row.to_status]
                continue
            visited = visited or [row.from_status]
            flip_flop = flip_flop or row.to_status in visited
            visited.append(row.to_status)
        withdrawn_while_present = present and any(row.to_status in ("cooling", "resolved") for row in moves)
        # End-state terms count where the step could have caused them: the card moved, or its case's presence changed.
        relevant = bool(moves) or was_present.get(result.case_id) != presence.get(result.case_id)
        shown_while_absent = relevant and not present and result.lifecycle_status in SHOWN_WHILE_PRESENT
        cooling_while_present = relevant and present and result.lifecycle_status == "cooling"
        churned += flip_flop or withdrawn_while_present or shown_while_absent or cooling_while_present
    return MetricCount(churned, total)


def duplicate_questions(before: CanonicalState, after: CanonicalState) -> MetricCount:
    open_rows = sorted((row for row in after.questions if row.state == "open"), key=lambda row: row.question_id)
    closed = {(row.case_id, row.dedup_key) for row in after.questions if row.state in ("answered", "dismissed")}
    seen = {row.question_id for row in before.questions}
    first: set[tuple[str, str]] = set()
    duplicated = 0
    for row in open_rows:          # each open question counts at most once: a second copy, or a new repeat of a closed question
        key = (row.case_id, row.dedup_key)
        duplicated += key in first or (row.question_id not in seen and key in closed)
        first.add(key)
    return MetricCount(duplicated, len(open_rows))


STEP_COUNTERS = {
    "case_identity_stability": case_identity,
    "unnecessary_new_card_rate": unnecessary_new_cards,
    "unnecessary_field_rewrite_rate": unnecessary_rewrites,
    "grounding_failure_rate": grounding_failures,
    "validation_rejection_rate": validation_rejections,
    "lifecycle_churn_rate": lifecycle_churn,
    "duplicate_question_rate": duplicate_questions,
}


def step_counts(before: CanonicalState, after: CanonicalState) -> dict[str, MetricCount]:
    return {name: STEP_COUNTERS[name](before, after) for name in STEP_METRICS}


def duplicates(state: CanonicalState) -> int:
    """Duplicate canonical state (Phase 18 duplicate-work protection, observed): more than one open card per case, a gap in a card's
    version sequence, more than one open LLM work item per case, more than one open question per (case, dedup key), more than one synced
    memory copy of the same content in the same session. Each extra row counts once."""
    open_cards = Counter(result.case_id for result in state.results if result.lifecycle_status in OPEN_LIFECYCLE)
    versions: dict[str, list[int]] = {}
    for row in state.versions:
        versions.setdefault(row.result_id, []).append(row.version)
    gaps = sum(1 for numbers in versions.values() if sorted(numbers) != list(range(1, len(numbers) + 1)))
    open_work = Counter(row.case_id for row in state.work if row.requires_llm and row.status in OPEN_WORK)
    open_questions = Counter((row.case_id, row.dedup_key) for row in state.questions if row.state == "open")
    synced = Counter(state.synced_memory)
    return (sum(n - 1 for n in open_cards.values() if n > 1) + gaps + sum(n - 1 for n in open_work.values() if n > 1)
            + sum(n - 1 for n in open_questions.values() if n > 1) + sum(n - 1 for n in synced.values() if n > 1))


def total(counts: Sequence[MetricCount]) -> MetricCount:
    result = MetricCount()
    for count in counts:
        result = result + count
    return result
