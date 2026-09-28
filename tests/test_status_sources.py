"""Runtime rules found by running the pipeline on real Monday history (contract 1.2.0).

Every test goes through the public ``reconstruct_cycles()`` path.
"""

import json
import unittest

import monday_factory as mf

from atlas_commander import cycles as c
from atlas_commander.metrics import NOT_CLASSIFIABLE_ETA_PRECISION, MetricPolicy, deadline_result, deadline_summary
from atlas_commander.normalization import normalize_events, status_mapping_config
from atlas_commander.pipeline import reconstruct_cycles
from atlas_commander.runtime import load_contract_version

NOW = "2026-09-28T00:00:00Z"
AHMED = 12


def base_logs(item_id, start="2026-09-01T10:00:00Z", end="2026-09-01T22:00:00Z", video=(8,), extra=()):
    logs = [
        mf.editor(f"{item_id}-ed", item_id, "2026-09-01T09:00:00Z", [AHMED]),
        mf.video_type(f"{item_id}-vt", item_id, "2026-09-01T09:00:01Z", list(video)),
        mf.status(f"{item_id}-s0", item_id, "2026-09-01T09:30:00Z", None, "Create File"),
        mf.status(f"{item_id}-s1", item_id, start, "Create File", "In Progress"),
    ]
    if end:
        logs.append(mf.status(f"{item_id}-s2", item_id, end, "In Progress", "Ready For Approval"))
    return logs + list(extra)


class SourceFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract_version("1.2.0")
        cls.v11 = load_contract_version("1.1.0")

    def run_pipeline(self, *logs, contract=None, **kwargs):
        return reconstruct_cycles(mf.payload(*logs), contract or self.contract, **kwargs)

    def cycle(self, *logs, **kwargs):
        return self.run_pipeline(*logs, **kwargs).cycles[0]


class StatusAliasTests(SourceFixture):
    def test_renamed_label_with_same_index_is_normalized(self):
        logs = base_logs("1", extra=[mf.status("a1", "1", "2026-09-02T00:00:00Z", "Ready For Approval", "Ready To Sent"),
                                     mf.status("a2", "1", "2026-09-02T01:00:00Z", "Ready To Sent", "Sent")])
        result = self.run_pipeline(*logs)
        by_id = {event["event_id"]: event for event in result.status_events}
        self.assertEqual((by_id["a1"]["to_status"], by_id["a1"]["raw_to_status"]), ("Ready To Send", "Ready To Sent"))
        self.assertEqual((by_id["a2"]["from_status"], by_id["a2"]["raw_from_status"]), ("Ready To Send", "Ready To Sent"))
        self.assertEqual(by_id["a1"]["mapping_version"], "monday-status-v1.1")
        self.assertEqual(result.quarantined_status_logs, [])

    def test_alias_requires_the_matching_label_index(self):
        logs = base_logs("1", extra=[mf.status("a1", "1", "2026-09-02T00:00:00Z", "Ready For Approval", "Ready To Sent", after_index=8)])
        result = self.run_pipeline(*logs)
        self.assertEqual([(entry["reason"], entry["raw_source"]["id"]) for entry in result.quarantined_status_logs], [("UNKNOWN_STATUS", "a1")])

    def test_contract_11_keeps_the_v10_quarantine_behavior(self):
        from atlas_commander.monday_source import status_log_records
        payload = mf.payload(mf.status("a1", "1", "2026-09-02T00:00:00Z", "Ready For Approval", "Ready To Sent"),
                             mf.status("a2", "1", "2026-09-02T01:00:00Z", "Uploading", "Ready For Approval"))
        records = status_log_records(payload, mf.STATUS)
        old = normalize_events(records, status_mapping_config(self.v11))
        self.assertEqual([(q["reason"], q["raw_source"]["id"]) for q in old.quarantined], [("UNKNOWN_STATUS", "a1"), ("UNKNOWN_STATUS", "a2")])
        new = normalize_events(records, status_mapping_config(self.contract))
        self.assertEqual([event["event_id"] for event in new.accepted], ["a1", "a2"])

    def test_normalize_events_rejects_malformed_aliases(self):
        mapping = status_mapping_config(self.contract)
        mapping["aliases"] = {"Ready To Sent": {"canonical": "Ready To Send"}}
        with self.assertRaises(ValueError):
            normalize_events([], mapping)


