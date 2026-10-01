"""Reasoning V3 Phase 05: evidence fingerprints, material deltas and the Change Gate (``REV/05``).

The decisive property: running the same source snapshot twice creates no reasoning work on the second run.
"""

import copy
import dataclasses
import json
import os
import random
import subprocess
import sys
import threading
import unittest
from pathlib import Path

import reasoning_factory as factory
import reasoning_snapshots as snapshots
from reasoning_db import fresh_database, requires_db, test_database_url

from atlas_reasoning.case_builder import build_case_document
from atlas_reasoning.case_mapping import map_findings
from atlas_reasoning.change_gate import (
    EVIDENCE_CHANGED,
    FIRST_OBSERVATION,
    NOT_IN_SNAPSHOT,
    REAPPEARED_SAME_EVIDENCE,
    SAME_EVIDENCE,
    STILL_ABSENT,
    case_for_work,
    prepare_cases,
    run_gate,
)
from atlas_reasoning.contracts import ReasoningResult, case_errors
from atlas_reasoning.delta import is_empty, material_delta
from atlas_reasoning.enums import GateAction, LifecycleStatus, WorkKind, WorkStatus
from atlas_reasoning.fingerprint import canonical_evidence, evidence_fingerprint
from atlas_reasoning.reasoning_input_boundary import ReasoningInput, upstream_finding
from atlas_reasoning.store.repository import ReasoningStore

ROOT = Path(__file__).resolve().parents[1]
T0, T1 = "2026-09-28T00:10:00Z", "2026-09-28T01:10:00Z"
DEADLINE_12 = "case-identity-v1|editor|editor-label-12|deadline"


def rows() -> list[dict]:
    return snapshots.intelligence_copy()["findings"]


def payload_with(findings: list[dict], snapshot_id: str | None = None) -> ReasoningInput:
    """The showcase payload with other findings (a simulated later upstream snapshot)."""
    base = snapshots.reasoning_input()
    snapshot = dataclasses.replace(base.snapshot, source_snapshot_id=snapshot_id) if snapshot_id else base.snapshot
    return dataclasses.replace(base, findings=tuple(upstream_finding(row) for row in findings), snapshot=snapshot)


def documents(payload: ReasoningInput) -> dict[str, dict]:
    return {case.document["identity_key"]: dict(case.document) for case in prepare_cases(payload, T0)[1].values()}


def first_change_editor(findings: list[dict], editor: str = "editor-label-12") -> dict:
    return next(r for r in findings if r["finding_type"] == "change.editor" and r["scope"]["editor_id"] == editor
                and r["statements"][0]["params"].get("measure") == "late_rate")


