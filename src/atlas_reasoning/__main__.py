"""Reasoning V3 operator commands. Output is JSON on stdout; secrets never appear in it.

    python -m atlas_reasoning migrate                 apply pending database migrations (works with the feature flag off)
    python -m atlas_reasoning db-health               database reachable, migrated, untampered (exit 1 when not)
    python -m atlas_reasoning case <case_id>          everything stored about one case
    python -m atlas_reasoning result <result_id>      every version of one result
    python -m atlas_reasoning run <run_id>            one run and its Change Gate decisions
    python -m atlas_reasoning inspect <site_dir>      cases, member findings and fingerprints of a built site (no database)
    python -m atlas_reasoning gate <site_dir>         run the Change Gate on a built site (needs ATLAS_REASONING_V3=on)
    python -m atlas_reasoning lifecycle <result_id>   lifecycle status, transition history and policy of one result
    python -m atlas_reasoning reason <run_id> [--resume] [--no-executive]
                                                      orchestrate the run (Phase 18: priority, call budget, run status; --resume
                                                      retries eligible failures), then the executive brief when the run is ready;
                                                      exit 0 only when the run is complete (needs ATLAS_REASONING_V3=on and the
                                                      OpenRouter key; Honcho memory only with ATLAS_REASONING_MEMORY=on)
    python -m atlas_reasoning provider-health [--dry-run] [--record]
                                                      check the OpenRouter configuration (--dry-run: no network call) or make
                                                      one minimal structured call to the pinned model (--record: into llm_calls)
    python -m atlas_reasoning memory-health [--dry-run]
                                                      check the Honcho memory configuration (--dry-run: no network call) or
                                                      get-or-create the environment's workspace
    python -m atlas_reasoning memory-sync [--limit N] retire expired teaching copies, copy teachings that came into effect,
                                                      then re-send pending or failed memory copies rebuilt from canonical rows

The database comes from ATLAS_REASONING_DATABASE_URL (or ATLAS_REASONING_DATABASE_URL_FILE); the OpenRouter key from
OPENROUTER_API_KEY (or OPENROUTER_API_KEY_FILE). Neither is ever printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from atlas_reasoning import settings
from atlas_reasoning.reasoning_input_boundary import ReasoningInputError
from atlas_reasoning.store.db import Database, DatabaseError


def _print(value: Any) -> None:
    json.dump(value, sys.stdout, indent=1, default=str, sort_keys=True)
    print()


def _database() -> Database:
    return Database(settings.database_url())


def _store() -> Any:
    from atlas_reasoning.store.repository import ReasoningStore

    return ReasoningStore(_database())


def cmd_migrate(args: argparse.Namespace) -> int:
    from atlas_reasoning.store.migrate import apply_migrations

    db = _database()
    _print({"database": db.display_url, "applied": apply_migrations(db)})
    return 0


def cmd_db_health(args: argparse.Namespace) -> int:
    from atlas_reasoning.store.health import database_health

    report = database_health(_database())
    _print(report)
    return 0 if report["ok"] else 1


def cmd_case(args: argparse.Namespace) -> int:
    _print(_store().case_debug(args.case_id))
    return 0


def cmd_result(args: argparse.Namespace) -> int:
    _print(_store().result_history(args.result_id))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    store = _store()
    observations = store.observations(run_id=args.run_id)
    _print({"run": store.get_run(args.run_id),
            "decisions": [{key: row[key] for key in ("case_id", "action", "reason_code", "reason_detail", "evidence_fingerprint", "previous_fingerprint",
                                                     "work_item_id")} for row in observations],
            "work_items": [item.__dict__ for item in store.work_items(run_id=args.run_id)]})
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    from atlas_reasoning.change_gate import prepare_cases
    from atlas_reasoning.reasoning_input_boundary import load_reasoning_input

    payload = load_reasoning_input(Path(args.site_dir))
    mapping, prepared = prepare_cases(payload, payload.snapshot.generated_at)
    _print({"source_snapshot_id": payload.snapshot.source_snapshot_id, "mapping_version": mapping.mapping_version, "unmapped": list(mapping.unmapped),
            "warnings": list(mapping.warnings),
            "cases": [{"case_id": case.case_id, "identity_key": case.document["identity_key"], "case_type": case.document["case_type"],
                       "orientation": case.document["orientation"], "evidence_fingerprint": case.fingerprint,
                       "supporting": [row["member_key"] for row in case.document["supporting_findings"]],
                       "contradicting": [row["member_key"] for row in case.document["contradicting_findings"]],
                       "references": len(case.document["current_evidence"]["references"])} for case in prepared.values()]})
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    from atlas_reasoning.change_gate import run_gate
    from atlas_reasoning.reasoning_input_boundary import load_reasoning_input
    from atlas_reasoning.store.repository import ReasoningStore

    settings.require_enabled()
    report = run_gate(load_reasoning_input(Path(args.site_dir)), ReasoningStore(_database()))
    output = report.to_dict()
    for decision in output["decisions"]:
        decision["detail"].pop("material_delta", None)
    _print(output)
    return 0


def cmd_lifecycle(args: argparse.Namespace) -> int:
    from atlas_reasoning.lifecycle import policy_from_env

    store = _store()
    with store.transaction() as tx:
        result = tx.get_result(args.result_id)
        versions = [{key: row[key] for key in ("version", "change_kind", "lifecycle_status", "run_id", "reason", "created_at")}
                    for row in tx.result_history(args.result_id)]
        transitions = tx.lifecycle_transitions(result_id=args.result_id)
    _print({"result_id": result.result_id, "case_id": result.case_id, "lifecycle_status": result.lifecycle_status.value,
            "superseded_by": result.to_dict()["superseded_by"], "policy": policy_from_env().to_dict(), "versions": versions,
            "transitions": [{key: row[key] for key in ("result_version", "from_status", "to_status", "reason_code", "reason_detail", "run_id",
                                                       "work_item_id", "superseded_by_case_id", "superseded_by_result_id", "created_at")}
                            for row in transitions]})
    return 0


def cmd_reason(args: argparse.Namespace) -> int:
    from atlas_reasoning.honcho_client import backend_from_env
    from atlas_reasoning.openrouter_client import OpenRouterTransport
    from atlas_reasoning.reasoning_context import HumanContext
    from atlas_reasoning.reasoning_runtime import build_runtime
    from atlas_reasoning.reviewer import reviewer_from_env
    from atlas_reasoning.store.calls import StoreCallRecorder
    from atlas_reasoning.store.repository import ReasoningStore

    settings.require_enabled()
    router = settings.openrouter_settings()
    store = ReasoningStore(_database())
    store.get_run(args.run_id)
    # Phase 18: one shared ProviderControls for every gateway of this process (case reasoning, reviewer, executive); the pass budget
    # (ATLAS_REASONING_RUN_CALL_BUDGET) charges case reasoning, the executive budget only executive synthesis. Human context around every
    # call (Honcho memory when ATLAS_REASONING_MEMORY=on); Phase 15 guardrails and the optional reviewer (ATLAS_REASONING_REVIEWER=on).
    runtime = build_runtime(store, OpenRouterTransport(router), recorder=StoreCallRecorder(store), secrets=(router.api_key,),
                            context=HumanContext(store, backend_from_env()), reviewer_factory=reviewer_from_env)
    report = runtime.orchestrator.resume(args.run_id) if args.resume else runtime.orchestrator.run(args.run_id)
    executive = runtime.synthesize(args.run_id).to_dict() if report.executive_ready and not args.no_executive else None
    _print({"orchestration": report.to_dict(), "executive": executive, "provider_controls": runtime.snapshot()})
    return 0 if report.status == "complete" else 1


HEALTH_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}


def cmd_provider_health(args: argparse.Namespace) -> int:
    from atlas_reasoning.gateway import MemoryRecorder, ReasoningGateway
    from atlas_reasoning.openrouter_client import OpenRouterTransport
    from atlas_reasoning.provider import CallContext, Message, ProviderError, ProviderRequest
    from atlas_reasoning.structured import schema_output

    limits = settings.gateway_settings()
    report: dict[str, Any] = {"provider": "openrouter", "model": limits.model, "pinned_model": settings.PINNED_MODEL, "timeout_seconds": limits.timeout_seconds,
                              "max_retries": limits.max_retries, "concurrency": limits.concurrency}
    try:
        router = settings.openrouter_settings()
        report.update(api_key_configured=True, base_url=router.base_url)
    except settings.ReasoningConfigError as error:
        report.update(ok=False, api_key_configured=False, error=str(error))
        _print(report)
        return 1
    if args.dry_run:
        report.update(ok=True, live_call=False)
        _print(report)
        return 0
    recorder: Any = MemoryRecorder()
    if args.record:
        from atlas_reasoning.store.calls import StoreCallRecorder
        from atlas_reasoning.store.repository import ReasoningStore

        recorder = StoreCallRecorder(ReasoningStore(_database()))
    gateway = ReasoningGateway(OpenRouterTransport(router), limits, recorder=recorder, secrets=(router.api_key,))
    request = ProviderRequest(CallContext(purpose="provider_health"), (Message("user", 'Reply with the JSON object {"ok": true} and nothing else.'),),
                              schema_output("atlas_health", HEALTH_SCHEMA), max_output_tokens=200, reasoning_effort="low")
    try:
        response = gateway.call(request)
        report.update(ok=response.parsed == {"ok": True}, live_call=True, request_id=response.request_id, response_model=response.model,
                      input_tokens=response.input_tokens, output_tokens=response.output_tokens)
    except ProviderError as error:
        report.update(ok=False, live_call=True, error_class=error.error_class, provider_status=error.provider_status, error=str(error))
    calls = getattr(recorder, "calls", [])
    if calls:
        report["latency_ms"] = calls[-1].latency_ms
        report["attempts"] = calls[-1].attempts
    _print(report)
    return 0 if report["ok"] else 1


def cmd_memory_health(args: argparse.Namespace) -> int:
    from atlas_reasoning.honcho_client import HonchoClient

    report: dict[str, Any] = {"memory_enabled": settings.memory_enabled()}
    if not report["memory_enabled"]:
        report.update(ok=True, note=f"{settings.MEMORY_FLAG_ENV} is off: canonical context only, nothing is sent to Honcho")
        _print(report)
        return 0
    honcho = settings.honcho_settings()
    report.update(api_key_configured=True, base_url=honcho.base_url, environment=honcho.environment, workspace=honcho.workspace_id)
    if args.dry_run:
        report.update(ok=True, live_call=False)
    else:
        report.update(HonchoClient(honcho).health(), live_call=True)
    _print(report)
    return 0 if report["ok"] else 1


def cmd_memory_sync(args: argparse.Namespace) -> int:
    from atlas_reasoning.honcho_client import backend_from_env
    from atlas_reasoning.human_context import sync_service
    from atlas_reasoning.teach_atlas import TeachAtlas

    backend = backend_from_env()
    store = _store()
    service = sync_service(store, backend)
    teach = TeachAtlas(store, service)
    retired = teach.retire_expired()                             # copies of teachings whose validity ended
    started = teach.sync_effective()                             # teachings whose validity began since they were written
    outcomes = service.retry(limit=args.limit)
    _print({"memory_enabled": backend is not None, "expired_teaching_copies_retired": retired,
            "effective_teachings": [outcome.__dict__ for outcome in started], "outcomes": [outcome.__dict__ for outcome in outcomes]})
    return 0 if all(outcome.status != "failed" for outcome in [*started, *outcomes]) else 1


COMMANDS: dict[str, tuple[Callable[[argparse.Namespace], int], str]] = {
    "migrate": (cmd_migrate, "apply pending database migrations"),
    "db-health": (cmd_db_health, "check the Reasoning V3 database"),
    "case": (cmd_case, "show one case"),
    "result": (cmd_result, "show every version of one result"),
    "run": (cmd_run, "show one run and its gate decisions"),
    "inspect": (cmd_inspect, "show the cases of a built site without a database"),
    "gate": (cmd_gate, "run the Change Gate on a built site"),
    "lifecycle": (cmd_lifecycle, "show the lifecycle history of one result"),
    "reason": (cmd_reason, "orchestrate a run's reasoning (priority, budget, status), then executive synthesis when ready"),
    "provider-health": (cmd_provider_health, "check the OpenRouter configuration or connectivity"),
    "memory-health": (cmd_memory_health, "check the Honcho memory configuration or connectivity"),
    "memory-sync": (cmd_memory_sync, "re-send pending or failed memory copies"),
}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python -m atlas_reasoning", description="Atlas Reasoning V3 operator commands")
    sub = root.add_subparsers(dest="command", required=True)
    for name, (_, help_text) in COMMANDS.items():
        command = sub.add_parser(name, help=help_text)
        if name == "case":
            command.add_argument("case_id")
        elif name in ("result", "lifecycle"):
            command.add_argument("result_id")
        elif name in ("run", "reason"):
            command.add_argument("run_id")
            if name == "reason":
                command.add_argument("--resume", action="store_true", help="resume the run: retry eligible failures and pending work")
                command.add_argument("--no-executive", action="store_true", help="do not run executive synthesis when the run is ready")
        elif name in ("inspect", "gate"):
            command.add_argument("site_dir")
        elif name == "provider-health":
            command.add_argument("--dry-run", action="store_true", help="validate configuration only; no network call")
            command.add_argument("--record", action="store_true", help="record the call in llm_calls")
        elif name == "memory-health":
            command.add_argument("--dry-run", action="store_true", help="validate configuration only; no network call")
        elif name == "memory-sync":
            command.add_argument("--limit", type=int, default=100)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return COMMANDS[args.command][0](args)
    except (settings.ReasoningConfigError, settings.ReasoningDisabled, DatabaseError, ReasoningInputError) as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
