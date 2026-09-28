import json
import unittest

import monday_factory as mf

from atlas_commander import cycles as c
from atlas_commander.attribution import UNRESOLVED, TransitionRoleMapping
from atlas_commander.contracts import validate
from atlas_commander.metrics import (
    COMPARABLE,
    FASTER,
    INSUFFICIENT_SAMPLE,
    SLOWER,
    THRESHOLD_NOT_CONFIGURED,
    MetricPolicy,
    classify_deadline,
    deadline_result,
    deadline_summary,
    speed_benchmarks,
)
from atlas_commander.pipeline import reconstruct_cycles
from atlas_commander.runtime import load_contract_version

NOW = "2026-09-28T00:00:00Z"
AHMED, MICHAEL = 12, 13  # Editor Name label IDs in monday-editor-v1.0


def item(item_id, editor=AHMED, video=(4,), start="2026-09-01T10:00:00Z", end="2026-09-01T22:00:00Z", prefix=None, extra=()):
    """One item with the standard Editor/Video Type setup and a first cycle start -> end."""
    p = prefix or f"i{item_id}"
    logs = [
        mf.editor(f"{p}-ed", item_id, "2026-09-01T09:00:00Z", [editor]),
        mf.video_type(f"{p}-vt", item_id, "2026-09-01T09:00:01Z", list(video)),
        mf.status(f"{p}-s0", item_id, "2026-09-01T09:30:00Z", None, "Create File"),
        mf.status(f"{p}-s1", item_id, start, "Create File", "In Progress"),
    ]
    if end:
        logs.append(mf.status(f"{p}-s2", item_id, end, "In Progress", "Ready For Approval"))
    return logs + list(extra)


class CycleFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract_version("1.2.0")
        # Class A (4) is not mapped; use Class A+ (8) as the default resolved cohort.
        cls.policy = MetricPolicy.from_contract(cls.contract)

    def cycles(self, *logs, contract=None):
        return {cycle.monday_item_id: cycle for cycle in reconstruct_cycles(mf.payload(*logs), contract or self.contract).cycles}

    def with_minimum(self, minimum):
        contract = json.loads(json.dumps(self.contract))
        contract["speed_benchmark"]["minimum_editor_sample_size"] = minimum
        return MetricPolicy.from_contract(contract)


