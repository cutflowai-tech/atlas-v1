"""Production sync configuration and Monday token handling (no network, no real token)."""

import io
import json
import pickle
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from test_ingest import COLUMNS, FakeMonday, items, project_logs

from atlas_commander import ingest as ing
from atlas_commander.ingest import main as ingest_main
from atlas_commander.profile_cli import main as profile_cli
from atlas_commander.runtime import ACTIVE_CONTRACT_VERSION, ROOT, load_contract_version
from atlas_monday_probe import client as monday_client
from atlas_monday_probe.client import DEFAULT_API_VERSION, InvalidMondaySetting, MissingAccess, ReadOnlyMondayClient, ReadOnlyViolation
from atlas_sync.config import REDACTED, ConfigError, Secret, SyncConfig, load_sync_config

TOKEN = "tok-DO-NOT-LEAK-7f3a9c"
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
BOARD = str(load_contract_version(ACTIVE_CONTRACT_VERSION)["source_board"]["board_id"])


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def outside_git() -> Path:
    directory = Path(tempfile.mkdtemp(prefix="atlas-config-"))
    assert not any((parent / ".git").exists() for parent in [directory, *directory.parents])
    return directory


class SyncConfigTests(unittest.TestCase):
    def setUp(self):
        self.data = outside_git()
        self.env = {"ATLAS_DATA_DIR": str(self.data), "MONDAY_API_TOKEN": TOKEN}

    def load(self, **overrides):
        env = {**self.env, **overrides}
        return load_sync_config({k: v for k, v in env.items() if v is not None}, now=NOW)

    def problems(self, **overrides):
        with self.assertRaises(ConfigError) as caught:
            self.load(**overrides)
        self.assertNotIn(TOKEN, str(caught.exception))
        return "\n".join(caught.exception.problems)

    # --- defaults and required values

    def test_defaults_come_from_the_contract_and_validated_runs(self):
        config = self.load()
        self.assertEqual((config.contract_version, config.board_id, config.monday_api_version), (ACTIVE_CONTRACT_VERSION, BOARD, DEFAULT_API_VERSION))
        self.assertEqual((config.raw_dir, config.build_dir, config.publish_dir),
                         (self.data / "raw/monday", self.data / "builds", self.data / "published"))
        self.assertEqual((config.history_start, config.sync_interval_seconds, config.stale_after_seconds, config.max_consecutive_failures),
                         ("2026-02-01T00:00:00Z", 3600, 7200, 3))
        self.assertEqual(config.retention_hours, 96)
        self.assertEqual(config.contract()["source_board"]["board_id"], config.board_id)

    def test_missing_data_directories_fail_clearly(self):
        text = self.problems(ATLAS_DATA_DIR=None)
        for name in ("ATLAS_RAW_DIR", "ATLAS_BUILD_DIR", "ATLAS_PUBLISH_DIR"):
            self.assertIn(f"{name} is required", text)

    def test_explicit_directories_override_the_data_dir(self):
        other = outside_git()
        config = self.load(ATLAS_DATA_DIR=None, ATLAS_RAW_DIR=str(other / "raw"), ATLAS_BUILD_DIR=str(other / "b"), ATLAS_PUBLISH_DIR=str(other / "p"))
        self.assertEqual(config.raw_dir, other / "raw")

    def test_missing_token_fails_closed_only_when_monday_access_is_needed(self):
        config = self.load(MONDAY_API_TOKEN=None)
        self.assertIsNone(config.monday_token)
        with self.assertRaisesRegex(MissingAccess, "MONDAY_API_TOKEN or MONDAY_API_TOKEN_FILE"):
            config.require_monday_token()
        with self.assertRaises(MissingAccess):
            config.monday_client()
        with self.assertRaisesRegex(ConfigError, "MONDAY_API_TOKEN is not set"):
            load_sync_config({"ATLAS_DATA_DIR": str(self.data)}, require_token=True, now=NOW)

    # --- token sources

    def test_token_from_environment(self):
        config = self.load()
        self.assertEqual((config.monday_token.reveal(), config.monday_token_source), (TOKEN, "MONDAY_API_TOKEN"))

    def test_token_from_secret_file(self):
        secret = outside_git() / "monday_api_token"
        secret.write_text(TOKEN + "\n")
        config = self.load(MONDAY_API_TOKEN=None, MONDAY_API_TOKEN_FILE=str(secret))
        self.assertEqual((config.monday_token.reveal(), config.monday_token_source), (TOKEN, "MONDAY_API_TOKEN_FILE"))

    def test_bad_token_sources_fail_without_revealing_the_token(self):
        secret = outside_git() / "monday_api_token"
        secret.write_text(TOKEN)
        self.assertIn("not both", self.problems(MONDAY_API_TOKEN_FILE=str(secret)))
        self.assertIn("does not name a readable file", self.problems(MONDAY_API_TOKEN=None, MONDAY_API_TOKEN_FILE=str(secret) + ".missing"))
        empty = outside_git() / "empty"
        empty.write_text("\n")
        self.assertIn("is empty", self.problems(MONDAY_API_TOKEN=None, MONDAY_API_TOKEN_FILE=str(empty)))
        spaced = outside_git() / "spaced"
        spaced.write_text(f"{TOKEN} {TOKEN}")
        self.assertIn("contains whitespace", self.problems(MONDAY_API_TOKEN=None, MONDAY_API_TOKEN_FILE=str(spaced)))

    # --- the token never leaks

    def test_token_never_appears_in_repr_str_logs_or_serialisation(self):
        config = self.load()
        for text in (repr(config), str(config), repr(config.monday_token), str(config.monday_token), f"{config.monday_token}",
                     f"{config.monday_token:>40}", json.dumps(config.redacted()), repr(config.monday_client())):
            self.assertNotIn(TOKEN, text)
        self.assertEqual(config.redacted()["monday_token"], REDACTED)
        with self.assertRaises(TypeError):
            json.dumps(config.monday_token)
        with self.assertRaises(TypeError):
            pickle.dumps(config.monday_token)
        self.assertEqual(Secret(TOKEN), config.monday_token)

    def test_ingestion_outputs_never_contain_the_token(self):
        """End to end through the real urllib transport (patched): raw files, manifest, extract, profiles and dashboard."""
        fake = FakeMonday(project_logs("1", "2026-09-01T10:00:00Z", "2026-09-01T22:00:00Z"), items())
        seen_headers = []

        def urlopen(request, timeout):
            seen_headers.append(dict(request.header_items()))
            body = json.loads(request.data)
            return _Response(fake(body["query"], body["variables"]))

        config = self.load()
        with mock.patch.object(monday_client.urllib.request, "urlopen", urlopen):
            ing.ingest(config.monday_client(), mf_board(), COLUMNS, "2026-08-15T00:00:00Z", "2026-09-10T00:00:00Z", config.raw_dir / "run")
        self.assertTrue(all(h["Authorization"] == TOKEN for h in seen_headers))   # the token is sent only as the auth header
        out = config.build_dir / "run"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(profile_cli(["dashboard", str(config.raw_dir / "run" / "extract.json"), str(out), "--generated-at", "2026-09-28T00:00:00Z"]), 0)
        written = [p for root in (config.raw_dir, config.build_dir) for p in root.rglob("*") if p.is_file()]
        self.assertTrue(any(p.name == "manifest.json" for p in written) and any(p.name == "dashboard.html" for p in written))
        for path in written:
            self.assertNotIn(TOKEN.encode(), path.read_bytes(), path.name)

    # --- validation of values

    def test_invalid_paths_fail_validation(self):
        self.assertIn("must be an absolute path", self.problems(ATLAS_DATA_DIR="relative/data"))
        self.assertIn("must be an absolute path", self.problems(ATLAS_RAW_DIR="raw"))
        existing_file = outside_git() / "file"
        existing_file.write_text("x")
        self.assertIn("is not a directory", self.problems(ATLAS_BUILD_DIR=str(existing_file)))
        self.assertIn("separate, non-nested", self.problems(ATLAS_PUBLISH_DIR=str(self.data / "raw/monday/published")))
        self.assertIn("separate, non-nested", self.problems(ATLAS_BUILD_DIR=str(self.data / "raw/monday")))

    def test_raw_evidence_cannot_be_configured_inside_the_git_checkout(self):
        text = self.problems(ATLAS_RAW_DIR=str(ROOT / "raw-evidence"))
        self.assertIn("ATLAS_RAW_DIR must be outside any Git checkout", text)
        self.assertIn("ATLAS_PUBLISH_DIR must be outside any Git checkout", self.problems(ATLAS_PUBLISH_DIR=str(ROOT / "published")))

    def test_invalid_values_fail_validation(self):
        self.assertIn("YYYY-MM", self.problems(MONDAY_API_VERSION="latest"))
        self.assertIn("not an approved contract version", self.problems(ATLAS_CONTRACT_VERSION="9.9.9"))
        self.assertIn("does not match board", self.problems(ATLAS_MONDAY_BOARD_ID="123"))
        self.assertEqual(self.load(ATLAS_MONDAY_BOARD_ID=BOARD).board_id, BOARD)
        self.assertIn("must be UTC", self.problems(ATLAS_HISTORY_START="2026-02-01"))
        self.assertIn("must be in the past", self.problems(ATLAS_HISTORY_START="2027-01-01T00:00:00Z"))
        self.assertIn("whole number", self.problems(ATLAS_SYNC_INTERVAL_SECONDS="hourly"))
        self.assertIn("between 300", self.problems(ATLAS_SYNC_INTERVAL_SECONDS="60"))
        self.assertIn("must be greater than", self.problems(ATLAS_STALE_AFTER_SECONDS="3600"))
        self.assertIn("between 1", self.problems(ATLAS_MAX_CONSECUTIVE_FAILURES="0"))
        self.assertIn("between 1", self.problems(ATLAS_RETENTION_HOURS="0"))

    def test_every_problem_is_reported_at_once(self):
        with self.assertRaises(ConfigError) as caught:
            load_sync_config({"MONDAY_API_VERSION": "x", "ATLAS_SYNC_INTERVAL_SECONDS": "1"}, now=NOW)
        self.assertGreaterEqual(len(caught.exception.problems), 5)

    def test_config_is_immutable(self):
        config = self.load()
        with self.assertRaises(AttributeError):
            config.raw_dir = Path("/tmp")  # type: ignore[misc]
        self.assertIsInstance(config, SyncConfig)


