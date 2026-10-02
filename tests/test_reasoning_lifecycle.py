"""Reasoning V3 Phase 09: the deterministic result lifecycle (``REV/09``). Fake model answers only."""

import itertools
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

import psycopg
import reasoning_snapshots as snapshots
from reasoning_db import fresh_database, requires_db, test_database_url
from reasoning_engine_support import DEADLINE_12, changed_rows, engine, payload_with, rows, times, without_deadline_12
from reasoning_fakes import update_answer

from atlas_reasoning import analyst, lifecycle, updater
from atlas_reasoning.change_gate import run_gate
from atlas_reasoning.enums import CaseType, GateAction, LifecycleStatus, WorkKind, WorkStatus
from atlas_reasoning.lifecycle import (
    ABSENT_FOR_CONFIGURED_RUNS,
    CREATED,
    DIRECT_FACT_NO_LONGER_TRUE,
    NOT_IN_SNAPSHOT,
    OBSERVED_AGAIN,
    PATCH_ACCEPTED,
    REAPPEARED,
    REAPPEARED_AFTER_RESOLUTION,
    SUPERSEDED,
    TRANSITIONS,
    UPDATE_SETTLED,
    InvalidTransition,
    LifecyclePolicy,
    check_transition,
    decide,
    policy_from_env,
)
from atlas_reasoning.settings import ReasoningConfigError
from atlas_reasoning.store.repository import ReasoningStore

ROOT = Path(__file__).resolve().parents[1]
DATA_SIGNAL = "case-identity-v1|data_source|monday|data_quality|signal=deadline_not_classifiable"
NEW, ACTIVE, UPDATED, COOLING, RESOLVED, SUPERSEDED_STATUS = (LifecycleStatus.NEW, LifecycleStatus.ACTIVE, LifecycleStatus.UPDATED,
                                                             LifecycleStatus.COOLING, LifecycleStatus.RESOLVED, LifecycleStatus.SUPERSEDED)
POLICY = LifecyclePolicy(cooling_runs_to_resolve=3)
DIRECT = LifecyclePolicy(cooling_runs_to_resolve=3, direct_fact_case_types=frozenset({CaseType.OPEN_WORK_RISK, CaseType.DATA_QUALITY}))


class TransitionTableTests(unittest.TestCase):
    def test_every_pair_outside_the_table_is_refused(self):
        reasons = sorted({reason for allowed in TRANSITIONS.values() for reason in allowed})
        for before, after in itertools.product([None, *LifecycleStatus], LifecycleStatus):
            for reason in reasons:
                allowed = reason in TRANSITIONS.get((before, after), frozenset())
                with self.subTest(before=before, after=after, reason=reason):
                    if allowed:
                        check_transition(before, after, reason)
                    else:
                        with self.assertRaises(InvalidTransition):
                            check_transition(before, after, reason)

    def test_terminal_and_required_paths(self):
        self.assertFalse([pair for pair in TRANSITIONS if pair[0] == SUPERSEDED_STATUS], "superseded is final")
        self.assertFalse([pair for pair in TRANSITIONS if pair[0] in (NEW, ACTIVE, UPDATED) and pair[1] == RESOLVED
                          and TRANSITIONS[pair] != {DIRECT_FACT_NO_LONGER_TRUE}], "only a direct fact resolves without cooling")
        for pair, reason in (((None, NEW), CREATED), ((NEW, ACTIVE), OBSERVED_AGAIN), ((ACTIVE, UPDATED), PATCH_ACCEPTED), ((UPDATED, ACTIVE), UPDATE_SETTLED),
                             ((ACTIVE, COOLING), NOT_IN_SNAPSHOT), ((COOLING, ACTIVE), REAPPEARED), ((COOLING, RESOLVED), ABSENT_FOR_CONFIGURED_RUNS),
                             ((RESOLVED, ACTIVE), REAPPEARED_AFTER_RESOLUTION), ((COOLING, SUPERSEDED_STATUS), SUPERSEDED)):
            self.assertIn(reason, TRANSITIONS[pair])

    def test_database_check_is_the_same_table(self):
        sql = (ROOT / "src/atlas_reasoning/store/migrations/0101_result_lifecycle.sql").read_text()
        listed = set(re.findall(r"'([a-z-]*>[a-z]+:[a-z_]+)'", sql))
        expected = {f"{before.value if before else '-'}>{after.value}:{reason}" for (before, after), allowed in TRANSITIONS.items() for reason in allowed}
        self.assertEqual(listed, expected)

    def test_the_model_has_no_lifecycle_authority(self):
        self.assertNotIn("lifecycle_status", analyst.analyst_output_schema()["properties"])
        self.assertNotIn("lifecycle_status", updater.update_output_schema()["properties"])
        self.assertNotIn("lifecycle_status", updater.update_output_schema()["properties"]["patch"]["properties"])
        self.assertNotIn("superseded_by", updater.update_output_schema()["properties"]["patch"]["properties"])