class WorkCycleTests(CycleFixture):
    def test_duration_is_elapsed_clock_time_from_first_in_progress_to_first_ready(self):
        cycle = self.cycles(*item("1", video=(8,)))["1"]
        self.assertEqual(cycle.state, c.COMPLETED)
        self.assertEqual(cycle.duration_seconds, 12 * 3600)  # 10:00 -> 22:00, nights are not excluded
        contract = cycle.to_contract()
        self.assertEqual(validate(contract, "work-cycle.schema.json"), ["MISSING_REQUESTED_ETA"])  # schema-valid; ETA gap is a data-quality code
        self.assertEqual((contract["editor_id"], contract["video_type"]), ("editor-label-12", "8"))

    def test_weekends_are_not_excluded(self):
        cycle = self.cycles(*item("1", video=(8,), start="2026-09-04T17:00:00Z", end="2026-09-07T09:00:00Z"))["1"]  # Fri -> Mon
        self.assertEqual(cycle.duration_seconds, 64 * 3600)

    def test_only_first_completed_cycle_is_measured_and_later_cycles_are_retained(self):
        later = [
            mf.status("x-3", "1", "2026-09-02T09:00:00Z", "Ready For Approval", "In Progress"),
            mf.status("x-4", "1", "2026-09-02T15:00:00Z", "In Progress", "Ready For Approval"),
            mf.status("x-5", "1", "2026-09-03T09:00:00Z", "Ready For Approval", "Sent"),
            mf.status("x-6", "1", "2026-09-04T09:00:00Z", "Sent", "Revisions"),
            mf.status("x-7", "1", "2026-09-04T12:00:00Z", "Revisions", "Ready For Approval"),
        ]
        cycle = self.cycles(*item("1", video=(8,), extra=later))["1"]
        self.assertEqual(cycle.duration_seconds, 12 * 3600)
        self.assertEqual(cycle.ready_for_approval_event["event_id"], "i1-s2")
        self.assertEqual(cycle.post_cycle_event_ids, ["x-3", "x-4", "x-5", "x-6", "x-7"])
        self.assertEqual(cycle.later_ready_for_approval_event_ids, ["x-4", "x-7"])
        self.assertEqual(cycle.revision_context["client_revision_events"], 1)

    def test_repeated_in_progress_stays_in_the_original_cycle(self):
        extra = [mf.status("r-1", "1", "2026-09-01T12:00:00Z", "In Progress", "Create File"),
                 mf.status("r-2", "1", "2026-09-01T13:00:00Z", "Create File", "In Progress")]
        cycle = self.cycles(*item("1", video=(8,), end="2026-09-01T20:00:00Z", extra=extra))["1"]
        self.assertEqual(cycle.duration_seconds, 10 * 3600)
        self.assertIn(c.REPEATED_IN_PROGRESS, cycle.flags)

    def test_open_cycle_is_retained_and_excluded(self):
        cycle = self.cycles(*item("1", video=(8,), end=None))["1"]
        self.assertEqual((cycle.state, cycle.exclusions), (c.OPEN, [c.OPEN_CYCLE]))
        self.assertIsNone(cycle.to_contract())

    def test_ready_without_start_is_flagged_not_measured(self):
        logs = [mf.status("a", "1", "2026-09-01T09:00:00Z", None, "Create File"),
                mf.status("b", "1", "2026-09-01T10:00:00Z", "Create File", "Ready For Approval")]
        cycle = self.cycles(*logs)["1"]
        self.assertEqual(cycle.state, c.INVALID)
        self.assertIn(c.MISSING_IN_PROGRESS, cycle.exclusions)

    def test_duplicate_and_undone_transitions_are_ignored_for_timing(self):
        extra = [mf.status("dup", "1", "2026-09-01T11:00:00Z", "In Progress", "In Progress"),
                 mf.status("undo", "1", "2026-09-01T12:00:00Z", "In Progress", "Ready For Approval", undo=True)]
        cycle = self.cycles(*item("1", video=(8,), extra=extra))["1"]
        self.assertEqual(cycle.ready_for_approval_event["event_id"], "i1-s2")
        self.assertIn(c.DUPLICATE_TRANSITION, cycle.flags)
        self.assertIn(c.UNDO_ACTION_IGNORED, cycle.flags)

    def test_unknown_status_is_quarantined_and_flagged(self):
        result = reconstruct_cycles(mf.payload(*item("1", video=(8,), extra=[mf.status("u", "1", "2026-09-02T00:00:00Z", "Ready For Approval", "Brand New")])), self.contract)
        self.assertEqual([entry["reason"] for entry in result.quarantined_status_logs], ["UNKNOWN_STATUS"])
        self.assertIn(c.UNMAPPED_STATUS_IN_HISTORY, result.cycles[0].flags)

    def test_editor_comes_from_editor_column_not_the_actor(self):
        logs = item("1", video=(8,))
        cycle = self.cycles(*logs)["1"]
        self.assertEqual(cycle.editor_id, "editor-label-12")
        self.assertEqual(cycle.editor_event_id, "i1-ed")

    def test_editor_quarantine_cases(self):
        cases = {
            "missing-history": ([log for log in item("1", video=(8,)) if log["id"] != "i1-ed"], c.MISSING_EDITOR_EVENT),
            "unmapped": (item("1", editor=4, video=(8,)), "UNMAPPED_EDITOR"),
            "shared-account-id": (item("1", editor=99154021, video=(8,)), "UNMAPPED_EDITOR"),
            "two-editors": ([mf.editor("i1-ed", "1", "2026-09-01T09:00:00Z", [AHMED, MICHAEL]), *item("1", video=(8,))[1:]], "AMBIGUOUS_EDITOR"),
            "changed-within": (item("1", video=(8,), extra=[mf.editor("chg", "1", "2026-09-01T15:00:00Z", [MICHAEL])]), c.EDITOR_CHANGED_WITHIN_CYCLE),
        }
        for name, (logs, reason) in cases.items():
            with self.subTest(name):
                cycle = self.cycles(*logs)["1"]
                self.assertIsNone(cycle.editor_id)
                self.assertIn(reason, cycle.exclusions)
                self.assertIsNone(cycle.to_contract())

    def test_video_type_is_exact_and_quarantined_when_unknown(self):
        # 13 is not a label ID on the live board; it must never be guessed.
        cycles = self.cycles(*item("1", video=(8,)), *item("2", video=(5, 8)), *item("3", video=(13,)), *item("4", video=(8, 13)), *item("5", video=(4,)))
        self.assertEqual((cycles["1"].cohort_key, cycles["2"].cohort_key, cycles["5"].cohort_key), ("8", "5:8", "4"))
        for key in ("3", "4"):
            self.assertIsNone(cycles[key].cohort_key)
            self.assertIn("UNMAPPED_VIDEO_TYPE", cycles[key].exclusions)
            self.assertIn("id:13", cycles[key].video_type.unmapped)

    def test_video_type_change_after_ready_is_flagged(self):
        cycle = self.cycles(*item("1", video=(8,), extra=[mf.video_type("vt2", "1", "2026-09-03T00:00:00Z", [5])]))["1"]
        self.assertEqual(cycle.cohort_key, "8")
        self.assertIn(c.VIDEO_TYPE_CHANGED_AFTER_READY_FOR_APPROVAL, cycle.flags)