class UnmappedStatusTests(SourceFixture):
    def test_entry_into_a_known_status_from_an_unmapped_one_is_kept_with_raw_previous(self):
        logs = base_logs("1", end=None, extra=[mf.status("u1", "1", "2026-09-01T15:00:00Z", "In Progress", "Uploading"),
                                               mf.status("u2", "1", "2026-09-01T16:00:00Z", "Uploading", "Ready For Approval")])
        result = self.run_pipeline(*logs)
        entry = {event["event_id"]: event for event in result.status_events}["u2"]
        self.assertEqual((entry["to_status"], entry["from_status"], entry["raw_from_status"], entry["status_phase_from"]),
                         ("Ready For Approval", None, "Uploading", None))
        self.assertEqual([(q["reason"], q["raw_source"]["id"]) for q in result.quarantined_status_logs], [("UNKNOWN_STATUS", "u1")])
        cycle = result.cycles[0]
        # The real Ready For Approval entry is kept, but the unknown state inside the window excludes the cycle from metrics.
        self.assertEqual((cycle.state, cycle.ready_for_approval_event["event_id"]), (c.COMPLETED, "u2"))
        self.assertIn(c.UNMAPPED_STATUS_WITHIN_CYCLE_WINDOW, cycle.exclusions)
        self.assertIn(c.UNRESOLVED_PREVIOUS_STATUS, cycle.flags)
        self.assertIsNone(deadline_result(cycle, MetricPolicy.from_contract(self.contract), NOW))

    def test_unknown_status_before_the_start_also_excludes(self):
        logs = base_logs("1", extra=[mf.status("u0", "1", "2026-09-01T09:45:00Z", "Create File", "Editing Now")])
        cycle = self.cycle(*logs)
        self.assertIn(c.UNMAPPED_STATUS_WITHIN_CYCLE_WINDOW, cycle.exclusions)

    def test_unknown_status_after_ready_for_approval_is_only_flagged(self):
        logs = base_logs("1", extra=[mf.status("u9", "1", "2026-09-03T00:00:00Z", "Ready For Approval", "Uploading")])
        cycle = self.cycle(*logs)
        self.assertNotIn(c.UNMAPPED_STATUS_WITHIN_CYCLE_WINDOW, cycle.exclusions)
        self.assertIn(c.UNMAPPED_STATUS_IN_HISTORY, cycle.flags)
        self.assertEqual(cycle.exclusions, [])

    def test_cleared_status_is_quarantined_but_does_not_hide_a_boundary(self):
        logs = base_logs("1", extra=[mf.status("b1", "1", "2026-09-01T09:40:00Z", "Create File", ""),
                                     mf.status("b2", "1", "2026-09-01T09:50:00Z", "", "Create File")])
        result = self.run_pipeline(*logs)
        self.assertEqual([(q["reason"], q["raw_source"]["id"]) for q in result.quarantined_status_logs], [("STATUS_CLEARED", "b1")])
        cycle = result.cycles[0]
        self.assertEqual(cycle.exclusions, [])
        self.assertIn(c.STATUS_CLEARED_IN_HISTORY, cycle.flags)
        self.assertEqual({event["event_id"]: event for event in result.status_events}["b2"]["raw_from_status"], "")


class CreationValueTests(SourceFixture):
    def test_creation_video_type_is_the_first_observation(self):
        logs = [log for log in base_logs("1") if log["id"] != "1-vt"]
        logs.append(mf.create_pulse("cp1", "1", "2026-09-01T08:00:00Z", {"dropdown_mm062ga0": {"chosenValues": [{"id": 8, "name": "Class A+"}]}}))
        cycle = self.cycle(*logs)
        self.assertEqual((cycle.cohort_key, cycle.video_type_event_id, cycle.video_type_source), ("8", "cp1", "create_pulse"))
        self.assertEqual(cycle.exclusions, [])

    def test_creation_eta_enters_the_history_and_a_later_change_wins(self):
        logs = base_logs("1", extra=[
            mf.create_pulse("cp1", "1", "2026-09-01T08:00:00Z", {"date": {"date": "2026-09-01", "time": "20:00:00"}}),
            mf.eta("e2", "1", "2026-09-01T12:00:00Z", "2026-09-02", "01:00:00")])
        cycle = self.cycle(*logs)
        self.assertEqual([(entry["source"], entry["event_id"]) for entry in cycle.requested_eta_history], [("create_pulse", "cp1"), ("activity_log", "e2")])
        self.assertEqual(cycle.requested_eta, "2026-09-02T01:00:00Z")

    def test_status_at_creation_is_a_flag_not_a_transition(self):
        logs = base_logs("1", extra=[mf.create_pulse("cp1", "1", "2026-09-01T08:00:00Z", {"project_status": {"label": {"text": "Sent", "index": 7}}}, duplicate=True)])
        result = self.run_pipeline(*logs)
        self.assertNotIn("cp1", [event["event_id"] for event in result.status_events])
        self.assertIn(c.INITIAL_STATUS_AT_CREATION, result.cycles[0].flags)


