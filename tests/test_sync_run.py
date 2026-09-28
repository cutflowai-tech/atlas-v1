"""One-shot production sync orchestration (Task 4): fake Monday only, never the real API."""

import functools
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import monday_factory as mf
from test_ingest import FakeMonday, items, project_logs

from atlas_commander.contracts import validate
from atlas_commander.profile import ProfileError
from atlas_monday_probe import client as monday_client
from atlas_monday_probe.client import HttpFailure
from atlas_sync import __main__ as sync_cli
from atlas_sync import run as sync
from atlas_sync.config import MAX_DURATION_ENV, ConfigError, load_sync_config

TOKEN = "tok-SYNC-DO-NOT-LEAK-9d41"
HISTORY = "2026-08-15T00:00:00Z"
T0 = datetime(2026, 9, 20, 12, 30, 45, tzinfo=timezone.utc)
PUBLISHED_PAGE = b"<html>published dashboard from an earlier sync</html>"


class Clock:
    """Deterministic wall clock: each call advances by ``step``."""

    def __init__(self, start=T0, step=timedelta(hours=1)):
        self.now, self.step = start, step

    def __call__(self):
        value = self.now
        self.now += self.step
        return value


class Monotonic:
    """Deterministic monotonic clock; tests move it forward explicitly (``advance``) or per call (``per_call``)."""

    def __init__(self, per_call=0.0):
        self.value, self.per_call = 1000.0, per_call

    def __call__(self):
        self.value += self.per_call
        return self.value

    def advance(self, seconds):
        self.value += seconds


class Faulty:
    def __init__(self, inner, at, error, times=1):
        self.inner, self.at, self.error, self.times, self.calls = inner, at, error, times, 0

    def __call__(self, query, variables):
        self.calls += 1
        if self.at <= self.calls < self.at + self.times:
            raise self.error
        return self.inner(query, variables)


def logs():
    """Two projects: item 1 by Editor label 6, item 2 by Editor label 12 (both mapped in contract 1.4.0)."""
    second = [log if not log["id"].startswith("ed-") else mf.editor("ed-2", "2", "2026-09-01T09:00:00Z", [12])
              for log in project_logs("2", "2026-09-03T10:00:00Z", "2026-09-04T10:00:00Z")]
    return project_logs("1", "2026-09-01T10:00:00Z", "2026-09-01T22:00:00Z") + second


