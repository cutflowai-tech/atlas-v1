"""Reasoning V3 Phase 06: the provider gateway for GPT-5.6 Sol through OpenRouter (``REV/06``). No test makes a live call."""

import ast
import http.client
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import reasoning_factory as factory
from reasoning_db import fresh_database, requires_db

from atlas_reasoning import settings
from atlas_reasoning.enums import LLMCallStatus
from atlas_reasoning.fake_provider import FakeError, FakeProvider, FakeReply
from atlas_reasoning.gateway import MemoryRecorder, ReasoningGateway
from atlas_reasoning.openrouter_client import HttpResult, OpenRouterTransport
from atlas_reasoning.provider import (
    ERROR_CLASSES,
    CallContext,
    Message,
    ProviderAuthError,
    ProviderBadRequest,
    ProviderContentFiltered,
    ProviderNetworkError,
    ProviderQuotaExceeded,
    ProviderRateLimited,
    ProviderRequest,
    ProviderResponseError,
    ProviderTimeout,
    ProviderTruncated,
    ProviderUnavailable,
    StructuredOutputError,
    redact,
)
from atlas_reasoning.settings import PINNED_MODEL, GatewaySettings, OpenRouterSettings
from atlas_reasoning.store.calls import StoreCallRecorder
from atlas_reasoning.store.repository import ReasoningStore
from atlas_reasoning.structured import contract_output, inline_schema, schema_output

ROOT = Path(__file__).resolve().parents[1]
SECRET = "sk-or-v1-0123456789abcdef0123456789abcdefSECRET"
OK_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}


def request(case_id: str = "rc1_" + "a" * 32, structured: bool = True, purpose: str = "test") -> ProviderRequest:
    return ProviderRequest(CallContext(purpose=purpose, run_id="run_" + "1" * 32, case_id=case_id, prompt_version="analyst-v1",
                                       source_snapshot_id="snapshot-1", evidence_fingerprint="ef1_" + "2" * 64),
                           (Message("system", "Return JSON."), Message("user", "Case evidence ...")),
                           schema_output("ok", OK_SCHEMA) if structured else None)


class Sleeps:
    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def gateway(transport, **limits) -> tuple[ReasoningGateway, MemoryRecorder, Sleeps]:
    recorder, sleeps = MemoryRecorder(), Sleeps()
    config = GatewaySettings(**{"max_retries": 3, "backoff_seconds": 2.0, "max_backoff_seconds": 30.0, "concurrency": 4, **limits})
    return ReasoningGateway(transport, config, recorder=recorder, sleep=sleeps, jitter=lambda: 0.0, secrets=(SECRET,)), recorder, sleeps