def items_payload(item_id, date, time, changed_at=None):
    value = {"date": date, "time": time}
    if changed_at:
        value["changed_at"] = changed_at
    return {"items": [{"id": item_id, "board": {"id": mf.BOARD}, "column_values": [{"id": mf.ETA, "type": "date", "value": json.dumps(value), "text": ""}]}]}


class DeadlineTests(CycleFixture):
    def run_pipeline(self, *eta_logs, items=None, ingestion=None, extra=()):
        logs = item("1", video=(8,), end="2026-09-07T15:00:00Z", start="2026-09-07T10:00:00Z", extra=(*eta_logs, *extra))
        return reconstruct_cycles(mf.payload(*logs), self.contract, items_payload=items, ingestion=ingestion).cycles[0]

    def deadline(self, *eta_logs, **kwargs):
        cycle = self.run_pipeline(*eta_logs, **kwargs)
        return cycle, deadline_result(cycle, self.policy, NOW)

    def test_latest_logged_eta_is_used_even_when_changed_after_ready_for_approval(self):
        # Ready at Monday 15:00; ETA was 14:00 at that moment, then changed to 17:00 -> 2 hours EARLY.
        _, result = self.deadline(mf.eta("e1", "1", "2026-09-06T00:00:00Z", "2026-09-07", "14:00:00"),
                                  mf.eta("e2", "1", "2026-09-07T16:00:00Z", "2026-09-07", "17:00:00"))
        metric = result["metric"]
        self.assertEqual((result["delta_seconds"], metric["delta_seconds"], metric["result"]), (-7200, -7200, "early"))
        self.assertEqual(metric["requested_eta"], "2026-09-07T17:00:00Z")
        values = metric["evidence"]["source_values"]
        self.assertEqual(values["requested_eta_source"], "activity_log")
        self.assertEqual([entry["event_id"] for entry in values["requested_eta_history"]], ["e1", "e2"])
        self.assertEqual([entry["requested_eta"] for entry in values["requested_eta_history"]], ["2026-09-07T14:00:00Z", "2026-09-07T17:00:00Z"])
        self.assertIn("e2", metric["evidence"]["event_ids"])
        self.assertEqual(validate(metric, "deadline-metric-v1.1.schema.json"), [])

    def test_current_item_snapshot_is_the_latest_eta_through_the_pipeline(self):
        # Ready For Approval at 15:00; history holds an earlier 14:00 ETA; Monday's current item value is 18:00.
        cycle, result = self.deadline(mf.eta("e1", "1", "2026-09-06T00:00:00Z", "2026-09-07", "14:00:00"),
                                      items=items_payload("1", "2026-09-07", "18:00:00", changed_at="2026-09-07T20:00:00.000Z"),
                                      ingestion={"retrieved_at": NOW})
        metric = result["metric"]
        self.assertEqual((metric["requested_eta"], metric["delta_seconds"], metric["result"]), ("2026-09-07T18:00:00Z", -3 * 3600, "early"))
        self.assertIn(c.SNAPSHOT_DIFFERS_FROM_LOG, cycle.flags)
        history = metric["evidence"]["source_values"]["requested_eta_history"]
        self.assertEqual([(entry["source"], entry["requested_eta"]) for entry in history],
                         [("activity_log", "2026-09-07T14:00:00Z"), ("item_snapshot", "2026-09-07T18:00:00Z")])
        snapshot = history[-1]
        # No timestamp is invented for the snapshot: only Monday's own changed_at and the ingestion time are recorded.
        self.assertIsNone(snapshot["occurred_at"])
        self.assertEqual((snapshot["source_changed_at"], snapshot["retrieved_at"]), ("2026-09-07T20:00:00.000Z", NOW))
        self.assertEqual(snapshot["event_id"], f"item-snapshot:1:{mf.ETA}@{NOW}")
        self.assertIn(snapshot["event_id"], metric["evidence"]["event_ids"])
        self.assertEqual(metric["evidence"]["source_values"]["requested_eta_source"], "item_snapshot")

    def test_matching_snapshot_is_not_flagged_and_snapshot_alone_is_enough(self):
        cycle = self.run_pipeline(mf.eta("e1", "1", "2026-09-06T00:00:00Z", "2026-09-07", "14:00:00"), items=items_payload("1", "2026-09-07", "14:00:00"))
        self.assertNotIn(c.SNAPSHOT_DIFFERS_FROM_LOG, cycle.flags)
        _, result = self.deadline(items=items_payload("1", "2026-09-07", "16:00:00"))
        self.assertEqual((result["delta_seconds"], result["metric"]["result"]), (-3600, "early"))

    def test_empty_current_snapshot_means_no_eta_even_if_logs_had_one(self):
        empty = {"items": [{"id": "1", "board": {"id": mf.BOARD}, "column_values": [{"id": mf.ETA, "type": "date", "value": None, "text": ""}]}]}
        cycle, result = self.deadline(mf.eta("e1", "1", "2026-09-06T00:00:00Z", "2026-09-07", "14:00:00"), items=empty)
        self.assertIsNone(result)
        self.assertEqual(cycle.requested_eta_issue, "MISSING_REQUESTED_ETA")
        self.assertIn(c.SNAPSHOT_DIFFERS_FROM_LOG, cycle.flags)

    def test_history_is_never_claimed_complete_without_ingestion_proof(self):
        eta = mf.eta("e1", "1", "2026-09-06T00:00:00Z", "2026-09-07", "17:00:00")
        window = {"since": "2026-09-01T00:00:00Z", "until": "2026-09-28T00:00:00Z"}
        default = self.run_pipeline(eta).requested_eta_history_coverage
        self.assertEqual(default["status"], c.OBSERVED_IN_INGESTED_EVIDENCE)
        windowed = self.run_pipeline(eta, ingestion={"activity_log_window": window}).requested_eta_history_coverage
        self.assertEqual((windowed["status"], windowed["activity_log_window"]), (c.OBSERVED_IN_INGESTED_EVIDENCE, window))
        other = self.run_pipeline(eta, ingestion={"activity_log_window": window, "complete_history_item_ids": ["2"]}).requested_eta_history_coverage
        self.assertEqual(other["status"], c.OBSERVED_IN_INGESTED_EVIDENCE)
        proven = self.run_pipeline(eta, ingestion={"activity_log_window": window, "complete_history_item_ids": ["1"],
                                                   "complete_history_basis": "window starts before item creation; all pages read"})
        self.assertEqual(proven.requested_eta_history_coverage["status"], c.COMPLETE)
        _, result = self.deadline(eta)
        self.assertEqual(result["metric"]["evidence"]["source_values"]["requested_eta_history_coverage"]["status"], c.OBSERVED_IN_INGESTED_EVIDENCE)

    def test_early_on_time_late_are_distinct_with_no_tolerance(self):
        cases = (("14:59:59", 1, "late"), ("15:00:00", 0, "on_time"), ("15:00:01", -1, "early"), ("14:30:00", 1800, "late"))
        for time, delta, label in cases:
            with self.subTest(eta=time):
                _, result = self.deadline(mf.eta("e1", "1", "2026-09-06T00:00:00Z", "2026-09-07", time))
                self.assertEqual((result["delta_seconds"], result["metric"]["result"]), (delta, label))
                self.assertEqual(classify_deadline(delta), label)

    def test_summary_counts_and_rates(self):
        results = [{"delta_seconds": delta} for delta in (-7200, -60, 0, 1800)]
        summary = deadline_summary(results, [])
        self.assertEqual((summary["evaluated"], summary["early"], summary["on_time"], summary["late"]), (4, 2, 1, 1))
        self.assertEqual((summary["early_rate"], summary["on_time_rate"], summary["late_rate"]), (0.5, 0.25, 0.25))
        self.assertEqual((summary["median_delta_seconds"], summary["on_time_tolerance"]), (-30, "none"))
        empty = deadline_summary([], [])
        self.assertEqual((empty["evaluated"], empty["early_rate"], empty["median_delta_seconds"]), (0, None, None))

    def test_missing_or_date_only_eta_yields_no_result(self):
        cycle, result = self.deadline()
        self.assertIsNone(result)
        self.assertEqual(cycle.requested_eta_issue, "MISSING_REQUESTED_ETA")
        cycle, result = self.deadline(mf.eta("e1", "1", "2026-09-06T00:00:00Z", "2026-09-07", "14:00:00"),
                                      mf.eta("e2", "1", "2026-09-07T16:00:00Z", "2026-09-08", None))
        self.assertIsNone(result)
        self.assertEqual(cycle.requested_eta_issue, "REQUESTED_ETA_DATE_ONLY")
        summary = deadline_summary([], [cycle])
        self.assertEqual(summary["not_evaluated"][0]["reasons"], ["REQUESTED_ETA_DATE_ONLY"])
        cycle, result = self.deadline(items=items_payload("1", "2026-09-08", None))
        self.assertIsNone(result)
        self.assertEqual(cycle.requested_eta_issue, "REQUESTED_ETA_DATE_ONLY")

    def test_revisions_do_not_change_the_deadline_result(self):
        eta = mf.eta("e1", "1", "2026-09-06T00:00:00Z", "2026-09-07", "17:00:00")
        _, plain = self.deadline(eta)
        revisions = [mf.status("r1", "1", "2026-09-08T00:00:00Z", "Ready For Approval", "Revisions"),
                     mf.status("r2", "1", "2026-09-08T05:00:00Z", "Revisions", "Ready For Approval")]
        _, revised = self.deadline(eta, extra=revisions)
        self.assertEqual((plain["delta_seconds"], plain["metric"]["result"]), (revised["delta_seconds"], revised["metric"]["result"]))


