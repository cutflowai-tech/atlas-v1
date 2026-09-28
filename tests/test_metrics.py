import json
import unittest
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from atlas_commander.contracts import ROOT, validate
from atlas_commander.metrics import MetricInputError, QualityMapping, derive_deadline, derive_quality, derive_speed


class MetricsTests(unittest.TestCase):
    def setUp(self):
        def fixture(name):
            return json.loads((ROOT / "fixtures" / "good" / (name + ".json")).read_text())
        self.cycle = fixture("work-cycle")
        self.speed = fixture("speed-metric")["evidence"]
        self.deadline = fixture("deadline-metric")["evidence"]
        self.quality = fixture("quality-metric")["evidence"]
        self.mapping = QualityMapping("board-1", "performance_label", "quality-label-v1",
                                      {"Meets Expectations": "Meets Expectations"}, approved=True)

    def peer(self, seconds, identity="peer", video_type="short-form"):
        cycle, evidence = deepcopy(self.cycle), deepcopy(self.speed)
        cycle.update(cycle_id=identity, monday_item_id=identity, duration_seconds=seconds, video_type=video_type)
        cycle["ready_for_approval_at"] = (datetime(2026, 9, 1, 9, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat()
        evidence["monday_item_id"] = identity
        evidence["source_timestamps"] = [cycle["in_progress_at"], cycle["ready_for_approval_at"]]
        evidence["source_values"]["video_type"] = video_type
        return cycle, evidence

    def test_all_outputs_match_contracts(self):
        results = [derive_speed(self.cycle, self.speed, [self.peer(7500)]),
                   derive_deadline(self.cycle, self.deadline), derive_quality(self.cycle, self.quality, self.mapping)]
        for result in results:
            self.assertEqual(validate(result, result["metric_name"] + "-metric.schema.json"), [])
        self.assertEqual(results[0]["cohort_median_seconds"], 7500)
        self.assertEqual(results[1]["result"], "on_time")
        self.assertEqual(results[2]["performance_label"], "Meets Expectations")

    def test_same_canonical_type_only_and_no_global_fallback(self):
        other = self.peer(300, video_type="Short-Form")
        self.assertIsNone(derive_speed(self.cycle, self.speed, [other])["cohort_median_seconds"])
        result = derive_speed(self.cycle, self.speed, [other, self.peer(7400)])
        self.assertEqual(result["cohort_median_seconds"], 7400)
        sources = result["evidence"]["source_values"]["speed_derivation"]["cohort"]
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["evidence"]["monday_item_id"], "peer")
        self.assertEqual(sources[0]["evidence"]["event_ids"], self.speed["event_ids"])

    def test_even_and_odd_medians_and_order(self):
        peers = [self.peer(7000, "a"), self.peer(8000, "b"), self.peer(9000, "c")]
        self.assertEqual(derive_speed(self.cycle, self.speed, peers)["cohort_median_seconds"], 8000)
        self.assertEqual(derive_speed(self.cycle, self.speed, peers[:2])["cohort_median_seconds"], 7500)
        self.assertEqual(derive_speed(self.cycle, self.speed, peers), derive_speed(self.cycle, self.speed, peers[::-1]))

    def test_fractional_median_is_explicitly_unsupported(self):
        with self.assertRaisesRegex(MetricInputError, "Fractional"):
            derive_speed(self.cycle, self.speed, [self.peer(1, "a"), self.peer(2, "b")])

    def test_duplicate_cohort_rejected(self):
        with self.assertRaisesRegex(MetricInputError, "Duplicate"):
            derive_speed(self.cycle, self.speed, [self.peer(10), self.peer(10)])

    def test_deadline_equality_late_and_timezone_comparison(self):
        for eta, expected in [("2026-09-01T11:00:00Z", "on_time"), ("2026-09-01T10:59:59Z", "late"),
                              ("2026-09-01T13:00:00+02:00", "on_time")]:
            with self.subTest(eta=eta):
                self.cycle["requested_eta"] = eta
                self.deadline["source_values"]["requested_eta"] = eta
                self.assertEqual(derive_deadline(self.cycle, self.deadline)["result"], expected)

    def test_missing_eta_has_no_metric(self):
        self.cycle["requested_eta"] = None
        self.assertIsNone(derive_deadline(self.cycle, self.deadline))

    def test_deadline_rejects_mismatched_source_eta(self):
        self.deadline["source_values"]["requested_eta"] = "2026-09-01T10:00:00Z"
        with self.assertRaises(MetricInputError):
            derive_deadline(self.cycle, self.deadline)

    def test_quality_mapping_approval_version_scope_and_label(self):
        for mapping in [replace(self.mapping, approved=False), replace(self.mapping, version=""),
                        replace(self.mapping, board_id="other"), replace(self.mapping, column_id="other"),
                        replace(self.mapping, labels={})]:
            with self.subTest(mapping=mapping), self.assertRaises(MetricInputError):
                derive_quality(self.cycle, self.quality, mapping)

    def test_quality_uses_only_mapped_source_label(self):
        self.quality["source_values"]["performance_label"] = "unknown"
        with self.assertRaises(MetricInputError):
            derive_quality(self.cycle, self.quality, self.mapping)

    def test_revisions_are_neutral_for_every_metric(self):
        before = derive_quality(self.cycle, self.quality, self.mapping)
        for context in [None, {"count": 0}, {"count": 999, "score": -100}]:
            self.cycle["revision_context"] = context
            after = derive_quality(self.cycle, self.quality, self.mapping)
            self.assertEqual(after["performance_label"], before["performance_label"])
            self.assertEqual(after["revision_context"], context)
            self.assertEqual(derive_speed(self.cycle, self.speed)["duration_seconds"], 7200)
            self.assertEqual(derive_deadline(self.cycle, self.deadline)["result"], "on_time")

    def test_evidence_required_monday_and_bound_to_cycle(self):
        for field, value in [("source", "ai"), ("event_ids", []), ("monday_item_id", "other"), ("source_values", {})]:
            with self.subTest(field=field):
                evidence = deepcopy(self.speed)
                evidence[field] = value
                with self.assertRaises(MetricInputError):
                    derive_speed(self.cycle, evidence)
        peer, evidence = self.peer(500)
        evidence["source"] = "ai"
        with self.assertRaises(MetricInputError):
            derive_speed(self.cycle, self.speed, [(peer, evidence)])
        self.quality["source"] = "ai"
        with self.assertRaises(MetricInputError):
            derive_quality(self.cycle, self.quality, self.mapping)

    def test_exact_duration_required_without_truncation(self):
        for end in ["2026-09-01T11:00:00.500Z", "2026-09-01T08:00:00Z"]:
            self.cycle["ready_for_approval_at"] = end
            with self.assertRaises(MetricInputError):
                derive_speed(self.cycle, self.speed)

    def test_inputs_and_outputs_are_independent(self):
        original = deepcopy((self.cycle, self.speed, self.deadline, self.quality))
        speed = derive_speed(self.cycle, self.speed, [self.peer(100)])
        quality = derive_quality(self.cycle, self.quality, self.mapping)
        derive_deadline(self.cycle, self.deadline)
        speed["evidence"]["event_ids"].append("changed")
        quality["revision_context"]["count"] = 100
        self.assertEqual((self.cycle, self.speed, self.deadline, self.quality), original)


if __name__ == "__main__":
    unittest.main()
