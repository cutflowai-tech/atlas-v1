import copy
import json
import unittest

from atlas_commander.contracts import ROOT, validate
from atlas_commander.metrics import (
    CycleSource,
    MetricError,
    PerformanceLabelObservation,
    QualityLabelMapping,
    derive_deadline_metric,
    derive_deadline_metrics,
    derive_quality_metric,
    derive_speed_metrics,
)

CALCULATED_AT = "2026-09-01T11:05:00Z"
FIXTURES = ROOT / "fixtures"


def _fixture(relative):
    return json.loads((FIXTURES / relative).read_text())


def _cycle(cycle_id, video_type="short-form", duration=7200, **overrides):
    cycle = _fixture("good/work-cycle.json")
    hours, seconds = divmod(duration, 3600)
    minutes, seconds = divmod(seconds, 60)
    cycle.update(
        cycle_id=cycle_id,
        video_type=video_type,
        monday_item_id=f"item-{cycle_id}",
        in_progress_event_id=f"{cycle_id}-start",
        ready_for_approval_event_id=f"{cycle_id}-ready",
        in_progress_at="2026-09-01T00:00:00Z",
        ready_for_approval_at=f"2026-09-01T{hours:02d}:{minutes:02d}:{seconds:02d}Z",
        duration_seconds=duration,
    )
    cycle.update(overrides)
    return cycle


def _source(cycle):
    return CycleSource(cycle=cycle, status_column_id="status", video_type_column_id="video_type", requested_eta_column_id="requested_eta")


MAPPING = QualityLabelMapping(
    version="quality-label-v1",
    label_column_id="performance_label",
    approved=True,
    labels={"Meets Expectations": "Meets Expectations", "Exceeds Expectations": "Exceeds Expectations"},
)


def _observation(label="Meets Expectations", **overrides):
    values = {
        "monday_board_id": "board-1",
        "monday_item_id": "item-1",
        "column_id": "performance_label",
        "event_id": "event-102",
        "observed_at": "2026-09-01T11:10:00Z",
        "label": label,
    }
    values.update(overrides)
    return PerformanceLabelObservation(**values)


