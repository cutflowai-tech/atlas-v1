"""Phase 19-B: the evaluation runner (``atlas_reasoning.evaluation_runner``), its CLI and the human review checklist.

The runner executes the published Phase 19-A golden cases on the real Change Gate, engine, Phase 18 orchestration and PostgreSQL with the
deterministic offline model, and hands the result to the frozen Phase 19-A harness. These tests prove: the release evaluation PASSes and
its canonical report is byte-identical to the Phase 19-A golden driver's; every vocabulary term is performed; threshold, coverage and
audit failures are machine-readable FAILs with stable codes (never a crash, never a PASS); the database guard; no network; determinism.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import socket
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

from reasoning_db import fresh_database, requires_db, test_database_url

from atlas_reasoning import evaluation_cli, evaluation_review, evaluation_runner
from atlas_reasoning.evaluation import evaluate, load_golden_cases
from atlas_reasoning.evaluation_runner import (
    EXIT_CODES,
    EvaluationConfigurationError,
    EvaluationPlan,
    ResultCode,
    check_disposable,
    evaluation_database_url,
    run_evaluation,
)
from atlas_reasoning.evaluation_thresholds import release_thresholds
from atlas_reasoning.evaluation_types import (
    RUNTIME_KEYS,
    Comparator,
    EvidenceVariant,
    FaultKind,
    HumanKind,
    Op,
    Threshold,
    ThresholdSet,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "atlas_reasoning"
OFFLINE_MODULES = ("evaluation_runner.py", "evaluation_offline_model.py", "evaluation_review.py", "evaluation_live.py", "evaluation_cli.py",
                   "store/evaluation_audit.py", "store/evaluation_scenario.py")
SMALL = ("unchanged-evidence", "circuit-breaker-outage")


def plan(**changes: Any) -> EvaluationPlan:
    url = test_database_url()
    assert url is not None
    return EvaluationPlan(database_url=url, **changes)


def imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def cli(argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = evaluation_cli.main(argv, env=env)
    return code, out.getvalue(), err.getvalue()


@requires_db
class ReleaseEvaluationTests(unittest.TestCase):
    """All 20 golden cases through the runner (one fresh database each), compared with the Phase 19-A golden driver."""

    result: ClassVar[Any] = None
    driver: ClassVar[Any] = None

    @classmethod
    def setUpClass(cls):
        from reasoning_evaluation_driver import run_case

        from atlas_reasoning.store.repository import ReasoningStore

        cls.result = run_evaluation(plan())
        cases = load_golden_cases()
        cls.driver = evaluate(cases, [run_case(ReasoningStore(fresh_database()), case) for case in cases],
                              environment=dict(cls.result.report.environment))

    def test_the_release_evaluation_passes(self):
        result, report = self.result, self.result.report
        self.assertEqual((result.code, result.exit_code, result.passed), (ResultCode.PASS, 0, True))
        self.assertTrue(report.passed and report.coverage["release_conformant"])
        self.assertEqual(report.failures, ())
        self.assertEqual(report.thresholds.version, release_thresholds().version)
        self.assertEqual(sorted(case.number for case in load_golden_cases()), list(range(1, 21)))

    def test_canonical_report_is_byte_identical_to_the_golden_driver(self):
        self.assertEqual(self.result.report.canonical_json(), self.driver.canonical_json())

    def test_json_output_embeds_the_canonical_report(self):
        document = json.loads(self.result.to_json())
        canonical = self.result.report.canonical_json()
        self.assertEqual(document["report"], json.loads(canonical))
        self.assertEqual(document["report_sha256"], hashlib.sha256(canonical.encode()).hexdigest())
        self.assertEqual((document["schema"], document["result"], document["code"], document["exit_code"], document["mode"]),
                         ("reasoning-evaluation-run-v1", "PASS", "PASS", 0, "offline"))
        self.assertEqual(self.result.to_json(), self.result.to_json())
        self.assertEqual(document["report"]["environment"]["dataset"], "showcase-v1")


class VocabularyTests(unittest.TestCase):
    def test_the_published_cases_exercise_the_whole_vocabulary(self):
        cases = load_golden_cases()
        actions = [action for case in cases for step in case.steps for action in step.actions]
        self.assertEqual({action.op for action in actions}, set(Op))
        self.assertEqual({EvidenceVariant(a.params["evidence"]) for a in actions if a.op == Op.GATE}, set(EvidenceVariant))
        self.assertEqual({FaultKind(a.params["kind"]) for a in actions if a.op == Op.FAULT}, set(FaultKind))
        self.assertEqual({HumanKind(a.params["kind"]) for a in actions if a.op == Op.HUMAN}, set(HumanKind))
        self.assertEqual({key for case in cases for key in case.runtime} | {"gateway_concurrency"}, set(RUNTIME_KEYS) | {"gateway_concurrency"})

    def test_the_runner_dispatches_every_term(self):
        source = (SRC / "evaluation_runner.py").read_text(encoding="utf-8")
        for op in Op:
            self.assertIn(f"Op.{op.name}", source)
        for enum in (FaultKind, HumanKind):
            for member in enum:
                self.assertIn(f"{enum.__name__}.{member.name}", source)
        for variant in EvidenceVariant:
            self.assertIn(f"EvidenceVariant.{variant.name}", source)
        for key in RUNTIME_KEYS:
            self.assertIn(f'"{key}"', source)


@requires_db
class ResultPathTests(unittest.TestCase):
    """FAIL paths on small case subsets: each is a machine-readable result with a stable code, never a crash and never a PASS."""

    def test_partial_coverage_fails(self):
        result = run_evaluation(plan(case_ids=("unchanged-evidence",)))
        self.assertEqual((result.code, result.exit_code, result.passed), (ResultCode.EVALUATION_FAILED, 1, False))
        self.assertIsNotNone(result.report)
        self.assertEqual(len(result.report.coverage["missing"]), 19)
        self.assertTrue(any("coverage" in failure or "missing" in failure for failure in result.failures), result.failures)

    def test_a_threshold_failure_fails(self):
        impossible = ThresholdSet("test-impossible", tuple(
            Threshold(t.metric, Comparator.AT_MOST, "0", t.on_no_data) if t.metric == "case_identity_stability" else t
            for t in release_thresholds().thresholds))
        result = run_evaluation(plan(case_ids=("unchanged-evidence",), thresholds=impossible, required_numbers=(1,)))
        self.assertEqual(result.code, ResultCode.EVALUATION_FAILED)
        self.assertEqual(result.exit_code, 1)
        failed = [r.threshold.metric for r in result.report.threshold_results if not r.passed]
        self.assertIn("case_identity_stability", failed)

    def test_runs_are_reproducible(self):
        first, second = (run_evaluation(plan(case_ids=SMALL)) for _ in range(2))
        self.assertEqual(first.to_json(), second.to_json())
        self.assertEqual(first.report.canonical_json(), second.report.canonical_json())

    def test_a_step_reasoning_v3_cannot_perform_is_a_failed_evaluation(self):
        error = evaluation_runner.EvaluationRuntimeError("unchanged-evidence: the focus card has no open question to answer")
        with mock.patch.object(evaluation_runner.CaseRunner, "perform", side_effect=error):
            result = run_evaluation(plan(case_ids=("unchanged-evidence",)))
        self.assertEqual((result.code, result.exit_code, result.passed, result.report), (ResultCode.EVALUATION_FAILED, 1, False, None))
        self.assertIn("no open question", result.failures[0])

    def test_a_database_failure_mid_run_is_an_internal_error(self):
        from atlas_reasoning.store.db import DatabaseError

        with mock.patch.object(evaluation_runner, "fresh_database", side_effect=DatabaseError("connection lost")), \
             self.assertRaises(evaluation_runner.EvaluationInternalError):
            run_evaluation(plan(case_ids=("unchanged-evidence",)))
        with mock.patch.object(evaluation_runner, "fresh_database", side_effect=DatabaseError("connection lost")):
            code, out, err = cli(["run", "--case", "unchanged-evidence"], {"ATLAS_REASONING_EVALUATION_DATABASE_URL": test_database_url() or ""})
        self.assertEqual((code, json.loads(out)["code"]), (5, "EVALUATION_INTERNAL_ERROR"))
        self.assertNotIn("Traceback", out + err)

    def test_an_unreachable_database_is_a_configuration_error(self):
        code, out, _ = cli(["run"], {"ATLAS_REASONING_EVALUATION_DATABASE_URL": "postgresql://atlas:pw@127.0.0.1:1/atlas_reasoning_test"})
        self.assertEqual((code, json.loads(out)["code"]), (2, "EVALUATION_CONFIGURATION_INVALID"))
        self.assertNotIn(":pw@", out)

    def test_unknown_case_is_a_configuration_error(self):
        with self.assertRaises(EvaluationConfigurationError):
            run_evaluation(plan(case_ids=("no-such-case",)))

    def test_no_network_is_used(self):
        def refuse(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("the offline evaluation opened a network connection")

        with mock.patch.object(socket, "create_connection", refuse), mock.patch.object(socket.socket, "connect", refuse), \
             mock.patch("atlas_reasoning.openrouter_client.urllib_http", refuse):
            result = run_evaluation(plan(case_ids=("provider-failure",)))
        self.assertIsNotNone(result.report)
        self.assertEqual([check.to_dict() for check in result.report.checks if not check.passed and check.fixture_id == "provider-failure"], [])


def refusal_hook(*, request_id: str | None, at_step: str) -> Any:
    """A step hook that writes one refused candidate after ``at_step`` — with an unknown request ID, or (``None``) citing an existing
    reasoning call made before the step (so the step has more refusals than answered calls)."""

    def hook(store: Any, case: Any, step: Any) -> None:
        if step.step_id != at_step:
            return
        with store.transaction() as tx:
            row = tx._one("SELECT case_id FROM reasoning_cases ORDER BY case_id LIMIT 1")
            call = tx._one("SELECT request_id FROM llm_calls ORDER BY request_id LIMIT 1")
            tx.record_failed_candidate(case_id=row["case_id"], request_id=request_id or call["request_id"], purpose="analyst", attempt=1,
                                       validator_version="test", error_codes=["TEST"], violations=[{"code": "TEST"}], candidate=None)

    return hook


@requires_db
class AuditInconsistencyTests(unittest.TestCase):
    """Phase 19-A finding L4: an inconsistent audit trail is EVALUATION_AUDIT_INCONSISTENCY (exit 3), never a crash, a clipped metric or
    a PASS."""

    def steps(self) -> list[str]:
        case = next(case for case in load_golden_cases() if case.fixture_id == "unchanged-evidence")
        return [step.step_id for step in case.steps if step.evaluated]

    def assert_inconsistent(self, result: Any, kind: str) -> None:
        self.assertEqual((result.code, result.exit_code, result.passed), (ResultCode.EVALUATION_AUDIT_INCONSISTENCY, 3, False))
        self.assertIsNone(result.report)                       # no metric value is produced
        self.assertEqual(result.audit["kind"], kind)
        self.assertEqual(result.audit["fixture_id"], "unchanged-evidence")
        document = json.loads(result.to_json())
        self.assertEqual((document["result"], document["code"], document["report"], document["report_sha256"]),
                         ("FAIL", "EVALUATION_AUDIT_INCONSISTENCY", None, None))
        self.assertNotIn("Traceback", result.to_json())

    def test_a_refusal_without_its_provider_call(self):
        step = self.steps()[-1]
        result = run_evaluation(plan(case_ids=("unchanged-evidence",), step_hook=refusal_hook(request_id=f"req_{uuid.uuid4().hex}", at_step=step)))
        self.assert_inconsistent(result, "refusal_without_call")
        self.assertEqual(result.audit["step_id"], step)

    def test_more_refusals_than_answered_calls(self):
        # The second (unchanged) step makes no reasoning call; a refusal citing an earlier call gives refused 1 / answered 0, which the
        # frozen Phase 19-A MetricCount refuses (numerator > denominator).
        step = self.steps()[-1]
        result = run_evaluation(plan(case_ids=("unchanged-evidence",), step_hook=refusal_hook(request_id=None, at_step=step)))
        self.assert_inconsistent(result, "invalid_metric_count")
        self.assertIn("invalid metric count", result.audit["detail"])

    def test_other_value_errors_are_not_audit_results(self):
        with mock.patch.object(evaluation_runner, "observe_step", side_effect=ValueError("unrelated bug")), \
             self.assertRaisesRegex(ValueError, "unrelated bug"):
            run_evaluation(plan(case_ids=("unchanged-evidence",)))

    def test_the_cli_reports_an_audit_inconsistency_without_a_traceback(self):
        hook = refusal_hook(request_id=f"req_{uuid.uuid4().hex}", at_step=self.steps()[-1])
        original = evaluation_runner.offline_plan

        def with_hook(env: Any, *, case_ids: Any = ()) -> EvaluationPlan:
            built = original(env, case_ids=case_ids)
            built.step_hook = hook
            return built

        with mock.patch.object(evaluation_cli, "offline_plan", with_hook):
            code, out, err = cli(["run", "--case", "unchanged-evidence"], {"ATLAS_REASONING_EVALUATION_DATABASE_URL": test_database_url() or ""})
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)["code"], "EVALUATION_AUDIT_INCONSISTENCY")
        self.assertNotIn("Traceback", out + err)


@requires_db
class CliTests(unittest.TestCase):
    def env(self) -> dict[str, str]:
        return {"ATLAS_REASONING_EVALUATION_DATABASE_URL": test_database_url() or ""}

    def test_a_partial_run_exits_one_with_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "run.json"
            code, out, _ = cli(["run", "--case", "unchanged-evidence", "--output", str(output)], self.env())
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(out)["code"], "EVALUATION_FAILED")
            self.assertEqual(output.read_text(encoding="utf-8"), out)

    def test_an_unwritable_output_never_exits_zero_or_prints_a_traceback(self):
        with mock.patch.object(evaluation_cli, "run_evaluation", return_value=evaluation_runner.RunnerResult(ResultCode.PASS)):
            code, out, err = cli(["run", "--output", "/nonexistent-dir/run.json"], self.env())
        self.assertEqual(code, 5)
        self.assertNotIn("Traceback", out + err)

    def test_configuration_errors_exit_two_with_json(self):
        code, out, err = cli(["run"], {})
        self.assertEqual(code, 2)
        document = json.loads(out)
        self.assertEqual((document["code"], document["result"], document["report"]), ("EVALUATION_CONFIGURATION_INVALID", "FAIL", None))
        self.assertNotIn("Traceback", out + err)

    def test_an_internal_error_exits_five_never_pass(self):
        with mock.patch.object(evaluation_cli, "run_evaluation", side_effect=RuntimeError("boom Bearer sk-or-v1-abcdefghijklmnop")):
            code, out, err = cli(["run"], self.env())
        self.assertEqual(code, 5)
        document = json.loads(out)
        self.assertEqual((document["code"], document["result"]), ("EVALUATION_INTERNAL_ERROR", "FAIL"))
        self.assertNotIn("Traceback", out + err)
        self.assertNotIn("sk-or-v1-abcdefghijklmnop", out + err)

    def test_the_operator_entry_point_delegates(self):
        from atlas_reasoning import __main__ as entry

        with mock.patch.object(evaluation_cli, "main", return_value=4) as delegated:
            self.assertEqual(entry.main(["evaluate", "run", "--case", "x"]), 4)
        self.assertEqual(delegated.call_args.args, (["run", "--case", "x"],))

    def test_exit_codes_are_stable(self):
        self.assertEqual({code.value: EXIT_CODES[code] for code in ResultCode},
                         {"PASS": 0, "EVALUATION_FAILED": 1, "EVALUATION_CONFIGURATION_INVALID": 2, "EVALUATION_AUDIT_INCONSISTENCY": 3,
                          "EVALUATION_BUDGET_EXHAUSTED": 4, "EVALUATION_INTERNAL_ERROR": 5})


class DatabaseGuardTests(unittest.TestCase):
    """The runner drops the schema once per case: only a disposable test database that is not the canonical database is accepted."""

    def test_disposable_test_databases_are_accepted(self):
        url = "postgresql://atlas@127.0.0.1:5432/atlas_reasoning_eval_test"
        self.assertEqual(check_disposable(url, {}), url)
        self.assertEqual(evaluation_database_url({"ATLAS_REASONING_EVALUATION_DATABASE_URL": url}), url)

    def test_a_database_without_test_in_its_name_is_refused(self):
        with self.assertRaisesRegex(EvaluationConfigurationError, "the word 'test'"):
            check_disposable("postgresql://atlas:secret@db/atlas_reasoning", {})

    def test_the_canonical_database_is_refused(self):
        url = "postgresql://atlas:pw@db:5432/atlas_reasoning_test"
        with self.assertRaisesRegex(EvaluationConfigurationError, "ATLAS_REASONING_DATABASE_URL") as raised:
            check_disposable(url, {"ATLAS_REASONING_DATABASE_URL": "postgresql://other:pw2@db/atlas_reasoning_test"})
        self.assertNotIn("pw", str(raised.exception).replace("***", ""))

    def test_the_canonical_database_from_a_file_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            secret = Path(tmp) / "url"
            secret.write_text("postgresql://atlas@db/atlas_reasoning_test\n", encoding="utf-8")
            with self.assertRaises(EvaluationConfigurationError):
                check_disposable("postgresql://atlas@db:5432/atlas_reasoning_test", {"ATLAS_REASONING_DATABASE_URL_FILE": str(secret)})

    def test_libpq_query_parameters_cannot_redirect_the_target(self):
        for url in ("postgresql://atlas:pw@db/atlas_reasoning_test?dbname=atlas_reasoning", "postgresql://db/",
                    "postgresql://db/atlas_reasoning_test?service=prod"):
            with self.subTest(url=url), self.assertRaises(EvaluationConfigurationError) as raised:
                check_disposable(url, {})
            self.assertNotIn(":pw@", str(raised.exception))
        with self.assertRaises(EvaluationConfigurationError):
            check_disposable("postgresql:///atlas_reasoning_test?host=/tmp",
                             {"ATLAS_REASONING_DATABASE_URL": "postgresql://atlas@localhost/atlas_reasoning_test"})
        self.assertTrue(check_disposable("postgresql://db/x?dbname=atlas_reasoning_eval_test", {}))

    def test_test_must_be_a_word_of_the_name(self):
        for name in ("atlas_reasoning_latest", "contest", "attestation", "atlas_reasoning_testing"):
            with self.subTest(name=name), self.assertRaises(EvaluationConfigurationError):
                check_disposable(f"postgresql://db/{name}", {})
        for name in ("atlas_reasoning_test", "test_atlas", "atlas_reasoning_eval_test2", "atlas-tests"):
            self.assertTrue(check_disposable(f"postgresql://db/{name}", {}))

    def test_a_hand_built_plan_cannot_bypass_the_guard(self):
        for function in (run_evaluation, lambda built: evaluation_runner.observe_cases(built, load_golden_cases()[:1])):
            with self.assertRaisesRegex(EvaluationConfigurationError, "the word 'test'"):
                function(EvaluationPlan(database_url="postgresql://atlas:pw@db/atlas_reasoning"))

    def test_plans_never_show_the_database_password(self):
        self.assertNotIn("s3cret", repr(EvaluationPlan(database_url="postgresql://atlas:s3cret@db/atlas_reasoning_test")))

    def test_non_postgres_and_missing_urls_are_refused(self):
        with self.assertRaisesRegex(EvaluationConfigurationError, "postgresql"):
            check_disposable("sqlite:///tmp/x_test.db", {})
        with self.assertRaises(EvaluationConfigurationError):
            evaluation_database_url({})

    def test_the_test_database_variable_is_never_used_implicitly(self):
        with self.assertRaises(EvaluationConfigurationError):
            evaluation_database_url({"ATLAS_REASONING_TEST_DATABASE_URL": "postgresql://atlas@db/atlas_reasoning_test"})


class BoundaryTests(unittest.TestCase):
    def test_evaluation_modules_never_reach_a_network_client_or_test_code(self):
        # Live mode gets its transport from the operator command (__main__), the only module that wires OpenRouter.
        forbidden = ("atlas_reasoning.openrouter_client", "atlas_reasoning.honcho_client", "atlas_reasoning.evaluation_live", "urllib",
                     "http", "socket", "requests", "httpx")
        for name in OFFLINE_MODULES:
            allowed = {"urllib.parse"} | ({"atlas_reasoning.evaluation_live"} if name == "evaluation_cli.py" else set())
            found = {module for module in imports(SRC / name) - allowed
                     if module.split(".")[0] in ("urllib", "http", "socket", "requests", "httpx") or module in forbidden}
            self.assertEqual(found, set(), name)
            self.assertFalse({module for module in imports(SRC / name) if module.startswith(("reasoning_", "tests"))}, name)

    def test_the_runner_never_imports_the_review(self):
        self.assertNotIn("atlas_reasoning.evaluation_review", imports(SRC / "evaluation_runner.py"))

    def test_the_showcase_dataset_equals_the_test_snapshot(self):
        import reasoning_snapshots

        from atlas_reasoning.reasoning_input_boundary import showcase_reasoning_input

        self.assertEqual(showcase_reasoning_input(), reasoning_snapshots.reasoning_input())

    def test_live_mode_is_not_wired_into_make_or_ci(self):
        root = SRC.parents[1]
        texts = [(root / "Makefile").read_text(encoding="utf-8")]
        texts += [path.read_text(encoding="utf-8") for pattern in ("*.yml", "*.yaml") for path in (root / ".github").rglob(pattern)]
        for text in texts:
            self.assertNotIn("EVALUATION_LIVE", text)
            self.assertNotIn("--live", text)


class ReviewChecklistTests(unittest.TestCase):
    REQUIRED = ("factual_grounding", "proportionality", "management_usefulness", "uncertainty_calibration", "unnecessary_churn",
                "lifecycle_correctness", "atlas_questions_quality", "duplicate_questions", "hr_blame_personality_language",
                "evidence_traceability", "executive_brief_usefulness", "limitations_counter_evidence")

    def completed(self) -> dict[str, Any]:
        record = evaluation_review.template({"report_sha256": "a" * 64, "mode": "live"})
        record.update(reviewer="Release owner", reviewed_at="2026-10-03")
        for item in record["items"]:
            item["rating"] = "meets"
        return record

    def test_the_checklist_is_complete(self):
        self.assertEqual(evaluation_review.ITEM_IDS, self.REQUIRED)
        for item in evaluation_review.CHECKLIST:
            self.assertTrue(item.question.endswith("?") and item.look_for)

    def test_the_lifecycle_item_uses_the_canonical_lifecycle_vocabulary(self):
        # Ties the checklist to the Phase 09 lifecycle contract: a renamed, added or removed LifecycleStatus (or a non-canonical state
        # written into the guidance) fails here.
        import re

        from atlas_reasoning.enums import LifecycleStatus

        item = next(item for item in evaluation_review.CHECKLIST if item.item_id == "lifecycle_correctness")
        named = re.search(r"\(([^)]*)\)", item.question)
        assert named is not None
        self.assertEqual(tuple(state.strip() for state in named.group(1).split(",")), tuple(status.value for status in LifecycleStatus))
        self.assertEqual(evaluation_review.LIFECYCLE_STATES, tuple(status.value for status in LifecycleStatus))
        text = f"{item.question} {item.look_for}".lower()
        for word in ("monitoring", "stale", "archived", "dormant", "closed", "expired"):
            self.assertNotIn(word, text)
        templated = next(row for row in evaluation_review.template()["items"] if row["item_id"] == "lifecycle_correctness")
        self.assertEqual(templated["question"], item.question)

    def test_a_blank_template_is_not_a_valid_review(self):
        problems = evaluation_review.validate(evaluation_review.template())
        self.assertIn("reviewer is required", problems)
        self.assertIn("report_sha256 must name the reviewed evaluation report", problems)
        self.assertTrue(all(any(item in problem for problem in problems) for item in self.REQUIRED))

    def test_a_completed_review_validates_and_summarizes(self):
        record = self.completed()
        record["items"][2].update(rating="concern", notes="Two cards restate the data.")
        self.assertEqual(evaluation_review.validate(record, run={"report_sha256": "a" * 64}), [])
        summary = evaluation_review.summarize(record)
        self.assertEqual(summary["counts"], {"meets": 11, "concern": 1, "fails": 0, "not_applicable": 0})
        self.assertEqual(summary["concerns"], ["management_usefulness"])
        self.assertTrue(summary["release_input_only"])

    def test_invalid_reviews_are_refused(self):
        record = self.completed()
        record["items"][0].update(rating="fails", notes="")
        record["items"][1]["rating"] = "great"
        record["items"].append(dict(record["items"][3]))
        record["items"].append({"item_id": "vibes", "rating": "meets"})
        problems = evaluation_review.validate(record, run={"report_sha256": "b" * 64})
        self.assertIn("factual_grounding: a fails rating needs notes", problems)
        self.assertTrue(any(p.startswith("proportionality: rating must be") for p in problems))
        self.assertIn("uncertainty_calibration: rated twice", problems)
        self.assertTrue(any("unknown item 'vibes'" in p for p in problems))
        self.assertIn("report_sha256 does not match the evaluation run", problems)
        del record["items"][5]
        self.assertTrue(any(p.endswith(": not rated") for p in evaluation_review.validate(record)))

    def test_review_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_file, record_file = Path(tmp) / "run.json", Path(tmp) / "review.json"
            run_file.write_text(json.dumps({"report_sha256": "a" * 64, "mode": "live"}), encoding="utf-8")
            code, out, _ = cli(["review-template", "--run", str(run_file)], {})
            self.assertEqual((code, json.loads(out)["report_sha256"]), (0, "a" * 64))
            record_file.write_text(out, encoding="utf-8")
            code, out, _ = cli(["review-validate", str(record_file), "--run", str(run_file)], {})
            self.assertEqual((code, json.loads(out)["valid"]), (1, False))
            record_file.write_text(json.dumps(self.completed()), encoding="utf-8")
            code, out, _ = cli(["review-validate", str(record_file), "--run", str(run_file)], {})
            self.assertEqual((code, json.loads(out)["valid"]), (0, True))
            code, _, err = cli(["review-validate", str(Path(tmp) / "missing.json")], {})
            self.assertEqual(code, 2)
            self.assertIn("EvaluationConfigurationError", err)
            run_file.write_text("[1, 2]", encoding="utf-8")
            for argv in (["review-template", "--run", str(run_file)], ["review-validate", str(record_file), "--run", str(run_file)]):
                code, out, err = cli(argv, {})
                self.assertEqual(code, 2, argv)
                self.assertNotIn("Traceback", out + err)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