class SpeedBenchmarkTests(CycleFixture):
    def team(self):
        return list(self.cycles(
            *item("1", editor=AHMED, video=(8,), end="2026-09-01T14:00:00Z"),   # 4h
            *item("2", editor=AHMED, video=(8,), end="2026-09-01T16:00:00Z"),   # 6h
            *item("3", editor=MICHAEL, video=(8,), end="2026-09-01T20:00:00Z"),  # 10h
            *item("4", editor=MICHAEL, video=(8,), end="2026-09-01T22:00:00Z"),  # 12h
            *item("5", editor=MICHAEL, video=(5, 8), end="2026-09-01T11:00:00Z"),  # 1h, other cohort
            *item("6", editor=AHMED, video=(5, 8), end="2026-09-02T10:00:00Z"),  # 24h, other cohort
        ).values())

    def test_cohorts_are_exact_and_never_mixed(self):
        result = speed_benchmarks("editor-label-12", self.team(), self.with_minimum(2), NOW)
        by_key = {cohort["cohort_key"]: cohort for cohort in result["cohorts"]}
        self.assertEqual(set(by_key), {"8", "5:8"})
        self.assertEqual((by_key["8"]["team_sample_size"], by_key["8"]["team_median_seconds"]), (4, 8 * 3600))
        self.assertEqual((by_key["5:8"]["team_sample_size"], by_key["5:8"]["team_median_seconds"]), (2, int(12.5 * 3600)))
        for metric in result["metrics"]:
            self.assertEqual(metric["video_type"], metric["cohort_video_type"])
            self.assertEqual(validate(metric, "speed-metric.schema.json"), [])

    def test_no_conclusion_until_minimum_sample_is_configured(self):
        result = speed_benchmarks("editor-label-12", self.team(), self.policy, NOW)
        self.assertIsNone(self.policy.minimum_editor_sample_size)
        for cohort in result["cohorts"]:
            self.assertEqual((cohort["comparison_status"], cohort["conclusion"]), (THRESHOLD_NOT_CONFIGURED, None))
            self.assertGreater(cohort["editor_sample_size"], 0)
            self.assertIsNotNone(cohort["editor_median_seconds"])

    def test_insufficient_sample_reports_raw_values_without_conclusion(self):
        cohorts = {cohort["cohort_key"]: cohort for cohort in speed_benchmarks("editor-label-12", self.team(), self.with_minimum(2), NOW)["cohorts"]}
        self.assertEqual((cohorts["5:8"]["comparison_status"], cohorts["5:8"]["conclusion"]), (INSUFFICIENT_SAMPLE, None))
        self.assertEqual((cohorts["8"]["comparison_status"], cohorts["8"]["conclusion"]), (COMPARABLE, FASTER))
        self.assertEqual(cohorts["8"]["editor_minus_team_median_seconds"], -3 * 3600)
        michael = {cohort["cohort_key"]: cohort for cohort in speed_benchmarks("editor-label-13", self.team(), self.with_minimum(2), NOW)["cohorts"]}
        self.assertEqual(michael["8"]["conclusion"], SLOWER)

    def test_later_cycles_never_enter_speed(self):
        later = [mf.status("x-3", "1", "2026-09-02T09:00:00Z", "Ready For Approval", "In Progress"),
                 mf.status("x-4", "1", "2026-09-05T09:00:00Z", "In Progress", "Ready For Approval")]
        cycles = list(self.cycles(*item("1", video=(8,), end="2026-09-01T14:00:00Z", extra=later)).values())
        cohort = speed_benchmarks("editor-label-12", cycles, self.with_minimum(1), NOW)["cohorts"][0]
        self.assertEqual((cohort["editor_sample_size"], cohort["editor_median_seconds"]), (1, 4 * 3600))

    def test_excluded_cycles_do_not_enter_speed(self):
        cycles = list(self.cycles(*item("1", video=(8,)), *item("2", video=(8,), end=None), *item("3", editor=4, video=(8,))).values())
        cohort = speed_benchmarks("editor-label-12", cycles, self.policy, NOW)["cohorts"][0]
        self.assertEqual((cohort["team_sample_size"], cohort["editor_cycle_ids"]), (1, [f"cycle:{mf.BOARD}:1"]))

    def test_minimum_sample_policy_is_validated(self):
        for bad in (0, -1, 1.5, True, "3"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.with_minimum(bad)


class TransitionRoleTests(CycleFixture):
    def test_roles_follow_the_versioned_table_and_ignore_the_shared_account(self):
        mapping = TransitionRoleMapping.from_contract(self.contract)
        logs = item("1", video=(8,), extra=[
            mf.status("t3", "1", "2026-09-02T00:00:00Z", "Ready For Approval", "Sent"),
            mf.status("t4", "1", "2026-09-03T00:00:00Z", "Sent", "Revisions"),
            mf.status("t5", "1", "2026-09-03T05:00:00Z", "Revisions", "Ready For Approval"),
            mf.status("t6", "1", "2026-09-03T06:00:00Z", "Ready For Approval", "In Progress"),
            mf.status("t7", "1", "2026-09-03T07:00:00Z", "In Progress", "Ready For Approval", user="105392408"),
            mf.status("t8", "1", "2026-09-03T08:00:00Z", "Ready For Approval", "Ready To Send"),
        ])
        roles = {record["event_id"]: record for record in reconstruct_cycles(mf.payload(*logs), self.contract).transitions}
        self.assertEqual({key: roles[key]["role"] for key in ("i1-s1", "i1-s2", "t3", "t4", "t5", "t6", "t7", "t8")}, {
            "i1-s1": UNRESOLVED, "i1-s2": "editor", "t3": "production_manager", "t4": "editor", "t5": "editor",
            "t6": "editor", "t7": "editor", "t8": UNRESOLVED})
        self.assertTrue(roles["i1-s2"]["actor_is_shared_account"])
        self.assertFalse(roles["t7"]["actor_is_shared_account"])
        self.assertEqual(roles["t3"]["mapping_version"], mapping.mapping_version)

    def test_conflicting_rules_are_rejected(self):
        contract = json.loads(json.dumps(self.contract))
        contract["transition_roles"]["rules"].append({"from": "In Progress", "to": "Ready For Approval", "role": "production_manager"})
        with self.assertRaises(ValueError):
            TransitionRoleMapping.from_contract(contract)


class ManagementDecisionRegressionTests(CycleFixture):
    """D1-D4 (Waset management, 2026-09-28) through the public reconstruct_cycles() path."""

    def test_d1_latest_eta_from_activity_history(self):
        logs = item("1", video=(8,), start="2026-09-07T10:00:00Z", end="2026-09-07T15:00:00Z", extra=[
            mf.eta("e1", "1", "2026-09-06T00:00:00Z", "2026-09-07", "14:00:00"),
            mf.eta("e2", "1", "2026-09-07T16:00:00Z", "2026-09-07", "17:00:00")])
        cycle = reconstruct_cycles(mf.payload(*logs), self.contract).cycles[0]
        self.assertLess(c.parse_time(cycle.ready_for_approval_at), c.parse_time("2026-09-07T16:00:00Z"))  # ETA change came after RFA
        self.assertEqual(deadline_result(cycle, self.policy, NOW)["metric"]["result"], "early")

    def test_d1_latest_eta_from_current_item_snapshot(self):
        logs = item("1", video=(8,), start="2026-09-07T10:00:00Z", end="2026-09-07T15:00:00Z",
                    extra=[mf.eta("e1", "1", "2026-09-06T00:00:00Z", "2026-09-07", "14:00:00")])
        without = reconstruct_cycles(mf.payload(*logs), self.contract).cycles[0]
        self.assertEqual(deadline_result(without, self.policy, NOW)["metric"]["result"], "late")
        cycle = reconstruct_cycles(mf.payload(*logs), self.contract, items_payload=items_payload("1", "2026-09-07", "17:00:00")).cycles[0]
        result = deadline_result(cycle, self.policy, NOW)
        self.assertEqual((result["delta_seconds"], result["metric"]["result"]), (-7200, "early"))

    def test_d2_only_first_completed_cycle_contributes_to_speed(self):
        later = [mf.status("x-3", "1", "2026-09-02T09:00:00Z", "Ready For Approval", "In Progress"),
                 mf.status("x-4", "1", "2026-09-02T10:00:00Z", "In Progress", "Ready For Approval")]
        cycles = reconstruct_cycles(mf.payload(*item("1", video=(8,), end="2026-09-01T14:00:00Z", extra=later)), self.contract).cycles
        self.assertEqual(len(cycles), 1)
        cohort = speed_benchmarks("editor-label-12", cycles, self.with_minimum(1), NOW)["cohorts"][0]
        self.assertEqual((cohort["editor_sample_size"], cohort["editor_median_seconds"]), (1, 4 * 3600))
        self.assertEqual(cycles[0].later_ready_for_approval_event_ids, ["x-4"])

    def test_d3_duration_is_elapsed_clock_time(self):
        night = reconstruct_cycles(mf.payload(*item("1", video=(8,), start="2026-09-01T10:00:00Z", end="2026-09-01T22:00:00Z")), self.contract).cycles[0]
        weekend = reconstruct_cycles(mf.payload(*item("2", video=(8,), start="2026-09-04T17:00:00Z", end="2026-09-07T09:00:00Z")), self.contract).cycles[0]
        self.assertEqual((night.duration_seconds, weekend.duration_seconds), (12 * 3600, 64 * 3600))

    def test_d4_no_conclusion_until_threshold_configured_and_met(self):
        logs = [*item("1", editor=AHMED, video=(8,), end="2026-09-01T12:00:00Z"), *item("2", editor=MICHAEL, video=(8,), end="2026-09-01T20:00:00Z")]
        cycles = reconstruct_cycles(mf.payload(*logs), self.contract).cycles
        unset = speed_benchmarks("editor-label-12", cycles, self.policy, NOW)["cohorts"][0]
        self.assertEqual((unset["comparison_status"], unset["conclusion"], unset["editor_sample_size"]), (THRESHOLD_NOT_CONFIGURED, None, 1))
        unmet = speed_benchmarks("editor-label-12", cycles, self.with_minimum(2), NOW)["cohorts"][0]
        self.assertEqual((unmet["comparison_status"], unmet["conclusion"]), (INSUFFICIENT_SAMPLE, None))
        met = speed_benchmarks("editor-label-12", cycles, self.with_minimum(1), NOW)["cohorts"][0]
        self.assertEqual((met["comparison_status"], met["conclusion"]), (COMPARABLE, FASTER))


class ContractVersionTests(unittest.TestCase):
    def test_v12_preserves_v11_registries_and_extends_video_types_without_renumbering(self):
        v11, v12 = load_contract_version("1.1.0"), load_contract_version("1.2.0")
        for key in ("status_mapping_version", "status_mapping", "caption_states", "cycle_boundaries", "editor_attribution", "quarantine_policy"):
            self.assertEqual(v11[key], v12[key], key)
        old, new = v11["video_type_cohorts"], v12["video_type_cohorts"]
        self.assertEqual(new["mapping_version"], "monday-video-type-v1.2")
        self.assertEqual({label: new["label_to_id"][label] for label in old["label_to_id"]}, old["label_to_id"])
        for key in ("multi_select_policy", "cohort_key", "comparison_policy", "unresolved_policy"):
            self.assertEqual(old[key], new[key], key)
        self.assertEqual(len(set(new["label_to_id"].values())), len(new["label_to_id"]))  # one label per ID, nothing merged
        self.assertIsNone(v12["speed_benchmark"]["minimum_editor_sample_size"])
        self.assertEqual(v12["deadline"]["requested_eta_selection"], "latest-available-requested-eta")

    def test_video_type_versions_resolve_label_4_differently(self):
        from atlas_commander.runtime import resolve_contract_video_type
        self.assertIsNone(resolve_contract_video_type(ids=[4], config=load_contract_version("1.1.0")).cohort_key)
        resolved = resolve_contract_video_type(ids=[10, 4], config=load_contract_version("1.2.0"))
        self.assertEqual((resolved.cohort_key, resolved.canonical_labels, resolved.mapping_version), ("10:4", ("2*", "Class A"), "monday-video-type-v1.2"))
        self.assertNotEqual(resolved.cohort_key, resolve_contract_video_type(ids=[4], config=load_contract_version("1.2.0")).cohort_key)


if __name__ == "__main__":
    unittest.main()