class GatewayTests(unittest.TestCase):
    def test_success_with_structured_output_and_metadata(self):
        fake = FakeProvider(default=FakeReply({"ok": True}, input_tokens=321, output_tokens=12))
        gw, recorder, sleeps = gateway(fake)
        response = gw.call(request())
        self.assertEqual(response.parsed, {"ok": True})
        self.assertRegex(response.request_id, r"^req_[0-9a-f]{32}$")
        [call] = recorder.calls
        self.assertEqual((call.status, call.attempts, call.retries, call.error_class), (LLMCallStatus.SUCCEEDED, 1, 0, None))
        self.assertEqual((call.input_tokens, call.output_tokens, call.model, call.provider), (321, 12, PINNED_MODEL, "fake"))
        self.assertEqual((call.run_id, call.case_id, call.prompt_version, call.source_snapshot_id, call.evidence_fingerprint),
                         ("run_" + "1" * 32, "rc1_" + "a" * 32, "analyst-v1", "snapshot-1", "ef1_" + "2" * 64))
        self.assertEqual(call.request_id, response.request_id)
        self.assertGreaterEqual(call.latency_ms, 0)
        self.assertEqual(sleeps.waits, [])

    def test_timeout_is_retried_with_exponential_backoff_then_fails(self):
        fake = FakeProvider(default=FakeError(ProviderTimeout("no response")))
        gw, recorder, sleeps = gateway(fake)
        with self.assertRaises(ProviderTimeout):
            gw.call(request())
        self.assertEqual(len(fake.requests), 4, "first attempt + 3 bounded retries")
        self.assertEqual(sleeps.waits, [2.0, 4.0, 8.0])
        [call] = recorder.calls
        self.assertEqual((call.status, call.attempts, call.retries, call.error_class), (LLMCallStatus.FAILED, 4, 3, "timeout"))

    def test_retry_then_success(self):
        fake = FakeProvider().script("rc1_" + "a" * 32, FakeError(ProviderTimeout("slow")), FakeError(ProviderUnavailable("503", status=503)),
                                     FakeReply({"ok": True}))
        gw, recorder, sleeps = gateway(fake)
        self.assertEqual(gw.call(request()).parsed, {"ok": True})
        self.assertEqual((recorder.calls[0].attempts, recorder.calls[0].status), (3, LLMCallStatus.SUCCEEDED))
        self.assertEqual(sleeps.waits, [2.0, 4.0])

    def test_rate_limit_honours_retry_after_up_to_the_cap(self):
        fake = FakeProvider().script("rc1_" + "a" * 32, FakeError(ProviderRateLimited("busy", status=429, retry_after=7)),
                                     FakeError(ProviderRateLimited("busy", status=429, retry_after=999)), FakeReply({"ok": True}))
        gw, recorder, sleeps = gateway(fake)
        gw.call(request())
        self.assertEqual(sleeps.waits, [7.0, 30.0])
        self.assertEqual(recorder.calls[0].provider_status, "200")

    def test_jitter_is_bounded(self):
        gw = ReasoningGateway(FakeProvider(), GatewaySettings(backoff_seconds=2, max_backoff_seconds=100), jitter=lambda: 1.0)
        self.assertEqual([gw.backoff(n) for n in (1, 2, 3)], [2.5, 5.0, 10.0])

    def test_non_retryable_errors_are_not_retried(self):
        for error in (ProviderAuthError("no", status=401), ProviderBadRequest("bad", status=400), ProviderQuotaExceeded("credits", status=402),
                      ProviderContentFiltered("flagged", status=403), ProviderTruncated("length")):
            with self.subTest(error=error.error_class):
                fake = FakeProvider(default=FakeError(error))
                gw, recorder, sleeps = gateway(fake)
                with self.assertRaises(type(error)):
                    gw.call(request())
                self.assertEqual((len(fake.requests), sleeps.waits, recorder.calls[0].error_class), (1, [], error.error_class))

    def test_malformed_structured_output_is_rejected_and_retried(self):
        for content in ("not json at all", "[1, 2]", {"ok": "yes"}, {"ok": True, "extra": 1}):
            with self.subTest(content=content):
                fake = FakeProvider(default=FakeReply(content))
                gw, recorder, _ = gateway(fake, max_retries=1)
                with self.assertRaises(StructuredOutputError):
                    gw.call(request())
                self.assertEqual((len(fake.requests), recorder.calls[0].error_class), (2, "invalid_structured_output"))

    def test_structured_output_matches_reasoning_v3_contracts(self):
        output = contract_output("reasoning-update-v1.schema.json")
        self.assertNotIn("$ref", json.dumps(inline_schema("reasoning-update-v1.schema.json")))
        self.assertEqual(dict(output.schema)["additionalProperties"], False)
        update = factory.update_dict()
        fake = FakeProvider(default=FakeReply(update))
        gw, _, _ = gateway(fake)
        req = ProviderRequest(request().context, request().messages, output)
        self.assertEqual(gw.call(req).parsed, update)
        bad = {**update, "changed_fields": [{"field": "case_id", "value": "x"}]}
        fake.default = FakeReply(bad)
        with self.assertRaises(StructuredOutputError):
            gw.call(ProviderRequest(CallContext(purpose="t2"), request().messages, output))
        for name in ("reasoning-case-v1.schema.json", "reasoning-result-v1.schema.json"):
            self.assertNotIn("$ref", json.dumps(inline_schema(name)))
        self.assertEqual(contract_output("reasoning-result-v1.schema.json").validate(factory.result_dict()), [])

    def test_concurrency_limit(self):
        fake = FakeProvider(default=FakeReply({"ok": True}, delay=0.05))
        gw, recorder, _ = gateway(fake, concurrency=2)
        outcomes = gw.call_many([request(case_id=f"rc1_{i:032x}") for i in range(8)])
        self.assertTrue(all(outcome.ok for outcome in outcomes))
        self.assertEqual(fake.peak_in_flight, 2)
        self.assertEqual(len(recorder.calls), 8)
        threads = [threading.Thread(target=gw.call, args=(request(case_id=f"rc1_{i + 100:032x}"),)) for i in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(fake.peak_in_flight, 2, "the limit holds across independent callers too")

    def test_one_failing_case_does_not_affect_the_others(self):
        class Broken(FakeProvider):
            def complete(self, request, *, model, timeout):
                if request.context.case_id == "rc1_" + "d" * 32:
                    raise KeyError("transport bug")
                return super().complete(request, model=model, timeout=timeout)

        fake = Broken(default=FakeReply({"ok": True}))
        fake.script("rc1_" + "b" * 32, FakeError(ProviderBadRequest("refused", status=400)))
        gw, recorder, _ = gateway(fake)
        outcomes = gw.call_many([request(case_id="rc1_" + c * 32) for c in "abcd"])
        self.assertEqual([o.ok for o in outcomes], [True, False, True, False])
        self.assertEqual([o.error.error_class for o in outcomes if o.error], ["bad_request", "internal_error"])
        self.assertEqual([o.request.context.case_id for o in outcomes], ["rc1_" + c * 32 for c in "abcd"])
        self.assertEqual(sorted(c.status for c in recorder.calls), ["failed", "failed", "succeeded", "succeeded"])

    def test_a_recorder_failure_never_loses_the_result(self):
        class FailingRecorder:
            def record(self, call):
                raise RuntimeError("database down")

        gw = ReasoningGateway(FakeProvider(default=FakeReply({"ok": True})), GatewaySettings(), recorder=FailingRecorder())
        with self.assertLogs("atlas_reasoning.gateway", level="ERROR") as logs:
            self.assertEqual(gw.call(request()).parsed, {"ok": True})
        self.assertIn("not recorded", "\n".join(logs.output))

    def test_secrets_never_reach_logs_errors_or_records(self):
        def leaky(url, headers, body, timeout):
            self.assertEqual(headers["Authorization"], f"Bearer {SECRET}")
            return HttpResult(500, {}, json.dumps({"error": {"code": 500, "message": f"upstream echoed Authorization: Bearer {SECRET}"}}).encode())

        transport = OpenRouterTransport(OpenRouterSettings(api_key=SECRET), http=leaky)
        gw, recorder, _ = gateway(transport, max_retries=1)
        with self.assertLogs("atlas_reasoning.gateway", level="DEBUG") as logs, self.assertRaises(ProviderUnavailable) as caught:
            gw.call(request())
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertNotIn(SECRET, "\n".join(logs.output))
        self.assertNotIn(SECRET, repr(recorder.calls))
        self.assertNotIn(SECRET, repr(OpenRouterSettings(api_key=SECRET)))
        self.assertNotIn(SECRET, repr(transport))
        self.assertEqual(redact(f"key={SECRET} header=Bearer abc.def", ()), "key=*** header=Bearer ***")

        def crashing(url, headers, body, timeout):
            raise OSError(f"proxy refused {SECRET}")

        with self.assertRaises(ProviderNetworkError) as caught:
            ReasoningGateway(OpenRouterTransport(OpenRouterSettings(api_key=SECRET), http=crashing), GatewaySettings(max_retries=0)).call(request())
        self.assertNotIn(SECRET, str(caught.exception))

    def test_error_classes_are_stable_and_unique(self):
        self.assertEqual(len(ERROR_CLASSES), len(set(ERROR_CLASSES)))
        self.assertIn("rate_limited", ERROR_CLASSES)


class OpenRouterTransportTests(unittest.TestCase):
    def transport(self, status: int = 200, body: object = None, headers: dict | None = None, raise_: Exception | None = None):
        sent = {}

        def http(url, request_headers, payload, timeout):
            sent.update(url=url, headers=dict(request_headers), body=json.loads(payload), timeout=timeout)
            if raise_ is not None:
                raise raise_
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            return HttpResult(status, headers or {}, raw)

        return OpenRouterTransport(OpenRouterSettings(api_key=SECRET), http=http), sent

    def completion(self, content='{"ok": true}', finish="stop") -> dict:
        return {"id": "gen-1", "model": PINNED_MODEL, "provider": "OpenAI", "choices": [{"message": {"content": content, "reasoning": "hidden"},
                                                                                      "finish_reason": finish}],
                "usage": {"prompt_tokens": 1200, "completion_tokens": 80}}

    def test_request_body_pins_the_model_and_asks_for_strict_json(self):
        transport, sent = self.transport(body=self.completion())
        req = ProviderRequest(request().context, request().messages, schema_output("ok", OK_SCHEMA), max_output_tokens=500, reasoning_effort="medium")
        response = transport.complete(req, model=PINNED_MODEL, timeout=30)
        body = sent["body"]
        self.assertEqual(sent["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(body["model"], "openai/gpt-5.6-sol")
        self.assertEqual(body["response_format"], {"type": "json_schema", "json_schema": {"name": "ok", "strict": True, "schema": OK_SCHEMA}})
        self.assertEqual(body["provider"], {"require_parameters": True})
        self.assertEqual(body["reasoning"], {"exclude": True, "effort": "medium"})
        self.assertEqual(body["max_tokens"], 500)
        self.assertEqual(body["messages"][0], {"role": "system", "content": "Return JSON."})
        self.assertEqual(sent["timeout"], 30)
        self.assertEqual((response.content, response.input_tokens, response.output_tokens, response.provider_response_id),
                         ('{"ok": true}', 1200, 80, "gen-1"))
        self.assertNotIn("hidden", repr(response), "raw reasoning is never kept")

    def test_http_and_provider_errors_map_to_the_taxonomy(self):
        cases = [
            (429, {"error": {"code": 429, "message": "Rate limit"}}, {"retry-after": "12"}, ProviderRateLimited),
            (401, {"error": {"code": 401, "message": "No auth"}}, {}, ProviderAuthError),
            (402, {"error": {"code": 402, "message": "Credits"}}, {}, ProviderQuotaExceeded),
            (403, {"error": {"code": 403, "message": "Flagged"}}, {}, ProviderContentFiltered),
            (400, {"error": {"code": 400, "message": "Bad"}}, {}, ProviderBadRequest),
            (404, {"error": {"code": 404, "message": "No model"}}, {}, ProviderBadRequest),
            (408, {"error": {"code": 408, "message": "Timeout"}}, {}, ProviderTimeout),
            (500, {"error": {"code": 500, "message": "Oops"}}, {}, ProviderUnavailable),
            (502, {"error": {"code": 502, "message": "Model down"}}, {}, ProviderUnavailable),
            (503, b"<html>gateway</html>", {}, ProviderUnavailable),
            (200, {"error": {"code": 502, "message": "upstream"}}, {}, ProviderUnavailable),
            (200, b"not json", {}, ProviderResponseError),
            (200, {"choices": []}, {}, ProviderResponseError),
            (200, self.completion(content=""), {}, ProviderResponseError),
            (200, self.completion(finish="length"), {}, ProviderTruncated),
            (200, self.completion(finish="content_filter"), {}, ProviderContentFiltered),
        ]
        for status, body, headers, expected in cases:
            with self.subTest(status=status, expected=expected.__name__):
                transport, _ = self.transport(status, body, headers)
                with self.assertRaises(expected) as caught:
                    transport.complete(request(), model=PINNED_MODEL, timeout=5)
                if expected is ProviderRateLimited:
                    self.assertEqual(caught.exception.retry_after, 12.0)

    def test_network_failures(self):
        for error, expected in ((TimeoutError("timed out"), ProviderTimeout), (TimeoutError(), ProviderTimeout),
                                (urllib.error.URLError(TimeoutError()), ProviderTimeout), (urllib.error.URLError("refused"), ProviderNetworkError),
                                (ConnectionResetError("reset"), ProviderNetworkError), (http.client.IncompleteRead(b"partial"), ProviderNetworkError),
                                (http.client.RemoteDisconnected("closed"), ProviderNetworkError)):
            with self.subTest(error=type(error).__name__):
                transport, _ = self.transport(raise_=error)
                with self.assertRaises(expected):
                    transport.complete(request(), model=PINNED_MODEL, timeout=5)

    def test_gateway_and_transport_together_retry_a_rate_limit(self):
        replies = iter([HttpResult(429, {"retry-after": "3"}, b'{"error": {"code": 429, "message": "slow down"}}'),
                        HttpResult(200, {}, json.dumps(self.completion()).encode())])
        transport = OpenRouterTransport(OpenRouterSettings(api_key=SECRET), http=lambda *args: next(replies))
        gw, recorder, sleeps = gateway(transport)
        self.assertEqual(gw.call(request()).parsed, {"ok": True})
        self.assertEqual(sleeps.waits, [3.0])
        self.assertEqual((recorder.calls[0].attempts, recorder.calls[0].provider, recorder.calls[0].output_tokens), (2, "openrouter", 80))


class SettingsTests(unittest.TestCase):
    def test_model_is_pinned(self):
        self.assertEqual(settings.gateway_settings({}).model, "openai/gpt-5.6-sol")
        with self.assertRaises(settings.ReasoningConfigError):
            settings.gateway_settings({"ATLAS_REASONING_MODEL": "openai/gpt-6.1-sol"})
        override = {"ATLAS_REASONING_MODEL": "openai/gpt-6.1-sol", "ATLAS_REASONING_ALLOW_MODEL_OVERRIDE": "on"}
        self.assertEqual(settings.gateway_settings(override).model, "openai/gpt-6.1-sol")

    def test_limits_are_bounded(self):
        for name, value in (("ATLAS_REASONING_LLM_CONCURRENCY", "0"), ("ATLAS_REASONING_LLM_CONCURRENCY", "100"), ("ATLAS_REASONING_LLM_MAX_RETRIES", "50"),
                            ("ATLAS_REASONING_LLM_TIMEOUT_SECONDS", "1"), ("ATLAS_REASONING_LLM_TIMEOUT_SECONDS", "soon")):
            with self.subTest(name=name, value=value), self.assertRaises(settings.ReasoningConfigError):
                settings.gateway_settings({name: value})
        limits = settings.gateway_settings({"ATLAS_REASONING_LLM_CONCURRENCY": "8", "ATLAS_REASONING_LLM_MAX_RETRIES": "0"})
        self.assertEqual((limits.concurrency, limits.max_retries), (8, 0))

    def test_key_comes_from_environment_or_file_never_both(self):
        self.assertEqual(settings.openrouter_settings({"OPENROUTER_API_KEY": SECRET}).api_key, SECRET)
        with tempfile.NamedTemporaryFile("w", suffix=".key") as handle:
            handle.write(SECRET + "\n")
            handle.flush()
            self.assertEqual(settings.openrouter_settings({"OPENROUTER_API_KEY_FILE": handle.name}).api_key, SECRET)
            with self.assertRaises(settings.ReasoningConfigError) as caught:
                settings.openrouter_settings({"OPENROUTER_API_KEY": SECRET, "OPENROUTER_API_KEY_FILE": handle.name})
            self.assertNotIn(SECRET, str(caught.exception))
        with self.assertRaises(settings.ReasoningConfigError):
            settings.openrouter_settings({})
        for url in ("http://evil.example/api", "http://127.0.0.1.evil.example/api", "http://localhost.evil.example/api", "ftp://openrouter.ai"):
            with self.subTest(url=url), self.assertRaises(settings.ReasoningConfigError):
                settings.openrouter_settings({"OPENROUTER_API_KEY": SECRET, "ATLAS_REASONING_OPENROUTER_BASE_URL": url})
        for url in ("https://openrouter.ai/api/v1", "http://127.0.0.1:8080/api/v1", "http://localhost:9/api"):
            self.assertEqual(settings.openrouter_settings({"OPENROUTER_API_KEY": SECRET, "ATLAS_REASONING_OPENROUTER_BASE_URL": url}).base_url, url)


class IsolationTests(unittest.TestCase):
    def test_only_the_gateway_layer_knows_openrouter(self):
        package = ROOT / "src" / "atlas_reasoning"
        importers = set()
        for path in package.rglob("*.py"):
            tree = ast.parse(path.read_text())
            if any(isinstance(node, ast.ImportFrom) and node.module == "atlas_reasoning.openrouter_client" for node in ast.walk(tree)):
                importers.add(path.name)
        self.assertEqual(importers, {"__main__.py"}, "only the operator command wires the OpenRouter transport")
        domain = ("contracts.py", "enums.py", "case_identity.py", "case_mapping.py", "case_builder.py", "fingerprint.py", "delta.py", "change_gate.py")
        for name in domain:
            text = (package / name).read_text()
            tree = ast.parse(text)
            imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
            with self.subTest(module=name):
                self.assertNotIn("openrouter", text.lower())
                self.assertFalse(imports & {"atlas_reasoning.provider", "atlas_reasoning.gateway", "atlas_reasoning.openrouter_client"})


@requires_db
class CallRecordingTests(unittest.TestCase):
    def test_calls_are_persisted_to_llm_calls(self):
        store = ReasoningStore(fresh_database())
        fake = FakeProvider(default=FakeReply({"ok": True}, input_tokens=10, output_tokens=2))
        fake.script("failing-health", FakeError(ProviderTimeout("slow")), FakeError(ProviderTimeout("slow")))
        gw = ReasoningGateway(fake, GatewaySettings(max_retries=1), recorder=StoreCallRecorder(store), sleep=lambda s: None)
        ok = gw.call(ProviderRequest(CallContext(purpose="health"), request().messages, schema_output("ok", OK_SCHEMA)))
        with self.assertRaises(ProviderTimeout):
            gw.call(ProviderRequest(CallContext(purpose="failing-health", request_id="req-failing"), request().messages, None))
        with store.transaction() as tx:
            rows = {row["request_id"]: row for row in tx.llm_calls(run_id=None)}
        self.assertEqual(rows[ok.request_id]["status"], "succeeded")
        self.assertEqual((rows[ok.request_id]["input_tokens"], rows[ok.request_id]["output_tokens"], rows[ok.request_id]["retries"]), (10, 2, 0))
        failed = rows["req-failing"]
        self.assertEqual((failed["status"], failed["error_class"], failed["attempts"], failed["retries"]), ("failed", "timeout", 2, 1))

    def test_unknown_run_or_case_never_loses_the_result(self):
        store = ReasoningStore(fresh_database())
        gw = ReasoningGateway(FakeProvider(default=FakeReply({"ok": True})), GatewaySettings(), recorder=StoreCallRecorder(store))
        with self.assertLogs("atlas_reasoning.gateway", level="ERROR"):
            self.assertEqual(gw.call(request()).parsed, {"ok": True})


class FakeServer(BaseHTTPRequestHandler):
    seen: ClassVar[list[dict]] = []

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        FakeServer.seen.append({"path": self.path, "auth": self.headers["Authorization"], "body": json.loads(self.rfile.read(length))})
        body = json.dumps({"id": "gen-local", "model": PINNED_MODEL, "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 20, "completion_tokens": 5}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class HealthCommandTests(unittest.TestCase):
    def _run(self, *args: str, env: dict) -> subprocess.CompletedProcess:
        base = {key: value for key, value in os.environ.items() if not key.startswith(("ATLAS_REASONING", "OPENROUTER"))}
        base.update(PYTHONPATH=str(ROOT / "src"), **env)
        return subprocess.run([sys.executable, "-m", "atlas_reasoning", "provider-health", *args], env=base, capture_output=True, text=True, check=False)

    def test_dry_run_validates_configuration_without_network(self):
        missing = self._run("--dry-run", env={})
        self.assertEqual(missing.returncode, 1)
        self.assertIn("OPENROUTER_API_KEY", missing.stdout)
        ok = self._run("--dry-run", env={"OPENROUTER_API_KEY": SECRET})
        self.assertEqual(ok.returncode, 0, ok.stderr)
        report = json.loads(ok.stdout)
        self.assertEqual((report["model"], report["live_call"], report["api_key_configured"]), (PINNED_MODEL, False, True))
        self.assertNotIn(SECRET, ok.stdout + ok.stderr)

    def test_live_check_against_a_local_server(self):
        server = HTTPServer(("127.0.0.1", 0), FakeServer)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = self._run(env={"OPENROUTER_API_KEY": SECRET, "ATLAS_REASONING_OPENROUTER_BASE_URL": f"http://127.0.0.1:{server.server_port}/api/v1"})
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual((report["ok"], report["live_call"], report["response_model"], report["attempts"]), (True, True, PINNED_MODEL, 1))
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        seen = FakeServer.seen[-1]
        self.assertEqual((seen["path"], seen["auth"], seen["body"]["model"]), ("/api/v1/chat/completions", f"Bearer {SECRET}", PINNED_MODEL))


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    unittest.main()