def mf_board():
    import monday_factory as mf
    return mf.BOARD


class MondayClientConfigTests(unittest.TestCase):
    def capture_headers(self, client):
        headers = []

        def urlopen(request, timeout):
            headers.append(dict(request.header_items()))
            return _Response(b'{"data": {"boards": []}}')

        with mock.patch.object(monday_client.urllib.request, "urlopen", urlopen):
            client.query('query { boards(ids: ["1"]) { id } }', {})
        return headers[0]

    def test_configured_api_version_reaches_the_request(self):
        self.assertEqual(self.capture_headers(ReadOnlyMondayClient.from_env({"MONDAY_API_TOKEN": TOKEN}))["Api-version"], DEFAULT_API_VERSION)
        client = ReadOnlyMondayClient.from_env({"MONDAY_API_TOKEN": TOKEN, "MONDAY_API_VERSION": "2025-10"})
        self.assertEqual((client.api_version, self.capture_headers(client)["Api-version"]), ("2025-10", "2025-10"))
        config = load_sync_config({"ATLAS_DATA_DIR": str(outside_git()), "MONDAY_API_TOKEN": TOKEN, "MONDAY_API_VERSION": "2026-01"}, now=NOW)
        self.assertEqual(self.capture_headers(config.monday_client())["Api-version"], "2026-01")

    def test_from_env_reads_the_token_file(self):
        secret = outside_git() / "token"
        secret.write_text(TOKEN)
        self.assertEqual(self.capture_headers(ReadOnlyMondayClient.from_env({"MONDAY_API_TOKEN_FILE": str(secret)}))["Authorization"], TOKEN)

    def test_client_setting_errors_never_contain_the_token(self):
        with self.assertRaises(InvalidMondaySetting) as caught:
            ReadOnlyMondayClient.from_env({"MONDAY_API_TOKEN": TOKEN, "MONDAY_API_VERSION": "v2"})
        self.assertNotIn(TOKEN, str(caught.exception))
        with self.assertRaises(MissingAccess):
            ReadOnlyMondayClient.from_token("")

    def test_read_only_guard_still_rejects_writes_before_any_request(self):
        config = load_sync_config({"ATLAS_DATA_DIR": str(outside_git()), "MONDAY_API_TOKEN": TOKEN}, now=NOW)
        with mock.patch.object(monday_client.urllib.request, "urlopen", side_effect=AssertionError("request sent")) as sent:
            for query in ('mutation { delete_item(item_id: 1) { id } }', "subscription { x }", '  MUTATION { change_column_value }'):
                with self.assertRaises(ReadOnlyViolation):
                    config.monday_client().query(query, {})
            sent.assert_not_called()

    def test_ingest_cli_reports_bad_settings_without_a_traceback_or_token(self):
        err = io.StringIO()
        env = {"MONDAY_API_TOKEN": TOKEN, "MONDAY_API_VERSION": "bad"}
        with mock.patch.dict("os.environ", env, clear=True), redirect_stderr(err):
            code = ingest_main(["--since", "2026-09-01T00:00:00Z", "--raw-dir", str(outside_git() / "run")])
        self.assertEqual(code, 2)
        self.assertIn("INVALID_CONFIGURATION", err.getvalue())
        self.assertNotIn(TOKEN, err.getvalue())


if __name__ == "__main__":
    unittest.main()
