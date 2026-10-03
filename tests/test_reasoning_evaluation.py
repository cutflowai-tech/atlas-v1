"""Phase 19-A (REV/19): the Reasoning V3 evaluation harness — golden cases, structural expectations, stability metrics, release thresholds
and the deterministic machine-readable report.

Unit tests (no database) cover the fixture vocabulary, every metric's numerator / denominator / zero-denominator semantics, exact
threshold boundaries and report determinism. The golden suite runs all 20 golden cases end to end on PostgreSQL with an offline model
(``reasoning_evaluation_driver``: ``ScriptedAnalyst`` + ``FakeHoncho``) through the real Change Gate, engine, Phase 15 guardrails and
Phase 18 orchestration. No network, no credentials.
"""

from __future__ import annotations

import copy
import json
import random
import unittest
from fractions import Fraction
from pathlib import Path
from typing import Any, ClassVar

import reasoning_factory as factory
from reasoning_db import fresh_database, requires_db

from atlas_reasoning import evaluation_metrics as em
from atlas_reasoning.contracts import PATCHABLE_FIELDS
from atlas_reasoning.evaluation import check_case, evaluate, fixture_digest, load_golden_cases, matches, observe_step, parse_case, parse_cases
from atlas_reasoning.evaluation_thresholds import RELEASE_THRESHOLDS_FILE, check, evaluate_thresholds, parse_thresholds, release_thresholds
from atlas_reasoning.evaluation_types import (
    FACTS,
    REQUIRED_CASE_NUMBERS,
    CallState,
    CanonicalState,
    CaseState,
    Comparator,
    EvaluationMetric,
    EvaluationObservation,
    FixtureError,
    MetricCount,
    NoData,
    ObservationState,
    QuestionState,
    RefusalState,
    ResultState,
    StepObservation,
    Threshold,
    TransitionState,
    VersionState,
    WorkState,
    decimal_string,
)

GOLDEN = Path(__file__).resolve().parents[1] / "src" / "atlas_reasoning" / "evaluation_golden"
D12 = "case-identity-v1|editor|editor-label-12|deadline"
FIELDS = tuple((name, "h0") for name in PATCHABLE_FIELDS)


def golden_document(fixture_id: str) -> dict[str, Any]:
    return json.loads((GOLDEN / f"case-{fixture_id}.json").read_text())


def minimal_case(**changes: Any) -> dict[str, Any]:
    document = {"schema": "reasoning-golden-case-v1", "fixture_id": "x", "number": 99, "title": "t", "requirement": "r", "category": "stability",
                "focus": D12, "steps": [{"step_id": "s", "actions": [{"op": "gate", "evidence": "showcase"}], "expect": {"calls.reasoning": 0}}]}
    document.update(changes)
    return document


def with_expect(**expect: Any) -> dict[str, Any]:
    return minimal_case(steps=[{"step_id": "s", "actions": [{"op": "orchestrate"}], "expect": expect}])


# --- golden fixtures ----------------------------------------------------------------------------------------------------------


