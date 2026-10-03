"""Phase 19-B: the optional live evaluation mode (``atlas_reasoning.evaluation_live``), tested with an injected fake HTTP function only.

No test here makes a provider call: the OpenRouter transport is real but its ``http`` is a local fake that answers like the offline model
and records what it was sent. Proves: explicit opt-in only (never from a credential, never in CI), mandatory budgets, the pinned model,
the disposable database guard, budget termination before any extra request, local fault injection, and that the key never leaks.
"""

from __future__ import annotations

import contextlib
import io
import json
import threading
import unittest
from collections.abc import Mapping
from typing import Any
from unittest import mock

from reasoning_db import requires_db, test_database_url

from atlas_reasoning import evaluation_cli
from atlas_reasoning.evaluation import load_golden_cases
from atlas_reasoning.evaluation_live import (
    LIVE_ENV,
    LiveBudget,
    LiveBudgetExhausted,
    LiveTransport,
    check_live_opt_in,
    live_plan,
)
from atlas_reasoning.evaluation_offline_model import MARKER, analyst_answer, golden_update
from atlas_reasoning.evaluation_runner import EvaluationConfigurationError, ResultCode, run_evaluation
from atlas_reasoning.openrouter_client import HttpResult, OpenRouterTransport
from atlas_reasoning.provider import CallContext, Message, ProviderRequest, ProviderUnavailable
from atlas_reasoning.settings import PINNED_MODEL

KEY = "sk-or-v1-test-0123456789abcdef"
DB = "postgresql://atlas@127.0.0.1:5432/atlas_reasoning_eval_test"


