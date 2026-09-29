"""Hardened read-only Monday client: typed errors, request-level retries and safe metadata (no network, no real token)."""

import io
import json
import socket
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from unittest import mock

from atlas_monday_probe import __main__ as probe_cli
from atlas_monday_probe import client as monday_client
from atlas_monday_probe.client import (
    ApiVersionError,
    AuthenticationFailed,
    HttpFailure,
    InvalidMondaySetting,
    MissingAccess,
    MondayError,
    PermanentApiError,
    PermissionDenied,
    RateLimited,
    ReadOnlyMondayClient,
    ReadOnlyViolation,
    RetryPolicy,
    TransientApiError,
    TransportError,
)
from atlas_sync.config import ConfigError, load_sync_config

TOKEN = "tok-DO-NOT-LEAK-91b2"
OK = b'{"data": {"boards": []}, "account_id": 1}'
QUERY = 'query { boards(ids: ["1"]) { id } }'


def body(*errors, **legacy):
    return json.dumps({"errors": list(errors), **legacy} if errors else legacy).encode()


class Script:
    """A transport that plays back a list of outcomes (bytes to return, or exceptions to raise) and records each call."""

    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    def __call__(self, query, variables):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def client(*outcomes, jitter=0.5, **policy):
    sleeps = []
    transport = Script(*outcomes)
    c = ReadOnlyMondayClient(transport, retry_policy=RetryPolicy(**policy), sleep=sleeps.append, random=lambda: jitter,
                             redact=lambda text: text.replace(TOKEN, "<redacted>"))
    return c, transport, sleeps


