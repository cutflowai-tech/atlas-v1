"""Reasoning V3 Phase 07: the LLM analyst reasoning engine (``REV/07``). Every model answer is a fake: no network."""

import copy
import dataclasses
import json
import os
import random
import subprocess
import sys
import unittest
from pathlib import Path

import reasoning_factory as factory
import reasoning_snapshots as snapshots
from reasoning_db import fresh_database, requires_db
from reasoning_fakes import ScriptedAnalyst, analyst_answer, gateway, request_input

from atlas_reasoning import analyst
from atlas_reasoning.change_gate import prepare_cases, run_gate
from atlas_reasoning.contracts import PATCHABLE_FIELDS, ContractViolation, ReasoningCase
from atlas_reasoning.engine import ReasoningEngine
from atlas_reasoning.enums import LifecycleStatus, WorkKind, WorkStatus
from atlas_reasoning.output_checks import case_numbers, supported, text_numbers, unsupported_number_errors
from atlas_reasoning.provider import ProviderAuthError, ProviderResponse, ProviderUnavailable
from atlas_reasoning.reasoning_input_boundary import upstream_finding
from atlas_reasoning.settings import PINNED_MODEL
from atlas_reasoning.store.calls import StoreCallRecorder
from atlas_reasoning.store.repository import ReasoningStore

T0, T1 = "2026-09-28T00:10:00Z", "2026-09-28T01:10:00Z"
NOW = "2026-09-28T00:20:00.000000Z"
# Changing the analyst prompt text requires a new ANALYST_PROMPT_VERSION; update this pin together with the version.
ANALYST_V1_SHA256 = "1dd74efdd2d548133938842a1cfb5c9988dcea711aa879e54c96e4c96075b9ed"


def factory_case() -> ReasoningCase:
    case = factory.case_dict()
    case.update(previous_result_id=None, previous_result_version=None)
    return ReasoningCase.from_dict(factory.seal_case(case))


def response(case: ReasoningCase, answer, request_id: str = "req_" + "1" * 32, model: str = PINNED_MODEL) -> ProviderResponse:
    return ProviderResponse(request_id=request_id, model=model, content=json.dumps(answer), parsed=answer)


def answer_for(case: ReasoningCase) -> dict:
    return analyst_answer(analyst.analyst_input(case))


