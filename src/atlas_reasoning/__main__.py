"""Reasoning V3 operator commands. Output is JSON on stdout; secrets never appear in it.

    python -m atlas_reasoning migrate                 apply pending database migrations (works with the feature flag off)
    python -m atlas_reasoning db-health               database reachable, migrated, untampered (exit 1 when not)
    python -m atlas_reasoning case <case_id>          everything stored about one case
    python -m atlas_reasoning result <result_id>      every version of one result
    python -m atlas_reasoning run <run_id>            one run and its Change Gate decisions
    python -m atlas_reasoning inspect <site_dir>      cases, member findings and fingerprints of a built site (no database)
    python -m atlas_reasoning gate <site_dir>         run the Change Gate on a built site (needs ATLAS_REASONING_V3=on)

The database comes from ATLAS_REASONING_DATABASE_URL (or ATLAS_REASONING_DATABASE_URL_FILE).
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


COMMANDS: dict[str, tuple[Callable[[argparse.Namespace], int], str]] = {
    "migrate": (cmd_migrate, "apply pending database migrations"),
    "db-health": (cmd_db_health, "check the Reasoning V3 database"),
    "case": (cmd_case, "show one case"),
    "result": (cmd_result, "show every version of one result"),
    "run": (cmd_run, "show one run and its gate decisions"),
    "inspect": (cmd_inspect, "show the cases of a built site without a database"),
    "gate": (cmd_gate, "run the Change Gate on a built site"),
}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python -m atlas_reasoning", description="Atlas Reasoning V3 operator commands")
    sub = root.add_subparsers(dest="command", required=True)
    for name, (_, help_text) in COMMANDS.items():
        command = sub.add_parser(name, help=help_text)
        if name == "case":
            command.add_argument("case_id")
        elif name == "result":
            command.add_argument("result_id")
        elif name == "run":
            command.add_argument("run_id")
        elif name in ("inspect", "gate"):
            command.add_argument("site_dir")
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
