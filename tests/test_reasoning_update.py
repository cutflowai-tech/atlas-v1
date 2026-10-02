"""Reasoning V3 Phase 08: update-only reasoning and the deterministic patch merge (``REV/08``). Fake model answers only."""

import copy
import json
import unittest
from unittest import mock

import reasoning_snapshots as snapshots
from reasoning_db import fresh_database, requires_db
from reasoning_engine_support import (
    DEADLINE_12,
    LATER,
    changed_case,
    changed_rows,
    engine,
    first_result,
    new_case,
    payload_with,
    times,
    with_new_topic,
)
from reasoning_fakes import analyst_answer, request_input, update_answer

from atlas_reasoning import analyst, patch, updater
from atlas_reasoning.change_gate import run_gate
from atlas_reasoning.contracts import IMMUTABLE_RESULT_FIELDS, PATCHABLE_FIELDS, ContractViolation, ReasoningUpdate
from atlas_reasoning.enums import ResultChangeKind, WorkKind, WorkStatus
from atlas_reasoning.provider import ProviderResponse
from atlas_reasoning.settings import PINNED_MODEL
from atlas_reasoning.store.repository import ReasoningStore, StoreTransaction

# Changing the update prompt text requires a new UPDATE_PROMPT_VERSION; update this pin together with the version.
UPDATE_V1_SHA256 = "40a7849f176823e1c53e8b7dce5a48ba8e9951d2605f9349c93297ea38e3bded"


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class MergeTests(unittest.TestCase):
    """REV/08 #5–#10 without a database."""

    def setUp(self):
        self.v1 = first_result(new_case())
        self.case = changed_case(self.v1)
        self.payload = updater.update_input(self.v1, self.case)

    def _apply(self, answer, now=LATER):
        response = ProviderResponse(request_id="req_" + "2" * 32, model=PINNED_MODEL, content="", parsed=answer)
        return updater.apply_response(self.v1, self.case, response, provider="fake", now=now, lifecycle_status=self.v1.lifecycle_status.value)

    def _codes(self, answer) -> list[str]:
        return sorted({error.split(":", 1)[0] for error in updater.update_output_errors(answer, self.v1.to_dict(), self.case.to_dict())})

    def _required(self) -> dict:
        fresh = analyst_answer(self.payload)
        fresh["observation"]["statement"] = "12 of 16 projects in the current window were late (75%)."
        return {"observation": fresh["observation"]}

    def test_untouched_fields_keep_their_exact_wording(self):
        change = {**self._required(), "confidence": {"level": "weak", "rationale": "Only one more late project."}}
        applied = self._apply(update_answer(self.payload, change=change))
        before, after = self.v1.to_dict(), applied.result.to_dict()
        for name in PATCHABLE_FIELDS:
            with self.subTest(field=name):
                if name in change:
                    self.assertEqual(after[name], change[name])
                else:
                    self.assertEqual(canonical(after[name]), canonical(before[name]))
        self.assertEqual(list(applied.update.changed_names), ["observation", "confidence"])

    def test_identity_and_history_fields_are_protected(self):
        applied = self._apply(update_answer(self.payload, change=self._required()))
        before, after = self.v1.to_dict(), applied.result.to_dict()
        for name in ("contract_version", "result_id", "case_id", "created_at", "superseded_by", "lifecycle_status"):
            self.assertEqual(after[name], before[name], name)
        self.assertEqual((after["version"], after["evidence_fingerprint"], after["source_snapshot_id"], after["updated_at"], after["prompt_version"]),
                         (2, self.case.evidence_fingerprint, self.case.source_snapshot_id, LATER, "update-v1"))
        self.assertEqual(after["model_metadata"], {"provider": "fake", "model": PINNED_MODEL, "request_ids": ["req_" + "2" * 32]})
        update = applied.update.to_dict()
        self.assertEqual((update["case_id"], update["result_id"], update["base_version"], update["evidence_fingerprint_before"],
                          update["evidence_fingerprint_after"]), (self.v1.case_id, self.v1.result_id, 1, self.v1.evidence_fingerprint, self.case.evidence_fingerprint))

    def test_the_model_cannot_patch_immutable_or_unknown_paths(self):
        for name in ("case_id", "result_id", "version", "lifecycle_status", "created_at"):
            answer = update_answer(self.payload, change=self._required())
            answer["changed_fields"].append(name)
            with self.subTest(field=name):
                self.assertIn("IMMUTABLE_FIELD", self._codes(answer))
        for path in ("observation.statement", "observation/evidence_refs", "summary", "chain_of_thought"):
            answer = update_answer(self.payload, change=self._required())
            answer["changed_fields"].append(path)
            with self.subTest(path=path):
                self.assertIn("UNKNOWN_FIELD", self._codes(answer))
        answer = update_answer(self.payload, change=self._required())
        answer["patch"]["case_id"] = "rc1_" + "f" * 32
        self.assertEqual(self._codes(answer), ["UNKNOWN_FIELD"])
        answer = update_answer(self.payload, change=self._required())
        answer["case_id"] = "rc1_" + "f" * 32
        self.assertEqual(self._codes(answer), ["UNKNOWN_FIELD"])
        self.assertTrue(set(updater.update_output_schema()["properties"]["patch"]["properties"]).isdisjoint(IMMUTABLE_RESULT_FIELDS))

    def test_field_accounting_and_values_must_agree(self):
        answer = update_answer(self.payload, change=self._required())
        answer["preserved_fields"].remove("title")
        self.assertIn("FIELD_ACCOUNTING", self._codes(answer))
        answer = update_answer(self.payload, change=self._required())
        answer["patch"]["title"] = "A reworded title nobody asked for"
        self.assertEqual(self._codes(answer), ["PATCH_VALUE_MISMATCH"])
        answer = update_answer(self.payload, change=self._required())
        answer["action"] = "no_change"
        self.assertIn("ACTION_MISMATCH", self._codes(answer))
        answer = update_answer(self.payload, change=self._required())
        answer["patch"]["observation"] = {"statement": "Unsupported.", "evidence_refs": []}
        self.assertIn("INVALID_FIELD_VALUE", self._codes(answer))

    def test_fields_the_evidence_invalidated_must_change(self):
        self.assertEqual(self.payload["fields_requiring_change"], {"observation": [updater.STALE_NUMBER]})
        self.assertEqual(self._codes(update_answer(self.payload, change={})), ["REQUIRED_CHANGE_MISSING"])
        self.assertEqual(self._codes(update_answer(self.payload, change={"confidence": {"level": "weak", "rationale": "x"}})), ["REQUIRED_CHANGE_MISSING"])
        members = [ref.member_key for ref in self.case.current_evidence.references]
        gone = next(ref.ref_id for ref in self.case.current_evidence.references if members.count(ref.member_key) > 1
                    and ref.ref_id in self.v1.supporting_evidence[0].evidence_refs)
        removed = changed_case(self.v1, mutate=lambda case: case["current_evidence"].update(
            references=[ref for ref in case["current_evidence"]["references"] if ref["ref_id"] != gone]))
        reasons = updater.required_changes(self.v1.to_dict(), removed.to_dict())
        citing = [name for name in PATCHABLE_FIELDS if gone in updater.cited_refs(self.v1.to_dict()[name])]
        self.assertIn("supporting_evidence", citing)
        for name in citing:
            self.assertIn(updater.STALE_EVIDENCE_REF, reasons[name], name)

    def test_patched_values_are_checked_like_a_new_result(self):
        change = self._required()
        change["observation"]["statement"] = "13 of 16 projects were late."
        self.assertEqual(self._codes(update_answer(self.payload, change=change)), ["UNSUPPORTED_NUMBER"])
        change = self._required()
        change["observation"]["evidence_refs"] = ["ev1_" + "d" * 24]
        self.assertIn("UNKNOWN_EVIDENCE_REF", self._codes(update_answer(self.payload, change=change)))
        self.assertIn("CONFIDENCE_EXCEEDS_UPSTREAM",
                      self._codes(update_answer(self.payload, change={**self._required(), "confidence": {"level": "strong", "rationale": "x"}})))
        with self.assertRaises(ContractViolation):
            self._apply(update_answer(self.payload, change={}))

    def test_no_change_review_preserves_every_field_byte_for_byte(self):
        unchanged = changed_case(self.v1, mutate=lambda case: case["current_evidence"]["references"][0]["values"].update(delta_seconds=14401))
        self.assertEqual(updater.required_changes(self.v1.to_dict(), unchanged.to_dict()), {})
        answer = update_answer(updater.update_input(self.v1, unchanged), change={}, rationale="One record moved by a second; the card still holds.")
        response = ProviderResponse(request_id="req_" + "3" * 32, model=PINNED_MODEL, content="", parsed=answer)
        applied = updater.apply_response(self.v1, unchanged, response, provider="fake", now=LATER, lifecycle_status="new")
        self.assertFalse(applied.is_patch)
        before, after = self.v1.to_dict(), applied.result.to_dict()
        self.assertEqual(canonical({n: after[n] for n in PATCHABLE_FIELDS}), canonical({n: before[n] for n in PATCHABLE_FIELDS}))
        changes = patch.diff(before, after)
        self.assertEqual((changes["changed_fields"], changes["fields"]), ([], {}))
        self.assertEqual(set(changes["provenance"]), {"version", "evidence_fingerprint", "model_metadata", "prompt_version", "updated_at"})

    def test_merge_refuses_a_stale_or_foreign_update(self):
        update = updater.build_update(update_answer(self.payload, change=self._required()), self.v1.to_dict(), self.case.to_dict())
        provenance = patch.VersionProvenance("s", self.case.evidence_fingerprint, {"provider": "p", "model": "m", "request_ids": ["r"]}, "update-v1", LATER, "new")
        for mutate, code in ((lambda u: u.update(base_version=3), "STALE_BASE_VERSION"), (lambda u: u.update(result_id="rr1_" + "c" * 32), "IMMUTABLE_FIELD"),
                             (lambda u: u["changed_fields"].append({"field": "created_at", "value": LATER}), "IMMUTABLE_FIELD")):
            bad = copy.deepcopy(update)
            mutate(bad)
            with self.subTest(code=code), self.assertRaises(ContractViolation) as caught:
                patch.merge(self.v1.to_dict(), bad, provenance)
            self.assertIn(code, caught.exception.codes)

    def test_update_prompt_is_separate_versioned_and_complete(self):
        self.assertEqual(updater.UPDATE_PROMPT_VERSION, "update-v1")
        self.assertNotEqual(analyst.prompt_text("update-v1"), analyst.prompt_text("analyst-v1"))
        self.assertEqual(analyst.prompt_sha256("update-v1"), UPDATE_V1_SHA256)
        request = updater.update_request(self.v1, self.case, run_id="run_" + "1" * 32)
        self.assertEqual((request.context.purpose, request.context.prompt_version), ("update", "update-v1"))
        sent = request_input(request)
        self.assertEqual(sent["previous_result"], {"version": 1, "fields": {n: self.v1.to_dict()[n] for n in PATCHABLE_FIELDS}})
        self.assertEqual(sent["fingerprints"], {"before": self.v1.evidence_fingerprint, "after": self.case.evidence_fingerprint})
        self.assertEqual(sent["material_delta"], self.case.to_dict()["material_delta"])
        self.assertTrue(sent["material_delta"]["changed_values"])
        self.assertEqual(sent["fields_requiring_change"], {"observation": ["uses_numbers_no_longer_in_the_case"]})
        self.assertEqual(len(sent["evidence_references"]), len(self.case.current_evidence.references))
        self.assertEqual(updater.update_messages(self.v1, self.case), updater.update_messages(self.v1, self.case))
        for name in ("result_id", "case_id"):
            self.assertNotIn(getattr(self.v1, name), request.messages[1].content)