class AnalystOutputTests(unittest.TestCase):
    """Phase 07 #1–#11 without a database: one case → one validated result."""

    def setUp(self):
        self.case = factory_case()

    def test_valid_output_becomes_a_version_one_result_with_python_owned_identity(self):
        answer = answer_for(self.case)
        result = analyst.result_from_response(self.case, response(self.case, answer), provider="fake", result_id="rr1_" + "b" * 32, now=NOW)
        self.assertEqual((result.case_id, result.result_id, result.version), (self.case.case_id, "rr1_" + "b" * 32, 1))
        self.assertEqual(result.lifecycle_status, LifecycleStatus.NEW)
        self.assertEqual((result.evidence_fingerprint, result.source_snapshot_id), (self.case.evidence_fingerprint, self.case.source_snapshot_id))
        self.assertEqual(result.prompt_version, analyst.ANALYST_PROMPT_VERSION)
        self.assertEqual((result.model_metadata.provider, result.model_metadata.model, result.model_metadata.request_ids),
                         ("fake", PINNED_MODEL, ("req_" + "1" * 32,)))
        self.assertEqual((result.created_at, result.updated_at), (NOW, NOW))
        document = result.to_dict()
        for name in PATCHABLE_FIELDS:   # the model's explicit fields, verbatim
            self.assertEqual(document[name], answer[name])

    def test_evidence_references_are_preserved_exactly(self):
        answer = answer_for(self.case)
        result = analyst.result_from_response(self.case, response(self.case, answer), provider="fake", result_id="rr1_" + "b" * 32, now=NOW).to_dict()
        self.assertEqual(result["observation"]["evidence_refs"], answer["observation"]["evidence_refs"])
        self.assertEqual([c["evidence_refs"] for c in result["counter_evidence"]], [c["evidence_refs"] for c in answer["counter_evidence"]])
        invented = copy.deepcopy(answer)
        invented["observation"]["evidence_refs"] = ["ev1_" + "f" * 24]
        self.assertIn("UNKNOWN_EVIDENCE_REF", self._codes(invented))

    def test_the_model_cannot_set_or_change_the_case_or_result_identity(self):
        for name, value in (("case_id", "rc1_" + "f" * 32), ("result_id", "rr1_" + "f" * 32), ("lifecycle_status", "resolved"), ("version", 7),
                            ("evidence_fingerprint", "ef1_" + "f" * 64)):
            answer = {**answer_for(self.case), name: value}
            with self.subTest(field=name):
                self.assertEqual(self._codes(answer), ["UNKNOWN_FIELD"])
        self.assertNotIn("case_id", analyst.analyst_output_schema()["properties"])
        self.assertEqual(set(analyst.analyst_output_schema()["properties"]), set(PATCHABLE_FIELDS))

    def test_missing_and_malformed_fields_fail(self):
        answer = answer_for(self.case)
        del answer["counter_evidence"]
        self.assertEqual(self._codes(answer), ["SCHEMA_INVALID"])
        self.assertEqual(self._codes("not an object"), ["SCHEMA_INVALID"])
        answer = answer_for(self.case)
        answer["confidence"] = {"level": "certain", "rationale": "x"}
        self.assertEqual(self._codes(answer), ["INVALID_ENUM"])
        answer = answer_for(self.case)
        answer["observation"]["evidence_refs"] = []
        self.assertEqual(self._codes(answer), ["MISSING_EVIDENCE"])
        with self.assertRaises(ContractViolation):
            analyst.result_from_response(self.case, response(self.case, answer), provider="fake", result_id="rr1_" + "b" * 32, now=NOW)

    def test_hidden_reasoning_fields_are_refused(self):
        for name in ("raw_reasoning", "chain_of_thought", "reasoning", "thinking"):
            with self.subTest(field=name):
                self.assertEqual(self._codes({**answer_for(self.case), name: "step 1: ..."}), ["UNKNOWN_FIELD"])

    def test_counter_evidence_and_confidence_ceiling_are_enforced(self):
        answer = answer_for(self.case)
        answer["counter_evidence"] = []
        self.assertIn("COUNTER_EVIDENCE_MISSING", self._codes(answer))
        answer = answer_for(self.case)
        answer["confidence"]["level"] = "strong"   # strongest supporting finding is moderate
        self.assertIn("CONFIDENCE_EXCEEDS_UPSTREAM", self._codes(answer))

    def test_invented_numbers_are_refused_and_case_numbers_accepted(self):
        answer = answer_for(self.case)
        answer["observation"]["statement"] = "11 of 16 projects were late (69%, up from 50%); 18.75 points more."
        self.assertEqual(self._codes(answer), [])
        for text in ("23 of 40 projects were late.", "The late rate will reach 90% next month.", "Ahmed missed 7 deadlines."):
            answer["observation"]["statement"] = text
            with self.subTest(text=text):
                self.assertEqual(self._codes(answer), ["UNSUPPORTED_NUMBER"])

    def test_number_tokens_inside_identifiers_and_dates_are_not_numbers(self):
        self.assertEqual([token for token, _, _ in text_numbers("editor-label-12 in Q3, rc1_00ab and 2026-09-01: 11 of 16, 68.75%.")],
                         ["2026", "11", "16", "68.75"])
        allowed = case_numbers(self.case.to_dict())
        self.assertTrue(supported(69, 0, allowed) and supported(68.8, 1, allowed) and supported(0.6875, 4, allowed))
        self.assertFalse(supported(70, 0, allowed))
        self.assertEqual(unsupported_number_errors({"title": "No numbers at all"}, self.case.to_dict()), [])

    def _codes(self, answer) -> list[str]:
        return sorted({error.split(":", 1)[0] for error in analyst.analyst_output_errors(answer, self.case.to_dict())})