class VideoTypeSnapshotTests(SourceFixture):
    def test_latest_valid_value_at_or_before_ready_for_approval(self):
        logs = base_logs("1", video=(5,), extra=[
            mf.video_type("vt2", "1", "2026-09-01T12:00:00Z", [8]),
            mf.video_type("vt3", "1", "2026-09-01T13:00:00Z", []),       # cleared: not a valid value
            mf.video_type("vt4", "1", "2026-09-02T00:00:00Z", [5, 8])])  # after Ready For Approval
        cycle = self.cycle(*logs)
        self.assertEqual((cycle.cohort_key, cycle.video_type_event_id, cycle.video_type_skipped_event_ids), ("8", "vt2", ["vt3"]))
        self.assertIn(c.VIDEO_TYPE_CHANGED_AFTER_READY_FOR_APPROVAL, cycle.flags)
        self.assertEqual(cycle.to_dict()["video_type"]["mapping_version"], "monday-video-type-v1.2")

    def test_only_cleared_values_means_missing_video_type(self):
        logs = [log for log in base_logs("1") if log["id"] != "1-vt"] + [mf.video_type("vt0", "1", "2026-09-01T09:00:00Z", [])]
        cycle = self.cycle(*logs)
        self.assertIsNone(cycle.cohort_key)
        self.assertIn("MISSING_VIDEO_TYPE", cycle.exclusions)

    def test_former_label_names_resolve_only_with_their_id(self):
        cycle = self.cycle(*base_logs("1", extra=[mf.video_type("vt2", "1", "2026-09-01T09:10:00Z", [6], names=["Short"])]))
        self.assertEqual((cycle.cohort_key, cycle.video_type.canonical_labels), ("6", ("Simple Short",)))
        old_video = self.cycle(*base_logs("1", extra=[mf.video_type("vt2", "1", "2026-09-01T09:10:00Z", [7], names=["Video"])]))
        self.assertEqual(old_video.cohort_key, "7")  # "Video" is ID 7's former name, not today's ID 12
        mismatch = self.cycle(*base_logs("1", extra=[mf.video_type("vt2", "1", "2026-09-01T09:10:00Z", [8], names=["Short"])]))
        self.assertIsNone(mismatch.cohort_key)


class DateOnlyEtaTests(SourceFixture):
    def test_date_only_eta_is_explicitly_not_classifiable(self):
        cycle = self.cycle(*base_logs("1", extra=[mf.eta("e1", "1", "2026-09-01T08:00:00Z", "2026-09-02", None)]))
        self.assertIsNone(deadline_result(cycle, MetricPolicy.from_contract(self.contract), NOW))
        summary = deadline_summary([], [cycle])
        self.assertEqual(summary["not_evaluated"][0]["classification"], NOT_CLASSIFIABLE_ETA_PRECISION)
        self.assertEqual((summary["not_classifiable_insufficient_eta_precision"], summary["early"], summary["on_time"], summary["late"]), (1, 0, 0, 0))

    def test_for_bonus_is_context_only_in_the_contract(self):
        for_bonus = self.contract["quality_labels"]["for_bonus"]
        self.assertEqual((for_bonus["classification"], for_bonus["affects_quality"]), ("context-unclassified", False))


class ContractConfigTests(SourceFixture):
    def test_status_aliases_are_index_bound_and_v11_has_none(self):
        aliases = self.contract["status_label_aliases"]
        self.assertEqual({text: (alias["canonical"], alias["label_index"]) for text, alias in aliases.items()},
                         {"Ready To Sent": ("Ready To Send", 4), "ready to sent": ("Ready To Send", 4), "Creat File": ("Create File", 13)})
        self.assertNotIn("status_label_aliases", self.v11)
        self.assertEqual(json.loads(json.dumps(self.contract["video_type_cohorts"]["classification"]))["confirmed_base_ids"], [])


if __name__ == "__main__":
    unittest.main()