class RetryTests(unittest.TestCase):
    def test_1_success_without_retry(self):
        c, transport, sleeps = client(OK)
        self.assertEqual(c.query(QUERY, {}), OK)
        self.assertEqual((transport.calls, sleeps, c.stats.as_dict()["retries"], c.stats.requests), (1, [], 0, 1))

    def test_2_http_429_then_success(self):
        c, transport, _ = client(HttpFailure(429, body({"message": "Rate limit exceeded"})), OK)
        self.assertEqual(c.query(QUERY, {}), OK)
        self.assertEqual((transport.calls, c.stats.retries, c.stats.failures_by_category), (2, 1, {"rate_limited": 1}))

    def test_3_http_5xx_then_success(self):
        for status in (500, 502, 503):
            c, transport, _ = client(HttpFailure(status, b"<html>bad gateway</html>"), OK)
            self.assertEqual(c.query(QUERY, {}), OK)
            self.assertEqual((transport.calls, c.stats.failures_by_category), (2, {"transient_api": 1}), status)

    def test_4_repeated_transient_failure_stops_after_4_attempts(self):
        c, transport, sleeps = client(*[HttpFailure(503)] * 6)
        with self.assertRaises(TransientApiError) as caught:
            c.query(QUERY, {})
        self.assertEqual((transport.calls, len(sleeps), caught.exception.status), (4, 3, 503))
        self.assertEqual(c.stats.as_dict(), {"requests": 4, "retries": 3, "succeeded": 0, "failed": 1, "slept_seconds": round(sum(sleeps), 3),
                                             "failures_by_category": {"transient_api": 4}, "last_failure_category": "transient_api"})

    def test_5_network_error_then_success(self):
        for error in (urllib.error.URLError(socket.gaierror("name resolution failed")), TimeoutError("timed out"), ConnectionResetError("reset")):
            c, _, _ = client(error, OK)
            self.assertEqual(c.query(QUERY, {}), OK)
            self.assertEqual(c.stats.failures_by_category, {"transport": 1})
        c, transport, _ = client(*[ConnectionRefusedError("refused")] * 4)
        with self.assertRaises(TransportError):
            c.query(QUERY, {})
        self.assertEqual(transport.calls, 4)

    def test_6_complexity_budget_is_rate_limiting_not_missing_access(self):
        budget = {"message": "Complexity budget exhausted", "extensions": {"code": "COMPLEXITY_BUDGET_EXHAUSTED", "retry_in_seconds": 7}}
        c, _, sleeps = client(body(budget), OK)   # HTTP 200 with a GraphQL error: the audit's MissingAccess case
        self.assertEqual(c.query(QUERY, {}), OK)
        self.assertEqual((sleeps, c.stats.failures_by_category), ([7.0], {"rate_limited": 1}))
        legacy = body(error_code="ComplexityException", error_message="Complexity budget exhausted, query cost 30001 budget remaining 1 reset in 12 seconds",
                      status_code=429)
        c, _, sleeps = client(legacy, OK)
        c.query(QUERY, {})
        self.assertEqual(sleeps, [12.0])
        c, transport, _ = client(*[body(budget)] * 4)
        with self.assertRaises(RateLimited) as caught:
            c.query(QUERY, {})
        self.assertNotIsInstance(caught.exception, MissingAccess)
        self.assertEqual((transport.calls, caught.exception.category), (4, "rate_limited"))

    def test_6b_daily_limit_and_over_long_server_waits_are_not_retried(self):
        c, transport, sleeps = client(body({"message": "Daily limit exceeded", "extensions": {"code": "DAILY_LIMIT_EXCEEDED"}}), OK)
        with self.assertRaises(RateLimited):
            c.query(QUERY, {})
        self.assertEqual((transport.calls, sleeps), (1, []))
        c, transport, sleeps = client(HttpFailure(429, body({"message": "Rate limit", "extensions": {"retry_in_seconds": 900}})), OK)
        with self.assertRaises(RateLimited) as caught:
            c.query(QUERY, {})
        self.assertEqual((transport.calls, sleeps, caught.exception.retry_after), (1, [], 900.0))

    def test_7_server_retry_delay_is_honoured(self):
        c, _, sleeps = client(HttpFailure(429, b"", retry_after="17"), OK)
        c.query(QUERY, {})
        self.assertEqual(sleeps, [17.0])
        c, _, sleeps = client(HttpFailure(429, body({"message": "x", "extensions": {"retry_in_seconds": 95}})), OK)
        c.query(QUERY, {})
        self.assertEqual(sleeps, [95.0])                 # a server-provided wait is honoured even above the 60 s backoff cap

    def test_8_exponential_backoff_with_jitter_without_hint(self):
        c, _, sleeps = client(*[HttpFailure(500)] * 3, OK, jitter=0.5)
        c.query(QUERY, {})
        self.assertEqual(sleeps, [0.75, 1.5, 3.0])       # ceilings 1, 2, 4 s; equal jitter puts each in [ceiling/2, ceiling]
        low = RetryPolicy().backoff(3, 0.0)
        high = RetryPolicy().backoff(3, 0.999999)
        self.assertTrue(2.0 <= low < high <= 4.0)

    def test_9_backoff_never_exceeds_60_seconds(self):
        policy = RetryPolicy(max_attempts=20, base_delay_seconds=10)
        delays = [policy.backoff(attempt, 0.999999) for attempt in range(1, 20)]
        self.assertLessEqual(max(delays), 60.0)
        self.assertAlmostEqual(delays[-1], 60.0, places=3)
        c, _, sleeps = client(*[HttpFailure(502)] * 3, OK, base_delay_seconds=100, jitter=1.0)
        c.query(QUERY, {})
        self.assertEqual(sleeps, [60.0, 60.0, 60.0])

    def test_10_authentication_failure_is_not_retried(self):
        for outcome in (HttpFailure(401, body({"message": "Not Authenticated"})), body({"message": "Not Authenticated"}),
                        body({"message": "Invalid token", "extensions": {"code": "UNAUTHENTICATED"}})):
            c, transport, sleeps = client(outcome, OK)
            with self.assertRaises(AuthenticationFailed) as caught:
                c.query(QUERY, {})
            self.assertEqual((transport.calls, sleeps, caught.exception.category), (1, [], "authentication"))
            self.assertIsInstance(caught.exception, MissingAccess)   # existing CLIs still report MISSING_ACCESS

    def test_11_permission_failure_is_not_retried(self):
        for outcome in (HttpFailure(403, b""), body({"message": "User unauthorized to perform action", "extensions": {"code": "USER_UNAUTHORIZED"}}),
                        body(error_code="UserUnauthorizedException", error_message="User unauthorized", status_code=403)):
            c, transport, _ = client(outcome, OK)
            with self.assertRaises(PermissionDenied):
                c.query(QUERY, {})
            self.assertEqual(transport.calls, 1)

    def test_12_invalid_query_is_not_retried(self):
        for outcome in (body({"message": "Field 'nope' doesn't exist on type 'Board'", "extensions": {"code": "GRAPHQL_VALIDATION_FAILED"}}),
                        HttpFailure(400, body({"message": "Parse error on \"}\" (RCURLY)"})), HttpFailure(404, b"")):
            c, transport, sleeps = client(outcome, OK)
            with self.assertRaises(PermanentApiError) as caught:
                c.query(QUERY, {})
            self.assertEqual((transport.calls, sleeps, caught.exception.category), (1, [], "permanent_api"))

    def test_12b_api_version_rejection_is_surfaced_not_retried_or_switched(self):
        c, transport, _ = client(HttpFailure(400, body({"message": "API-Version 1999-01 is not supported"})), OK)
        with self.assertRaises(ApiVersionError) as caught:
            c.query(QUERY, {})
        self.assertEqual((transport.calls, caught.exception.category, c.api_version), (1, "api_version", "2025-04"))

    def test_13_14_writes_are_blocked_before_the_network(self):
        for operation in ("mutation { delete_item(item_id: 1) { id } }", "subscription { item_created { id } }",
                          "# read\n  Mutation Named { change_column_value(board_id: 1) { id } }"):
            c, transport, sleeps = client(OK)
            with self.assertRaises(ReadOnlyViolation):
                c.query(operation, {})
            self.assertEqual((transport.calls, c.stats.requests, sleeps), (0, 0, []))
        real = ReadOnlyMondayClient.from_token(TOKEN)
        with mock.patch.object(monday_client.urllib.request, "urlopen", side_effect=AssertionError("request sent")) as sent:
            with self.assertRaises(ReadOnlyViolation):
                real.query("mutation { archive_board(board_id: 1) { id } }", {})
            sent.assert_not_called()

    def test_13b_writes_hidden_by_comment_or_string_tricks_are_blocked_before_the_network(self):
        # A quote inside a comment is not a string: GraphQL would still run the mutation on the next line.
        for operation in ('# "\nmutation { delete_item(item_id: 1) { id } } # "',
                          '# """\nmutation { archive_item(item_id: 1) { id } }\n# """',
                          'query { a(x: "unterminated) }\nmutation { delete_item(item_id: 1) { id } }',
                          'query { a(x: "line\\\nmutation { delete_item(item_id: 1) { id } }")}',
                          'query { a(x: """never closed\nmutation { x } ) }',
                          '{ a }\r# "\rsubscription { item_created { id } }'):
            c, transport, sleeps = client(OK)
            with self.subTest(operation=operation), self.assertRaises(ReadOnlyViolation):
                c.query(operation, {})
            self.assertEqual((transport.calls, c.stats.requests, sleeps), (0, 0, []))

    def test_13c_mutation_words_inside_strings_and_comments_stay_readable(self):
        for operation in ('query { items(ids: [1]) { name } } # mutation { x }',
                          'query { a(x: "mutation { delete_item(item_id: 1) }") }',
                          'query { a(x: "escaped \\" mutation") }',
                          'query { a(x: """block "mutation" \\""" subscription""") }',
                          'query { mutation_log: items { id } }'):
            c, transport, _ = client(OK)
            with self.subTest(operation=operation):
                self.assertEqual(c.query(operation, {}), OK)
                self.assertEqual(transport.calls, 1)

    def test_15_token_never_in_errors_or_metadata(self):
        echo = body({"message": f"Invalid token {TOKEN}", "extensions": {"code": "UNAUTHENTICATED"}})
        real = ReadOnlyMondayClient.from_token(TOKEN, sleep=lambda s: None)
        http_error = urllib.error.HTTPError("https://api.monday.com/v2", 503, "Service Unavailable", Message(), io.BytesIO(TOKEN.encode()))
        for side_effect in (lambda *a, **k: io.BytesIO(echo), http_error, urllib.error.URLError(f"proxy said {TOKEN}")):
            with mock.patch.object(monday_client.urllib.request, "urlopen", side_effect=side_effect), self.assertRaises(MondayError) as caught:
                real.query(QUERY, {})
            error = caught.exception
            for text in (str(error), repr(error), repr(error.args), str(error.__cause__), str(error.__context__), json.dumps(real.stats.as_dict()), repr(real)):
                self.assertNotIn(TOKEN, text)
            self.assertNotIn("Authorization", str(error))

    def test_16_counters_across_requests(self):
        c, _, _ = client(HttpFailure(502), OK, OK, HttpFailure(429, b"", retry_after="1"), HttpFailure(429, b"", retry_after="2"), OK,
                         body({"message": "bad", "extensions": {"code": "INVALID_ARGUMENT"}}))
        c.query(QUERY, {})
        c.query(QUERY, {})
        c.query(QUERY, {})
        with self.assertRaises(PermanentApiError):
            c.query(QUERY, {})
        self.assertEqual(c.stats.as_dict(), {"requests": 7, "retries": 3, "succeeded": 3, "failed": 1, "slept_seconds": 3.75,
                                             "failures_by_category": {"permanent_api": 1, "rate_limited": 2, "transient_api": 1},
                                             "last_failure_category": "permanent_api"})

    def test_unreadable_response_is_transient(self):
        c, _, _ = client(b"<html>proxy error</html>", OK)
        self.assertEqual(c.query(QUERY, {}), OK)
        self.assertEqual(c.stats.failures_by_category, {"transient_api": 1})

    def test_real_transport_maps_http_errors(self):
        headers = Message()
        headers["Retry-After"] = "4"
        calls = []

        def urlopen(request, timeout):
            calls.append(request)
            if len(calls) == 1:
                raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", headers, io.BytesIO(b""))
            return io.BytesIO(OK)

        sleeps = []
        real = ReadOnlyMondayClient.from_token(TOKEN, "2025-04", sleep=sleeps.append)
        with mock.patch.object(monday_client.urllib.request, "urlopen", urlopen):
            self.assertEqual(real.query(QUERY, {}), OK)
        self.assertEqual((sleeps, len(calls), calls[0].get_header("Api-version")), ([4.0], 2, "2025-04"))