class FingerprintTests(unittest.TestCase):
    def test_same_snapshot_gives_the_same_fingerprints(self):
        first = documents(snapshots.reasoning_input())
        second = {case.document["identity_key"]: dict(case.document) for case in prepare_cases(snapshots.reasoning_input(), T1)[1].values()}
        self.assertEqual({k: d["evidence_fingerprint"] for k, d in first.items()}, {k: d["evidence_fingerprint"] for k, d in second.items()})
        for document in first.values():
            self.assertEqual(case_errors(document), [])
            self.assertRegex(document["evidence_fingerprint"], r"^ef1_[0-9a-f]{64}$")

    def test_reordering_does_not_change_fingerprints(self):
        expected = {k: d["evidence_fingerprint"] for k, d in documents(payload_with(rows())).items()}
        for seed in range(4):
            shuffled = rows()
            rng = random.Random(seed)
            rng.shuffle(shuffled)
            for row in shuffled:
                rng.shuffle(row["statements"])
                for block in row["supporting_evidence"] + row["contradicting_evidence"] + row["context_evidence"]:
                    rng.shuffle(block["records"])
                    for record in block["records"]:
                        rng.shuffle(record["event_ids"])
                        rng.shuffle(record["source_timestamps"])
                rng.shuffle(row["limitations"])
            with self.subTest(seed=seed):
                self.assertEqual({k: d["evidence_fingerprint"] for k, d in documents(payload_with(shuffled)).items()}, expected)

    def test_irrelevant_metadata_does_not_change_fingerprints(self):
        expected = {k: d["evidence_fingerprint"] for k, d in documents(payload_with(rows())).items()}
        changed = rows()
        for i, row in enumerate(changed):
            row["finding_id"] = f"{row['finding_type']}:{i:016x}"
            row["text"] = {"en": {"headline": "Generated wording that changed"}}
            row["time_window"] = dict(row["time_window"] or {}, start_date="2030-01-01", end_date_exclusive="2030-02-01")
            row["severity"] = "low"
            row["detector_version"] = "detector-v9"
            row["related"], row["cluster"] = [], None
            for statement in row["statements"]:
                if "editor_name" in statement["params"]:
                    statement["params"]["editor_name"] = "Renamed"
                if "retrieved_at" in statement["params"]:
                    statement["params"]["retrieved_at"] = "2030-01-01T00:00:00Z"
        later = documents(payload_with(changed, snapshot_id="snapshot-later"))
        self.assertEqual({k: d["evidence_fingerprint"] for k, d in later.items()}, expected)
        self.assertNotEqual(next(iter(later.values()))["source_snapshot_id"], snapshots.reasoning_input().snapshot.source_snapshot_id)

    def test_fingerprint_is_verifiable_from_the_case_itself(self):
        document = documents(snapshots.reasoning_input())[DEADLINE_12]
        tampered = copy.deepcopy(document)
        tampered["current_evidence"]["statements"][0]["params"]["current"] = 0.99
        self.assertIn("FINGERPRINT_MISMATCH", {e.split(":")[0] for e in case_errors(tampered)})
        tampered["evidence_fingerprint"] = evidence_fingerprint(canonical_evidence(tampered))
        self.assertEqual(case_errors(tampered), [])


class DeltaTests(unittest.TestCase):
    def setUp(self):
        self.base_rows = rows()
        self.base = documents(payload_with(self.base_rows))[DEADLINE_12]

    def _after(self, mutate) -> dict:
        changed = copy.deepcopy(self.base_rows)
        mutate(changed)
        return documents(payload_with(changed))[DEADLINE_12]

    def _delta(self, after: dict) -> dict:
        return material_delta(canonical_evidence(self.base), canonical_evidence(after))

    def test_no_change_is_an_empty_delta(self):
        delta = self._delta(self.base)
        self.assertTrue(is_empty(delta))
        self.assertEqual(delta["fingerprint_before"], delta["fingerprint_after"])

    def test_material_metric_change(self):
        def mutate(findings):
            for statement in first_change_editor(findings)["statements"]:
                statement["params"]["current"] = 0.8125
        after = self._after(mutate)
        delta = self._delta(after)
        self.assertNotEqual(after["evidence_fingerprint"], self.base["evidence_fingerprint"])
        self.assertTrue(any(c["path"].endswith("late_rate_changed/current") and c["before"] == 0.6875 and c["after"] == 0.8125 for c in delta["changed_values"]),
                        delta["changed_values"])
        self.assertEqual((delta["added_evidence"], delta["removed_evidence"], delta["added_findings"]), ([], [], []))

    def test_upstream_confidence_change(self):
        def mutate(findings):
            first_change_editor(findings)["confidence"]["level"] = "strong"
        delta = self._delta(self._after(mutate))
        self.assertEqual([(c["before"], c["after"]) for c in delta["changed_confidence"]], [("moderate", "strong")])

    def test_evidence_added_and_removed(self):
        def mutate(findings):
            block = first_change_editor(findings)["supporting_evidence"][0]
            block["records"] = block["records"][1:]
        delta = self._delta(self._after(mutate))
        self.assertEqual(len(delta["removed_evidence"]), 1)
        self.assertEqual(delta["removed_evidence"][0]["role"], "supporting")
        reverse = material_delta(canonical_evidence(self._after(mutate)), canonical_evidence(self.base))
        self.assertEqual(len(reverse["added_evidence"]), 1)

    def test_contradictions_added_and_removed(self):
        on_time = next(r for r in self.base["contradicting_findings"])
        self.assertEqual(on_time["direction"], "favourable")

        def remove(findings):
            findings[:] = [r for r in findings if not (r["finding_type"] == "concentration.positive" and r["scope"]["editor_id"] == "editor-label-12")]
        removed = self._delta(self._after(remove))
        self.assertEqual([c["kind"] for c in removed["removed_contradictions"]], ["finding"])
        self.assertIn(on_time["member_key"], removed["removed_findings"])
        added = material_delta(canonical_evidence(self._after(remove)), canonical_evidence(self.base))
        self.assertEqual([c["member_key"] for c in added["added_contradictions"] if c["kind"] == "finding"], [on_time["member_key"]])

        def contradict(findings):
            row = first_change_editor(findings)
            block = copy.deepcopy(row["supporting_evidence"][0])
            block.update(role="contradicting", code="team_late_rate_moved_same_way")
            row["contradicting_evidence"] = [block]
        evidence = self._delta(self._after(contradict))
        self.assertTrue(evidence["added_contradictions"])
        self.assertTrue(all(c["kind"] == "evidence" and c["ref_id"] for c in evidence["added_contradictions"]))

    def test_delta_is_empty_exactly_when_fingerprints_match(self):
        canonical = canonical_evidence(self.base)
        rng = random.Random(7)
        for trial in range(40):
            other = copy.deepcopy(canonical)
            member = rng.choice(sorted(other["findings"]))
            finding = other["findings"][member]
            choice = trial % 5
            if choice == 0 and finding["statements"]:
                key = rng.choice(sorted(finding["statements"]))
                finding["statements"][key]["__perturbed"] = trial
            elif choice == 1 and finding["records"]:
                del finding["records"][rng.choice(sorted(finding["records"]))]
            elif choice == 2:
                finding["limitations"] = [*finding["limitations"], f"new_{trial}"]
            elif choice == 3:
                finding["sample_size"] += 1
            # choice 4: unchanged
            delta = material_delta(canonical, other)
            with self.subTest(trial=trial):
                self.assertEqual(is_empty(delta), evidence_fingerprint(canonical) == evidence_fingerprint(other))

    def test_delta_satisfies_the_contract(self):
        def mutate(findings):
            for statement in first_change_editor(findings)["statements"]:
                statement["params"]["current"] = 0.75
        after = self._after(mutate)
        after["material_delta"] = self._delta(after)
        self.assertEqual(case_errors(after), [])


