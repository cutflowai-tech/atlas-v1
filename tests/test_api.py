import copy
import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from atlas_commander.api import (
    DEFAULT_HOST,
    FixtureProfileRepository,
    ProfileValidationError,
    create_server,
    main,
    profile_errors,
)
from atlas_commander.contracts import ROOT, schema_errors

GOOD = ROOT / "fixtures/good"


def load(name):
    return json.loads((GOOD / name).read_text())


def populated_profile():
    """Frozen-contract profile assembled verbatim from the good fixtures."""
    profile = load("editor-profile.json")
    profile["work_cycles"] = [load("work-cycle.json")]
    profile["metrics"] = {"speed": [load("speed-metric.json")], "deadline": [load("deadline-metric.json")], "quality": [load("quality-metric.json")]}
    return profile


class StaticRepository:
    data_mode = "fixture"
    provenance = "fixture:test-static"

    def __init__(self, profiles):
        self.profiles = profiles
        self.requests = []

    def get_profile(self, editor_id):
        self.requests.append(editor_id)
        return copy.deepcopy(self.profiles.get(editor_id))


class ServerTestCase(unittest.TestCase):
    def start(self, repository):
        server = create_server(repository, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.address = server.server_address[:2]
        return server

    def request(self, path, method="GET"):
        connection = HTTPConnection(*self.address, timeout=5)
        self.addCleanup(connection.close)
        connection.request(method, path)
        response = connection.getresponse()
        return response, json.loads(response.read())


class EvidenceAPIFixtureTests(ServerTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile = populated_profile()
        self.path = Path(self.tmp.name) / "editor-42.json"
        self.path.write_text(json.dumps(self.profile))
        self.repository = FixtureProfileRepository([self.path])
        self.start(self.repository)

    def test_profile_response_validates(self):
        response, body = self.request("/api/editors/editor-42")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "application/json")
        self.assertEqual(schema_errors(body, "editor-profile.schema.json"), [])
        self.assertEqual(profile_errors(body), [])

    def test_response_is_stored_profile_without_recalculation(self):
        _, body = self.request("/api/editors/editor-42")
        self.assertEqual(body, self.profile)

    def test_all_metrics_retain_evidence(self):
        _, body = self.request("/api/editors/editor-42")
        metrics = [metric for family in ("speed", "deadline", "quality") for metric in body["metrics"][family]]
        self.assertEqual(len(metrics), 3)
        for metric in metrics:
            with self.subTest(metric=metric["metric_name"]):
                evidence = metric["evidence"]
                self.assertEqual(evidence["source"], "monday")
                for key in ("monday_board_id", "monday_item_id", "column_ids", "event_ids", "source_timestamps", "source_values", "rule_version", "calculated_at"):
                    self.assertTrue(evidence[key], key)
        cycle = body["work_cycles"][0]
        self.assertEqual(set(body["metrics"]["speed"][0]["evidence"]["event_ids"]), {cycle["in_progress_event_id"], cycle["ready_for_approval_event_id"]})

    def test_fixture_provenance_headers(self):
        for path in ("/api/editors/editor-42", "/api/editors/unknown"):
            with self.subTest(path=path):
                response, _ = self.request(path)
                self.assertEqual(response.getheader("X-Atlas-Data-Mode"), "fixture")
                self.assertEqual(response.getheader("X-Atlas-Provenance"), f"fixture:{self.path.resolve()}")
                self.assertEqual(response.getheader("Cache-Control"), "no-store")

    def test_unknown_editor_is_404(self):
        response, body = self.request("/api/editors/editor-99")
        self.assertEqual(response.status, 404)
        self.assertEqual(body["error"]["code"], "EDITOR_NOT_FOUND")

    def test_invalid_editor_ids_are_400(self):
        for path in ("/api/editors/", "/api/editors/a/b", "/api/editors/%2E%2E", "/api/editors/editor%2F42", "/api/editors/-x", "/api/editors/" + "a" * 200):
            with self.subTest(path=path):
                response, body = self.request(path)
                self.assertEqual(response.status, 400)
                self.assertEqual(body["error"]["code"], "INVALID_EDITOR_ID")

    def test_unknown_routes_are_404(self):
        for path in ("/", "/api/editors", "/api/editor/editor-42", "/api/work-cycles/cycle-1"):
            with self.subTest(path=path):
                response, body = self.request(path)
                self.assertEqual(response.status, 404)
                self.assertEqual(body["error"]["code"], "ROUTE_NOT_FOUND")

    def test_query_string_is_ignored(self):
        response, body = self.request("/api/editors/editor-42?recalculate=true")
        self.assertEqual(response.status, 200)
        self.assertEqual(body, self.profile)

    def test_write_methods_are_405(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                response, body = self.request("/api/editors/editor-42", method)
                self.assertEqual(response.status, 405)
                self.assertEqual(response.getheader("Allow"), "GET")
                self.assertEqual(body["error"]["code"], "METHOD_NOT_ALLOWED")

    def test_repository_returns_copies(self):
        self.repository.get_profile("editor-42")["metrics"]["speed"].clear()
        _, body = self.request("/api/editors/editor-42")
        self.assertEqual(len(body["metrics"]["speed"]), 1)


class InjectedRepositoryTests(ServerTestCase):
    def assert_refused(self, profiles, editor_id="editor-42"):
        repository = StaticRepository(profiles)
        self.start(repository)
        response, body = self.request(f"/api/editors/{editor_id}")
        self.assertEqual(response.status, 500)
        self.assertEqual(body, {"error": {"code": "PROFILE_CONTRACT_VIOLATION", "message": "stored profile failed editor-profile contract validation"}})
        self.assertEqual(response.getheader("X-Atlas-Provenance"), "fixture:test-static")
        return repository

    def test_injected_repository_is_used(self):
        repository = StaticRepository({"editor-42": populated_profile()})
        self.start(repository)
        response, body = self.request("/api/editors/editor-42")
        self.assertEqual(response.status, 200)
        self.assertEqual(body, populated_profile())
        self.assertEqual(repository.requests, ["editor-42"])

    def test_metric_without_evidence_is_refused(self):
        profile = populated_profile()
        del profile["metrics"]["quality"][0]["evidence"]
        self.assert_refused({"editor-42": profile})

    def test_ai_sourced_evidence_is_refused(self):
        profile = populated_profile()
        profile["metrics"]["speed"][0]["evidence"]["source"] = "ai"
        self.assert_refused({"editor-42": profile})

    def test_cross_video_type_cohort_is_refused(self):
        profile = populated_profile()
        profile["metrics"]["speed"][0]["cohort_video_type"] = "long-form"
        self.assert_refused({"editor-42": profile})

    def test_deadline_result_mismatch_is_refused(self):
        profile = populated_profile()
        profile["metrics"]["deadline"][0]["result"] = "late"
        self.assert_refused({"editor-42": profile})

    def test_metric_for_other_editor_is_refused(self):
        profile = populated_profile()
        profile["metrics"]["quality"][0]["editor_id"] = "editor-7"
        self.assert_refused({"editor-42": profile})

    def test_profile_for_other_editor_is_refused(self):
        self.assert_refused({"editor-42": load("editor-profile.json") | {"editor": load("editor-identity.json") | {"editor_id": "editor-7"}}})

    def test_composite_score_field_is_refused(self):
        profile = populated_profile()
        profile["score"] = 87
        self.assert_refused({"editor-42": profile})


class ProfileValidationTests(unittest.TestCase):
    def test_missing_eta_cycle_is_valid_without_deadline_metric(self):
        profile = populated_profile()
        profile["work_cycles"][0]["requested_eta"] = None
        profile["metrics"]["deadline"] = []
        self.assertEqual(profile_errors(profile), [])

    def test_work_cycle_duration_mismatch_is_reported(self):
        profile = populated_profile()
        profile["work_cycles"][0]["duration_seconds"] = 60
        self.assertEqual(profile_errors(profile), ["DURATION_MISMATCH: work_cycles[0]"])

    def test_fixture_repository_rejects_invalid_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            profile = populated_profile()
            profile["metrics"]["speed"][0]["cohort_video_type"] = "long-form"
            path.write_text(json.dumps(profile))
            with self.assertRaises(ProfileValidationError) as raised:
                FixtureProfileRepository([path])
            self.assertIn("CROSS_VIDEO_TYPE_COHORT: metrics.speed[0]", raised.exception.errors[0])

    def test_fixture_repository_rejects_duplicate_editor(self):
        path = GOOD / "editor-profile.json"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            FixtureProfileRepository([path, path])

    def test_default_repository_serves_repo_fixture(self):
        repository = FixtureProfileRepository()
        self.assertEqual(repository.provenance, "fixture:fixtures/good/editor-profile.json")
        self.assertEqual(repository.get_profile("editor-42"), load("editor-profile.json"))

    def test_server_defaults_to_localhost(self):
        self.assertEqual(DEFAULT_HOST, "127.0.0.1")
        server = create_server(StaticRepository({}), port=0)
        self.addCleanup(server.server_close)
        self.assertEqual(server.server_address[0], "127.0.0.1")

    def test_main_rejects_invalid_fixture_before_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps({"contract_version": "1.0.0"}))
            with self.assertRaises(ProfileValidationError):
                main(["--port", "0", "--fixture", str(path)])


if __name__ == "__main__":
    unittest.main()