@requires_db
class UpdateEngineTests(unittest.TestCase):
    """Existing cards update surgically through the engine and stay historically recoverable."""

    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.engine, self.transport = engine(self.store)
        self.t = times(10)
        self.first = run_gate(snapshots.reasoning_input(), self.store, now=self.t[0])
        self.engine.process_run(self.first.run_id)
        self.case_id = next(d.case_id for d in self.first.decisions if d.identity_key == DEADLINE_12)
        with self.store.transaction() as tx:
            self.result_id = tx.open_result(self.case_id).result_id
            self.v1_row = tx._one("SELECT document::text AS text FROM reasoning_result_versions WHERE result_id = %s AND version = 1", (self.result_id,))
        self.v1 = self.store.get_result(self.result_id).to_dict()

    def _change(self):
        report = run_gate(payload_with(changed_rows(), "snapshot-2"), self.store, now=self.t[1])
        decision = next(d for d in report.decisions if d.case_id == self.case_id)
        self.assertEqual(decision.work_kind, WorkKind.UPDATE_RESULT)
        return report

    def test_changed_evidence_patches_the_same_result_as_a_new_version(self):
        report = self._change()
        outcome = next(o for o in self.engine.process_run(report.run_id).outcomes if o.case_id == self.case_id)
        self.assertEqual((outcome.status, outcome.result_id, outcome.version, outcome.change_kind), ("done", self.result_id, 2, "patched"))
        self.assertEqual(self.transport.purposes().count("update"), 1)
        with self.store.transaction() as tx:
            history = tx.result_history(self.result_id)
            diffs = tx.result_diffs(self.result_id)
            v1_row = tx._one("SELECT document::text AS text FROM reasoning_result_versions WHERE result_id = %s AND version = 1", (self.result_id,))
            self.assertIsNotNone(tx.open_result(self.case_id))
            self.assertEqual(tx._one("SELECT count(*) AS n FROM reasoning_results WHERE case_id = %s", (self.case_id,))["n"], 1)
        self.assertEqual([(h["version"], h["change_kind"], h["prompt_version"]) for h in history], [(1, "created", "analyst-v1"), (2, "patched", "update-v1")])
        self.assertEqual(v1_row, self.v1_row, "version 1 is never rewritten")
        v2 = history[1]["document"]
        update = ReasoningUpdate.from_dict(history[1]["update_document"])
        for name in PATCHABLE_FIELDS:
            if name not in update.changed_names:
                self.assertEqual(canonical(v2[name]), canonical(self.v1[name]), name)
        self.assertEqual(len(diffs), 1)
        self.assertEqual((diffs[0]["from_version"], diffs[0]["to_version"], diffs[0]["change_kind"], diffs[0]["changed_fields"]),
                         (1, 2, "patched", list(update.changed_names)))
        for name in update.changed_names:
            self.assertEqual(diffs[0]["field_diffs"][name], {"before": self.v1[name], "after": v2[name]})
        self.assertEqual(diffs[0]["provenance_diffs"]["evidence_fingerprint"]["after"], v2["evidence_fingerprint"])
        self.assertEqual(self.store.get_result(self.result_id, 1).to_dict(), self.v1)

    def test_no_change_review_keeps_the_card_and_records_the_review(self):
        report = self._change()
        self.transport.script(self.case_id, lambda payload: update_answer(payload, change={}, rationale="The direction and size are unchanged."))
        outcome = next(o for o in self.engine.process_run(report.run_id).outcomes if o.case_id == self.case_id)
        self.assertEqual((outcome.version, outcome.change_kind), (2, "no_change_review"))
        v2 = self.store.get_result(self.result_id).to_dict()
        self.assertEqual(canonical({n: v2[n] for n in PATCHABLE_FIELDS}), canonical({n: self.v1[n] for n in PATCHABLE_FIELDS}))
        self.assertEqual(v2["lifecycle_status"], self.v1["lifecycle_status"])
        diff = self.store.result_diffs(self.result_id)[0]
        self.assertEqual((diff["change_kind"], diff["changed_fields"], diff["field_diffs"]), ("no_change_review", [], {}))
        history = self.store.result_history(self.result_id)
        self.assertEqual(history[1]["update_document"]["action"], "no_change")
        self.assertEqual(history[1]["update_document"]["change_rationale"], "The direction and size are unchanged.")

    def test_failed_patch_rolls_back_completely(self):
        report = self._change()
        with mock.patch.object(StoreTransaction, "record_result_diff", side_effect=RuntimeError("disk full")):
            outcome = next(o for o in self.engine.process_run(report.run_id).outcomes if o.case_id == self.case_id)
        self.assertEqual((outcome.status, outcome.error), ("failed", "internal:RuntimeError"))
        with self.store.transaction() as tx:
            self.assertEqual(tx.open_result(self.case_id).version, 1)
            self.assertEqual([h["version"] for h in tx.result_history(self.result_id)], [1])
            self.assertEqual(tx.result_diffs(self.result_id), [])
            self.assertEqual(tx._one("SELECT count(*) AS n FROM reasoning_evidence_links WHERE result_id = %s AND version = 2", (self.result_id,))["n"], 0)
            item = tx.work_items(case_id=self.case_id, run_id=report.run_id)[0]
        self.assertEqual((item.status, item.kind), (WorkStatus.FAILED, WorkKind.UPDATE_RESULT))
        self.assertEqual(self.store.get_result(self.result_id).to_dict(), self.v1)

    def test_an_invalid_patch_from_the_model_changes_nothing(self):
        report = self._change()

        def rewrite_identity(payload):
            answer = update_answer(payload)
            answer["changed_fields"].append("case_id")
            return answer

        self.transport.script(self.case_id, rewrite_identity, rewrite_identity)
        outcome = next(o for o in self.engine.process_run(report.run_id).outcomes if o.case_id == self.case_id)
        self.assertEqual((outcome.status, outcome.error), ("failed", "provider:invalid_structured_output"))
        self.assertEqual(self.store.get_result(self.result_id).to_dict(), self.v1)

    def test_a_concurrent_writer_wins_and_the_stale_patch_is_dropped(self):
        report = self._change()
        original = updater.apply_response

        def racing(previous, case, response, **kwargs):
            applied = original(previous, case, response, **kwargs)
            with self.store.transaction() as tx:   # another worker appends version 2 first
                tx.append_version_with_diff(applied.result, previous=previous, change_kind=ResultChangeKind.PATCHED, update=applied.update)
            return applied

        with mock.patch.object(updater, "apply_response", side_effect=racing):
            outcome = next(o for o in self.engine.process_run(report.run_id).outcomes if o.case_id == self.case_id)
        self.assertEqual((outcome.status, outcome.error), ("failed", "store:VersionConflict"))
        self.assertEqual([h["version"] for h in self.store.result_history(self.result_id)], [1, 2])