def tree(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


class SyncRunTests(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="atlas-sync-"))
        assert not any((parent / ".git").exists() for parent in [self.data, *self.data.parents])
        self.env = {"MONDAY_API_TOKEN": TOKEN, "ATLAS_DATA_DIR": str(self.data), "ATLAS_HISTORY_START": HISTORY}
        self.raw, self.builds, self.publish = self.data / "raw" / "monday", self.data / "builds", self.data / "published"
        (self.publish / "current").mkdir(parents=True)
        (self.publish / "current" / "dashboard.html").write_bytes(PUBLISHED_PAGE)
        self.published_before = tree(self.publish)
        self.fake = FakeMonday(logs(), items())

    def tearDown(self):
        self.assertEqual(tree(self.publish), self.published_before, "a sync attempt modified the published location")

    def attempt(self, transport=None, **kwargs):
        options = {"clock": Clock(), "monotonic": Monotonic(), "sleep": lambda seconds: None, **kwargs}
        return sync.run_once(self.env, transport=transport or self.fake, **options)

    def assert_failed_without_marker(self, result, stage, category):
        self.assertEqual((result.status, result.failing_stage, result.error_category), ("failed", stage, category))
        self.assertIsNone(result.editor_count)
        self.assertFalse(result.published)
        if result.staged_build_dir:
            build = Path(result.staged_build_dir)
            self.assertFalse((build / sync.COMPLETE_NAME).exists())
            self.assertEqual(sync.build_state(build), "failed")
            record = json.loads((build / sync.FAILED_NAME).read_text())
            self.assertEqual((record["status"], record["failing_stage"], record["error_category"]), ("failed", stage, category))
        record = json.loads(Path(result.attempt_record).read_text())
        self.assertEqual(record["status"], "failed")

    # 1, 9, 10 — happy path, publish location untouched, completion marker
    def test_1_happy_path_produces_a_completed_staged_build(self):
        result = self.attempt()
        self.assertEqual(result.status, "success", result.as_dict())
        self.assertEqual(sync.exit_code(result), 0)
        self.assertIsNone(result.failing_stage)
        build = Path(result.staged_build_dir)
        self.assertEqual(build, (self.builds / result.attempt_id).resolve())
        self.assertEqual(sync.build_state(build), "complete")
        self.assertEqual(sorted(p.name for p in build.iterdir()), ["COMPLETE.json", "build.json", "site"])
        self.assertEqual(sorted(tree(build / "site")), ["dashboard.html", "dashboard.json", "profiles/editor-label-12.html",
                                                        "profiles/editor-label-12.json", "profiles/editor-label-6.html", "profiles/editor-label-6.json"])
        marker = json.loads((build / "COMPLETE.json").read_text())
        self.assertEqual((marker["status"], marker["attempt_id"], marker["source_run_id"], marker["published"]),
                         ("complete", result.attempt_id, result.source_run_id, False))
        self.assertEqual(marker["build_metadata_sha256"], sync._sha256((build / "build.json").read_bytes()))
        self.assertTrue(result.verification["passed"])
        self.assertEqual(json.loads(Path(result.attempt_record).read_text()), result.as_dict() | {"attempt_record": None})
        self.assertEqual(Path(result.attempt_record).parent, (self.builds / "attempts").resolve())
        self.assertTrue(all("mutation" not in query.lower() for query in self.fake.queries))

    # 2 — the exact ingestion run of this attempt is the build input
    def test_2_build_input_is_the_run_this_attempt_created(self):
        earlier = self.attempt()                                           # a complete, verified run from an earlier attempt
        decoy = self.raw / "29991231T235959Z-ffffffffffff"                 # sorts after every real run; must never be picked
        decoy.mkdir()
        result = self.attempt(clock=Clock(start=T0 + timedelta(days=1)))
        self.assertEqual(result.status, "success")
        self.assertNotIn(result.source_run_id, {earlier.source_run_id, decoy.name})
        metadata = json.loads((Path(result.staged_build_dir) / "build.json").read_text())
        manifest = json.loads((self.raw / result.source_run_id / "manifest.json").read_text())
        self.assertEqual(metadata["source"]["run_id"], manifest["run"]["run_id"])
        self.assertEqual(metadata["source"]["extract_sha256"], manifest["extract"]["sha256"])
        self.assertEqual(metadata["source"]["raw_run_dir"], str((self.raw / result.source_run_id).resolve()))
        profile = json.loads((Path(result.staged_build_dir) / "site/profiles/editor-label-6.json").read_text())
        self.assertEqual(profile["source"]["retrieved_at"], manifest["retrieved_at"])

    # 3 — Monday failure stops before verification and build
    def test_3_monday_failure_stops_before_verification_and_build(self):
        failing = Faulty(self.fake, at=3, error=HttpFailure(400, b'{"errors":[{"message":"Field x missing"}]}'))
        with mock.patch.object(sync, "verify", wraps=sync.verify) as verify:
            result = self.attempt(transport=failing)
        self.assert_failed_without_marker(result, "ingestion", "permanent_api")
        verify.assert_not_called()
        self.assertIsNone(result.staged_build_dir)
        self.assertFalse(any(p.name != "attempts" for p in self.builds.iterdir()))
        raw_run = Path(result.raw_run_dir)                                  # Task 3 failure evidence is kept
        self.assertEqual(raw_run.name, result.source_run_id)
        self.assertEqual(json.loads((raw_run / "FAILED.json").read_text())["failure"]["category"], "permanent_api")
        self.assertFalse((raw_run / "manifest.json").exists())
        self.assertEqual(sync.exit_code(result), sync.EXIT_MONDAY)

    # 4 — verification failure stops before any profile or dashboard is built
    def test_4_verification_failure_stops_before_the_build(self):
        real = sync.ingest_run

        def ingest_then_corrupt(*args, **kwargs):
            manifest = real(*args, **kwargs)
            (Path(args[4]) / manifest["run"]["run_id"] / ".extract.json.1.abc.staging").write_bytes(b"{}")
            return manifest

        with mock.patch.object(sync, "ingest_run", ingest_then_corrupt), mock.patch.object(sync, "build_profiles") as profiles, \
                mock.patch.object(sync, "build_dashboard_files") as dashboard:
            result = self.attempt()
        self.assert_failed_without_marker(result, "verification", "verification_failed")
        profiles.assert_not_called()
        dashboard.assert_not_called()
        self.assertIsNone(result.staged_build_dir)
        self.assertFalse(result.verification["passed"])
        self.assertTrue(any("staging" in failure for failure in result.verification["failures"]))
        self.assertEqual(sync.exit_code(result), sync.EXIT_VERIFICATION)

    # 5 — profile generation failure
    def test_5_profile_generation_failure_fails_the_attempt(self):
        with mock.patch.object(sync, "build_profiles", side_effect=ProfileError("profile violates schema")), \
                mock.patch.object(sync, "build_dashboard_files") as dashboard:
            result = self.attempt()
        self.assert_failed_without_marker(result, "profiles", "profile_generation")
        dashboard.assert_not_called()
        self.assertEqual(sync.exit_code(result), sync.EXIT_BUILD)

    # 6 — dashboard generation failure
    def test_6_dashboard_generation_failure_fails_the_attempt(self):
        with mock.patch.object(sync, "build_dashboard_files", side_effect=RuntimeError("renderer broke")):
            result = self.attempt()
        self.assert_failed_without_marker(result, "dashboard", "dashboard_generation")
        site = Path(result.staged_build_dir) / "site"
        self.assertTrue((site / "profiles/editor-label-6.json").exists())    # partial output kept for diagnosis
        self.assertFalse((Path(result.staged_build_dir) / "build.json").exists())

    # 7 — build validation failure
    def test_7_build_validation_failure_fails_the_attempt(self):
        real = sync.build_dashboard_files

        def truncating(result, contract, site, *args, **kwargs):
            document = real(result, contract, site, *args, **kwargs)
            (site / "dashboard.html").write_text("")
            (site / "profiles" / "editor-label-6.json").write_text(json.dumps({"contract_version": "1.4.0"}))
            return document

        with mock.patch.object(sync, "build_dashboard_files", truncating):
            result = self.attempt()
        self.assert_failed_without_marker(result, "validation", "build_validation")
        self.assertFalse((Path(result.staged_build_dir) / "build.json").exists())

    def test_7b_validation_catches_missing_unexpected_and_foreign_artifacts(self):
        result = self.attempt()
        build = Path(result.staged_build_dir)
        site = build / "site"
        extract = json.loads((Path(result.raw_run_dir) / "extract.json").read_text())
        manifest = json.loads((Path(result.raw_run_dir) / "manifest.json").read_text())
        contract = load_sync_config(self.env, now=T0).contract()
        reconstruction = sync.reconstruct_extract(extract, contract)
        sync.validate_site(site, reconstruction, contract, extract, manifest, TOKEN.encode())    # the real build passes
        copy = Path(tempfile.mkdtemp(prefix="atlas-site-"))
        for name, data in tree(site).items():
            (copy / name).parent.mkdir(parents=True, exist_ok=True)
            (copy / name).write_bytes(data)
        (copy / "profiles/editor-label-12.html").unlink()
        (copy / "notes.txt").write_text(f"debug {TOKEN}")
        with self.assertRaises(sync.BuildValidationError) as caught:
            sync.validate_site(copy, reconstruction, contract, {**extract, "retrieved_at": "2020-01-01T00:00:00Z"}, manifest, TOKEN.encode())
        problems = "\n".join(caught.exception.problems)
        for expected in ("missing required artifact profiles/editor-label-12.html", "unexpected artifact notes.txt",
                         "contains the Monday token", "does not come from source run", "dashboard.json does not come from the source run"):
            self.assertIn(expected, problems)
        self.assertNotIn(TOKEN, problems)

    # 8, 11 — failed and incomplete builds never look complete; publish location untouched (tearDown)
    def test_8_and_11_failed_or_incomplete_builds_have_no_marker(self):
        with mock.patch.object(sync, "build_dashboard_files", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.attempt()
        (build,) = [p for p in self.builds.iterdir() if p.name != "attempts"]
        self.assertEqual(sync.build_state(build), "failed")
        self.assertEqual(json.loads((build / "FAILED.json").read_text())["error_category"], "interrupted")
        crashed = self.builds / "20260920T000000Z-000000000000"             # e.g. killed before any marker was written
        (crashed / "site").mkdir(parents=True)
        self.assertEqual(sync.build_state(crashed), "incomplete")

    # 12, 13, 14, 15 — build metadata
    def test_12_to_15_build_metadata(self):
        result = self.attempt()
        build = Path(result.staged_build_dir)
        metadata = json.loads((build / "build.json").read_text())
        manifest = json.loads((Path(result.raw_run_dir) / "manifest.json").read_text())
        self.assertEqual(metadata["source"]["run_id"], result.source_run_id)                                    # 12
        self.assertEqual(metadata["attempt"]["attempt_id"], result.attempt_id)
        self.assertEqual(metadata["attempt"]["sync_started_at"], result.started_at)
        self.assertEqual(metadata["contract_version"], "1.4.0")                                                 # 13
        self.assertEqual(metadata["monday"], {"board_id": mf.BOARD, "api_version": "2025-04"})
        self.assertEqual(metadata["source"]["coverage"], {"history_start": HISTORY, "history_end": manifest["run"]["started_at"]})
        self.assertEqual(metadata["source"]["coverage"], manifest["coverage"])
        self.assertEqual(metadata["verification"], {"passed": True, "status": "complete", "require_production": True,
                                                    "raw_files_checked": len(manifest["raw_files"]) + 1})
        self.assertEqual((metadata["editor_count"], result.editor_count), (2, 2))                               # 14
        self.assertEqual([e["editor_id"] for e in metadata["editors"]], ["editor-label-12", "editor-label-6"])
        dashboard = json.loads((build / "site/dashboard.json").read_text())
        self.assertEqual(len(dashboard["editors"]), metadata["editor_count"])
        self.assertEqual(metadata["counts"]["completed_cycles"], 2)
        self.assertEqual(metadata["counts"]["projects"], 2)
        self.assertEqual(metadata["counts"]["items"], manifest["counts"]["items"])
        self.assertEqual(set(metadata["exclusions"]), {"quarantined_status_logs", "rejected_logs", "completed_not_attributed_by_reason",
                                                       "cycle_exclusions_by_reason"})
        files = metadata["artifacts"]["files"]                                                                   # 15
        self.assertEqual(set(files), set(tree(build / "site")))
        for name, record in files.items():
            data = (build / "site" / name).read_bytes()
            self.assertEqual((record["sha256"], record["size_bytes"]), (sync._sha256(data), len(data)), name)
        self.assertEqual((metadata["artifacts"]["root"], metadata["artifacts"]["entry"], metadata["published"]), ("site", "dashboard.html", False))

    # 16 — no token anywhere, through the real HTTPS code path
    def test_16_no_artifact_record_or_output_contains_the_token(self):
        seen = []

        def urlopen(request, timeout):
            seen.append(request.get_header("Authorization"))
            payload = json.loads(request.data)
            return io.BytesIO(self.fake(payload["query"], payload["variables"]))

        out = io.StringIO()
        with mock.patch.object(monday_client.urllib.request, "urlopen", urlopen), mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(sync_cli, "run_once", functools.partial(sync.run_once, clock=Clock())), redirect_stdout(out):
            self.assertEqual(sync_cli.main(["run-once", "--json"]), 0)
        self.assertEqual(set(seen), {TOKEN})                                  # the token was really used, only in the header
        with mock.patch.object(monday_client.urllib.request, "urlopen", urlopen):
            failed = sync.run_once(self.env, clock=Clock(start=T0 + timedelta(days=1)),
                                   max_duration_seconds=10, monotonic=Monotonic(per_call=4))
        self.assertEqual(failed.status, "failed")
        files = [p for p in self.data.rglob("*") if p.is_file()]
        self.assertTrue(any(p.name == "COMPLETE.json" for p in files) and any(p.name == "build.json" for p in files))
        for path in files:
            self.assertNotIn(TOKEN.encode(), path.read_bytes(), path)
            self.assertNotIn(b"Authorization", path.read_bytes(), path)
        self.assertNotIn(TOKEN, out.getvalue())
        self.assertNotIn(TOKEN, json.dumps(failed.as_dict()) + sync.summary(failed))

    # 17 — same-second attempts never collide
    def test_17_attempts_in_the_same_second_never_collide(self):
        first = self.attempt(clock=Clock(step=timedelta(0)))
        second = self.attempt(transport=FakeMonday(logs(), items()), clock=Clock(step=timedelta(0)))
        self.assertEqual((first.status, second.status), ("success", "success"))
        self.assertEqual(first.attempt_id[:16], second.attempt_id[:16])
        self.assertNotEqual(first.attempt_id, second.attempt_id)
        self.assertNotEqual(first.source_run_id, second.source_run_id)
        self.assertNotEqual(first.staged_build_dir, second.staged_build_dir)
        forced = self.attempt(transport=FakeMonday(logs(), items()), attempt_id_factory=lambda started: first.attempt_id)
        self.assertEqual((forced.status, forced.failing_stage, forced.error_category), ("failed", "build_directory", "build_directory"))
        self.assertIsNone(forced.staged_build_dir)
        self.assertEqual(sync.build_state(Path(first.staged_build_dir)), "complete")      # the earlier build is untouched
        self.assertIsNone(forced.attempt_record)                                           # its record name is taken; never overwritten

    # 18, 19 — time budget
    def test_18_budget_is_enforced_between_major_stages(self):
        mono = Monotonic()
        real = sync.build_profiles

        def slow_profiles(*args, **kwargs):
            profiles = real(*args, **kwargs)
            mono.advance(7200)
            return profiles

        with mock.patch.object(sync, "build_profiles", slow_profiles), mock.patch.object(sync, "build_dashboard_files") as dashboard:
            result = self.attempt(monotonic=mono)
        self.assert_failed_without_marker(result, "dashboard", "timeout")
        dashboard.assert_not_called()                                        # the next stage never started
        self.assertEqual(sync.exit_code(result), sync.EXIT_TIMEOUT)
        self.assertGreaterEqual(result.duration_seconds, 7200)

    def test_18b_default_budget_comes_from_configuration(self):
        self.assertEqual(load_sync_config(self.env, now=T0).max_sync_duration_seconds, 7200)
        self.assertEqual(load_sync_config({**self.env, MAX_DURATION_ENV: "900"}, now=T0).max_sync_duration_seconds, 900)
        for bad in ("0", "59", "86401", "soon"):
            with self.assertRaises(ConfigError):
                load_sync_config({**self.env, MAX_DURATION_ENV: bad}, now=T0)
        mono = Monotonic()
        with mock.patch.object(sync, "build_profiles", side_effect=lambda *a, **k: mono.advance(900) or ([], {})):
            result = sync.run_once({**self.env, MAX_DURATION_ENV: "900"}, transport=self.fake, clock=Clock(), monotonic=mono)
        self.assertEqual((result.failing_stage, result.error_category), ("dashboard", "timeout"))

    def test_19_timeout_during_ingestion_is_recorded_safely(self):
        result = self.attempt(max_duration_seconds=30, monotonic=Monotonic(per_call=2))   # budget runs out between Monday requests
        self.assert_failed_without_marker(result, "ingestion", "timeout")
        raw_failure = json.loads((Path(result.raw_run_dir) / "FAILED.json").read_text())
        self.assertEqual(raw_failure["failure"]["category"], "timeout")
        self.assertIsNone(result.staged_build_dir)
        record_text = Path(result.attempt_record).read_text()
        self.assertNotIn("exhausted", record_text)                          # no exception text, only the category
        self.assertEqual(json.loads(record_text)["error_type"], "SyncTimeout")
        slept = []                                                          # a retry wait longer than the budget left is never started
        retry_later = HttpFailure(503, b'{"errors":[{"message":"busy","extensions":{"code":"INTERNAL_SERVER_ERROR","retry_in_seconds":120}}]}')
        result = self.attempt(transport=Faulty(FakeMonday(logs(), items()), at=1, error=retry_later), max_duration_seconds=60,
                              sleep=slept.append, clock=Clock(start=T0 + timedelta(days=1)))
        self.assertEqual((result.failing_stage, result.error_category, slept), ("ingestion", "timeout", []))

    # 20, 21 — CLI
    def test_20_cli_returns_zero_only_for_a_completed_staged_build(self):
        out = io.StringIO()
        with mock.patch.object(sync_cli, "run_once", functools.partial(sync.run_once, self.env, transport=self.fake, clock=Clock())), \
                redirect_stdout(out):
            self.assertEqual(sync_cli.main(["run-once"]), 0)
        text = out.getvalue()
        self.assertIn("SYNC SUCCEEDED", text)
        self.assertIn("NOT PUBLISHED", text)
        self.assertIn("Editors built:  2", text)

    def test_21_cli_returns_non_zero_on_failed_sync(self):
        cases = [({k: v for k, v in self.env.items() if k != "MONDAY_API_TOKEN"}, self.fake, sync.EXIT_ACCESS, "configuration"),
                 (self.env, Faulty(self.fake, at=1, error=HttpFailure(401, b'{"errors":[{"message":"Not Authenticated"}]}')), sync.EXIT_ACCESS, "ingestion"),
                 (self.env, Faulty(FakeMonday(logs(), items()), at=2, error=HttpFailure(400, b"{}")), sync.EXIT_MONDAY, "ingestion")]
        for env, transport, code, stage in cases:
            out = io.StringIO()
            with mock.patch.object(sync_cli, "run_once", functools.partial(sync.run_once, env, transport=transport, clock=Clock())), \
                    redirect_stdout(out):
                self.assertEqual(sync_cli.main(["run-once"]), code, stage)
            self.assertIn(f"failed at stage: {stage}", out.getvalue())
            self.assertIn("NOT PUBLISHED", out.getvalue())
            self.assertNotIn(TOKEN, out.getvalue())
        self.assertFalse(any(p.name != "attempts" for p in self.builds.iterdir()))

    # 22 — the existing profile schema validation holds for staged profiles
    def test_22_staged_profiles_satisfy_the_existing_schema(self):
        result = self.attempt()
        for path in sorted((Path(result.staged_build_dir) / "site/profiles").glob("*.json")):
            profile = json.loads(path.read_text())
            self.assertEqual(profile["contract_version"], "1.4.0")
            self.assertEqual(validate(profile, "editor-profile-v1.4.schema.json"), [], path.name)

    # Architectural guard: the orchestrator has no way to reach the publish location.
    def test_orchestrator_never_references_the_publish_location(self):
        for module in (sync, sync_cli):
            source = Path(module.__file__).read_text()
            self.assertNotIn("publish_dir", source)
            self.assertNotIn("PUBLISH_DIR", source)
            self.assertNotIn("current", source.replace("currently", ""))


if __name__ == "__main__":
    unittest.main()