class GoldenFixtureTests(unittest.TestCase):
    def test_every_required_scenario_loads_and_validates(self):
        cases = load_golden_cases()
        self.assertEqual([case.number for case in cases], list(REQUIRED_CASE_NUMBERS))
        self.assertEqual(len({case.fixture_id for case in cases}), 20)
        self.assertEqual({case.category.value for case in cases}, {"stability", "human_context", "reliability"})
        for case in cases:
            self.assertTrue(case.evaluated_steps, case.fixture_id)
            self.assertEqual(parse_case(json.loads(json.dumps(case.to_dict())), source=case.fixture_id), case)   # round trip
        titles = {case.number: case.fixture_id for case in cases}
        self.assertEqual(titles, {1: "unchanged-evidence", 2: "updated-material-evidence", 3: "new-case", 4: "disappeared-case",
                                  5: "contradiction-added", 6: "contradiction-removed", 7: "insufficient-evidence", 8: "manager-note-added",
                                  9: "manager-answer-added", 10: "teaching-added", 11: "teaching-expired", 12: "memory-unavailable",
                                  13: "provider-failure", 14: "partial-run", 15: "degraded-run", 16: "resume-after-interruption",
                                  17: "budget-exhaustion-then-resume", 18: "circuit-breaker-outage", 19: "duplicate-work-prevention",
                                  20: "zero-call-unchanged"})

    def test_load_order_and_digest_are_stable(self):
        cases = load_golden_cases()
        shuffled = list(cases)
        random.Random(7).shuffle(shuffled)
        self.assertEqual(parse_cases((case.fixture_id, case.to_dict()) for case in shuffled), cases)
        self.assertEqual(fixture_digest(shuffled), fixture_digest(cases))
        changed = copy.deepcopy(cases[0].to_dict())
        changed["title"] += "!"
        self.assertNotEqual(fixture_digest([parse_case(changed)] + list(cases[1:])), fixture_digest(cases))

    def test_the_published_digest_pins_the_golden_set(self):
        from atlas_reasoning.evaluation import PUBLISHED_FIXTURE_DIGEST

        self.assertEqual(fixture_digest(load_golden_cases()), PUBLISHED_FIXTURE_DIGEST)

    def test_duplicate_fixture_ids_and_numbers_are_rejected(self):
        a = golden_document("unchanged-evidence")
        b = copy.deepcopy(a)
        b["number"] = 21
        with self.assertRaisesRegex(FixtureError, "duplicate fixture_id"):
            parse_cases([("a.json", a), ("b.json", b)])
        c = golden_document("new-case")
        c["number"] = 1
        with self.assertRaisesRegex(FixtureError, "duplicate number"):
            parse_cases([("a.json", a), ("c.json", c)])

    def test_the_file_name_must_match_the_fixture_id(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "case-other.json").write_text(json.dumps(golden_document("new-case")))
            with self.assertRaisesRegex(FixtureError, "file name"):
                load_golden_cases(Path(directory))

    def test_malformed_expected_outcomes_are_rejected(self):
        bad = {
            "unknown fact": with_expect(**{"focus.reasoning_summary": "x"}),
            "wrong type": with_expect(**{"calls.reasoning": "1"}),
            "bool as int": with_expect(**{"calls.reasoning": True}),
            "negative": with_expect(**{"calls.reasoning": -1}),
            "null not allowed": with_expect(**{"calls.reasoning": None}),
            "enum": with_expect(**{"run.status": "fine"}),
            "lifecycle": with_expect(**{"focus.lifecycle": "archived"}),
            "range keys": with_expect(**{"calls.reasoning": {"atleast": 1}}),
            "range order": with_expect(**{"calls.reasoning": {"min": 3, "max": 1}}),
            "unsorted list": with_expect(**{"run.reasons": ["b", "a"]}),
            "list of ints": with_expect(**{"run.reasons": [1]}),
            "includes and excludes": with_expect(**{"focus.context_sources": {"includes": ["a"], "excludes": ["a"]}}),
            "empty expect": with_expect(),
            "bool": with_expect(**{"focus.present": "yes"}),
            "vacuous range": with_expect(**{"calls.reasoning": {"min": 0}}),
            "vacuous includes": with_expect(**{"focus.context_sources": {"includes": []}}),
        }
        for name, document in bad.items():
            with self.subTest(name), self.assertRaises(FixtureError):
                parse_case(document)

    def test_malformed_scenarios_are_rejected(self):
        bad = {
            "schema": minimal_case(schema="v0"),
            "unknown key": minimal_case(notes="x"),
            "missing key": {k: v for k, v in minimal_case().items() if k != "focus"},
            "focus": minimal_case(focus="editor-12"),
            "category": minimal_case(category="vibes"),
            "dataset": minimal_case(dataset="production"),
            "number": minimal_case(number=0),
            "op": minimal_case(steps=[{"step_id": "s", "actions": [{"op": "deploy"}], "expect": {"calls.reasoning": 0}}]),
            "variant": minimal_case(steps=[{"step_id": "s", "actions": [{"op": "gate", "evidence": "prod"}], "expect": {"calls.reasoning": 0}}]),
            "missing param": minimal_case(steps=[{"step_id": "s", "actions": [{"op": "gate"}], "expect": {"calls.reasoning": 0}}]),
            "unknown param": minimal_case(steps=[{"step_id": "s", "actions": [{"op": "orchestrate", "threads": 2}], "expect": {"calls.reasoning": 0}}]),
            "budget": minimal_case(steps=[{"step_id": "s", "actions": [{"op": "orchestrate", "budget": -1}], "expect": {"calls.reasoning": 0}}]),
            "fault": minimal_case(steps=[{"step_id": "s", "actions": [{"op": "fault", "kind": "meteor", "target": "focus"}], "expect": {"calls.reasoning": 0}}]),
            "no evaluated step": minimal_case(steps=[{"step_id": "s", "actions": [{"op": "gate", "evidence": "showcase"}]}]),
            "duplicate step": minimal_case(steps=[{"step_id": "s", "actions": [{"op": "orchestrate"}]}, {"step_id": "s", "actions": [{"op": "orchestrate"}],
                                                                                                         "expect": {"calls.reasoning": 0}}]),
            "runtime": minimal_case(runtime={"breaker_threshold": 0}),
            "runtime key": minimal_case(runtime={"live_model": 1}),
            "exclusion metric": minimal_case(metric_exclusions={"expectation_failure_rate": "no"}),
            "exclusion reason": minimal_case(metric_exclusions={"validation_rejection_rate": " "}),
        }
        for name, document in bad.items():
            with self.subTest(name), self.assertRaises(FixtureError):
                parse_case(document)

    def test_expectations_are_structural_only(self):
        """No fact names model text: facts are counts, booleans, enums or code lists; none is a free-text field of a result."""
        self.assertEqual({spec.kind for spec in FACTS.values()}, {"int", "bool", "enum", "list"})
        # (``focus.confidence`` observes only the level enum, never the rationale text)
        text_fields = set(PATCHABLE_FIELDS) - {"confidence"} | {"chain", "thought", "thoughts", "hidden", "statement", "rationale", "text", "summary", "explanation"}
        for name in FACTS:
            self.assertFalse(set(name.replace(".", "_").split("_")) & text_fields, name)
        for case in load_golden_cases():
            for step in case.evaluated_steps:
                assert step.expect is not None
                for fact, expected in step.expect.checks:
                    self.assertIn(fact, FACTS)
                    self.assertFalse(isinstance(expected, str) and len(expected) > 40, (case.fixture_id, fact))

    def test_matching(self):
        self.assertTrue(matches(3, 3))
        self.assertFalse(matches(3, True))
        self.assertFalse(matches(True, 1))
        self.assertTrue(matches({"min": 1, "max": 3}, 3))
        self.assertFalse(matches({"min": 1}, 0))
        self.assertTrue(matches({"includes": ["a"], "excludes": ["c"]}, ["a", "b"]))
        self.assertFalse(matches({"excludes": ["c"]}, ["c"]))
        self.assertTrue(matches(None, None))
        self.assertTrue(matches(["a", "b"], ["a", "b"]))
        self.assertFalse(matches(["a"], ["a", "b"]))


# --- metrics ------------------------------------------------------------------------------------------------------------------


def state(**parts: Any) -> CanonicalState:
    return CanonicalState(**{key: tuple(value) for key, value in parts.items()})