@requires_db
class StabilityTests(unittest.TestCase):
    """The decisive property: same case + same evidence → no reasoning; changed evidence → patch; new topic → new result; never a
    duplicate card."""

    def test_same_evidence_changed_evidence_and_a_new_topic(self):
        store = ReasoningStore(fresh_database())
        reasoning, transport = engine(store)
        t = times(6)
        first = run_gate(snapshots.reasoning_input(), store, now=t[0])
        reasoning.process_run(first.run_id)
        cases = {d.case_id for d in first.decisions}
        results = self._open_results(store)
        self.assertEqual(set(results), cases)
        calls = len(transport.requests)

        # Same snapshot, then the same evidence under new V2 finding IDs and wording: no reasoning at all.
        for i, payload in enumerate((snapshots.reasoning_input(), payload_with(self._reworded(), "snapshot-reworded"))):
            report = run_gate(payload, store, now=t[1 + i])
            self.assertEqual(report.llm_work_item_ids, ())
            self.assertEqual(reasoning.process_run(report.run_id).outcomes, ())
        self.assertEqual(len(transport.requests), calls)
        self.assertEqual(self._open_results(store), results)

        # Changed evidence: the existing result is patched (same result_id, version 2).
        changed = run_gate(payload_with(changed_rows(), "snapshot-changed"), store, now=t[3])
        outcomes = reasoning.process_run(changed.run_id).outcomes
        self.assertEqual([(o.change_kind, o.version) for o in outcomes], [("patched", 2)])
        target = outcomes[0].case_id
        after = self._open_results(store)
        self.assertEqual(after[target][0], results[target][0])
        self.assertEqual({k: v for k, v in after.items() if k != target}, {k: v for k, v in results.items() if k != target})

        # A new topic: a new case and a new result; every other card untouched; still one open card per case.
        topic = run_gate(payload_with(with_new_topic(), "snapshot-topic"), store, now=t[4])
        new = [d for d in topic.decisions if d.case_id not in cases]
        outcomes = reasoning.process_run(topic.run_id).outcomes
        self.assertEqual([(o.case_id, o.change_kind) for o in outcomes if o.status == "done" and o.change_kind == "created"], [(new[0].case_id, "created")])
        final = self._open_results(store)
        self.assertEqual(set(final), cases | {new[0].case_id})
        with store.transaction() as tx:
            counts = tx._all("SELECT case_id, count(*) AS n FROM reasoning_results GROUP BY case_id")
        self.assertEqual({row["n"] for row in counts}, {1})

    @staticmethod
    def _reworded():
        findings = snapshots.intelligence_copy()["findings"]
        for i, row in enumerate(findings):
            row["finding_id"] = f"{row['finding_type']}:{i:016x}"
            row["text"] = {"en": {"headline": "Entirely different generated wording"}}
        return findings

    @staticmethod
    def _open_results(store) -> dict:
        with store.transaction() as tx:
            rows = tx._all("SELECT case_id, result_id, current_version FROM reasoning_results")
        return {row["case_id"]: (row["result_id"], row["current_version"]) for row in rows}


if __name__ == "__main__":
    unittest.main()
