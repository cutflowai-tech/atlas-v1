"""Read-only ingestion against a fake Monday transport (no network, no token)."""

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import monday_factory as mf

from atlas_commander import ingest as ing
from atlas_commander.pipeline import reconstruct_cycles
from atlas_commander.profile_cli import main as profile_cli
from atlas_commander.runtime import load_contract
from atlas_monday_probe.client import ReadOnlyMondayClient, ReadOnlyViolation
from atlas_monday_probe.raw_store import RawStoreError

COLUMNS = [mf.STATUS, mf.EDITOR, mf.VIDEO_TYPE, mf.ETA, mf.ISSUES, "dropdown_mm3tyvvc"]


def outside_git() -> Path:
    directory = Path(tempfile.mkdtemp(prefix="atlas-ingest-"))
    assert not any((parent / ".git").exists() for parent in [directory, *directory.parents])
    return directory / "run"


def project_logs(item, start, end):
    return [mf.create_pulse(f"cp-{item}", item, "2026-09-01T08:00:00Z", {mf.VIDEO_TYPE: {"chosenValues": [{"id": 4, "name": "Class A"}]}}),
            mf.editor(f"ed-{item}", item, "2026-09-01T09:00:00Z", [6]),
            mf.eta(f"eta-{item}", item, "2026-09-01T09:05:00Z", "2026-09-02", "20:00:00"),
            mf.status(f"s1-{item}", item, start, "Create File", "In Progress"),
            mf.status(f"s2-{item}", item, end, "In Progress", "Ready For Approval"),
            {"id": f"name-{item}", "event": "update_name", "user_id": mf.SHARED, "account_id": "1", "created_at": mf.ticks(start), "data": "{}"}]


class FakeMonday:
    """Serves Monday-shaped responses from a list of logs and items; records every query."""

    def __init__(self, logs, items, page_size=2):
        self.logs, self.items, self.page_size, self.queries = logs, items, page_size, []

    def _column(self, log):
        data = json.loads(log["data"])
        return data.get("column_id")

    def __call__(self, query, variables):
        self.queries.append(query)
        if "columns(ids:" in query:
            return json.dumps({"data": {"boards": [{"id": mf.BOARD, "name": "SYNTHETIC", "columns": [{"id": c, "title": c, "type": "x", "settings_str": "{}"} for c in COLUMNS]}]}}).encode()
        if "activity_logs" in query:
            since, until = re.search(r'from: "([^"]+)", to: "([^"]+)"', query).groups()
            page = int(re.search(r"page: (\d+)", query).group(1))
            lo, hi = mf.ticks(since), mf.ticks(until)
            selected = [log for log in self.logs if lo <= log["created_at"] < hi]
            if "column_ids" in query:
                wanted = json.loads(re.search(r"column_ids: (\[[^\]]*\])", query).group(1))
                selected = [log for log in selected if log["event"] == "update_column_value" and self._column(log) in wanted]
            selected.sort(key=lambda log: log["created_at"], reverse=True)
            chunk = selected[(page - 1) * self.page_size: page * self.page_size]
            return json.dumps({"data": {"boards": [{"activity_logs": chunk}]}}).encode()
        if "next_items_page" in query:
            return json.dumps({"data": {"next_items_page": {"cursor": None, "items": self.items[1:]}}}).encode()
        if "items_page" in query:
            return json.dumps({"data": {"boards": [{"items_page": {"cursor": "c2" if len(self.items) > 1 else None, "items": self.items[:1]}}]}}).encode()
        raise AssertionError(f"unexpected query {query}")


