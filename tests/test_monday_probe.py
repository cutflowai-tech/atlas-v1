import io
import json
import tempfile
import unittest
from pathlib import Path

from atlas_data.monday_probe import ProbeError, inspect_response, probe, retain


def payload(rows):
    return json.dumps({"data": {"boards": [{"id": "5091110326", "activity_logs": rows}]}}).encode()


ROW = {"id": "00123", "user_id": "007", "created_at": "17849376000000000",
       "data": '{"pulse_id":123,"value":{"label":"Unmapped"}}', "event": "update_column_value", "entity": "pulse"}


class MondayProbeTests(unittest.TestCase):
    def run_probe(self, transport, directory, **kwargs):
        return probe("secret", "5091110326", "2026-07-24T00:00:00Z", "2026-07-25T00:00:00Z",
                     directory, "2026-07", transport=transport, **kwargs)

    def test_read_only_pagination_retains_exact_bytes(self):
        replies = [payload([ROW]), payload([])]
        requests = []

        def send(request, timeout):
            requests.append(json.loads(request.data))
            self.assertEqual(request.full_url, "https://api.monday.com/v2")
            self.assertEqual(timeout, 30)
            return io.BytesIO(replies[len(requests) - 1])

        with tempfile.TemporaryDirectory() as temp:
            result = self.run_probe(send, Path(temp))
            self.assertTrue(result["complete"])
            for raw, page in zip(replies, result["pages"]):
                self.assertEqual((Path(temp) / page["file"]).read_bytes(), raw)
            self.assertEqual(inspect_response(replies[0], "5091110326")[0][0], ROW)
        self.assertEqual([r["variables"]["page"] for r in requests], [1, 2])
        self.assertTrue(all(r["query"].startswith("query ") and "mutation" not in r["query"] for r in requests))
        self.assertNotIn("user_ids", requests[0]["query"])  # Actor is not the evaluated Editor.
        self.assertNotIn("secret", json.dumps(result))

    def test_errors_drift_and_missing_board_fail_closed(self):
        for raw in [b'{"errors":[{"message":"private"}]}', b'{}', payload(None), b'[]']:
            with self.subTest(raw=raw), self.assertRaises(ProbeError):
                inspect_response(raw, "5091110326")
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ProbeError, "drift"):
                self.run_probe(lambda *a, **k: io.BytesIO(payload([{"id": "x"}])), Path(temp))
            self.assertEqual(len(list(Path(temp).glob('*.raw'))), 1)

    def test_bounds_duplicates_transport_and_input(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            send = lambda *a, **k: io.BytesIO(payload([ROW]))
            with self.assertRaisesRegex(ProbeError, "Duplicate"):
                self.run_probe(send, directory)
            with self.assertRaisesRegex(ProbeError, "bound"):
                self.run_probe(send, directory, max_pages=1)
            def fail(*a, **k):
                raise RuntimeError("secret")
            with self.assertRaisesRegex(ProbeError, "suppressed"):
                self.run_probe(fail, directory)
            with self.assertRaises(ProbeError):
                probe('', '1', 'invalid', 'invalid', directory, '2026-07', transport=fail)

    def test_storage_deterministic_exclusive_and_outside_git(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            first = retain(b'exact source', directory)
            self.assertEqual(first, retain(b'exact source', directory))
            self.assertEqual((directory / first['file']).stat().st_mode & 0o777, 0o400)
            (directory / '.git').touch()
            with self.assertRaises(ProbeError):
                retain(b'private', directory / 'nested')
