"""``python -m atlas_reasoning evaluate ...``: the Phase 19 evaluation runner and the human review checklist (Phase 19-B).

    evaluate run [--case ID ...] [--output PATH]
                                     the offline release evaluation (deterministic offline model, FakeHoncho, no network) on the
                                     disposable database ATLAS_REASONING_EVALUATION_DATABASE_URL names; exit 0 only on PASS
    evaluate run --live --max-calls N --max-executive-calls N [--case ID ...]
                                     the optional live evaluation (evaluation_live: needs ATLAS_REASONING_EVALUATION_LIVE=on, never
                                     in CI, explicit budgets, the pinned model)
    evaluate review-template [--run PATH]
                                     a blank management-quality review record, bound to an evaluation run's JSON
    evaluate review-validate RECORD [--run PATH]
                                     validate a completed review record (exit 0 when complete); release input only

``run`` prints one deterministic JSON object on stdout (``evaluation_runner.RunnerResult.to_json``) whatever the outcome, and exits
with the result code's exit status (``evaluation_runner.EXIT_CODES``): 0 PASS, 1 FAIL, 2 configuration invalid, 3 audit inconsistency,
4 live budget exhausted, 5 internal error. No traceback is printed; secrets and database passwords never are.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from atlas_reasoning import evaluation_review
from atlas_reasoning.evaluation_runner import (
    EXIT_CODES,
    RUNNER_SCHEMA,
    RUNNER_VERSION,
    EvaluationConfigurationError,
    ResultCode,
    offline_plan,
    run_evaluation,
)
from atlas_reasoning.evaluation_types import FixtureError
from atlas_reasoning.provider import redact
from atlas_reasoning.settings import ReasoningConfigError
from atlas_reasoning.store.db import DatabaseError

_URL_PASSWORD = re.compile(r"(postgres(?:ql)?://[^:/@\s]+:)[^@\s]+@")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python -m atlas_reasoning evaluate", description="Reasoning V3 evaluation runner (Phase 19)")
    sub = root.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run", help="run the golden evaluation; exit 0 only on PASS")
    run.add_argument("--case", action="append", default=[], dest="cases", metavar="FIXTURE_ID", help="only this golden case (repeatable; "
                     "a partial run never PASSes coverage)")
    run.add_argument("--output", type=Path, help="also write the JSON result to this file")
    run.add_argument("--live", action="store_true", help="the optional live evaluation (also needs ATLAS_REASONING_EVALUATION_LIVE=on)")
    run.add_argument("--max-calls", type=int, help="live: total provider requests allowed, retries included")
    run.add_argument("--max-executive-calls", type=int, help="live: executive provider requests allowed")
    template = sub.add_parser("review-template", help="a blank management-quality review record")
    template.add_argument("--run", type=Path, help="the evaluation run JSON the review is bound to")
    check = sub.add_parser("review-validate", help="validate a completed review record")
    check.add_argument("record", type=Path)
    check.add_argument("--run", type=Path, help="the evaluation run JSON the review must be bound to")
    return root


def _write(text: str) -> None:
    sys.stdout.write(text + "\n")


def _failure(code: ResultCode, error: BaseException, *, mode: str) -> dict[str, Any]:
    """The machine-readable result of a run that produced no result object: the error class and a redacted message, never a traceback."""
    message = _URL_PASSWORD.sub(r"\1***@", redact(f"{type(error).__name__}: {error}"))
    return {"schema": RUNNER_SCHEMA, "runner": RUNNER_VERSION, "mode": mode, "result": "FAIL", "code": code.value, "exit_code": EXIT_CODES[code],
            "failures": [message], "audit": None, "budget": None, "report_sha256": None, "report": None}


def _plan(args: argparse.Namespace, env: Mapping[str, str], live_transport: Any = None) -> Any:
    if args.live or args.max_calls is not None or args.max_executive_calls is not None:
        from atlas_reasoning.evaluation_live import live_plan

        return live_plan(env, live=args.live, max_calls=args.max_calls, max_executive_calls=args.max_executive_calls, case_ids=args.cases,
                         transport=live_transport)
    return offline_plan(env, case_ids=args.cases)


def run(args: argparse.Namespace, env: Mapping[str, str], live_transport: Any = None) -> int:
    mode = "live" if args.live else "offline"
    try:
        result = run_evaluation(_plan(args, env, live_transport))
        code, payload = result.code, result.to_json()
    except (EvaluationConfigurationError, FixtureError, ReasoningConfigError, DatabaseError) as error:
        code = ResultCode.EVALUATION_CONFIGURATION_INVALID
        payload = json.dumps(_failure(code, error, mode=mode), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except Exception as error:  # noqa: BLE001 - the top of the command: a bug is reported as EVALUATION_INTERNAL_ERROR, never a PASS
        code = ResultCode.EVALUATION_INTERNAL_ERROR
        payload = json.dumps(_failure(code, error, mode=mode), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        print(f"evaluation internal error: {type(error).__name__} (see the JSON result)", file=sys.stderr)
    _write(payload)
    if args.output is not None:
        try:
            args.output.write_text(payload + "\n", encoding="utf-8")
        except OSError as error:
            print(json.dumps({"error": type(error).__name__, "message": f"cannot write {args.output.name}"}), file=sys.stderr)
            return EXIT_CODES[ResultCode.EVALUATION_INTERNAL_ERROR] if code == ResultCode.PASS else EXIT_CODES[code]
    return EXIT_CODES[code]


def _load(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise EvaluationConfigurationError(f"cannot read {path.name}: {type(error).__name__}") from None
    if not isinstance(document, dict):
        raise EvaluationConfigurationError(f"{path.name} must hold a JSON object")
    return document


def review_template(args: argparse.Namespace) -> int:
    run_json = _load(args.run) if args.run else None
    _write(json.dumps(evaluation_review.template(run_json), indent=1, sort_keys=True, ensure_ascii=False))
    return 0


def review_validate(args: argparse.Namespace) -> int:
    record = _load(args.record)
    problems = evaluation_review.validate(record, run=_load(args.run) if args.run else None)
    summary = evaluation_review.summarize(record) if not problems else None
    _write(json.dumps({"valid": not problems, "problems": problems, "summary": summary}, indent=1, sort_keys=True, ensure_ascii=False))
    return 0 if not problems else 1


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None, *, live_transport: Any = None) -> int:
    """``live_transport`` builds the OpenRouter transport for ``run --live`` (``evaluation_live.ProviderFactory``); the operator command
    passes it. Without it live mode refuses to start."""
    args = parser().parse_args(list(argv) if argv is not None else None)
    environment = os.environ if env is None else env
    if args.action == "run":
        return run(args, environment, live_transport)
    try:
        return review_template(args) if args.action == "review-template" else review_validate(args)
    except EvaluationConfigurationError as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
