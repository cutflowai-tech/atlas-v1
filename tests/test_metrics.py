import json
import unittest
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from atlas_commander.contracts import ROOT, validate
from atlas_commander.metrics import (
    CycleSource,
    QualityMapping,
    UnsupportedMetricValue,
    derive_deadline,
    derive_quality,
    derive_speed,
)


def fixture(name):
    return json.loads((ROOT / 'fixtures/good' / f'{name}.json').read_text())


class MetricTests(unittest.TestCase):
    def setUp(self):
        self.cycle = fixture('work-cycle')
        self.speed = fixture('speed-metric')['evidence']
        self.deadline = fixture('deadline-metric')['evidence']
        self.quality = fixture('quality-metric')['evidence']
        self.quality['source_values'] = {'performance_label': 'label-1'}
        self.mapping = QualityMapping('board-1', 'performance_label', 'quality-label-v1',
                                      {'label-1': 'Meets Expectations'}, True)

    def member(self, identifier, duration, video_type='short-form'):
        cycle = deepcopy(self.cycle)
        cycle.update(cycle_id=identifier, duration_seconds=duration, video_type=video_type)
        start = datetime(2026, 9, 1, 9, tzinfo=timezone.utc)
        cycle['ready_for_approval_at'] = (start + timedelta(seconds=duration)).isoformat()
        evidence = deepcopy(self.speed)
        evidence['source_timestamps'] = [cycle['in_progress_at'], cycle['ready_for_approval_at']]
        return CycleSource(cycle, evidence)

    def test_same_canonical_video_type_and_all_contributing_evidence(self):
        cohort = [self.member('b', 8000), self.member('foreign', 90000, 'long-form'), self.member('a', 7000)]
        result = derive_speed(self.cycle, self.speed, cohort)
        self.assertEqual(validate(result, 'speed-metric.schema.json'), [])
        self.assertEqual(result['cohort_median_seconds'], 7500)
        self.assertEqual(result['duration_seconds'], 7200)
        contributors = result['evidence']['source_values']['cohort']
        self.assertEqual([s['work_cycle']['cycle_id'] for s in contributors], ['a', 'b'])
        self.assertEqual(contributors[0]['evidence']['event_ids'], self.speed['event_ids'])
        self.assertEqual(result, derive_speed(self.cycle, self.speed, list(reversed(cohort))))

    def test_no_global_fallback_or_implicit_target_inclusion(self):
        for cohort in ([], [self.member('foreign', 90000, 'Short Form')]):
            result = derive_speed(self.cycle, self.speed, cohort)
            self.assertIsNone(result['cohort_median_seconds'])
            self.assertEqual(validate(result, 'speed-metric.schema.json'), [])

    def test_odd_cohort_and_duplicate_rejection(self):
        cohort = [self.member('a', 1), self.member('b', 8), self.member('c', 99)]
        self.assertEqual(derive_speed(self.cycle, self.speed, cohort)['cohort_median_seconds'], 8)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            derive_speed(self.cycle, self.speed, [cohort[0], cohort[0]])

    def test_fractional_median_explicitly_unsupported(self):
        with self.assertRaises(UnsupportedMetricValue):
            derive_speed(self.cycle, self.speed, [self.member('a', 7200), self.member('b', 7201)])

    def test_duration_boundaries_and_no_truncation(self):
        for updates in ({'duration_seconds': 1}, {'end_status': 'Done'},
                        {'ready_for_approval_at': '2026-09-01T11:00:00.5Z'}):
            cycle = {**self.cycle, **updates}
            with self.assertRaises(ValueError):
                derive_speed(cycle, self.speed)

    def test_deadline_before_equal_after_and_offsets(self):
        for eta, expected in [('2026-09-01T11:30:00Z', 'on_time'),
                              ('2026-09-01T11:00:00Z', 'on_time'),
                              ('2026-09-01T13:00:00+02:00', 'on_time'),
                              ('2026-09-01T10:59:59Z', 'late')]:
            with self.subTest(eta=eta):
                cycle = {**self.cycle, 'requested_eta': eta}
                result = derive_deadline(cycle, self.deadline)
                self.assertEqual(result['result'], expected)
                self.assertEqual(validate(result, 'deadline-metric.schema.json'), [])
                self.assertEqual(result['evidence']['source_values']['work_cycle']['requested_eta'], eta)
        self.assertIsNone(derive_deadline({**self.cycle, 'requested_eta': None}, self.deadline))

    def test_quality_only_approved_monday_mapping_and_neutral_revisions(self):
        original = derive_quality(self.cycle, self.quality, self.mapping)
        self.assertEqual(validate(original, 'quality-metric.schema.json'), [])
        self.assertEqual(original['performance_label'], 'Meets Expectations')
        for context in (None, {'count': 1000, 'ai_score': -99}):
            changed = derive_quality({**self.cycle, 'revision_context': context}, self.quality, self.mapping)
            self.assertEqual(changed.pop('revision_context'), context)
            self.assertEqual(changed, {k: v for k, v in original.items() if k != 'revision_context'})
        for mapping in (replace(self.mapping, approved=False), replace(self.mapping, version=''),
                        replace(self.mapping, board_id='other'), replace(self.mapping, column_id='other')):
            with self.assertRaises(ValueError):
                derive_quality(self.cycle, self.quality, mapping)
        for value in ('unknown-id', 'Meets Expectations', None, 1):
            evidence = {**self.quality, 'source_values': {'performance_label': value}}
            with self.assertRaises(ValueError):
                derive_quality(self.cycle, evidence, self.mapping)

    def test_source_identity_and_required_events(self):
        for field, value in [('source', 'ai'), ('monday_item_id', 'other'), ('event_ids', [])]:
            with self.assertRaises(ValueError):
                derive_speed(self.cycle, {**self.speed, field: value})
        with self.assertRaisesRegex(ValueError, 'boundary'):
            derive_speed(self.cycle, {**self.speed, 'event_ids': ['unrelated']})
        with self.assertRaisesRegex(ValueError, 'Ready For Approval'):
            derive_deadline(self.cycle, {**self.deadline, 'event_ids': ['unrelated']})

    def test_determinism_and_no_input_or_output_alias_mutation(self):
        before = deepcopy((self.cycle, self.speed, self.deadline, self.quality, self.mapping.labels))
        for derive, evidence, extra in ((derive_speed, self.speed, ()), (derive_deadline, self.deadline, ()),
                                        (derive_quality, self.quality, (self.mapping,))):
            result = derive(self.cycle, evidence, *extra)
            self.assertEqual(result, derive(self.cycle, evidence, *extra))
            result['evidence']['source_values'].clear()
        self.assertEqual(before, (self.cycle, self.speed, self.deadline, self.quality, self.mapping.labels))


if __name__ == '__main__':
    unittest.main()
