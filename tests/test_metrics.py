import copy
import json
import unittest
from dataclasses import replace

from atlas_commander.contracts import ROOT, validate
from atlas_commander.metrics import (
    CycleSource,
    MetricError,
    PerformanceLabelObservation,
    QualityLabelMapping,
    SourceObservation,
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
    def observed(column, event, timestamp, value):
        return SourceObservation(cycle["monday_board_id"], cycle["monday_item_id"], column, event, timestamp, value)
    observations = (
        observed("status", cycle["in_progress_event_id"], cycle["in_progress_at"], cycle["start_status"]),
        observed("status", cycle["ready_for_approval_event_id"], cycle["ready_for_approval_at"], cycle["end_status"]),
        observed("video_type", "video-type-event", cycle["in_progress_at"], cycle.get("video_type")),
        observed("requested_eta", "eta-event", cycle["in_progress_at"], cycle["requested_eta"]),
    )
    return CycleSource(cycle, "status", "video_type", "requested_eta", observations)


MAPPING = QualityLabelMapping(
    monday_board_id="board-1",
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
    values["source_observation"] = SourceObservation(values["monday_board_id"], values["monday_item_id"],
        values["column_id"], values["event_id"], values["observed_at"], values["label"])
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
        mapping = QualityLabelMapping("quality-label-v2", "performance_label", True, {"Great": "Exceeds Expectations"}, "board-1")
        metric = derive_quality_metric(_source(_fixture("good/work-cycle.json")), _observation("Great"), mapping, CALCULATED_AT)
        self.assertEqual(metric["performance_label"], "Exceeds Expectations")
        self.assertEqual(metric["label_mapping_version"], "quality-label-v2")
        self.assertEqual(metric["evidence"]["source_values"]["performance_label"], "Great")

    def test_unapproved_or_unknown_labels_rejected(self):
        source = _source(_fixture("good/work-cycle.json"))
        unapproved = QualityLabelMapping("quality-label-v1", "performance_label", False, MAPPING.labels, "board-1")
        cases = [
            ("UNAPPROVED_LABEL_MAPPING", _observation(), unapproved),
            ("UNSUPPORTED_PERFORMANCE_LABEL", _observation("AI says great"), MAPPING),
            ("LABEL_COLUMN_MISMATCH", _observation(column_id="notes"), MAPPING),
            ("LABEL_ITEM_MISMATCH", _observation(monday_item_id="item-9"), MAPPING),
            ("UNVERSIONED_LABEL_MAPPING", _observation(), QualityLabelMapping("", "performance_label", True, MAPPING.labels, "board-1")),
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


class SourceIntegrityTests(unittest.TestCase):
    def test_fractional_duration_rejected(self):
        cycle = _cycle("fractional", ready_for_approval_at="2026-09-01T02:00:00.5Z")
        with self.assertRaises(MetricError) as caught:
            derive_speed_metrics([_source(cycle)], CALCULATED_AT)
        self.assertEqual(caught.exception.code, "UNSUPPORTED_FRACTIONAL_DURATION")

    def test_submicrosecond_precision_rejected(self):
        cycle = _cycle("fractional", ready_for_approval_at="2026-09-01T02:00:00.0000001Z")
        with self.assertRaises(MetricError) as caught:
            derive_speed_metrics([_source(cycle)], CALCULATED_AT)
        self.assertEqual(caught.exception.code, "UNSUPPORTED_TIMESTAMP_PRECISION")

    def test_source_records_must_prove_each_claim(self):
        source = _source(_fixture("good/work-cycle.json"))
        for index in range(4):
            for field, value in (("monday_board_id", "other"), ("monday_item_id", "other"),
                                 ("column_id", "unrelated"), ("value", "unrelated")):
                observations = list(source.observations)
                observations[index] = replace(observations[index], **{field: value})
                with self.subTest(index=index, field=field), self.assertRaises(MetricError) as caught:
                    derive_speed_metrics([replace(source, observations=observations)], CALCULATED_AT)
                self.assertEqual(caught.exception.code, "SOURCE_EVIDENCE_MISMATCH")
        for field, value in (("event_id", "unrelated"), ("observed_at", "2026-08-01T00:00:00Z")):
            observations = list(source.observations)
            observations[1] = replace(observations[1], **{field: value})
            with self.assertRaises(MetricError):
                derive_deadline_metric(replace(source, observations=observations), CALCULATED_AT)

    def test_quality_mapping_requires_board_scope_and_boolean_approval(self):
        source = _source(_fixture("good/work-cycle.json"))
        for mapping, code in ((replace(MAPPING, monday_board_id="other"), "LABEL_BOARD_MISMATCH"),
                              (replace(MAPPING, approved=1), "UNAPPROVED_LABEL_MAPPING")):
            with self.assertRaises(MetricError) as caught:
                derive_quality_metric(source, _observation(), mapping, CALCULATED_AT)
            self.assertEqual(caught.exception.code, code)

    def test_quality_requires_matching_source_record(self):
        source = _source(_fixture("good/work-cycle.json"))
        for field, value in (("event_id", "other"), ("observed_at", "2026-08-01T00:00:00Z"),
                             ("label", "Exceeds Expectations")):
            with self.subTest(field=field), self.assertRaises(MetricError) as caught:
                derive_quality_metric(source, replace(_observation(), **{field: value}), MAPPING, CALCULATED_AT)
            self.assertEqual(caught.exception.code, "LABEL_SOURCE_MISMATCH")

    def test_nested_context_and_mapping_evidence_are_detached(self):
        cycle = _fixture("good/work-cycle.json")
        cycle["revision_context"] = {"notes": [{"text": ["original"]}]}
        metric = derive_quality_metric(_source(cycle), _observation(), MAPPING, CALCULATED_AT)
        metric["revision_context"]["notes"][0]["text"].append("changed")
        metric["evidence"]["source_values"]["approved_mapping"]["labels"]["Meets Expectations"] = "changed"
        self.assertEqual(cycle["revision_context"], {"notes": [{"text": ["original"]}]})
        self.assertEqual(MAPPING.labels["Meets Expectations"], "Meets Expectations")


if __name__ == "__main__":
    unittest.main()