class DecisionTests(unittest.TestCase):
    def _decide(self, status, action, absent_runs=0, case_type=CaseType.EDITOR_PATTERN, changed=False, policy=POLICY):
        decision = decide(status, action, case_type=case_type, absent_runs=absent_runs, changed_in_this_run=changed, policy=policy)
        return (decision.to, decision.reason) if decision else None

    def test_disappearance_cools_then_resolves_after_the_configured_runs(self):
        for status in (NEW, ACTIVE, UPDATED):
            self.assertEqual(self._decide(status, GateAction.DISAPPEARED, 1), (COOLING, NOT_IN_SNAPSHOT))
        self.assertIsNone(self._decide(COOLING, GateAction.DISAPPEARED, 2))
        self.assertEqual(self._decide(COOLING, GateAction.DISAPPEARED, 3), (RESOLVED, ABSENT_FOR_CONFIGURED_RUNS))
        self.assertEqual(self._decide(COOLING, GateAction.DISAPPEARED, 5, policy=LifecyclePolicy(6)), None)
        self.assertIsNone(self._decide(RESOLVED, GateAction.DISAPPEARED, 9))
        self.assertIsNone(self._decide(SUPERSEDED_STATUS, GateAction.DISAPPEARED, 9))

    def test_direct_facts_resolve_at_once_only_when_approved(self):
        for case_type in CaseType:
            self.assertEqual(self._decide(ACTIVE, GateAction.DISAPPEARED, 1, case_type), (COOLING, NOT_IN_SNAPSHOT), "default: every case cools")
        for case_type in (CaseType.OPEN_WORK_RISK, CaseType.DATA_QUALITY):
            self.assertEqual(self._decide(ACTIVE, GateAction.DISAPPEARED, 1, case_type, policy=DIRECT), (RESOLVED, DIRECT_FACT_NO_LONGER_TRUE))
        for case_type in set(CaseType) - {CaseType.OPEN_WORK_RISK, CaseType.DATA_QUALITY}:
            self.assertEqual(self._decide(ACTIVE, GateAction.DISAPPEARED, 1, case_type, policy=DIRECT), (COOLING, NOT_IN_SNAPSHOT))

    def test_a_card_never_cools_and_resolves_in_the_same_run(self):
        self.assertIsNone(self._decide(COOLING, GateAction.DISAPPEARED, 5, changed=True))
        self.assertIsNone(self._decide(COOLING, GateAction.DISAPPEARED, 1, CaseType.DATA_QUALITY, changed=True, policy=DIRECT))

    def test_presence_reactivates_and_settles_badges(self):
        for action in (GateAction.UNCHANGED, GateAction.UPDATED):
            self.assertEqual(self._decide(COOLING, action), (ACTIVE, REAPPEARED))
            self.assertEqual(self._decide(RESOLVED, action), (ACTIVE, REAPPEARED_AFTER_RESOLUTION))
            self.assertEqual(self._decide(NEW, action), (ACTIVE, OBSERVED_AGAIN))
            self.assertEqual(self._decide(UPDATED, action), (ACTIVE, UPDATE_SETTLED))
            self.assertIsNone(self._decide(NEW, action, changed=True), "a new card keeps its badge for the run that created it")
            self.assertIsNone(self._decide(UPDATED, action, changed=True))
            self.assertIsNone(self._decide(ACTIVE, action))
            self.assertIsNone(self._decide(SUPERSEDED_STATUS, action))

    def test_policy_configuration(self):
        self.assertEqual(policy_from_env({}).to_dict(), {"version": "lifecycle-v1", "cooling_runs_to_resolve": 3, "direct_fact_case_types": []})
        self.assertEqual(policy_from_env({"ATLAS_REASONING_DIRECT_FACT_CASE_TYPES": "open_work_risk, data_quality"}).to_dict()["direct_fact_case_types"],
                         ["data_quality", "open_work_risk"])
        self.assertEqual(policy_from_env({"ATLAS_REASONING_COOLING_RUNS": "5", "ATLAS_REASONING_DIRECT_FACT_CASE_TYPES": "none"}).to_dict()
                         ["cooling_runs_to_resolve"], 5)
        self.assertEqual(policy_from_env({"ATLAS_REASONING_DIRECT_FACT_CASE_TYPES": "data_quality"}).direct_fact_case_types, {CaseType.DATA_QUALITY})
        for env in ({"ATLAS_REASONING_COOLING_RUNS": "1"}, {"ATLAS_REASONING_COOLING_RUNS": "x"}, {"ATLAS_REASONING_DIRECT_FACT_CASE_TYPES": "editor"}):
            with self.subTest(env=env), self.assertRaises(ReasoningConfigError):
                policy_from_env(env)