def case_row(case_id: str, key: str, presence: str = "present", fingerprint: str = "ef_a") -> CaseState:
    return CaseState(case_id, key, presence, fingerprint, 0)


def version(result_id: str, number: int, kind: str = "created", fingerprint: str = "ef_a", fields: Any = FIELDS, declared: tuple[str, ...] = (),
            codes: tuple[str, ...] = ()) -> VersionState:
    return VersionState(result_id, number, kind, fingerprint, tuple(fields), declared, "weak", codes)


def changed(*names: str) -> tuple[tuple[str, str], ...]:
    return tuple((name, "h1" if name in names else value) for name, value in FIELDS)


class MetricTests(unittest.TestCase):
    def test_every_metric_has_an_explicit_definition(self):
        self.assertEqual(em.METRIC_NAMES, ("case_identity_stability", "unnecessary_new_card_rate", "unnecessary_field_rewrite_rate", "grounding_failure_rate",
                                           "validation_rejection_rate", "lifecycle_churn_rate", "duplicate_question_rate", "expectation_failure_rate"))
        for metric in em.METRICS:
            for part in (metric.numerator, metric.denominator, metric.exclusions, metric.zero_denominator):
                self.assertTrue(part.strip(), metric.name)
            self.assertEqual(metric.to_dict()["name"], metric.name)

    def test_case_identity_stability(self):
        before = state(cases=[case_row("rc_a", "k1"), case_row("rc_b", "k2")], observations=[ObservationState("run1", "rc_a", "new")])
        after = state(cases=[case_row("rc_a", "k1"), case_row("rc_b", "k2"), case_row("rc_c", "k3")],
                      observations=[ObservationState("run1", "rc_a", "new"), ObservationState("run2", "rc_a", "unchanged"),
                                    ObservationState("run2", "rc_b", "updated"), ObservationState("run2", "rc_c", "new")])
        self.assertEqual(em.case_identity(before, after), MetricCount(2, 2))         # rc_c is new: no earlier identity, excluded
        regenerated = state(cases=[case_row("rc_a", "k1"), case_row("rc_x", "k2")], observations=[ObservationState("run2", "rc_x", "new")])
        self.assertEqual(em.case_identity(before, regenerated), MetricCount(0, 1))     # same semantic case (k2), another case_id
        self.assertEqual(em.case_identity(before, before), MetricCount(0, 0))          # no observation in the step: no data

    def test_an_identity_split_is_unstable(self):
        """case_id is a hash of the unique identity key, so a lost identity shows as a split: the known case disappears while a never-seen
        case about the same subject and topic appears in the same step (review H1)."""
        old, split = "case-identity-v1|editor|editor-label-12|deadline", "case-identity-v1|editor|editor-label-12|deadline|signal=x"
        other = "case-identity-v1|editor|editor-label-99|speed"
        before = state(cases=[case_row("rc_a", old), case_row("rc_b", "case-identity-v1|team|team|deadline")])
        after = state(cases=[case_row("rc_a", old, "absent"), case_row("rc_b", "case-identity-v1|team|team|deadline"), case_row("rc_s", split)],
                      observations=[ObservationState("run2", "rc_a", "disappeared"), ObservationState("run2", "rc_b", "unchanged"),
                                    ObservationState("run2", "rc_s", "new")])
        self.assertEqual(em.identity_splits(before, after), {"rc_a"})
        self.assertEqual(em.case_identity(before, after), MetricCount(1, 2))
        # a disappearance plus an unrelated new case is not a split
        unrelated = state(cases=[case_row("rc_a", old, "absent"), case_row("rc_n", other)],
                          observations=[ObservationState("run2", "rc_a", "disappeared"), ObservationState("run2", "rc_n", "new")])
        self.assertEqual(em.case_identity(before, unrelated), MetricCount(1, 1))

    def test_unnecessary_new_card_rate(self):
        before = state(cases=[case_row("rc_a", "k1"), case_row("rc_b", "k2"), case_row("rc_s", "k4")],
                       results=[ResultState("rr_a", "rc_a", 1, "active"), ResultState("rr_b", "rc_b", 1, "cooling"),
                                ResultState("rr_s", "rc_s", 2, "superseded")])
        after = state(cases=[case_row("rc_a", "k1"), case_row("rc_b", "k2", "absent"), case_row("rc_s", "k4"), case_row("rc_n", "k3")],
                      results=[ResultState("rr_a", "rc_a", 1, "active"), ResultState("rr_a2", "rc_a", 1, "new"), ResultState("rr_b", "rc_b", 1, "cooling"),
                               ResultState("rr_s", "rc_s", 2, "superseded"), ResultState("rr_s2", "rc_s", 1, "new"), ResultState("rr_n", "rc_n", 1, "new")])
        # Units: rc_a (reusable, present). rc_b is absent; rc_s had only a superseded card; rc_n is new. rc_a got a second card.
        self.assertEqual(em.unnecessary_new_cards(before, after), MetricCount(1, 1))
        self.assertEqual(em.unnecessary_new_cards(state(), after), MetricCount(0, 0))

    def test_unnecessary_field_rewrite_rate(self):
        n = len(PATCHABLE_FIELDS)
        before = state(results=[ResultState("rr_a", "rc_a", 1, "active"), ResultState("rr_b", "rc_b", 1, "active"), ResultState("rr_c", "rc_c", 1, "active")],
                       versions=[version("rr_a", 1), version("rr_b", 1), version("rr_c", 1)])
        after = state(results=[ResultState("rr_a", "rc_a", 2, "updated"), ResultState("rr_b", "rc_b", 2, "updated"), ResultState("rr_c", "rc_c", 2, "active"),
                               ResultState("rr_new", "rc_n", 1, "new")],
                      versions=[version("rr_a", 1), version("rr_b", 1), version("rr_c", 1), version("rr_new", 1),
                                # moved evidence, declared change of title and confidence, but limitations rewritten without declaring it
                                version("rr_a", 2, "patched", "ef_b", changed("title", "confidence", "limitations"), ("confidence", "title")),
                                # same evidence fingerprint: any changed field is unnecessary
                                version("rr_b", 2, "patched", "ef_a", changed("title"), ("title",)),
                                # lifecycle-only version: no field change
                                version("rr_c", 2, "lifecycle")])
        self.assertEqual(em.unnecessary_rewrites(before, after), MetricCount(2, 3 * n))   # limitations (rr_a) + title (rr_b); rr_new excluded
        self.assertEqual(em.unnecessary_rewrites(state(), after), MetricCount(0, 0))

    def test_grounding_failure_rate(self):
        before = state(versions=[version("rr_a", 1)])
        after = state(versions=[version("rr_a", 1), version("rr_a", 2, "patched", codes=("UNKNOWN_EVIDENCE",)), version("rr_a", 3, "lifecycle"),
                                version("rr_a", 4, "no_change_review"), version("rr_b", 1)])
        self.assertEqual(em.grounding_failures(before, after), MetricCount(1, 2))           # lifecycle and no_change_review copy content
        self.assertEqual(em.grounding_failures(after, after), MetricCount(0, 0))

    def test_grounding_recheck_runs_the_phase15_validator_on_stored_output(self):
        case = factory.case_dict()
        result = factory.result_dict(case)
        self.assertEqual(em.grounding_codes(result, case, model=result["model_metadata"]["model"], prompt_version=result["prompt_version"]), ())
        broken = copy.deepcopy(result)
        broken["observation"]["evidence_refs"] = ["ev1_" + "0" * 24]
        self.assertIn("UNKNOWN_EVIDENCE", em.grounding_codes(broken, case, model="m", prompt_version="p"))
        number = copy.deepcopy(result)
        number["observation"]["statement"] = "Exactly 977 projects were late."
        self.assertIn("UNSUPPORTED_NUMBER", em.grounding_codes(number, case, model="m", prompt_version="p"))
        self.assertEqual(em.grounding_codes(result, None, model="m", prompt_version="p"), ("NO_CASE_DOCUMENT",))
        # identity / provenance are not re-judged: a committed version is graded on grounding only
        self.assertEqual(em.grounding_codes(result, case, model="another/model", prompt_version="other"), ())

    def test_a_patch_is_regraded_against_the_case_the_engine_validated(self):
        """Review H2: a patch may quote the evidence it moved from (only in the material delta). The re-check rebuilds the update case
        with that delta, as the engine did; the raw work-item case document would wrongly flag the earlier value."""
        from reasoning_engine_support import changed_case, first_result, new_case

        from atlas_reasoning.fingerprint import canonical_evidence

        previous = first_result(new_case()).to_dict()
        case = changed_case(first_result(new_case())).to_dict()
        raw = {**case, "material_delta": None, "previous_result_id": None, "previous_result_version": None}     # as the gate stores it
        patched = copy.deepcopy(previous)
        patched.update(version=2, evidence_fingerprint=case["evidence_fingerprint"])
        patched["observation"]["statement"] = "The late rate rose from 69% to 75% of projects in the current window."
        rebuilt = em.update_case(raw, previous, canonical_evidence(new_case().to_dict()), canonical_evidence(case))
        assert rebuilt is not None
        self.assertEqual(rebuilt["material_delta"], case["material_delta"])
        self.assertEqual(em.grounding_codes(patched, rebuilt, model="m", prompt_version="p", previous=previous), ())
        self.assertEqual(em.grounding_codes(patched, raw, model="m", prompt_version="p", previous=previous), ("UNSUPPORTED_NUMBER",))
        self.assertIsNone(em.update_case(raw, previous, None, canonical_evidence(case)))

    def test_validation_rejection_rate(self):
        before = state(calls=[CallState("q0", "rc_a", "analyst", "succeeded", 1)])
        after = state(calls=[CallState("q0", "rc_a", "analyst", "succeeded", 1), CallState("q1", "rc_a", "update", "succeeded", 1),
                             CallState("q2", "rc_a", "update", "succeeded", 1), CallState("q3", "rc_b", "analyst", "failed", 0),
                             CallState("q4", None, "executive", "succeeded", 1), CallState("q5", "rc_a", "review", "succeeded", 1)],
                      refusals=[RefusalState("fc1", "rc_a", ("PATCH_INVALID",))])
        self.assertEqual(em.validation_rejections(before, after), MetricCount(1, 2))        # failed, executive and review calls excluded
        self.assertEqual(em.validation_rejections(after, after), MetricCount(0, 0))

    def test_lifecycle_churn_rate(self):
        def t(tid: str, rid: str, number: int, old: str | None, new: str) -> TransitionState:
            return TransitionState(tid, rid, number, old, new)

        cases = [case_row("rc_a", "k1"), case_row("rc_b", "k2", "absent"), case_row("rc_c", "k3"), case_row("rc_d", "k4"), case_row("rc_e", "k5"),
                 case_row("rc_f", "k6", "absent"), case_row("rc_g", "k7", "absent")]
        before = state(cases=[case_row(c.case_id, c.identity_key, "present" if c.case_id == "rc_b" else c.presence) for c in cases])
        after = state(cases=cases,
                      results=[ResultState("rr_a", "rc_a", 3, "updated"), ResultState("rr_b", "rc_b", 2, "active"), ResultState("rr_c", "rc_c", 3, "active"),
                               ResultState("rr_d", "rc_d", 2, "cooling"), ResultState("rr_e", "rc_e", 2, "superseded"), ResultState("rr_f", "rc_f", 2, "cooling")],
                      versions=[version("rr_a", 2, "lifecycle"), version("rr_a", 3, "patched"), version("rr_c", 2, "lifecycle"), version("rr_c", 3, "lifecycle"),
                                version("rr_d", 2, "lifecycle"), version("rr_f", 2, "lifecycle")],
                      transitions=[t("1", "rr_a", 2, "updated", "active"), t("2", "rr_a", 3, "active", "updated"),     # settle, then a patch: fine
                                   t("3", "rr_c", 2, "active", "cooling"), t("4", "rr_c", 3, "cooling", "active"),     # flip-flop (and cooled while present)
                                   t("5", "rr_d", 2, "active", "cooling"),                                             # cooled while present
                                   t("6", "rr_f", 2, "active", "cooling")])                                            # absent case cools: fine
        # rr_b: its case became absent in the step and it is still shown as current; rr_e superseded: excluded.
        self.assertEqual(em.lifecycle_churn(before, after), MetricCount(3, 5))
        # A persistent end state is counted where the step could cause it, not again in every later step (review L7) ...
        stale = state(cases=cases, results=[ResultState("rr_g", "rc_g", 1, "active")])
        self.assertEqual(em.lifecycle_churn(state(cases=cases), stale), MetricCount(0, 1))
        # ... and settle, patch, settle again in one step is not a flip-flop.
        again = state(cases=cases, results=[ResultState("rr_a", "rc_a", 4, "active")],
                      versions=[version("rr_a", 2, "lifecycle"), version("rr_a", 3, "patched"), version("rr_a", 4, "lifecycle")],
                      transitions=[t("1", "rr_a", 2, "updated", "active"), t("2", "rr_a", 3, "active", "updated"), t("3", "rr_a", 4, "updated", "active")])
        self.assertEqual(em.lifecycle_churn(state(cases=cases), again), MetricCount(0, 1))
        self.assertEqual(em.lifecycle_churn(after, state()), MetricCount(0, 0))

    def test_duplicate_question_rate(self):
        before = state(questions=[QuestionState("q1", "rc_a", "k", "open"), QuestionState("q2", "rc_b", "j", "answered")])
        after = state(questions=[QuestionState("q1", "rc_a", "k", "open"), QuestionState("q2", "rc_b", "j", "answered"),
                                 QuestionState("q3", "rc_a", "k", "open"),          # a second open copy
                                 QuestionState("q4", "rc_b", "j", "open"),          # re-asks an answered question
                                 QuestionState("q5", "rc_c", "k", "open"),          # same key, other case: fine
                                 QuestionState("q6", "rc_a", "z", "superseded")])
        self.assertEqual(em.duplicate_questions(before, after), MetricCount(2, 4))
        self.assertEqual(em.duplicate_questions(state(), state()), MetricCount(0, 0))

    def test_duplicates_invariant(self):
        clean = state(results=[ResultState("rr_a", "rc_a", 2, "active")], versions=[version("rr_a", 1), version("rr_a", 2, "lifecycle")])
        self.assertEqual(em.duplicates(clean), 0)
        dirty = state(results=[ResultState("rr_a", "rc_a", 2, "active"), ResultState("rr_b", "rc_a", 1, "new")],
                      versions=[version("rr_a", 1), version("rr_a", 3, "lifecycle"), version("rr_b", 1)],
                      work=[WorkState("w1", "rc_a", "pending", True), WorkState("w2", "rc_a", "in_progress", True), WorkState("w3", "rc_a", "pending", False)],
                      questions=[QuestionState("q1", "rc_a", "k", "open"), QuestionState("q2", "rc_a", "k", "open")],
                      synced_memory=[("prior_reasoning_summary", "rr_a", "s", "h"), ("prior_reasoning_summary", "rr_a", "s", "h")])
        self.assertEqual(em.duplicates(dirty), 5)

    def test_metric_count_rejects_impossible_fractions(self):
        for numerator, denominator in ((2, 1), (-1, 3), (0, -1)):
            with self.assertRaises(ValueError):
                MetricCount(numerator, denominator)
        self.assertEqual(MetricCount(1, 2) + MetricCount(2, 3), MetricCount(3, 5))
        self.assertIsNone(EvaluationMetric("m", MetricCount(0, 0)).value)                  # zero denominator: no data, never 0
        self.assertEqual(EvaluationMetric("m", MetricCount(3, 5)).value, Fraction(3, 5))