class PromptTests(unittest.TestCase):
    """Phase 07 #1, #2, #9: versioned prompt, bounded input, deterministic serialization."""

    def test_prompt_is_versioned_and_pinned(self):
        self.assertEqual(analyst.ANALYST_PROMPT_VERSION, "analyst-v1")
        self.assertEqual(analyst.prompt_sha256("analyst-v1"), ANALYST_V1_SHA256)
        text = analyst.prompt_text("analyst-v1")
        for rule in ("Do not invent numbers", "counter_evidence", "requires_context", "questions_for_management", "personality", "termination",
                     "never be higher than the strongest upstream confidence", "Never include hidden reasoning"):
            self.assertIn(rule, text)

    def test_request_carries_prompt_and_case_provenance(self):
        case = factory_case()
        request = analyst.analyst_request(case, run_id="run_" + "1" * 32, work_item_id="wi_" + "2" * 32)
        self.assertEqual([m.role for m in request.messages], ["system", "user"])
        self.assertEqual(request.messages[0].content, analyst.prompt_text("analyst-v1"))
        context = request.context
        self.assertEqual((context.purpose, context.prompt_version, context.case_id, context.evidence_fingerprint, context.source_snapshot_id),
                         ("analyst", "analyst-v1", case.case_id, case.evidence_fingerprint, case.source_snapshot_id))
        self.assertTrue(request.output.strict)
        self.assertEqual(request_input(request), json.loads(json.dumps(analyst.analyst_input(case))))

    def test_equivalent_cases_serialize_identically(self):
        base = snapshots.reasoning_input()
        reference = {c.document["identity_key"]: analyst.analyst_messages(ReasoningCase.from_dict(c.document))
                     for c in prepare_cases(base, T0)[1].values()}
        findings = snapshots.intelligence_copy()["findings"]
        rng = random.Random(5)
        rng.shuffle(findings)
        for i, row in enumerate(findings):
            row["finding_id"] = f"{row['finding_type']}:{i:016x}"   # new V2 IDs, as every day
            row["importance"]["rank"] = len(findings) - i
            rng.shuffle(row["statements"])
            for block in row["supporting_evidence"] + row["contradicting_evidence"] + row["context_evidence"]:
                rng.shuffle(block["records"])
        later = dataclasses.replace(base, findings=tuple(upstream_finding(row) for row in findings),
                                    snapshot=dataclasses.replace(base.snapshot, source_snapshot_id="snapshot-later"))
        for case in prepare_cases(later, T1)[1].values():
            with self.subTest(case=case.document["identity_key"]):
                self.assertEqual(analyst.analyst_messages(ReasoningCase.from_dict(case.document)), reference[case.document["identity_key"]])

    def test_volatile_values_never_reach_the_prompt(self):
        case = factory_case()
        text = analyst.analyst_messages(case)[1].content
        for value in (case.source_snapshot_id, case.created_at, case.case_id, *(f.finding_id for f in case.findings),
                      *(e for ref in case.current_evidence.references for e in ref.event_ids)):
            self.assertNotIn(value, text)
        self.assertIn(case.evidence_fingerprint, text)   # provenance of the evidence the answer is about

    def test_oversized_case_is_refused_not_truncated(self):
        case = factory.case_dict()
        case.update(previous_result_id=None, previous_result_version=None)
        case["manager_context"] = [{"source_type": "manager_interpretation", "source_id": f"n{i}", "body": "x" * 7000, "author": None,
                                    "recorded_at": "2026-09-20T09:00:00Z"} for i in range(60)]
        big = ReasoningCase.from_dict(factory.seal_case(case))
        with self.assertRaises(analyst.CaseTooLarge):
            analyst.analyst_request(big)


