"""Production-hardened ingestion runs: run identity, fixed boundary, failed-run evidence, manifest metadata (fake Monday only)."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import monday_factory as mf
from test_ingest import COLUMNS, FakeMonday, items, project_logs

from atlas_commander import ingest as ing
from atlas_commander.ingest_verify import verify
from atlas_monday_probe import client as monday_client
from atlas_monday_probe.client import AuthenticationFailed, HttpFailure, PermanentApiError, ReadOnlyMondayClient

TOKEN = "tok-DO-NOT-LEAK-3c7e"
HISTORY = "2026-08-15T00:00:00Z"
T0 = datetime(2026, 9, 20, 12, 30, 45, 250000, tzinfo=timezone.utc)   # sub-second on purpose: the boundary is whole seconds


class Clock:
    """Deterministic clock; each call advances by ``step`` so any repeated "now" would be visible."""

    def __init__(self, start=T0, step=timedelta(hours=1)):
        self.now, self.step, self.calls = start, step, 0

    def __call__(self):
        value = self.now
        self.now += self.step
        self.calls += 1
        return value


class Faulty:
    """Wraps a transport and raises ``error`` on the ``at``-th call (1-based), passing every other call through."""

    def __init__(self, inner, at, error, times=1):
        self.inner, self.at, self.error, self.times, self.calls = inner, at, error, times, 0

    def __call__(self, query, variables):
        self.calls += 1
        if self.at <= self.calls < self.at + self.times:
            raise self.error
        return self.inner(query, variables)


def outside_git() -> Path:
    directory = Path(tempfile.mkdtemp(prefix="atlas-runs-"))
    assert not any((parent / ".git").exists() for parent in [directory, *directory.parents])
    return directory


def logs():
    return project_logs("1", "2026-09-01T10:00:00Z", "2026-09-01T22:00:00Z") + project_logs("2", "2026-09-03T10:00:00Z", "2026-09-04T10:00:00Z")


def activity_to_values(queries):
    return [q.split('to: "', 1)[1].split('"', 1)[0] for q in queries if "activity_logs" in q]


class IngestRunTests(unittest.TestCase):
    def setUp(self):
        self.root = outside_git()
        self.fake = FakeMonday(logs(), items())
        self.client = ReadOnlyMondayClient(self.fake, sleep=lambda seconds: None)

    def run_once(self, client=None, clock=None, **kwargs):
        return ing.ingest_run(client or self.client, mf.BOARD, COLUMNS, HISTORY, self.root, clock=clock or Clock(), **kwargs)

    def only_run_dir(self):
        (run,) = [p for p in self.root.iterdir() if p.is_dir()]
        return run

    # 1, 2 — run identity
    def test_1_successful_ingestion_has_a_unique_run_id(self):
        manifest = self.run_once()
        run_id = manifest["run"]["run_id"]
        self.assertRegex(run_id, r"^20260920T123045Z-[0-9a-f]{12}$")
        self.assertEqual(self.only_run_dir().name, run_id)
        self.assertEqual(json.loads((self.root / run_id / "extract.json").read_text())["ingestion"]["run_id"], run_id)

    def test_2_runs_in_the_same_second_never_collide(self):
        first = self.run_once(clock=Clock(step=timedelta(0)))["run"]["run_id"]
        second = self.run_once(client=ReadOnlyMondayClient(FakeMonday(logs(), items())), clock=Clock(step=timedelta(0)))["run"]["run_id"]
        self.assertNotEqual(first, second)
        self.assertEqual(first[:16], second[:16])                         # same second
        self.assertEqual({p.name for p in self.root.iterdir()}, {first, second})
        fake = FakeMonday(logs(), items())
        with self.assertRaisesRegex(ing.IngestError, "already exists"):   # even a forced identical ID cannot reuse a directory
            self.run_once(client=ReadOnlyMondayClient(fake), run_id_factory=lambda started: first)
        self.assertEqual(fake.queries, [])                                # refused before any Monday request
        self.assertTrue(verify(self.root / first, require_production=True)["passed"])

    # 3, 4 — fixed boundary
    def test_3_boundary_is_captured_once_and_reused(self):
        clock = Clock()
        manifest = self.run_once(clock=clock)
        boundary = "2026-09-20T12:30:45Z"
        self.assertEqual((manifest["coverage"]["history_end"], manifest["window"]["until"]), (boundary, boundary))
        self.assertEqual(manifest["run"]["started_at"], boundary)
        self.assertEqual(max(activity_to_values(self.fake.queries)), boundary)       # every window ends at or before it
        self.assertTrue(all(w["until"] <= boundary for w in manifest["windows"]))
        self.assertEqual(clock.calls, 3)                                             # start, items retrieved, finish — never for windows
        self.assertGreater(manifest["retrieved_at"], boundary)

    def test_4_data_after_the_boundary_is_excluded(self):
        after = [mf.status("late-1", "1", "2026-09-20T12:30:45Z", "Sent", "Revisions"),       # exactly at the boundary: next run
                 mf.status("late-2", "1", "2026-09-20T13:00:00Z", "Revisions", "Sent")]
        before = mf.status("early-1", "2", "2026-09-20T12:30:44Z", "Sent", "Revisions")
        fake = FakeMonday([*logs(), *after, before], items())
        self.run_once(client=ReadOnlyMondayClient(fake))
        ids = {log["id"] for log in json.loads((self.only_run_dir() / "extract.json").read_text())["activity"]["boards"][0]["activity_logs"]}
        self.assertIn("early-1", ids)
        self.assertFalse({"late-1", "late-2"} & ids)

    # 5–8 — manifest metadata
    def test_5_to_8_manifest_records_production_metadata(self):
        flaky = Faulty(FakeMonday(logs(), items()), at=2, error=HttpFailure(503))
        client = ReadOnlyMondayClient(flaky, api_version="2025-04", sleep=lambda s: None)
        manifest = self.run_once(client=client)
        self.assertEqual(manifest["monday"], {"api_version": "2025-04", "board_id": mf.BOARD})
        self.assertEqual((manifest["contract_version"], manifest["board_id"], manifest["status"], manifest["ingest_version"]),
                         ("1.4.0", mf.BOARD, "complete", "atlas-ingest-v2"))
        self.assertEqual(manifest["client"]["requests"], flaky.calls)
        self.assertEqual((manifest["client"]["retries"], manifest["client"]["failures_by_category"], manifest["client"]["final_failure_category"]),
                         (1, {"transient_api": 1}, None))
        self.assertEqual(manifest["coverage"], {"history_start": HISTORY, "history_end": "2026-09-20T12:30:45Z"})
        self.assertLessEqual(manifest["run"]["started_at"], manifest["run"]["finished_at"])
        self.assertNotIn("token", json.dumps(manifest).lower().replace("tokens", ""))

    # 9 — no token anywhere
    def test_9_token_never_written_to_any_run_artifact(self):
        fake = FakeMonday(logs(), items())

        def urlopen(request, timeout):
            payload = json.loads(request.data)
            return io.BytesIO(fake(payload["query"], payload["variables"]))

        real = ReadOnlyMondayClient.from_token(TOKEN, sleep=lambda s: None)
        with mock.patch.object(monday_client.urllib.request, "urlopen", urlopen):
            self.run_once(client=real)
        calls = {"n": 0}

        def failing(request, timeout):
            calls["n"] += 1
            if calls["n"] == 3:
                return io.BytesIO(json.dumps({"errors": [{"message": f"bad token {TOKEN}", "extensions": {"code": "UNAUTHENTICATED"}}]}).encode())
            return urlopen(request, timeout)

        with mock.patch.object(monday_client.urllib.request, "urlopen", failing), self.assertRaises(AuthenticationFailed):
            self.run_once(client=ReadOnlyMondayClient.from_token(TOKEN, sleep=lambda s: None))
        files = [p for p in self.root.rglob("*") if p.is_file()]
        self.assertTrue(any(p.name == "manifest.json" for p in files) and any(p.name == "FAILED.json" for p in files))
        for path in files:
            self.assertNotIn(TOKEN.encode(), path.read_bytes(), path.name)
            self.assertNotIn(b"Authorization", path.read_bytes(), path.name)

    # 10–13 — failed runs
    def test_10_failure_before_any_response_is_clearly_failed(self):
        client = ReadOnlyMondayClient(Faulty(self.fake, at=1, error=HttpFailure(401, b'{"errors":[{"message":"Not Authenticated"}]}')))
        with self.assertRaises(AuthenticationFailed) as caught:
            self.run_once(client=client)
        run = self.only_run_dir()
        self.assertEqual(sorted(p.name for p in run.iterdir()), ["FAILED.json"])
        record = json.loads((run / "FAILED.json").read_text())
        self.assertEqual((record["status"], record["failure"]["category"], record["failure"]["stage"], record["raw_files"]),
                         ("failed", "authentication", "columns", []))
        # macOS exposes /var as a symlink to /private/var; compare canonical paths.
        self.assertEqual(caught.exception.atlas_failure_record.resolve(), (run / "FAILED.json").resolve())
        self.assertEqual(verify(run)["status"], "failed")

    def test_11_failure_after_partial_evidence_keeps_it(self):
        error = HttpFailure(400, b'{"errors":[{"message":"Field x missing"}]}')
        client = ReadOnlyMondayClient(Faulty(self.fake, at=6, error=error))
        with self.assertRaises(PermanentApiError):
            self.run_once(client=client)
        run = self.only_run_dir()
        record = json.loads((run / "FAILED.json").read_text())
        kept = {p.name for p in run.iterdir()} - {"FAILED.json"}
        self.assertTrue(kept)
        self.assertEqual({r["name"] for r in record["raw_files"]}, kept)
        for entry in record["raw_files"]:
            self.assertEqual(ing.write_immutable(run, entry["name"], (run / entry["name"]).read_bytes()).sha256, entry["sha256"])
        self.assertIsNotNone(record["failure"]["last_completed_window"])
        self.assertEqual(record["client"]["requests"], 6)

    def test_12_a_failed_run_never_has_a_complete_manifest_extract_pair(self):
        for at in (1, 4, 9):
            root = outside_git()
            client = ReadOnlyMondayClient(Faulty(FakeMonday(logs(), items()), at=at, error=ConnectionResetError("reset"), times=10),
                                          sleep=lambda s: None)
            with self.assertRaises(monday_client.TransportError):
                ing.ingest_run(client, mf.BOARD, COLUMNS, HISTORY, root, clock=Clock())
            (run,) = list(root.iterdir())
            self.assertFalse((run / "manifest.json").exists())
            self.assertFalse((run / "extract.json").exists())
            self.assertFalse(verify(run)["passed"])
        # Failure while committing the manifest: the extract is already on disk, but the run is still marked failed.
        real_write = ing.write_immutable_atomic

        def refuse_manifest(root, name, data):
            if name == "manifest.json":
                raise OSError("disk full")
            return real_write(root, name, data)

        with mock.patch.object(ing, "write_immutable_atomic", refuse_manifest), self.assertRaises(OSError):
            self.run_once()
        run = self.only_run_dir()
        self.assertEqual((run / "extract.json").exists(), True)
        self.assertFalse((run / "manifest.json").exists())
        record = json.loads((run / "FAILED.json").read_text())
        self.assertEqual((record["failure"]["stage"], record["failure"]["extract_written"], record["failure"]["category"]), ("manifest", True, "internal"))
        report = verify(run)
        self.assertFalse(report["passed"])
        self.assertTrue(any("marked failed" in f for f in report["failures"]))

    def test_13_failure_metadata_is_safe(self):
        error = PermanentApiError("SENSITIVE-DETAIL should never be stored")
        with self.assertRaises(PermanentApiError):
            self.run_once(client=ReadOnlyMondayClient(Faulty(self.fake, at=3, error=error)))
        text = (self.only_run_dir() / "FAILED.json").read_text()
        record = json.loads(text)
        self.assertNotIn("SENSITIVE-DETAIL", text)
        self.assertEqual((record["failure"]["category"], record["failure"]["error_type"]), ("permanent_api", "PermanentApiError"))
        self.assertEqual(set(record), {"ingest_version", "status", "run", "coverage", "monday", "contract_version", "failure", "client", "raw_files", "note"})
        self.assertEqual(record["client"]["final_failure_category"], "permanent_api")
        self.assertEqual(record["contract_version"], "1.4.0")
        self.assertEqual(record["monday"]["api_version"], "2025-04")

    # 14, 15 — verification
    def test_14_verify_accepts_a_valid_completed_production_run(self):
        run_id = self.run_once()["run"]["run_id"]
        report = verify(self.root / run_id, require_production=True)
        self.assertTrue(report["passed"], report["failures"])
        self.assertEqual((report["status"], report["run_id"], report["production_metadata"]), ("complete", run_id, True))

    def test_15_verify_rejects_incomplete_or_tampered_production_evidence(self):
        def fresh():
            root = outside_git()
            manifest = ing.ingest_run(ReadOnlyMondayClient(FakeMonday(logs(), items())), mf.BOARD, COLUMNS, HISTORY, root, clock=Clock())
            return root / manifest["run"]["run_id"]

        def rewrite(path, change):
            data = json.loads(path.read_text())
            change(data)
            path.chmod(0o644)
            path.write_text(json.dumps(data))

        cases = {
            "run_id": lambda d: d["run"].update(run_id="20260920T123045Z-000000000000"),
            "status": lambda d: d.update(status="failed"),
            "counters": lambda d: d["client"].update(requests=d["client"]["requests"] + 1),
            "boundary": lambda d: d["coverage"].update(history_end="2026-09-21T00:00:00Z"),
            "contract": lambda d: d.update(contract_version="9.9.9"),
            "api_version": lambda d: d["monday"].update(api_version="latest"),
            "board": lambda d: d["monday"].update(board_id="123"),
        }
        for name, change in cases.items():
            run = fresh()
            rewrite(run / "manifest.json", change)
            self.assertFalse(verify(run)["passed"], name)
        run = fresh()
        (run / "manifest.json").chmod(0o644)
        (run / "manifest.json").unlink()
        self.assertEqual(verify(run)["status"], "incomplete")
        run = fresh()
        (run / ".extract.json.1.abc.staging").write_text("{}")
        self.assertFalse(verify(run)["passed"])
        run = fresh()
        extract = run / "extract.json"
        extract.chmod(0o644)
        extract.write_bytes(extract.read_bytes() + b" ")
        self.assertTrue(any("SHA-256 mismatch" in f for f in verify(run)["failures"]))
        legacy = fresh()
        rewrite(legacy / "manifest.json", lambda d: [d.pop(k) for k in ("run", "coverage", "monday", "contract_version", "client", "status")])
        self.assertTrue(verify(legacy)["passed"], verify(legacy)["failures"])           # older manifests still verify as before...
        self.assertFalse(verify(legacy, require_production=True)["passed"])            # ...but never as production runs

    # 16–18 — existing protections under the production entry point
    def test_16_to_18_split_boundary_and_complete_history_protections_hold(self):
        boundary_log = mf.status("s-boundary", "1", "2026-09-01T00:00:00Z", "Ready For Approval", "Sent")
        extra_items = items() + [{"id": "4", "created_at": "2026-09-20T12:31:00Z", "board": {"id": mf.BOARD}, "group": {"id": "g"},
                                  "column_values": [{"id": mf.ETA, "type": "date", "text": "", "value": None}]}]
        fake = FakeMonday([*logs(), boundary_log], extra_items, inclusive_to=True)
        with mock.patch.object(ing, "WINDOW_CAP", 7), mock.patch("atlas_commander.ingest_verify.WINDOW_CAP", 7):
            manifest = self.run_once(client=ReadOnlyMondayClient(fake))
            report = verify(self.root / manifest["run"]["run_id"], require_production=True)
        self.assertTrue(report["passed"], report["failures"])
        self.assertTrue(any(w.get("split") for w in manifest["windows"]))
        extract = json.loads((self.root / manifest["run"]["run_id"] / "extract.json").read_text())
        ids = [log["id"] for log in extract["activity"]["boards"][0]["activity_logs"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids.count("s-boundary"), 1)
        self.assertEqual(extract["ingestion"]["complete_history_item_ids"], ["1"])      # 2 predates the history, 4 is after the boundary
        self.assertEqual(report["items_created_after_window"], ["4"])

    # 19 — determinism
    def test_19_identical_data_and_boundary_give_identical_evidence(self):
        first = self.run_once(clock=Clock())
        second = self.run_once(client=ReadOnlyMondayClient(FakeMonday(logs(), items())), clock=Clock())
        self.assertNotEqual(first["run"]["run_id"], second["run"]["run_id"])

        def normalized(manifest):
            extract = json.loads((self.root / manifest["run"]["run_id"] / "extract.json").read_text())
            for key in ("retrieved_at", "run_id"):
                extract["ingestion"].pop(key)
            extract.pop("retrieved_at")
            return extract

        self.assertEqual(normalized(first), normalized(second))
        self.assertEqual(first["raw_files"], second["raw_files"])                        # identical raw evidence, byte for byte

        def stable(manifest):
            return {k: v for k, v in manifest.items() if k not in ("run", "retrieved_at", "extract")}

        self.assertEqual(stable(first), stable(second))

    # 20 — per-run counters on a reused client
    def test_20_counters_cover_only_this_run(self):
        for _ in range(3):
            self.client.query(f'query {{ boards(ids: ["{mf.BOARD}"]) {{ id name columns(ids: []) {{ id }} }} }}', {})
        before = len(self.fake.queries)
        manifest = self.run_once()
        self.assertEqual(manifest["client"]["requests"], len(self.fake.queries) - before)
        self.assertEqual(self.client.stats.requests, len(self.fake.queries))
        second = self.run_once()
        self.assertEqual(second["client"]["requests"], manifest["client"]["requests"])

    # CLI
    def test_cli_raw_root_success_and_failure(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = ing.main(["--since", HISTORY, "--raw-root", str(self.root)], client=self.client)
        self.assertEqual(code, 0)
        run_id = json.loads(out.getvalue())["run_id"]
        self.assertTrue(verify(self.root / run_id, require_production=True)["passed"])
        err = io.StringIO()
        failing = ReadOnlyMondayClient(Faulty(FakeMonday(logs(), items()), at=2, error=HttpFailure(403)))
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = ing.main(["--since", HISTORY, "--raw-root", str(self.root)], client=failing)
        self.assertEqual(code, 2)
        self.assertIn("INGESTION_FAILED", err.getvalue())
        self.assertIn("MISSING_ACCESS", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            ing.main(["--since", HISTORY, "--raw-root", str(self.root), "--until", "2026-09-01T00:00:00Z"], client=self.client)

    def test_run_directories_are_listed_without_staging_leftovers(self):
        self.run_once()
        self.assertEqual([name for name in os.listdir(self.only_run_dir()) if name.startswith(".")], [])


if __name__ == "__main__":
    unittest.main()