class SettingsAndCliTests(unittest.TestCase):
    def test_17_invalid_api_version_fails_cleanly(self):
        for version in ("latest", "2025-4", "2025-13", ""):
            with self.assertRaises(InvalidMondaySetting) as caught:
                ReadOnlyMondayClient.from_token(TOKEN, version)
            self.assertNotIn(TOKEN, str(caught.exception))

    def test_18_probe_capture_handles_invalid_settings_without_traceback(self):
        raw = Path(tempfile.mkdtemp(prefix="atlas-probe-")) / "raw"
        args = ["capture", "--board", "1", "--items", "2", "--since", "2026-09-01T00:00:00Z", "--until", "2026-09-02T00:00:00Z", "--raw-dir", str(raw)]
        for env, expected in (({"MONDAY_API_TOKEN": TOKEN, "MONDAY_API_VERSION": "v9"}, "INVALID_CONFIGURATION"),
                              ({"MONDAY_API_TOKEN": TOKEN, "MONDAY_API_TOKEN_FILE": "/nonexistent"}, "INVALID_CONFIGURATION"),
                              ({}, "MISSING_ACCESS")):
            err = io.StringIO()
            with mock.patch.dict("os.environ", env, clear=True), redirect_stderr(err):
                self.assertEqual(probe_cli.main(args), 2)
            self.assertIn(expected, err.getvalue())
            self.assertNotIn("Traceback", err.getvalue())
            self.assertNotIn(TOKEN, err.getvalue())

    def test_probe_capture_reports_api_failures_by_category(self):
        raw = Path(tempfile.mkdtemp(prefix="atlas-probe-")) / "raw"
        args = ["capture", "--board", "1", "--items", "2", "--since", "2026-09-01T00:00:00Z", "--until", "2026-09-02T00:00:00Z", "--raw-dir", str(raw)]
        err = io.StringIO()
        with mock.patch.dict("os.environ", {"MONDAY_API_TOKEN": TOKEN}, clear=True), redirect_stderr(err), \
                mock.patch.object(monday_client.urllib.request, "urlopen", side_effect=lambda *a, **k: io.BytesIO(body({"message": "Field x missing"}))):
            self.assertEqual(probe_cli.main(args), 3)
        self.assertIn("MONDAY_API_ERROR [permanent_api]", err.getvalue())

    def test_19_production_config_accepts_only_contract_1_4_0(self):
        data = tempfile.mkdtemp(prefix="atlas-config-")
        now = datetime(2026, 9, 28, tzinfo=timezone.utc)
        self.assertEqual(load_sync_config({"ATLAS_DATA_DIR": data}, now=now).contract_version, "1.4.0")
        for version in ("1.0.0", "1.1.0", "1.2.0", "1.3.0"):
            with self.assertRaisesRegex(ConfigError, "not allowed for production sync"):
                load_sync_config({"ATLAS_DATA_DIR": data, "ATLAS_CONTRACT_VERSION": version}, now=now)


if __name__ == "__main__":
    unittest.main()