class ThresholdTests(unittest.TestCase):
    def test_release_thresholds_are_versioned_and_cover_every_metric(self):
        thresholds = release_thresholds()
        self.assertEqual(thresholds.version, "release-thresholds-v1")
        self.assertEqual([threshold.metric for threshold in thresholds.thresholds], list(em.METRIC_NAMES))
        self.assertTrue(all(threshold.on_no_data == NoData.FAIL for threshold in thresholds.thresholds))
        self.assertTrue(all(threshold.rationale for threshold in thresholds.thresholds))
        expected = {"case_identity_stability": (">=", "1"), "unnecessary_new_card_rate": ("<=", "0"), "unnecessary_field_rewrite_rate": ("<=", "0"),
                    "grounding_failure_rate": ("<=", "0"), "validation_rejection_rate": ("<=", "0.05"), "lifecycle_churn_rate": ("<=", "0"),
                    "duplicate_question_rate": ("<=", "0"), "expectation_failure_rate": ("<=", "0")}
        self.assertEqual({t.metric: (t.comparator.value, t.bound) for t in thresholds.thresholds}, expected)   # v1 is frozen
        self.assertIn('"version": "release-thresholds-v1"', RELEASE_THRESHOLDS_FILE.read_text())

    def test_boundaries_are_exact(self):
        at_most = Threshold("validation_rejection_rate", Comparator.AT_MOST, "0.05")
        self.assertTrue(check(at_most, Fraction(1, 20)).passed)                 # equal to the bound: passes
        self.assertTrue(check(at_most, Fraction(5, 100)).passed)
        self.assertFalse(check(at_most, Fraction(1, 20) + Fraction(1, 10**12)).passed)
        self.assertFalse(check(at_most, Fraction(51, 1000)).passed)
        self.assertTrue(check(at_most, Fraction(49, 1000)).passed)
        # 0.1 + 0.2 as floats is not 0.3; exact fractions are
        self.assertTrue(check(Threshold("m", Comparator.AT_MOST, "0.3"), Fraction(1, 10) + Fraction(2, 10)).passed)
        at_least = Threshold("case_identity_stability", Comparator.AT_LEAST, "1")
        self.assertTrue(check(at_least, Fraction(17, 17)).passed)
        self.assertFalse(check(at_least, Fraction(322, 323)).passed)
        zero = Threshold("grounding_failure_rate", Comparator.AT_MOST, "0")
        self.assertTrue(check(zero, Fraction(0, 1)).passed)
        self.assertFalse(check(zero, Fraction(1, 10**6)).passed)

    def test_no_data(self):
        failing = check(Threshold("m", Comparator.AT_MOST, "0"), None)
        self.assertEqual((failing.passed, failing.no_data, failing.value), (False, True, None))
        self.assertTrue(check(Threshold("m", Comparator.AT_MOST, "0", NoData.PASS), None).passed)
        results = evaluate_thresholds([EvaluationMetric(name, MetricCount()) for name in em.METRIC_NAMES], release_thresholds())
        self.assertTrue(all(result.no_data and not result.passed for result in results))

    def test_malformed_threshold_files_are_rejected(self):
        good = json.loads(RELEASE_THRESHOLDS_FILE.read_text())
        mutations = {
            "schema": lambda d: d.update(schema="x"),
            "float bound": lambda d: d["thresholds"][0].update(bound=1.0),
            "bad bound": lambda d: d["thresholds"][0].update(bound="one"),
            "out of range": lambda d: d["thresholds"][1].update(bound="2"),
            "comparator": lambda d: d["thresholds"][0].update(comparator="=="),
            "unknown metric": lambda d: d["thresholds"][0].update(metric="vibes"),
            "missing metric": lambda d: d["thresholds"].pop(),
            "repeated metric": lambda d: d["thresholds"].append(copy.deepcopy(d["thresholds"][0])),
            "no rationale": lambda d: d["thresholds"][0].update(rationale=""),
            "unknown key": lambda d: d.update(owner="me"),
            "no version": lambda d: d.update(version=""),
        }
        for name, mutate in mutations.items():
            document = copy.deepcopy(good)
            mutate(document)
            with self.subTest(name), self.assertRaises(FixtureError):
                parse_thresholds(document)

    def test_decimal_display(self):
        self.assertEqual(decimal_string(Fraction(1, 3)), "0.333333")
        self.assertEqual(decimal_string(Fraction(2, 3)), "0.666667")
        self.assertEqual(decimal_string(Fraction(1)), "1.000000")
        self.assertEqual(decimal_string(Fraction(0)), "0.000000")
        self.assertIsNone(decimal_string(None))