def items():
    return [{"id": item, "created_at": created, "board": {"id": mf.BOARD}, "group": {"id": "g"},
             "column_values": [{"id": mf.ETA, "type": "date", "text": "", "value": json.dumps({"date": "2026-09-02", "time": "21:00:00"})}]}
            for item, created in (("1", "2026-09-01T08:00:00Z"), ("2", "2026-08-01T08:00:00Z"))]


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.logs = project_logs("1", "2026-09-01T10:00:00Z", "2026-09-01T22:00:00Z") + project_logs("2", "2026-09-03T10:00:00Z", "2026-09-04T10:00:00Z")
        self.fake = FakeMonday(self.logs, items())
        self.client = ReadOnlyMondayClient(self.fake)
        self.raw = outside_git()

    def run_ingest(self, since="2026-08-15T00:00:00Z", until="2026-09-10T00:00:00Z"):
        return ing.ingest(self.client, mf.BOARD, COLUMNS, since, until, self.raw)

    def test_ingestion_is_read_only_and_retains_every_raw_response(self):
        manifest = self.run_ingest()
        self.assertTrue(all("mutation" not in query.lower() for query in self.fake.queries))
        stored = {path.name for path in self.raw.iterdir()}
        for record in manifest["raw_files"]:
            self.assertIn(record["name"], stored)
        self.assertEqual(manifest["counts"]["column_logs"], 8)   # 4 tracked updates x 2 items
        self.assertEqual(manifest["counts"]["create_pulse"], 2)
        self.assertEqual(manifest["counts"]["items"], 2)
        self.assertTrue(all(window.get("complete") for window in manifest["windows"]))
        with self.assertRaises(RawStoreError):  # immutable: the same run cannot be silently rewritten
            ing.write_immutable(self.raw, "manifest.json", b"changed")

    def test_extract_feeds_the_pipeline_and_profile(self):
        self.run_ingest()
        extract = json.loads((self.raw / "extract.json").read_text())
        result = reconstruct_cycles(extract["activity"], load_contract(), items_payload=extract["items"], ingestion=extract["ingestion"])
        by_item = {cycle.monday_item_id: cycle for cycle in result.cycles}
        self.assertEqual((by_item["1"].editor_id, by_item["1"].cohort_key, by_item["1"].video_type_source), ("editor-label-6", "4", "create_pulse"))
        self.assertEqual(by_item["1"].requested_eta, "2026-09-02T21:00:00Z")  # current item value is the latest ETA
        with tempfile.TemporaryDirectory() as out:
            self.assertEqual(profile_cli(["build", str(self.raw / "extract.json"), "editor-label-6", out, "--generated-at", "2026-09-28T00:00:00Z"]), 0)
            self.assertEqual(json.loads((Path(out) / "editor-label-6.json").read_text())["coverage"]["completed_projects"], 2)

    def test_history_is_complete_only_for_items_created_inside_the_window(self):
        self.run_ingest()
        extract = json.loads((self.raw / "extract.json").read_text())
        self.assertEqual(extract["ingestion"]["complete_history_item_ids"], ["1"])
        result = reconstruct_cycles(extract["activity"], load_contract(), items_payload=extract["items"], ingestion=extract["ingestion"])
        coverage = {cycle.monday_item_id: cycle.requested_eta_history_coverage["status"] for cycle in result.cycles}
        self.assertEqual(coverage, {"1": "complete", "2": "observed_in_ingested_evidence"})

    def test_capped_windows_are_split_until_complete(self):
        with mock.patch.object(ing, "WINDOW_CAP", 7):
            manifest = self.run_ingest()
        self.assertTrue(any(window.get("split") for window in manifest["windows"]))
        self.assertEqual(manifest["counts"]["column_logs"], 8)

    def test_raw_store_inside_git_is_refused(self):
        with self.assertRaises(RawStoreError):
            ing.ingest(self.client, mf.BOARD, COLUMNS, "2026-08-15T00:00:00Z", "2026-09-10T00:00:00Z", Path(__file__).resolve().parents[1] / "raw")

    def test_client_rejects_writes_and_bad_input(self):
        with self.assertRaises(ReadOnlyViolation):
            self.client.query("mutation { delete_item(item_id: 1) { id } }", {})
        with self.assertRaises(ing.IngestError):
            ing.ingest(self.client, "1; drop", COLUMNS, "2026-08-15T00:00:00Z", "2026-09-10T00:00:00Z", self.raw)
        with self.assertRaises(ing.IngestError):
            ing.ingest(self.client, mf.BOARD, COLUMNS, "2026-08-15", "2026-09-10T00:00:00Z", self.raw)

    def test_missing_token_stops_without_writing(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(ing.main(["--since", "2026-08-15T00:00:00Z", "--raw-dir", str(self.raw)]), 2)
        self.assertFalse(self.raw.exists())


if __name__ == "__main__":
    unittest.main()