class FakeOpenRouter:
    """A local stand-in for the OpenRouter HTTP endpoint (never the network): answers like the offline model."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def __call__(self, url: str, headers: Mapping[str, str], body: bytes, timeout: float) -> HttpResult:
        document = json.loads(body)
        with self.lock:
            self.calls.append({"url": url, "headers": dict(headers), "model": document["model"]})
            number = len(self.calls)
        text = next(m["content"] for m in document["messages"] if m["role"] == "user" and MARKER in m["content"])
        payload = json.loads(text[text.index(MARKER) + len(MARKER):])
        answer = golden_update(payload) if "previous_result" in payload else analyst_answer(payload)
        response = {"id": f"gen-{number}", "model": document["model"], "choices": [{"message": {"content": json.dumps(answer)}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 400}}
        return HttpResult(200, {}, json.dumps(response).encode())


def transport(http: FakeOpenRouter) -> Any:
    return lambda settings: OpenRouterTransport(settings, http=http)


def live_env(**changes: str) -> dict[str, str]:
    env = {LIVE_ENV: "on", "ATLAS_REASONING_EVALUATION_DATABASE_URL": test_database_url() or DB, "OPENROUTER_API_KEY": KEY,
           "ATLAS_REASONING_LLM_BACKOFF_SECONDS": "0", "ATLAS_REASONING_LLM_MAX_BACKOFF_SECONDS": "0"}
    env.update(changes)
    return {name: value for name, value in env.items() if value != "<unset>"}


def request(purpose: str = "analyst", case_id: str = "c1") -> ProviderRequest:
    content = "Case (JSON):\n" + json.dumps({"x": 1})
    return ProviderRequest(messages=(Message("user", content),), context=CallContext(purpose=purpose, case_id=case_id, request_id="req_1"))


class OptInTests(unittest.TestCase):
    def plan(self, env: dict[str, str], **kwargs: Any) -> Any:
        arguments: dict[str, Any] = {"live": True, "max_calls": 10, "max_executive_calls": 0, "transport": transport(FakeOpenRouter())}
        arguments.update(kwargs)
        return live_plan(env, **arguments)

    def test_an_explicit_operator_run_is_accepted(self):
        built = self.plan(live_env())
        self.assertEqual(built.mode, "live")
        self.assertEqual(dict(built.environment), {"provider": "openrouter", "model": PINNED_MODEL})
        self.assertNotIn(KEY, repr(built))
        self.assertNotIn(KEY, repr(built.model(load_golden_cases()[0])))

    def test_a_credential_alone_never_enables_live_mode(self):
        for env in (live_env(**{LIVE_ENV: "<unset>"}), live_env(**{LIVE_ENV: "off"})):
            with self.assertRaisesRegex(EvaluationConfigurationError, LIVE_ENV):
                self.plan(env)
        with self.assertRaisesRegex(EvaluationConfigurationError, "--live"):
            self.plan(live_env(), live=False)

    def test_the_cli_without_live_flags_runs_offline_even_with_a_credential(self):
        args = evaluation_cli.parser().parse_args(["run"])
        built = evaluation_cli._plan(args, live_env())
        self.assertEqual(built.mode, "offline")

    def test_live_mode_is_refused_in_ci(self):
        for name in ("CI", "GITHUB_ACTIONS", "BUILDKITE", "GITLAB_CI", "JENKINS_URL", "TF_BUILD", "CIRCLECI", "CODEBUILD_BUILD_ID"):
            with self.assertRaisesRegex(EvaluationConfigurationError, "CI"):
                check_live_opt_in(live_env(**{name: "true"}), live=True)
        check_live_opt_in(live_env(CI="false"), live=True)

    def test_budgets_are_mandatory_and_bounded(self):
        for kwargs in ({"max_calls": None}, {"max_executive_calls": None}, {"max_calls": 0}, {"max_calls": -1}, {"max_calls": 10**6},
                       {"max_executive_calls": -1}, {"max_calls": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(EvaluationConfigurationError):
                self.plan(live_env(), **kwargs)

    def test_only_the_pinned_model(self):
        for env in (live_env(ATLAS_REASONING_MODEL="other/model"),
                    live_env(ATLAS_REASONING_MODEL="other/model", ATLAS_REASONING_ALLOW_MODEL_OVERRIDE="on")):
            with self.assertRaisesRegex(EvaluationConfigurationError, "pinned model"):
                self.plan(env)

    def test_only_a_disposable_database(self):
        with self.assertRaisesRegex(EvaluationConfigurationError, "test"):
            self.plan(live_env(ATLAS_REASONING_EVALUATION_DATABASE_URL="postgresql://atlas@db/atlas_reasoning"))
        with self.assertRaisesRegex(EvaluationConfigurationError, "ATLAS_REASONING_DATABASE_URL"):
            self.plan(live_env(ATLAS_REASONING_EVALUATION_DATABASE_URL=DB, ATLAS_REASONING_DATABASE_URL=DB))

    def test_live_mode_needs_the_operator_commands_transport(self):
        with self.assertRaisesRegex(EvaluationConfigurationError, "operator command"):
            self.plan(live_env(), transport=None)

    def test_the_operator_command_wires_the_openrouter_transport(self):
        from atlas_reasoning import __main__ as entry

        with mock.patch.object(evaluation_cli, "main", return_value=2) as delegated:
            entry.main(["evaluate", "run", "--live"])
        self.assertIs(delegated.call_args.kwargs["live_transport"], OpenRouterTransport)

    def test_a_missing_credential_is_a_configuration_error(self):
        with self.assertRaises(EvaluationConfigurationError) as raised:
            self.plan(live_env(OPENROUTER_API_KEY="<unset>"))
        self.assertIn("OPENROUTER_API_KEY", str(raised.exception))

    def test_cli_refusals_exit_two_before_any_call(self):
        http = FakeOpenRouter()
        for argv, env in ((["run", "--live"], live_env()), (["run", "--max-calls", "5"], live_env()),
                          (["run", "--live", "--max-calls", "5", "--max-executive-calls", "0"], live_env(GITHUB_ACTIONS="true"))):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = evaluation_cli.main(argv, env=env)
            self.assertEqual(code, 2, argv)
            self.assertEqual(json.loads(out.getvalue())["code"], "EVALUATION_CONFIGURATION_INVALID")
            self.assertNotIn(KEY, out.getvalue() + err.getvalue())
        self.assertEqual(http.calls, [])


class TransportTests(unittest.TestCase):
    def test_the_budget_counts_requests_and_executive_requests(self):
        budget = LiveBudget(3, 1)
        self.assertTrue(budget.acquire("executive"))
        self.assertFalse(budget.acquire("executive"))
        self.assertTrue(budget.exhausted)
        self.assertFalse(budget.acquire("analyst"))          # exhausted is final: the evaluation is stopping
        self.assertEqual(budget.snapshot(), {"max_calls": 3, "used": 1, "max_executive_calls": 1, "executive_used": 1, "refused": 2,
                                             "exhausted": True})

    def test_an_exhausted_budget_refuses_before_any_request(self):
        class Provider:
            provider_name = "openrouter"
            calls = 0

            def complete(self, request: Any, *, model: str, timeout: float) -> Any:
                Provider.calls += 1
                raise AssertionError("must not be called")

        budget = LiveBudget(1, 0)
        budget.acquire("analyst")
        transport = LiveTransport(Provider(), budget)
        with self.assertRaises(LiveBudgetExhausted) as raised:
            transport.complete(request(), model=PINNED_MODEL, timeout=5)
        self.assertFalse(raised.exception.retryable)
        self.assertEqual(Provider.calls, 0)

    def test_scripted_faults_are_local_and_free(self):
        class Provider:
            provider_name = "openrouter"

            def complete(self, request: Any, *, model: str, timeout: float) -> Any:
                raise AssertionError("a scripted fault must not reach the provider")

        budget = LiveBudget(1, 0)
        transport = LiveTransport(Provider(), budget).script("c1", ProviderUnavailable("down"))
        with self.assertRaises(ProviderUnavailable):
            transport.complete(request(), model=PINNED_MODEL, timeout=5)
        self.assertEqual(budget.used, 0)


@requires_db
class LiveRunTests(unittest.TestCase):
    """End-to-end live mode on the disposable test database with the fake OpenRouter endpoint."""

    def test_a_live_run_within_budget(self):
        http = FakeOpenRouter()
        built = live_plan(live_env(), live=True, max_calls=200, max_executive_calls=0, case_ids=("provider-failure",), transport=transport(http))
        result = run_evaluation(built)
        self.assertEqual(result.code, ResultCode.EVALUATION_FAILED)            # a one-case run never covers 1-20
        self.assertEqual([c.to_dict() for c in result.report.checks if not c.passed and c.fixture_id == "provider-failure"], [])
        self.assertGreater(len(http.calls), 0)
        self.assertTrue(all(call["model"] == PINNED_MODEL and call["headers"]["Authorization"] == f"Bearer {KEY}" for call in http.calls))
        document = json.loads(result.to_json())
        self.assertEqual(document["mode"], "live")
        self.assertEqual(document["budget"]["used"], len(http.calls))
        self.assertNotIn(KEY, result.to_json())

    def test_budget_exhaustion_stops_the_evaluation_safely(self):
        http = FakeOpenRouter()
        built = live_plan(live_env(), live=True, max_calls=2, max_executive_calls=0, case_ids=("unchanged-evidence", "provider-failure"), transport=transport(http))
        result = run_evaluation(built)
        self.assertEqual((result.code, result.exit_code, result.passed), (ResultCode.EVALUATION_BUDGET_EXHAUSTED, 4, False))
        self.assertIsNone(result.report)
        self.assertEqual(len(http.calls), 2)                                     # never a request over budget
        self.assertEqual(result.budget["used"], 2)
        self.assertTrue(result.budget["exhausted"])
        self.assertIn("unchanged-evidence", result.failures[0])                  # stopped in the first case; the second never started
        self.assertNotIn(KEY, result.to_json())

    def test_the_cli_live_run_reports_budget_exhaustion(self):
        http = FakeOpenRouter()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = evaluation_cli.main(["run", "--live", "--max-calls", "1", "--max-executive-calls", "0", "--case", "unchanged-evidence"],
                                       env=live_env(), live_transport=transport(http))
        self.assertEqual(code, 4)
        self.assertEqual(json.loads(out.getvalue())["code"], "EVALUATION_BUDGET_EXHAUSTED")
        self.assertEqual(len(http.calls), 1)
        self.assertNotIn(KEY, out.getvalue() + err.getvalue())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