@requires_db
class AnalystEngineTests(unittest.TestCase):
    """The new-case path end to end: Change Gate → engine → gateway (fake) → validated result in PostgreSQL."""

    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.transport = ScriptedAnalyst()
        self.engine = ReasoningEngine(self.store, gateway(self.transport, recorder=StoreCallRecorder(self.store)))
        self.report = run_gate(snapshots.reasoning_input(), self.store, now=T0)

    def test_every_new_case_gets_one_evidence_linked_result(self):
        report = self.engine.process_run(self.report.run_id)
        new_items = [d for d in self.report.decisions if d.work_kind == WorkKind.NEW_RESULT]
        self.assertEqual(len(report.outcomes), len(new_items))
        self.assertEqual({o.status for o in report.outcomes}, {WorkStatus.DONE.value})
        self.assertEqual(set(self.transport.purposes()), {"analyst"})
        with self.store.transaction() as tx:
            for outcome in report.outcomes:
                result = tx.get_result(outcome.result_id).to_dict()
                self.assertEqual((result["case_id"], result["version"], result["lifecycle_status"]), (outcome.case_id, 1, "new"))
                links = tx.evidence_links(outcome.result_id, 1)
                self.assertEqual({row["ref_id"] for row in links}, _cited(result))
                self.assertTrue(all(row["monday_item_id"] and row["event_ids"] for row in links))
                history = tx.result_history(outcome.result_id)
                self.assertEqual([(row["change_kind"], row["prompt_version"], row["model"], row["work_item_id"]) for row in history],
                                 [("created", "analyst-v1", PINNED_MODEL, outcome.work_item_id)])
            calls = tx.llm_calls(run_id=self.report.run_id)
        self.assertEqual(len(calls), len(new_items))
        self.assertEqual({(c["purpose"], c["prompt_version"], c["status"], c["model"]) for c in calls}, {("analyst", "analyst-v1", "succeeded", PINNED_MODEL)})
        self.assertEqual(self.store.work_items(open_only=True), [])

    def test_same_snapshot_again_creates_no_reasoning(self):
        self.engine.process_run(self.report.run_id)
        calls = len(self.transport.requests)
        again = run_gate(snapshots.reasoning_input(), self.store, now=T1)
        self.assertEqual(again.llm_work_item_ids, ())
        self.assertEqual(self.engine.process_run(again.run_id).outcomes, ())
        self.assertEqual(len(self.transport.requests), calls)

    def test_provider_failure_is_isolated_to_its_case(self):
        items = [d for d in self.report.decisions if d.work_kind == WorkKind.NEW_RESULT]
        broken, flaky = items[0].case_id, items[1].case_id
        self.transport.script(broken, ProviderAuthError("bad key", status=401))
        self.transport.script(flaky, ProviderUnavailable("busy", status=503))   # retried once, then fine
        report = self.engine.process_run(self.report.run_id)
        by_case = {o.case_id: o for o in report.outcomes}
        self.assertEqual((by_case[broken].status, by_case[broken].error), ("failed", "provider:authentication"))
        self.assertEqual(by_case[flaky].status, "done")
        self.assertEqual(sum(o.status == "done" for o in report.outcomes), len(items) - 1)
        with self.store.transaction() as tx:
            self.assertIsNone(tx.open_result(broken))
            item = tx.work_items(case_id=broken)[0]
        self.assertEqual((item.status, item.result_id), (WorkStatus.FAILED, None))

    def test_malformed_and_invalid_output_fails_the_item_and_stores_nothing(self):
        items = [d for d in self.report.decisions if d.work_kind == WorkKind.NEW_RESULT]
        malformed, invented = items[0].case_id, items[1].case_id
        self.transport.script(malformed, "{not json", "still not json")

        def invent(payload):
            answer = analyst_answer(payload)
            answer["observation"]["evidence_refs"] = ["ev1_" + "e" * 24]
            return answer

        self.transport.script(invented, invent, invent)
        report = {o.case_id: o for o in self.engine.process_run(self.report.run_id).outcomes}
        self.assertEqual(report[malformed].error, "provider:invalid_structured_output")
        self.assertEqual(report[invented].error, "provider:invalid_structured_output")
        with self.store.transaction() as tx:
            self.assertIsNone(tx.open_result(malformed))
            self.assertIsNone(tx.open_result(invented))
            failed = [c for c in tx.llm_calls(run_id=self.report.run_id) if c["status"] == "failed"]
        self.assertEqual({(c["case_id"], c["attempts"], c["error_class"]) for c in failed},
                         {(malformed, 2, "invalid_structured_output"), (invented, 2, "invalid_structured_output")})

    def test_a_retry_after_invalid_output_can_still_succeed(self):
        case_id = next(d.case_id for d in self.report.decisions if d.work_kind == WorkKind.NEW_RESULT)
        self.transport.script(case_id, lambda payload: {**analyst_answer(payload), "chain_of_thought": "..."})
        outcome = next(o for o in self.engine.process_run(self.report.run_id).outcomes if o.case_id == case_id)
        self.assertEqual(outcome.status, "done")

    def test_a_substituted_model_is_refused(self):
        self.transport.model = "openai/gpt-4o"
        report = self.engine.process_run(self.report.run_id)
        self.assertEqual({o.error for o in report.outcomes}, {"work:MODEL_SUBSTITUTED"})
        with self.store.transaction() as tx:
            self.assertEqual(tx._one("SELECT count(*) AS n FROM reasoning_results")["n"], 0)


class ReasonCommandTests(unittest.TestCase):
    def _run(self, *args: str, env: dict) -> subprocess.CompletedProcess:
        base = {key: value for key, value in os.environ.items() if not key.startswith(("ATLAS_REASONING", "OPENROUTER"))}
        base.update({"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}, **env)
        return subprocess.run([sys.executable, "-m", "atlas_reasoning", *args], env=base, capture_output=True, text=True, check=False)

    def test_reason_needs_the_flag_and_the_provider_key(self):
        off = self._run("reason", "run_" + "0" * 32, env={})
        self.assertEqual((off.returncode, json.loads(off.stderr)["error"]), (2, "ReasoningDisabled"))
        keyless = self._run("reason", "run_" + "0" * 32, env={"ATLAS_REASONING_V3": "on"})
        self.assertEqual((keyless.returncode, json.loads(keyless.stderr)["error"]), (2, "ReasoningConfigError"))
        self.assertNotIn("Traceback", keyless.stderr)


def _cited(result: dict) -> set[str]:
    refs = set()
    for name in ("observation", "interpretation", "management_significance"):
        refs.update(result[name]["evidence_refs"])
    for name in ("supporting_evidence", "counter_evidence", "alternative_explanations", "suggested_investigations"):
        for row in result[name]:
            refs.update(row["evidence_refs"])
    return refs


if __name__ == "__main__":
    unittest.main()