# --- reports (synthetic observations: no database) ----------------------------------------------------------------------------


def synthetic_observations(cases: Any, *, fail: tuple[str, str] | None = None, count: MetricCount | None = None) -> list[EvaluationObservation]:
    """Observations that meet every expectation (each fact equal to its expectation), with one unit of every metric's data."""
    observations = []
    for case in cases:
        steps = []
        for step in case.evaluated_steps:
            facts = {}
            for fact, expected in step.expect.checks:
                if isinstance(expected, dict) and ("min" in expected or "max" in expected):
                    expected = expected.get("min", expected.get("max"))
                elif isinstance(expected, dict):
                    expected = list(expected.get("includes", []))
                facts[fact] = "broken" if fail == (case.fixture_id, fact) else expected
            counts = {name: (MetricCount(1, 1) if name == "case_identity_stability" else MetricCount(0, 1)) for name in em.STEP_METRICS}
            if count is not None:
                counts["validation_rejection_rate"] = count
            steps.append(StepObservation(step.step_id, facts, counts))
        observations.append(EvaluationObservation(case.fixture_id, tuple(steps)))
    return observations


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.cases = load_golden_cases()

    def test_pass_and_deterministic_ordering(self):
        observations = synthetic_observations(self.cases)
        report = evaluate(self.cases, observations, environment={"provider": "synthetic"}, metadata={"generated_at": "2026-10-03T00:00:00Z"})
        self.assertTrue(report.passed, report.failures)
        shuffled_cases, shuffled_obs = list(self.cases), list(observations)
        random.Random(3).shuffle(shuffled_cases)
        random.Random(4).shuffle(shuffled_obs)
        again = evaluate(shuffled_cases, shuffled_obs, environment={"provider": "synthetic"}, metadata={"generated_at": "2026-10-04T09:30:00Z"})
        self.assertEqual(again.canonical_json(), report.canonical_json())               # metadata (timestamps) excluded
        self.assertNotEqual(again.to_json(), report.to_json())
        document = json.loads(report.canonical_json())
        self.assertEqual(document["result"], "PASS")
        self.assertEqual(document["schema"], "reasoning-evaluation-v1")
        self.assertEqual([f["fixture_id"] for f in document["fixtures"]], [case.fixture_id for case in self.cases])
        self.assertEqual(document["coverage"]["missing"], [])
        self.assertEqual(document["thresholds"]["version"], "release-thresholds-v1")
        for key in ("reasoning_contract", "guardrails", "run_control", "reliability_metrics", "pinned_model", "evaluation_schema"):
            self.assertIn(key, document["versions"])
        self.assertNotIn("metadata", document)
        self.assertEqual(json.loads(report.to_json())["metadata"], {"generated_at": "2026-10-03T00:00:00Z"})

    def test_a_failed_expectation_fails_the_report(self):
        report = evaluate(self.cases, synthetic_observations(self.cases, fail=("new-case", "focus.result")))
        self.assertFalse(report.passed)
        self.assertIn("expectation: new-case/new_topic focus.result", report.failures)
        failed = [check for check in report.checks if not check.passed]
        self.assertEqual([(c.fixture_id, c.fact, c.expected, c.observed) for c in failed], [("new-case", "focus.result", "created", "broken")])
        self.assertEqual(json.loads(report.canonical_json())["result"], "FAIL")

    def test_a_threshold_failure_fails_the_report_and_names_the_exact_value(self):
        steps = sum(len(case.evaluated_steps) for case in self.cases if "validation_rejection_rate" not in case.metric_exclusions)
        # exactly at the bound (1 in 20 everywhere): passes; one more refusal: fails
        at_bound = evaluate(self.cases, synthetic_observations(self.cases, count=MetricCount(1, 20)))
        self.assertTrue(at_bound.passed, at_bound.failures)
        observations = synthetic_observations(self.cases, count=MetricCount(1, 20))
        first = observations[0]
        bumped = StepObservation(first.steps[0].step_id, first.steps[0].facts, {**first.steps[0].counts, "validation_rejection_rate": MetricCount(2, 20)})
        observations[0] = EvaluationObservation(first.fixture_id, (bumped,) + first.steps[1:])
        report = evaluate(self.cases, observations)
        self.assertFalse(report.passed)
        self.assertIn(f"threshold: validation_rejection_rate <= 0.05 (value {steps + 1}/{20 * steps})", report.failures)

    def test_excluded_cases_do_not_count_and_are_reported(self):
        report = evaluate(self.cases, synthetic_observations(self.cases))
        metric = next(m for m in report.metrics if m.name == "validation_rejection_rate")
        self.assertEqual(metric.excluded_fixtures, ("insufficient-evidence",))
        steps = sum(len(case.evaluated_steps) for case in self.cases)
        self.assertEqual(metric.count.denominator, steps - 1)

    def test_missing_coverage_fails(self):
        observations = [o for o in synthetic_observations(self.cases) if o.fixture_id != "circuit-breaker-outage"]
        report = evaluate(self.cases, observations)
        self.assertFalse(report.passed)
        self.assertEqual(report.coverage["missing"], [18])
        partial = synthetic_observations(self.cases)
        index = next(i for i, o in enumerate(partial) if o.fixture_id == "provider-failure")
        partial[index] = EvaluationObservation("provider-failure", partial[index].steps[:1])        # one evaluated step missing
        self.assertEqual(evaluate(self.cases, partial).coverage["missing"], [13])

    def test_only_the_published_golden_set_and_thresholds_can_pass(self):
        """Review M1: a laxer threshold set, edited golden cases or narrowed coverage can only FAIL."""
        from atlas_reasoning.evaluation_types import ThresholdSet

        observations = synthetic_observations(self.cases)
        published = release_thresholds()
        lax = ThresholdSet("lax", tuple(Threshold(t.metric, t.comparator, "1" if t.comparator == Comparator.AT_MOST else "0", NoData.PASS, "lax")
                                        for t in published.thresholds))
        report = evaluate(self.cases, observations, thresholds=lax)
        self.assertFalse(report.passed)
        self.assertIn("release: thresholds 'lax' are not the published release thresholds", report.failures)
        self.assertFalse(evaluate([], [], required_numbers=()).passed)
        edited = [parse_case({**case.to_dict(), "title": case.title + " (edited)"}) for case in self.cases]
        report = evaluate(edited, observations)
        self.assertFalse(report.passed)
        self.assertFalse(report.coverage["release_conformant"])
        self.assertTrue(evaluate(self.cases, observations).coverage["release_conformant"])

    def test_a_step_observed_twice_is_refused(self):
        observations = synthetic_observations(self.cases)
        first = observations[0]
        observations[0] = EvaluationObservation(first.fixture_id, first.steps + first.steps)
        with self.assertRaisesRegex(ValueError, "more than once"):
            evaluate(self.cases, observations)

    def test_unknown_or_repeated_observations_are_refused(self):
        observations = synthetic_observations(self.cases)
        with self.assertRaises(ValueError):
            evaluate(self.cases, observations + [EvaluationObservation("nope", ())])
        with self.assertRaises(ValueError):
            evaluate(self.cases, observations + [observations[0]])

    def test_check_case_marks_unobserved_steps(self):
        case = self.cases[0]
        results = check_case(case, EvaluationObservation(case.fixture_id, ()))
        self.assertTrue(results and not any(result.passed for result in results))
        self.assertEqual({result.observed for result in results}, {"<not observed>"})