@requires_db
class ChangeGateTests(unittest.TestCase):
    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.payload = snapshots.reasoning_input()

    def _decisions(self, report) -> dict[str, object]:
        return {d.identity_key: d for d in report.decisions}

    def test_first_run_creates_one_new_result_item_per_case(self):
        report = run_gate(self.payload, self.store, now=T0)
        self.assertEqual({d.action for d in report.decisions}, {GateAction.NEW})
        self.assertEqual({d.reason_code for d in report.decisions}, {FIRST_OBSERVATION})
        self.assertEqual(len(report.llm_work_item_ids), len(report.decisions))
        self.assertEqual({item.kind for item in self.store.work_items(run_id=report.run_id)}, {WorkKind.NEW_RESULT})
        self.assertEqual(self.store.get_run(report.run_id)["status"], "gated")
        self.assertEqual(self.store.get_run(report.run_id)["counts"]["new"], len(report.decisions))

    def test_same_snapshot_twice_creates_zero_work_on_the_second_run(self):
        first = run_gate(self.payload, self.store, now=T0)
        second = run_gate(self.payload, self.store, now=T1)
        self.assertEqual({d.action for d in second.decisions}, {GateAction.UNCHANGED})
        self.assertEqual({d.reason_code for d in second.decisions}, {SAME_EVIDENCE})
        self.assertEqual(second.llm_work_item_ids, ())
        self.assertEqual(self.store.work_items(run_id=second.run_id), [], "no work item of any kind on the second run")
        self.assertEqual(second.counts["llm_work_items"], 0)
        self.assertEqual({d.case_id: d.evidence_fingerprint for d in first.decisions}, {d.case_id: d.evidence_fingerprint for d in second.decisions})
        observations = self.store.observations(run_id=second.run_id)
        self.assertEqual(len(observations), len(first.decisions), "every case has a persisted decision in every run")
        self.assertTrue(all(row["work_item_id"] is None and row["reason_code"] == SAME_EVIDENCE for row in observations))
        self.assertEqual(len(self.store.work_items(open_only=True)), len(first.llm_work_item_ids), "the first run's work is untouched")

    def test_input_reordering_only_is_unchanged(self):
        run_gate(self.payload, self.store, now=T0)
        shuffled = rows()
        random.Random(3).shuffle(shuffled)
        report = run_gate(payload_with(shuffled), self.store, now=T1)
        self.assertEqual({d.action for d in report.decisions}, {GateAction.UNCHANGED})

    def test_changed_evidence_updates_the_same_case(self):
        first = run_gate(self.payload, self.store, now=T0)
        changed = rows()
        for statement in first_change_editor(changed)["statements"]:
            statement["params"]["current"] = 0.8125
        report = run_gate(payload_with(changed, "snapshot-2"), self.store, now=T1)
        decisions = self._decisions(report)
        target = decisions[DEADLINE_12]
        self.assertEqual(target.action, GateAction.UPDATED)
        self.assertEqual(target.reason_code, EVIDENCE_CHANGED)
        self.assertEqual(target.case_id, self._decisions(first)[DEADLINE_12].case_id)
        self.assertNotEqual(target.evidence_fingerprint, target.previous_fingerprint)
        self.assertTrue(target.detail["material_delta"]["changed_values"])
        self.assertEqual({d.action for k, d in decisions.items() if k != DEADLINE_12}, {GateAction.UNCHANGED})
        items = self.store.work_items(case_id=target.case_id)
        self.assertEqual([(i.kind, i.status) for i in items], [(WorkKind.NEW_RESULT, WorkStatus.SUPERSEDED), (WorkKind.NEW_RESULT, WorkStatus.PENDING)],
                         "no result exists yet, so the newer evidence supersedes the pending new-result item")
        observation = next(r for r in self.store.observations(run_id=report.run_id) if r["case_id"] == target.case_id)
        self.assertEqual(observation["material_delta"]["fingerprint_after"], target.evidence_fingerprint)

    def test_update_work_carries_the_delta_from_the_open_results_evidence(self):
        first = run_gate(self.payload, self.store, now=T0)
        case_id = self._decisions(first)[DEADLINE_12].case_id
        with self.store.transaction() as tx:
            item = tx.open_work_item(case_id, requires_llm=True)
            case = case_for_work(tx, item)
            result = factory.result_dict()
            refs = [ref.ref_id for ref in case.current_evidence.references]
            contradicting = [ref.ref_id for ref in case.current_evidence.references if ref.member_key in {f.member_key for f in case.contradicting_findings}]
            for name in ("observation", "interpretation", "management_significance"):
                result[name]["evidence_refs"] = refs[:2]
            result["supporting_evidence"] = [{"statement": "Late rate rose.", "evidence_refs": refs[:3]}]
            result["counter_evidence"] = [{"statement": "Class A is on time.", "evidence_refs": contradicting[:1]}]
            result["suggested_investigations"] = []
            result.update(case_id=case_id, evidence_fingerprint=case.evidence_fingerprint, source_snapshot_id=case.source_snapshot_id)
            tx.create_result(ReasoningResult.from_dict(result), run_id=first.run_id, work_item_id=item.work_item_id)
            tx.set_work_item_status(item.work_item_id, WorkStatus.DONE)
        changed = rows()
        for statement in first_change_editor(changed)["statements"]:
            statement["params"]["current"] = 0.8125
        report = run_gate(payload_with(changed, "snapshot-2"), self.store, now=T1)
        target = self._decisions(report)[DEADLINE_12]
        self.assertEqual(target.work_kind, WorkKind.UPDATE_RESULT)
        with self.store.transaction() as tx:
            item = tx.open_work_item(case_id, requires_llm=True)
            update_case = case_for_work(tx, item)
        self.assertEqual((item.result_id, item.base_result_version, item.fingerprint_before), (result["result_id"], 1, result["evidence_fingerprint"]))
        self.assertEqual(update_case.previous_result_id, result["result_id"])
        self.assertEqual(update_case.previous_result_version, 1)
        assert update_case.material_delta is not None
        self.assertEqual(update_case.material_delta.fingerprint_before, result["evidence_fingerprint"])
        self.assertEqual(update_case.material_delta.fingerprint_after, update_case.evidence_fingerprint)
        self.assertTrue(update_case.material_delta.changed_values)
        back = run_gate(self.payload, self.store, now="2026-09-28T02:10:00Z")
        self.assertEqual(self._decisions(back)[DEADLINE_12].action, GateAction.UPDATED)
        self.assertIsNone(self._decisions(back)[DEADLINE_12].work_item_id, "evidence returned to what the result says: no work")
        self.assertEqual(self.store.work_items(case_id=case_id, open_only=True), [])
        self.assertEqual([i.status for i in self.store.work_items(case_id=case_id) if i.kind == WorkKind.UPDATE_RESULT], [WorkStatus.CANCELLED])

    def test_new_topic_creates_a_new_case(self):
        run_gate(self.payload, self.store, now=T0)
        added = rows()
        extra = copy.deepcopy(next(r for r in added if r["finding_type"] == "editor.speed_pattern"))
        extra["scope"]["editor_id"] = "editor-label-99"
        added.append(extra)
        report = run_gate(payload_with(added), self.store, now=T1)
        new = [d for d in report.decisions if d.action == GateAction.NEW]
        self.assertEqual([d.identity_key for d in new], ["case-identity-v1|editor|editor-label-99|speed"])
        self.assertEqual(new[0].work_kind, WorkKind.NEW_RESULT)

    def test_disappeared_case_is_kept_and_tracked(self):
        first = run_gate(self.payload, self.store, now=T0)
        case_id = self._decisions(first)[DEADLINE_12].case_id
        with self.store.transaction() as tx:
            item = tx.open_work_item(case_id, requires_llm=True)
            case = case_for_work(tx, item)
        result = factory.result_dict()
        refs = [ref.ref_id for ref in case.current_evidence.references]
        contradicting = [ref.ref_id for ref in case.current_evidence.references if ref.member_key in {f.member_key for f in case.contradicting_findings}]
        for name in ("observation", "interpretation", "management_significance"):
            result[name]["evidence_refs"] = refs[:1]
        result["supporting_evidence"] = [{"statement": "Late rate rose.", "evidence_refs": refs[:1]}]
        result["counter_evidence"] = [{"statement": "Class A is on time.", "evidence_refs": contradicting[:1]}]
        result["suggested_investigations"] = []
        result.update(case_id=case_id, evidence_fingerprint=case.evidence_fingerprint, source_snapshot_id=case.source_snapshot_id)
        with self.store.transaction() as tx:
            tx.create_result(ReasoningResult.from_dict(result))
        without = [r for r in rows() if r["scope"].get("editor_id") != "editor-label-12" or r["finding_type"] in ("editor.speed_pattern", "contradiction.hidden_risk")]
        gone = run_gate(payload_with(without), self.store, now=T1)
        decision = self._decisions(gone)[DEADLINE_12]
        self.assertEqual((decision.action, decision.reason_code, decision.work_kind), (GateAction.DISAPPEARED, NOT_IN_SNAPSHOT, WorkKind.LIFECYCLE))
        self.assertEqual(decision.detail["absent_runs"], 1)
        stored = self.store.get_result(result["result_id"])
        self.assertEqual(stored.lifecycle_status, LifecycleStatus.ACTIVE, "a disappeared case never deletes or resolves its result")
        again = run_gate(payload_with(without), self.store, now="2026-09-28T02:10:00Z")
        decision = self._decisions(again)[DEADLINE_12]
        self.assertEqual((decision.action, decision.reason_code, decision.work_item_id), (GateAction.DISAPPEARED, STILL_ABSENT, None))
        self.assertEqual(decision.detail["absent_runs"], 2)
        back = run_gate(self.payload, self.store, now="2026-09-28T03:10:00Z")
        decision = self._decisions(back)[DEADLINE_12]
        self.assertEqual((decision.action, decision.reason_code, decision.work_item_id), (GateAction.UNCHANGED, REAPPEARED_SAME_EVIDENCE, None))
        self.assertEqual(self.store.get_case(case_id).presence, "present")
        self.assertEqual(len(self.store.observations(case_id=case_id)), 4)

    def test_concurrent_gates_serialize(self):
        reports, errors = [], []

        def gate(at: str) -> None:
            try:
                reports.append(run_gate(self.payload, self.store, now=at))
            except Exception as error:  # noqa: BLE001
                errors.append(error)

        threads = [threading.Thread(target=gate, args=(at,)) for at in (T0, T1)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        actions = sorted({d.action for d in report.decisions} for report in reports)
        self.assertEqual(sorted(map(sorted, actions)), [[GateAction.NEW], [GateAction.UNCHANGED]])
        self.assertEqual(len(self.store.work_items()), len(reports[0].decisions))

    def test_historical_replay(self):
        first = run_gate(self.payload, self.store, now=T0)
        later = run_gate(snapshots.reasoning_input(snapshots.shifted(7)), self.store, now=T1)
        before = self._decisions(first)
        after = self._decisions(later)
        persisting = set(before) & {k for k, d in after.items() if d.action != GateAction.DISAPPEARED}
        self.assertTrue(persisting)
        for key in persisting:
            self.assertIn(after[key].action, (GateAction.UNCHANGED, GateAction.UPDATED))
            self.assertEqual(after[key].case_id, before[key].case_id)
        self.assertEqual({d.action for k, d in after.items() if k not in before}, {GateAction.NEW} if set(after) - set(before) else set())
        replay = run_gate(snapshots.reasoning_input(snapshots.shifted(7)), self.store, now="2026-09-28T02:10:00Z")
        self.assertEqual({d.action for d in replay.decisions if d.action != GateAction.DISAPPEARED}, {GateAction.UNCHANGED})
        self.assertEqual(replay.llm_work_item_ids, ())


@requires_db
class CommandTests(unittest.TestCase):
    def _run(self, *args: str, flag: str) -> subprocess.CompletedProcess:
        env = {key: value for key, value in os.environ.items() if not key.startswith("ATLAS_REASONING")}
        env.update(PYTHONPATH=str(ROOT / "src"), ATLAS_REASONING_DATABASE_URL=test_database_url() or "", ATLAS_REASONING_V3=flag)
        return subprocess.run([sys.executable, "-m", "atlas_reasoning", *args], env=env, capture_output=True, text=True, check=False)

    def test_gate_needs_the_flag_and_reports_zero_work_on_rerun(self):
        import shutil
        import tempfile

        from atlas_commander import profile_cli

        fresh_database()
        site = Path(tempfile.mkdtemp(prefix="atlas-gate-cli-"))
        try:
            profile_cli.build_all(snapshots._reconstruction(), snapshots.CONTRACT, site, snapshots.GENERATED_AT)
            refused = self._run("gate", str(site), flag="off")
            self.assertEqual(refused.returncode, 2)
            self.assertIn("ReasoningDisabled", refused.stderr)
            inspected = self._run("inspect", str(site), flag="off")
            self.assertEqual(inspected.returncode, 0, inspected.stderr)
            self.assertEqual(len(json.loads(inspected.stdout)["cases"]), len(prepare_cases(snapshots.reasoning_input(), T0)[1]))
            first = json.loads(self._run("gate", str(site), flag="on").stdout)
            second = json.loads(self._run("gate", str(site), flag="on").stdout)
            self.assertEqual(first["counts"]["new"], len(first["decisions"]))
            self.assertEqual(second["counts"]["llm_work_items"], 0)
            self.assertEqual(second["counts"]["unchanged"], len(second["decisions"]))
            shown = json.loads(self._run("run", second["run_id"], flag="off").stdout)
            self.assertEqual({row["action"] for row in shown["decisions"]}, {"unchanged"})
        finally:
            shutil.rmtree(site, ignore_errors=True)


class MappingDocumentTests(unittest.TestCase):
    def test_case_documents_are_valid_for_every_snapshot(self):
        for at in (snapshots.GENERATED_AT, snapshots.shifted(7)):
            payload = snapshots.reasoning_input(at)
            for candidate in map_findings(payload.findings).candidates:
                with self.subTest(at=at, case=candidate.identity.identity_key):
                    self.assertEqual(case_errors(build_case_document(candidate, payload, T0)), [])


if __name__ == "__main__":
    unittest.main()