class SpeedMetricTests(unittest.TestCase):
    def test_fixture_cycle_reproduces_contract_fixture_shape(self):
        [metric] = derive_speed_metrics([_source(_fixture("good/work-cycle.json"))], CALCULATED_AT)
        expected = _fixture("good/speed-metric.json")
        self.assertEqual(validate(metric, "speed-metric.schema.json"), [])
        for key in ("editor_id", "video_type", "duration_seconds", "cohort_video_type"):
            self.assertEqual(metric[key], expected[key])
        self.assertEqual(metric["cohort_median_seconds"], 7200)
        for key in ("monday_board_id", "monday_item_id", "column_ids", "event_ids", "source_timestamps", "rule_version"):
            self.assertEqual(metric["evidence"][key], expected["evidence"][key])

    def test_same_video_type_speed_cohort(self):
        sources = [
            _source(_cycle("a", "short-form", 3600)),
            _source(_cycle("b", "short-form", 7200)),
            _source(_cycle("c", "short-form", 10800)),
            _source(_cycle("d", "long-form", 36000)),
        ]
        metrics = {m["evidence"]["source_values"]["cycle_id"]: m for m in derive_speed_metrics(sources, CALCULATED_AT)}
        self.assertEqual(metrics["a"]["cohort_median_seconds"], 7200)
        self.assertEqual(metrics["d"]["cohort_median_seconds"], 36000)
        for metric in metrics.values():
            self.assertEqual(metric["cohort_video_type"], metric["video_type"])
            self.assertEqual(validate(metric, "speed-metric.schema.json"), [])
        cohort = metrics["a"]["evidence"]["source_values"]["cohort_sources"]
        self.assertEqual([member["cycle_id"] for member in cohort], ["a", "b", "c"])
        self.assertEqual(cohort[1]["ready_for_approval_event_id"], "b-ready")
        self.assertEqual([m["cycle_id"] for m in metrics["d"]["evidence"]["source_values"]["cohort_sources"]], ["d"])

    def test_video_type_is_not_normalized_or_globally_pooled(self):
        sources = [_source(_cycle("a", "short-form", 3600)), _source(_cycle("b", "Short-Form", 7200))]
        metrics = derive_speed_metrics(sources, CALCULATED_AT)
        self.assertEqual([m["cohort_median_seconds"] for m in metrics], [3600, 7200])
        self.assertEqual([m["evidence"]["source_values"]["cohort_size"] for m in metrics], [1, 1])

    def test_fractional_median_is_not_rounded(self):
        sources = [_source(_cycle("a", duration=3600)), _source(_cycle("b", duration=3601))]
        for metric in derive_speed_metrics(sources, CALCULATED_AT):
            self.assertIsNone(metric["cohort_median_seconds"])
            values = metric["evidence"]["source_values"]
            self.assertEqual(values["cohort_median_status"], "unsupported_fractional")
            self.assertEqual(values["cohort_median_exact"], "3600.5")
            self.assertEqual(validate(metric, "speed-metric.schema.json"), [])

    def test_even_cohort_with_integer_median(self):
        sources = [_source(_cycle("a", duration=3600)), _source(_cycle("b", duration=3602))]
        self.assertEqual(derive_speed_metrics(sources, CALCULATED_AT)[0]["cohort_median_seconds"], 3601)

    def test_deterministic_regardless_of_input_order(self):
        sources = [_source(_cycle(name, duration=3600 * (i + 1))) for i, name in enumerate("abc")]
        self.assertEqual(derive_speed_metrics(sources, CALCULATED_AT), derive_speed_metrics(list(reversed(sources)), CALCULATED_AT))

    def test_invalid_cycles_rejected(self):
        with self.assertRaises(MetricError) as caught:
            derive_speed_metrics([_source(_fixture("bad/end-before-start.json"))], CALCULATED_AT)
        self.assertEqual(caught.exception.code, "END_BEFORE_START")
        with self.assertRaises(MetricError) as caught:
            derive_speed_metrics([_source(_fixture("bad/missing-video-type.json"))], CALCULATED_AT)
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")
        with self.assertRaises(MetricError) as caught:
            derive_speed_metrics([_source(_cycle("a", duration=3600, duration_seconds=3000))], CALCULATED_AT)
        self.assertEqual(caught.exception.code, "DURATION_MISMATCH")
        with self.assertRaises(MetricError) as caught:
            derive_speed_metrics([_source(_cycle("a")), _source(_cycle("a"))], CALCULATED_AT)
        self.assertEqual(caught.exception.code, "DUPLICATE_CYCLE")

    def test_missing_eta_does_not_block_speed(self):
        [metric] = derive_speed_metrics([_source(_fixture("bad/missing-eta.json"))], CALCULATED_AT)
        self.assertEqual(metric["duration_seconds"], 7200)


class DeadlineMetricTests(unittest.TestCase):
    def test_deadline_compares_ready_for_approval_with_requested_eta(self):
        metric = derive_deadline_metric(_source(_fixture("good/work-cycle.json")), CALCULATED_AT)
        expected = _fixture("good/deadline-metric.json")
        self.assertEqual(metric["result"], "on_time")
        self.assertEqual(validate(metric, "deadline-metric.schema.json"), [])
        for key in ("editor_id", "ready_for_approval_at", "requested_eta", "result"):
            self.assertEqual(metric[key], expected[key])
        for key in ("column_ids", "event_ids", "source_timestamps", "rule_version"):
            self.assertEqual(metric["evidence"][key], expected["evidence"][key])

    def test_late_when_ready_after_eta(self):
        cycle = _fixture("good/work-cycle.json")
        cycle["requested_eta"] = "2026-09-01T10:59:59Z"
        self.assertEqual(derive_deadline_metric(_source(cycle), CALCULATED_AT)["result"], "late")

    def test_equality_is_on_time(self):
        cycle = _fixture("good/work-cycle.json")
        cycle["requested_eta"] = cycle["ready_for_approval_at"]
        self.assertEqual(derive_deadline_metric(_source(cycle), CALCULATED_AT)["result"], "on_time")

    def test_equality_across_offsets_is_on_time(self):
        cycle = _fixture("good/work-cycle.json")
        cycle["requested_eta"] = "2026-09-01T13:00:00+02:00"
        self.assertEqual(derive_deadline_metric(_source(cycle), CALCULATED_AT)["result"], "on_time")

    def test_missing_requested_eta_yields_no_metric(self):
        self.assertIsNone(derive_deadline_metric(_source(_fixture("bad/missing-eta.json")), CALCULATED_AT))
        sources = [_source(_cycle("a", requested_eta=None)), _source(_cycle("b"))]
        self.assertEqual([m["evidence"]["source_values"]["cycle_id"] for m in derive_deadline_metrics(sources, CALCULATED_AT)], ["b"])