# --- the golden suite (PostgreSQL, offline model) -----------------------------------------------------------------------------


MODEL_TEXT = ("The supporting findings point the same way", "Worth a short review with the team lead", "Assignments or briefs may have changed")


@requires_db
class GoldenSuiteTests(unittest.TestCase):
    """All 20 golden cases end to end, each on a fresh database, then the release evaluation."""

    report: Any = None
    observations: ClassVar[dict[str, EvaluationObservation]] = {}

    @classmethod
    def setUpClass(cls):
        from reasoning_evaluation_driver import run_case

        from atlas_reasoning.store.repository import ReasoningStore

        cls.cases = load_golden_cases()
        cls.observations = {case.fixture_id: run_case(ReasoningStore(fresh_database()), case) for case in cls.cases}
        cls.report = evaluate(cls.cases, list(cls.observations.values()), environment={"provider": "scripted-fake", "dataset": "showcase-v1"})

    def assert_case(self, fixture_id: str) -> None:
        case = next(case for case in self.cases if case.fixture_id == fixture_id)
        failed = [check.to_dict() for check in check_case(case, self.observations[fixture_id]) if not check.passed]
        self.assertEqual(failed, [])
        for step in self.observations[fixture_id].steps:
            self.assertEqual(step.facts["integrity.duplicates"], 0, (fixture_id, step.step_id))

    def facts(self, fixture_id: str, step_id: str) -> dict[str, Any]:
        return dict(next(step for step in self.observations[fixture_id].steps if step.step_id == step_id).facts)

    # stability
    def test_01_unchanged_evidence_preserves_identity_and_result(self):
        self.assert_case("unchanged-evidence")
        self.assertEqual(self.facts("unchanged-evidence", "non_material_change")["calls.reasoning"], 0)     # irrelevant change: no rewrite

    def test_02_material_change_updates_instead_of_regenerating(self):
        self.assert_case("updated-material-evidence")

    def test_03_new_case(self):
        self.assert_case("new-case")

    def test_04_disappeared_case_follows_lifecycle(self):
        self.assert_case("disappeared-case")

    def test_05_contradiction_added(self):
        self.assert_case("contradiction-added")

    def test_06_contradiction_removed(self):
        self.assert_case("contradiction-removed")

    def test_07_insufficient_evidence(self):
        self.assert_case("insufficient-evidence")

    # human context
    def test_08_manager_note(self):
        self.assert_case("manager-note-added")

    def test_09_manager_answer(self):
        self.assert_case("manager-answer-added")

    def test_10_teaching_added(self):
        self.assert_case("teaching-added")

    def test_11_teaching_expired(self):
        self.assert_case("teaching-expired")

    def test_12_memory_unavailable(self):
        self.assert_case("memory-unavailable")

    def test_13_provider_failure(self):
        self.assert_case("provider-failure")

    # Phase 18
    def test_14_partial_run(self):
        self.assert_case("partial-run")

    def test_15_degraded_run(self):
        self.assert_case("degraded-run")

    def test_16_resume_after_interruption(self):
        self.assert_case("resume-after-interruption")

    def test_17_budget_exhaustion_then_resume(self):
        self.assert_case("budget-exhaustion-then-resume")

    def test_18_circuit_breaker_outage(self):
        self.assert_case("circuit-breaker-outage")

    def test_19_duplicate_work_prevention(self):
        self.assert_case("duplicate-work-prevention")

    def test_20_zero_call_unchanged(self):
        self.assert_case("zero-call-unchanged")

    # the release evaluation
    def test_release_evaluation_passes_on_the_offline_model(self):
        self.assertTrue(self.report.passed, self.report.failures)
        document = json.loads(self.report.canonical_json())
        self.assertEqual(document["result"], "PASS")
        self.assertEqual(document["coverage"]["observed_in_full"], list(REQUIRED_CASE_NUMBERS))
        metrics = {metric["name"]: metric for metric in document["metrics"]}
        for name in em.METRIC_NAMES:
            self.assertGreater(metrics[name]["denominator"], 0, name)          # every metric measured something
        self.assertEqual(metrics["validation_rejection_rate"]["excluded_fixtures"], ["insufficient-evidence"])

    def test_the_report_carries_no_model_text_identifiers_or_timestamps(self):
        text = self.report.canonical_json()
        for phrase in MODEL_TEXT:
            self.assertNotIn(phrase, text)
        import re
        for pattern in (r"rc1_[0-9a-f]{32}", r"rr1_[0-9a-f]{32}", r"ef1_[0-9a-f]{64}", r"run_[0-9a-f]{32}", r"req_[0-9a-f]{32}", r"wi_[0-9a-f]{32}",
                        r"rp_[0-9a-f]{32}", r"20\d\d-\d\d-\d\dT"):
            self.assertIsNone(re.search(pattern, text), pattern)

    def test_reproducible_and_independent_of_model_wording(self):
        """The same golden cases with a model that words every answer differently give the same canonical report: the harness
        evaluates structure, never text (and there is no hidden reasoning to evaluate)."""
        from reasoning_evaluation_driver import GoldenRunner

        from atlas_reasoning.store.repository import ReasoningStore

        def reworded(payload: dict[str, Any]) -> Any:
            from reasoning_fakes import analyst_answer

            answer = analyst_answer(payload, title="A differently worded card title")
            answer["reasoning_summary"] = "Worded another way: the same deterministic findings, summarised differently."
            return answer

        subset = [case for case in self.cases if case.fixture_id in ("unchanged-evidence", "provider-failure", "circuit-breaker-outage",
                                                                      "duplicate-work-prevention", "manager-answer-added")]
        for case in subset:
            with self.subTest(case.fixture_id):
                runner = GoldenRunner(ReasoningStore(fresh_database()), case)
                runner.transport.script("analyst", *[reworded] * 40)
                again = runner.run()
                self.assertEqual(json.dumps(again.to_dict(), sort_keys=True), json.dumps(self.observations[case.fixture_id].to_dict(), sort_keys=True))
                rerun = {**self.observations, case.fixture_id: again}
                self.assertEqual(evaluate(self.cases, list(rerun.values()), environment={"provider": "scripted-fake", "dataset": "showcase-v1"}).canonical_json(),
                                 self.report.canonical_json())          # the canonical report is byte-identical

    def test_observe_step_refuses_a_setup_step(self):
        from atlas_reasoning.evaluation_types import CanonicalState as State

        case = next(case for case in self.cases if case.fixture_id == "unchanged-evidence")
        with self.assertRaises(ValueError):
            observe_step(case, State(), State(), step_id="baseline")


if __name__ == "__main__":
    unittest.main()