@requires_db
class LifecycleEngineTests(unittest.TestCase):
    """Cards stay stable across temporary evidence fluctuations."""

    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.engine, self.transport = engine(self.store)
        self.engine.policy = POLICY
        self.t = iter(times(20))
        self.first = self._run(snapshots.reasoning_input())
        self.case_id = self._case(DEADLINE_12)
        self.result_id = self.store.get_result(self._open(self.case_id)).result_id

    def _run(self, payload):
        report = run_gate(payload, self.store, now=next(self.t))
        self.engine.process_run(report.run_id)
        return report

    def _case(self, identity_key):
        return next(d.case_id for d in self.first.decisions if d.identity_key == identity_key)

    def _open(self, case_id):
        with self.store.transaction() as tx:
            return tx.open_result(case_id).result_id

    def _status(self, result_id=None):
        return self.store.get_result(result_id or self.result_id).lifecycle_status

    def _transitions(self, result_id=None):
        return [(row["from_status"], row["to_status"], row["reason_code"]) for row in self.store.lifecycle_transitions(result_id=result_id or self.result_id)]

    def test_new_becomes_active_on_the_next_run(self):
        self.assertEqual(self._status(), NEW)
        second = self._run(snapshots.reasoning_input())
        self.assertEqual(self._status(), ACTIVE)
        rows_ = self.store.lifecycle_transitions(result_id=self.result_id)
        self.assertEqual(self._transitions(), [(None, "new", CREATED), ("new", "active", OBSERVED_AGAIN)])
        self.assertEqual((rows_[0]["run_id"], rows_[1]["run_id"]), (self.first.run_id, second.run_id))
        self.assertEqual(rows_[1]["policy_version"], "lifecycle-v1")
        history = self.store.result_history(self.result_id)
        self.assertEqual([(h["version"], h["change_kind"], h["lifecycle_status"]) for h in history], [(1, "created", "new"), (2, "lifecycle", "active")])
        self.assertEqual(history[1]["document"]["observation"], history[0]["document"]["observation"])

    def test_disappeared_case_cools_persists_and_resolves(self):
        self._run(snapshots.reasoning_input())
        gone = self._run(payload_with(without_deadline_12()))
        self.assertEqual(self._status(), COOLING)
        last = self.store.lifecycle_transitions(result_id=self.result_id)[-1]
        self.assertEqual((last["reason_code"], last["run_id"], last["reason_detail"]["absent_runs"]), (NOT_IN_SNAPSHOT, gone.run_id, 1))
        item = next(i for i in self.store.work_items(case_id=self.case_id) if i.kind == WorkKind.LIFECYCLE)
        self.assertEqual(item.status, WorkStatus.DONE)
        self._run(payload_with(without_deadline_12()))
        self.assertEqual(self._status(), COOLING, "still cooling after two absent runs")
        third = self._run(payload_with(without_deadline_12()))
        self.assertEqual(self._status(), RESOLVED)
        last = self.store.lifecycle_transitions(result_id=self.result_id)[-1]
        self.assertEqual((last["from_status"], last["reason_code"], last["run_id"], last["reason_detail"]["absent_runs"]),
                         ("cooling", ABSENT_FOR_CONFIGURED_RUNS, third.run_id, 3))
        self.assertEqual(self.store.get_result(self.result_id, 1).result_id, self.result_id, "never deleted")

    def test_reappearance_reactivates_the_same_card_without_reasoning(self):
        self._run(payload_with(without_deadline_12()))
        self.assertEqual(self._status(), COOLING)
        calls = len(self.transport.requests)
        self._run(snapshots.reasoning_input())
        self.assertEqual((self._open(self.case_id), self._status()), (self.result_id, ACTIVE))
        self.assertEqual(self._transitions()[-1], ("cooling", "active", REAPPEARED))
        self.assertEqual(len(self.transport.requests), calls, "same evidence: no model call")

    def test_resolved_case_that_returns_reopens_its_card(self):
        for _ in range(3):
            self._run(payload_with(without_deadline_12()))
        self.assertEqual(self._status(), RESOLVED)
        self._run(snapshots.reasoning_input())
        self.assertEqual((self._open(self.case_id), self._status()), (self.result_id, ACTIVE))
        self.assertEqual(self._transitions()[-1], ("resolved", "active", REAPPEARED_AFTER_RESOLUTION))
        with self.store.transaction() as tx:
            self.assertEqual(tx._one("SELECT count(*) AS n FROM reasoning_results WHERE case_id = %s", (self.case_id,))["n"], 1)

    def test_resolved_case_that_returns_with_new_evidence_is_patched_not_regenerated(self):
        for _ in range(3):
            self._run(payload_with(without_deadline_12()))
        report = run_gate(payload_with(changed_rows(), "snapshot-back"), self.store, now=next(self.t))
        self.assertEqual(next(d.work_kind for d in report.decisions if d.case_id == self.case_id), WorkKind.NEW_RESULT,
                         "the gate sees no open result, so it asks for a new one")
        outcome = next(o for o in self.engine.process_run(report.run_id).outcomes if o.case_id == self.case_id)
        self.assertEqual((outcome.result_id, outcome.change_kind), (self.result_id, "patched"))
        self.assertEqual(self._status(), UPDATED)
        self.assertEqual(self._transitions()[-2:], [("resolved", "active", REAPPEARED_AFTER_RESOLUTION), ("active", "updated", PATCH_ACCEPTED)])
        with self.store.transaction() as tx:
            self.assertEqual(tx._one("SELECT count(*) AS n FROM reasoning_results WHERE case_id = %s", (self.case_id,))["n"], 1)

    def test_updated_card_settles_back_to_active(self):
        self._run(snapshots.reasoning_input())
        changed = self._run(payload_with(changed_rows(), "snapshot-2"))
        self.assertEqual(self._status(), UPDATED)
        patch_row = self.store.lifecycle_transitions(result_id=self.result_id)[-1]
        self.assertEqual((patch_row["from_status"], patch_row["to_status"], patch_row["run_id"]), ("active", "updated", changed.run_id))
        self._run(payload_with(changed_rows(), "snapshot-3"))
        self.assertEqual(self._status(), ACTIVE)
        self.assertEqual(self._transitions()[-1], ("updated", "active", UPDATE_SETTLED))

    def test_a_no_change_review_keeps_the_lifecycle(self):
        self._run(snapshots.reasoning_input())
        self.transport.script(self.case_id, lambda payload: update_answer(payload, change={}))
        self._run(payload_with(changed_rows(), "snapshot-2"))
        self.assertEqual(self._status(), ACTIVE)
        self.assertEqual(self.store.result_history(self.result_id)[-1]["change_kind"], "no_change_review")

    def test_direct_fact_case_resolves_immediately_when_approved(self):
        self.engine.policy = DIRECT
        data_case = self._case(DATA_SIGNAL)
        data_result = self._open(data_case)
        self._run(payload_with([r for r in rows() if r["finding_type"] != "data.deadline_not_classifiable"]))
        self.assertEqual(self._status(data_result), RESOLVED)
        self.assertEqual(self._transitions(data_result)[-1], ("new", "resolved", DIRECT_FACT_NO_LONGER_TRUE))
        self.assertEqual(self._status(), ACTIVE, "a card still present only settles")

    def test_supersede_names_the_replacement(self):
        other = self._open(self._case("case-identity-v1|editor|editor-label-12|speed"))
        change = lifecycle.supersede(self.store, self.result_id, by_result_id=other, policy=POLICY, clock=self.engine.clock, detail={"rule": "test"})
        result = self.store.get_result(self.result_id)
        self.assertEqual(result.lifecycle_status, SUPERSEDED_STATUS)
        self.assertEqual((result.superseded_by.result_id, result.superseded_by.case_id), (other, self.store.get_result(other).case_id))
        row = self.store.lifecycle_transitions(result_id=self.result_id)[-1]
        self.assertEqual((row["to_status"], row["superseded_by_result_id"], row["reason_code"], change.to_status), ("superseded", other, SUPERSEDED, "superseded"))
        with self.assertRaises(InvalidTransition):
            lifecycle.supersede(self.store, self.result_id, by_result_id=other, policy=POLICY, clock=self.engine.clock)
        for target in (other, "rr1_" + "9" * 32):
            with self.subTest(target=target), self.assertRaises(InvalidTransition):
                lifecycle.supersede(self.store, other, by_result_id=self.result_id if target == other else target, policy=POLICY, clock=self.engine.clock)
        with self.assertRaises(InvalidTransition):
            lifecycle.supersede(self.store, other, by_result_id=other, policy=POLICY, clock=self.engine.clock)
        self._run(snapshots.reasoning_input())
        self.assertEqual(self._status(), SUPERSEDED_STATUS, "superseded is final")

    def test_an_older_run_never_moves_a_card_backwards(self):
        self._run(payload_with(without_deadline_12()))
        self.assertEqual(self._status(), COOLING)
        self.assertEqual(lifecycle.sweep(self.store, self.first.run_id, policy=POLICY, clock=self.engine.clock), [])
        self.assertEqual(self.engine.process_run(self.first.run_id).lifecycle, ())
        self.assertEqual(self._status(), COOLING)

    def test_sweeping_after_skipped_runs_is_still_idempotent(self):
        self._run(snapshots.reasoning_input())
        for _ in range(3):   # three absent runs gated while the engine was not running
            last = run_gate(payload_with(without_deadline_12()), self.store, now=next(self.t))
        changes = self.engine.process_run(last.run_id).lifecycle
        self.assertIn((self.result_id, "cooling"), [(c.result_id, c.to_status) for c in changes])
        self.assertEqual(lifecycle.sweep(self.store, last.run_id, policy=POLICY, clock=self.engine.clock), [])
        self.assertEqual(self._status(), COOLING, "it cools now and resolves on a later run, never both at once")

    def test_stale_work_never_reopens_a_resolved_card_of_an_absent_case(self):
        for _ in range(3):
            self._run(payload_with(without_deadline_12()))
        self.assertEqual(self._status(), RESOLVED)
        result = self.store.get_result(self.result_id)
        with self.store.transaction() as tx:   # a new_result item left over from before the case disappeared
            document = tx.get_case_evidence(self.case_id, result.evidence_fingerprint)["case_document"]
            item_id = tx.create_work_item(run_id=self.first.run_id, case_id=self.case_id, kind=WorkKind.NEW_RESULT, gate_action=GateAction.NEW,
                                          result_id=None, base_result_version=None, fingerprint_before=None, fingerprint_after=result.evidence_fingerprint,
                                          material_delta=None, case_document=document)
        calls = len(self.transport.requests)
        outcome = next(o for o in self.engine.process_work(self.engine.pending_work()) if o.work_item_id == item_id)
        self.assertEqual((outcome.status, outcome.result_id), ("done", self.result_id))
        self.assertEqual(self._status(), RESOLVED)
        self.assertEqual(len(self.transport.requests), calls)

    def test_sweeping_a_run_twice_changes_nothing_more(self):
        second = self._run(snapshots.reasoning_input())
        versions = len(self.store.result_history(self.result_id))
        self.assertEqual(lifecycle.sweep(self.store, second.run_id, policy=POLICY, clock=self.engine.clock), [])
        self.assertEqual(len(self.store.result_history(self.result_id)), versions)

    def test_the_database_refuses_transitions_outside_the_table(self):
        with self.assertRaises(psycopg.errors.CheckViolation), self.store.transaction() as tx:
            tx._exec("""INSERT INTO reasoning_lifecycle_transitions (transition_id, result_id, case_id, result_version, from_status, to_status, reason_code,
                                                                    policy_version, created_at)
                        VALUES (%s, %s, %s, 1, 'resolved', 'cooling', 'not_in_snapshot', 'x', now())""", ("lt_" + "1" * 32, self.result_id, self.case_id))
        with self.assertRaises(psycopg.errors.IntegrityConstraintViolation), self.store.transaction() as tx:
            tx._exec("DELETE FROM reasoning_lifecycle_transitions WHERE result_id = %s", (self.result_id,))

    def test_lifecycle_debug_command(self):
        self._run(snapshots.reasoning_input())
        env = {key: value for key, value in os.environ.items() if not key.startswith("ATLAS_REASONING")}
        env.update(PYTHONPATH=str(ROOT / "src"), ATLAS_REASONING_DATABASE_URL=test_database_url() or "")
        shown = subprocess.run([sys.executable, "-m", "atlas_reasoning", "lifecycle", self.result_id], env=env, capture_output=True, text=True, check=False)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        output = json.loads(shown.stdout)
        self.assertEqual((output["lifecycle_status"], output["policy"]["cooling_runs_to_resolve"]), ("active", 3))
        self.assertEqual([(row["from_status"], row["to_status"], row["reason_code"]) for row in output["transitions"]],
                         [(None, "new", CREATED), ("new", "active", OBSERVED_AGAIN)])
        self.assertEqual([row["change_kind"] for row in output["versions"]], ["created", "lifecycle"])


if __name__ == "__main__":
    unittest.main()