class QualityMetricTests(unittest.TestCase):
    def test_quality_label_only(self):
        metric = derive_quality_metric(_source(_fixture("good/work-cycle.json")), _observation(), MAPPING, "2026-09-01T11:12:00Z")
        self.assertEqual(metric, _fixture("good/quality-metric.json") | {"evidence": metric["evidence"]})
        self.assertEqual(metric["evidence"]["source_values"]["performance_label"], "Meets Expectations")
        self.assertEqual(validate(metric, "quality-metric.schema.json"), [])
        self.assertNotIn("score", metric)

    def test_mapping_translates_monday_label_value(self):
        mapping = QualityLabelMapping("quality-label-v2", "performance_label", True, {"Great": "Exceeds Expectations"})
        metric = derive_quality_metric(_source(_fixture("good/work-cycle.json")), _observation("Great"), mapping, CALCULATED_AT)
        self.assertEqual(metric["performance_label"], "Exceeds Expectations")
        self.assertEqual(metric["label_mapping_version"], "quality-label-v2")
        self.assertEqual(metric["evidence"]["source_values"]["performance_label"], "Great")

    def test_unapproved_or_unknown_labels_rejected(self):
        source = _source(_fixture("good/work-cycle.json"))
        unapproved = QualityLabelMapping("quality-label-v1", "performance_label", False, MAPPING.labels)
        cases = [
            ("UNAPPROVED_LABEL_MAPPING", _observation(), unapproved),
            ("UNSUPPORTED_PERFORMANCE_LABEL", _observation("AI says great"), MAPPING),
            ("LABEL_COLUMN_MISMATCH", _observation(column_id="notes"), MAPPING),
            ("LABEL_ITEM_MISMATCH", _observation(monday_item_id="item-9"), MAPPING),
            ("UNVERSIONED_LABEL_MAPPING", _observation(), QualityLabelMapping("", "performance_label", True, MAPPING.labels)),
        ]
        for code, observation, mapping in cases:
            with self.subTest(code=code), self.assertRaises(MetricError) as caught:
                derive_quality_metric(source, observation, mapping, CALCULATED_AT)
            self.assertEqual(caught.exception.code, code)

    def test_missing_label_yields_no_metric(self):
        source = _source(_fixture("good/work-cycle.json"))
        self.assertIsNone(derive_quality_metric(source, _observation(None), MAPPING, CALCULATED_AT))
        self.assertIsNone(derive_quality_metric(source, _observation(""), MAPPING, CALCULATED_AT))


class RevisionNeutralityTests(unittest.TestCase):
    def test_revisions_neutral(self):
        base = _fixture("good/work-cycle.json")
        heavy = copy.deepcopy(base) | {"revision_context": {"count": 25, "notes": ["redo intro"]}}
        none = copy.deepcopy(base) | {"revision_context": None}
        results = []
        for cycle in (base, heavy, none):
            source = _source(cycle)
            speed = derive_speed_metrics([source], CALCULATED_AT)[0]
            deadline = derive_deadline_metric(source, CALCULATED_AT)
            quality = derive_quality_metric(source, _observation(), MAPPING, CALCULATED_AT)
            self.assertEqual(quality["revision_context"], cycle["revision_context"])
            quality = {key: value for key, value in quality.items() if key != "revision_context"}
            results.append((speed, deadline, quality))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], results[2])

    def test_revision_context_is_copied_not_shared(self):
        cycle = _fixture("good/work-cycle.json")
        metric = derive_quality_metric(_source(cycle), _observation(), MAPPING, CALCULATED_AT)
        metric["revision_context"]["count"] = 99
        self.assertEqual(cycle["revision_context"], {"count": 3})


if __name__ == "__main__":
    unittest.main()
