import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas_monday.probe import BOARD, QUERY, ProbeError, activity_probe, snapshot_report, store_raw


class MondayProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_probe(self, transport, **kwargs):
        return activity_probe(self.root, 'secret', '2026-07', ['123'],
                              '2026-07-01T00:00:00Z', '2026-07-26T00:00:00Z', transport, **kwargs)

    def response(self, events):
        return json.dumps({'data': {'boards': [{'id': BOARD, 'activity_logs': events}]}}).encode()

    def event(self):
        return {'id': '9007199254740993', 'created_at': '17850000001234567', 'data': '{"pulse_id":123}',
                'entity': 'pulse', 'event': 'update_column_value', 'user_id': '99154021', 'account_id': '99'}

    def test_raw_byte_preservation_exclusive_and_readonly(self):
        payload = b' {"id":9007199254740993,"created_at":"17850000001234567"}\n'
        first = store_raw(self.root, payload)
        path = self.root / first['raw_file']
        self.assertEqual(path.read_bytes(), payload)
        self.assertEqual(path.stat().st_mode & 0o777, 0o400)
        self.assertEqual(store_raw(self.root, payload), first)
        path.chmod(0o600)
        path.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ProbeError, 'integrity'):
            store_raw(self.root, payload)

    def test_reject_raw_inside_git(self):
        (self.root / '.git').write_text('gitdir: somewhere')
        with self.assertRaisesRegex(ProbeError, 'outside git'):
            store_raw(self.root / 'raw', b'secret')

    def test_symlink_cannot_substitute_raw(self):
        import hashlib
        target = self.root / 'other'
        target.write_bytes(b'raw')
        (self.root / (hashlib.sha256(b'raw').hexdigest() + '.raw')).symlink_to(target)
        with self.assertRaises(ProbeError):
            store_raw(self.root, b'raw')

    def test_pagination_preserves_identifiers_timestamps_no_actor_filter(self):
        calls = []
        payload = self.response([self.event()])

        def transport(token, version, variables):
            calls.append(variables)
            return payload if variables['page'] == 1 else self.response([])

        report = self.run_probe(transport)
        self.assertEqual(report['event_count'], 1)
        self.assertEqual([c['page'] for c in calls], [1, 2])
        self.assertEqual(calls[0]['items'], ['123'])
        self.assertNotIn('user_ids', QUERY)
        self.assertTrue(QUERY.startswith('query '))
        self.assertNotIn('mutation', QUERY)
        self.assertEqual((self.root / report['pages'][0]['raw_file']).read_bytes(), payload)
        self.assertNotIn('99154021', json.dumps(report))
        self.assertNotIn('secret', json.dumps(report))
        self.assertEqual(report['metric_outputs'], [])

    def test_errors_and_drift_retain_raw(self):
        for payload in [b'{"errors":[{"message":"secret"}]}', b'not json', self.response(None),
                        self.response([{'id': 12}]), b'{"data":{"boards":[]}}']:
            with self.subTest(payload=payload):
                with self.assertRaises(ProbeError) as error:
                    self.run_probe(lambda *args, payload=payload: payload)
                self.assertNotIn('secret', str(error.exception))
                self.assertIn(payload, [p.read_bytes() for p in self.root.glob('*.raw')])

    def test_duplicate_and_page_cap_fail_closed(self):
        with self.assertRaisesRegex(ProbeError, 'Duplicate'):
            self.run_probe(lambda *args: self.response([self.event()]))
        with self.assertRaisesRegex(ProbeError, 'cap'):
            self.run_probe(lambda *args: self.response([self.event()]), max_pages=1)

    def test_missing_access_and_invalid_scope_do_not_call_transport(self):
        with patch('atlas_monday.probe.fetch') as transport:
            for token, ids, start in [('', ['123'], '2026-07-01T00:00:00Z'),
                                      ('secret', [], '2026-07-01T00:00:00Z'),
                                      ('secret', ['123'], '2026-07-01')]:
                with self.assertRaises(ProbeError):
                    activity_probe(self.root, token, '2026-07', ids, start, '2026-07-26T00:00:00Z', transport)
            transport.assert_not_called()

    def test_snapshot_drift_deterministic_and_redacted(self):
        source = b'''board_id: '5091110326'
## Columns
| `project_status` | Status | `status` | False | `{"labels":{"9":"In Progress","3":"Ready For Approval","1":"Done"}}` |
| `dropdown_mm1emgt8` | Editor Name | `dropdown` | False | `{"labels":[{"name":"Private Person","id":4}]}` |
## Groups
## Items (1 returned)
### Private Client
- **item_id:** `123`
- **updated_at:** `2026-07-25T00:00:00Z`
'''
        report = snapshot_report(source)
        self.assertEqual(report, snapshot_report(source))
        self.assertEqual(report['observed_items'], 1)
        self.assertEqual(report['status_labels_outside_contract'], ['Done'])
        self.assertNotIn('Private', json.dumps(report))
        self.assertEqual(report['metric_outputs'], [])
        with self.assertRaises(ProbeError):
            snapshot_report(source.replace(b'5091110326', b'other'))


if __name__ == '__main__':
    unittest.main()
