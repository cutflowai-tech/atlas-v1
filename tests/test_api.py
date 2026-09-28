import copy
import json
import unittest
from http.client import HTTPConnection
from threading import Thread

from atlas_commander.api import create_server, fixture_repository, validate_profile
from atlas_commander.contracts import ROOT, schema_errors


class ProfileValidationTests(unittest.TestCase):
    def test_fixture_contract_and_metric_evidence(self):
        profile = fixture_repository()["editor-42"]
        validate_profile(profile, "editor-42")
        self.assertEqual(schema_errors(profile, "editor-profile.schema.json"), [])
        for name in ("speed", "deadline", "quality"):
            expected = json.loads((ROOT / "fixtures/good" / f"{name}-metric.json").read_text())
            self.assertEqual(profile["metrics"][name], [expected])

    def test_missing_evidence_and_invalid_semantics_rejected(self):
        for name in ("speed", "deadline", "quality"):
            profile = fixture_repository()["editor-42"]
            del profile["metrics"][name][0]["evidence"]
            with self.assertRaises(ValueError):
                validate_profile(profile, "editor-42")
        profile = fixture_repository()["editor-42"]
        profile["metrics"]["speed"][0]["cohort_video_type"] = "other"
        with self.assertRaises(ValueError):
            validate_profile(profile, "editor-42")


class APITests(unittest.TestCase):
    def setUp(self):
        self.repository = fixture_repository()
        self.server = create_server(self.repository, port=0)
        # Bounded test-only HTTP listener; no persistent service is launched.
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        self.assertFalse(self.thread.is_alive())

    def request(self, path="/api/editors/editor-42", method="GET"):
        connection = HTTPConnection(*self.server.server_address, timeout=2)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_real_http_contract_and_all_evidence_are_preserved(self):
        original = copy.deepcopy(self.repository["editor-42"])
        status, headers, body = self.request()
        profile = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(schema_errors(profile, "editor-profile.schema.json"), [])
        self.assertEqual(profile, original)
        self.assertEqual(self.repository["editor-42"], original)
        self.assertEqual(headers["X-Atlas-Provenance"], "fixture")
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(int(headers["Content-Length"]), len(body))
        for name in ("speed", "deadline", "quality"):
            expected = json.loads((ROOT / "fixtures/good" / f"{name}-metric.json").read_text())
            self.assertEqual(profile["metrics"][name], [expected])
            self.assertEqual(profile["metrics"][name][0]["evidence"], expected["evidence"])
        self.assertEqual(body, self.request()[2])

    def test_routes_and_unknown_editor(self):
        for path in ("/", "/api/editors", "/api/editors/", "/api/editors/editor-42/extra", "/api/editors/unknown"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request("/api/editors/editor%2D42?view=evidence")[0], 200)
        self.assertEqual(self.request("/api/editors/%FF")[0], 400)

    def test_unsupported_methods(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"):
            status, headers, body = self.request(method=method)
            self.assertEqual(status, 405)
            self.assertEqual(headers["Allow"], "GET")
            if method == "HEAD":
                self.assertEqual(body, b"")

    def test_invalid_profiles_fail_closed(self):
        original = copy.deepcopy(self.repository["editor-42"])
        mutations = [
            lambda p: p.update(generated_at="invalid"),
            lambda p: p["editor"].update(editor_id="someone-else"),
            lambda p: p["metrics"]["speed"][0].update(editor_id="someone-else"),
            lambda p: p["metrics"]["speed"][0].update(cohort_video_type="other"),
            lambda p: p["metrics"]["deadline"][0].update(result="late"),
            lambda p: p["metrics"]["deadline"][0].update(requested_eta=None),
            lambda p: p["work_cycles"][0].update(duration_seconds=1),
        ]
        for name in ("speed", "deadline", "quality"):
            mutations.append(lambda p, name=name: p["metrics"][name][0].pop("evidence"))
            mutations.append(lambda p, name=name: p["metrics"][name][0]["evidence"].update(source="ai"))
        for mutate in mutations:
            profile = copy.deepcopy(original)
            mutate(profile)
            self.repository["editor-42"] = profile
            status, _, body = self.request()
            self.assertEqual(status, 500)
            self.assertEqual(json.loads(body), {"error": "profile_unavailable"})

    def test_missing_eta_cycle_with_no_deadline_is_preserved(self):
        self.repository["editor-42"]["work_cycles"][0]["requested_eta"] = None
        self.repository["editor-42"]["metrics"]["deadline"] = []
        status, _, body = self.request()
        self.assertEqual(status, 200)
        self.assertIsNone(json.loads(body)["work_cycles"][0]["requested_eta"])
        self.assertEqual(json.loads(body)["metrics"]["deadline"], [])

    def test_injected_repository_failure_is_sanitized(self):
        class BrokenRepository:
            def get(self, editor_id):
                raise RuntimeError("private repository detail")

        with create_server(BrokenRepository(), host="127.0.0.1", port=0) as server:
            thread = Thread(target=server.handle_request)
            thread.start()
            connection = HTTPConnection(*server.server_address, timeout=2)
            try:
                connection.request("GET", "/api/editors/editor-42")
                response = connection.getresponse()
                self.assertEqual(response.status, 500)
                self.assertEqual(json.loads(response.read()), {"error": "profile_unavailable"})
            finally:
                connection.close()
                thread.join(timeout=2)
            self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
