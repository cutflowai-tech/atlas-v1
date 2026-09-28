import json
import unittest
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from atlas_commander.contracts import ROOT, assert_valid
from atlas_commander.metrics import MetricInputError, QualityMapping, derive_deadline, derive_quality, derive_speed


def fixture(name):
    return json.loads((ROOT / "fixtures" / "good" / (name + ".json")).read_text())


class MetricTests(unittest.TestCase):
    def setUp(self):
        self.cycle = fixture("work-cycle")
        self.speed = fixture("speed-metric")["evidence"]
        self.deadline = fixture("deadline-metric")["evidence"]
        self.quality = fixture("quality-metric")["evidence"]
        self.mapping = QualityMapping("board-1", "performance_label", "quality-label-v1",
                                      {"Meets Expectations": "Meets Expectations"}, True)

    def member(self, name, duration, video_type="short-form"):
        cycle, evidence = deepcopy(self.cycle), deepcopy(self.speed)
        cycle.update(cycle_id=name, monday_item_id=name, duration_seconds=duration, video_type=video_type)
        start = datetime(2026, 9, 1, 9, tzinfo=timezone.utc)
        cycle["ready_for_approval_at"] = (start + timedelta(seconds=duration)).isoformat()
        cycle["in_progress_event_id"] = name + "-start"
        cycle["ready_for_approval_event_id"] = name + "-end"
        evidence.update(monday_item_id=name, event_ids=[name + "-start", name + "-end"],
                        source_timestamps=[cycle["in_progress_at"], cycle["ready_for_approval_at"]])
        evidence["source_values"]["video_type"] = video_type
        return cycle, evidence

    def test_same_type_cohort_with_contributing_source_evidence(self):
        a, b, other = self.member("a", 7200), self.member("b", 7800), self.member("other", 1, "long-form")
        metric = derive_speed(self.cycle, self.speed, [b, other, a])
        self.assertEqual(metric["cohort_median_seconds"], 7500)
        self.assertEqual(metric["duration_seconds"], 7200)
        self.assertEqual(metric["editor_id"], "editor-42")
        records = metric["evidence"]["source_values"]["cohort"]
        self.assertEqual([r["work_cycle"]["cycle_id"] for r in records], ["a", "b"])
        self.assertEqual(records[0]["source_evidence"], a[1])
        self.assertEqual(metric, derive_speed(self.cycle, self.speed, [a, b, other]))
        assert_valid(metric, "speed-metric.schema.json")

    def test_no_global_fallback_or_canonical_id_guess(self):
        for cohort in ([], [self.member("other", 1, "long-form")], [self.member("alias", 1, "Short-Form")]):
            metric = derive_speed(self.cycle, self.speed, cohort)
            self.assertIsNone(metric["cohort_median_seconds"])
            self.assertEqual(metric["cohort_video_type"], "short-form")
            assert_valid(metric, "speed-metric.schema.json")

    def test_odd_and_even_integer_medians(self):
        for values, expected in (([1], 1), ([1, 3], 2), ([1, 3, 9], 3)):
            cohort = [self.member(str(i), value) for i, value in enumerate(values)]
            self.assertEqual(derive_speed(self.cycle, self.speed, cohort)["cohort_median_seconds"], expected)

    def test_fractional_median_is_explicitly_unsupported(self):
        with self.assertRaisesRegex(MetricInputError, "Fractional cohort median"):
            derive_speed(self.cycle, self.speed, [self.member("a", 1), self.member("b", 2)])

    def test_duplicate_cohort_rejected(self):
        member = self.member("a", 1)
        with self.assertRaisesRegex(MetricInputError, "Duplicate"):
            derive_speed(self.cycle, self.speed, [member, member])

    def test_deadline_boundaries_and_timezones(self):
        for eta, expected in (("2026-09-01T11:30:00Z", "on_time"), ("2026-09-01T11:00:00Z", "on_time"),
                              ("2026-09-01T13:00:00+02:00", "on_time"), ("2026-09-01T10:59:59Z", "late")):
            with self.subTest(eta=eta):
                self.cycle["requested_eta"] = eta
                self.deadline["source_values"]["requested_eta"] = eta
                metric = derive_deadline(self.cycle, self.deadline)
                self.assertEqual(metric["result"], expected)
                self.assertEqual(metric["evidence"]["source_values"]["subject"]["source_evidence"], self.deadline)
                assert_valid(metric, "deadline-metric.schema.json")

    def test_missing_eta_has_no_metric_or_fallback(self):
        self.cycle["requested_eta"] = None
        self.deadline["source_values"].update(requested_eta=None, due_date="2030-01-01T00:00:00Z")
        self.assertIsNone(derive_deadline(self.cycle, self.deadline))
        assert_valid(derive_speed(self.cycle, self.speed), "speed-metric.schema.json")
        assert_valid(derive_quality(self.cycle, self.quality, self.mapping), "quality-metric.schema.json")

    def test_quality_approved_label_and_neutral_revisions(self):
        for context in (None, {"count": 0}, {"count": 999, "notes": "many revisions"}):
            self.cycle["revision_context"] = context
            metric = derive_quality(self.cycle, self.quality, self.mapping)
            self.assertEqual(metric["performance_label"], "Meets Expectations")
            self.assertEqual(metric["revision_context"], context)
            self.assertEqual(metric["label_mapping_version"], "quality-label-v1")
            self.assertEqual(metric["evidence"]["source_values"]["subject"]["source_evidence"], self.quality)
            assert_valid(metric, "quality-metric.schema.json")

    def test_quality_rejects_unapproved_unversioned_wrong_board_or_column(self):
        for mapping in (replace(self.mapping, approved=False), replace(self.mapping, version=""),
                        replace(self.mapping, monday_board_id="other"), replace(self.mapping, column_id="other"),
                        replace(self.mapping, labels={})):
            with self.subTest(mapping=mapping), self.assertRaises(MetricInputError):
                derive_quality(self.cycle, self.quality, mapping)

    def test_quality_requires_label_not_revision_or_ai_inference(self):
        for values in ({}, {"revision_count": 0}, {"ai_quality": "Meets Expectations"}, {"performance_label": "Unknown"}):
            self.quality["source_values"] = values
            with self.assertRaises(MetricInputError):
                derive_quality(self.cycle, self.quality, self.mapping)

    def test_canonical_column_and_label_id_mapping(self):
        self.quality["column_ids"] = ["status_123"]
        self.quality["source_values"] = {"status_123": "label-7"}
        mapping = replace(self.mapping, column_id="status_123", labels={"label-7": "Meets Expectations"})
        self.assertEqual(derive_quality(self.cycle, self.quality, mapping)["performance_label"], "Meets Expectations")

    def test_bad_evidence_rejected_for_subject_and_cohort(self):
        for changes in ({"source": "ai"}, {"event_ids": []}, {"monday_item_id": "wrong"}, {"monday_board_id": "wrong"}):
            source = {**self.speed, **changes}
            with self.subTest(changes=changes), self.assertRaises(MetricInputError):
                derive_speed(self.cycle, source)
            with self.assertRaises(MetricInputError):
                derive_speed(self.cycle, self.speed, [(self.cycle, source)])

    def test_inconsistent_and_fractional_durations_rejected(self):
        for end in ("2026-09-01T11:00:00.5Z", "2026-09-01T08:00:00Z", "2026-09-01T12:00:00Z"):
            self.cycle["ready_for_approval_at"] = end
            with self.assertRaisesRegex(MetricInputError, "Duration"):
                derive_speed(self.cycle, self.speed)

    def test_deterministic_and_independent_input_output_objects(self):
        before = deepcopy((self.cycle, self.speed, self.deadline, self.quality))
        for derive, args in ((derive_speed, (self.speed,)), (derive_deadline, (self.deadline,)),
                             (derive_quality, (self.quality, self.mapping))):
            first = derive(self.cycle, *args)
            self.assertEqual(first, derive(self.cycle, *args))
            first["evidence"]["source_values"]["subject"]["work_cycle"]["revision_context"]["count"] = 999
        self.assertEqual(before, (self.cycle, self.speed, self.deadline, self.quality))


if __name__ == "__main__":
    unittest.main()
