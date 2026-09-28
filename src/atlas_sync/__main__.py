"""Atlas production sync commands.

    PYTHONPATH=src python3 -m atlas_sync run-once [--json]
    PYTHONPATH=src python3 -m atlas_sync publish <attempt_id> [--json]
    PYTHONPATH=src python3 -m atlas_sync rollback [<attempt_id>] [--json]

``run-once`` performs one sync attempt (see :mod:`atlas_sync.run`) and stages a build; it never publishes.
Exit status: 0 only for a verified, validated, completed staged build; 2 configuration or Monday access;
3 Monday read or ingestion; 4 production verification; 5 build (reconstruction, profiles, dashboard,
validation, metadata); 6 time budget exhausted.

``publish`` and ``rollback`` (see :mod:`atlas_sync.publish`) re-validate a completed build and switch the
live site to it atomically; they never rebuild. Exit status: 0 only after the switch was verified and its
metadata written; 2 configuration; 3 rejected (live site unchanged); 4 switch failed (live site unchanged);
5 switched, but verification or metadata failed (the new build is live; the output says how to recover).

All three commands exit 75 (EX_TEMPFAIL) when another Atlas production operation holds the shared lock;
nothing is started. The lock is taken inside run_once, publish and rollback, never here.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import publish as publication
from .run import exit_code, run_once, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas_sync", description="Atlas production sync (read-only Monday; staged builds; explicit publication).")
    sub = parser.add_subparsers(dest="command", required=True)
    once = sub.add_parser("run-once", help="one sync attempt: Monday -> verified raw run -> staged build (not published)")
    once.add_argument("--json", action="store_true", help="print the full attempt result as JSON instead of the summary")
    promote = sub.add_parser("publish", help="re-validate a completed staged build and make it the live site")
    promote.add_argument("attempt_id")
    promote.add_argument("--json", action="store_true")
    back = sub.add_parser("rollback", help="switch the live site back to a previously published build (default: the one before)")
    back.add_argument("attempt_id", nargs="?", default=None)
    back.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "run-once":
        result = run_once()
        print(json.dumps(result.as_dict(), indent=1) if args.json else summary(result))
        return exit_code(result)
    outcome = publication.publish(args.attempt_id) if args.command == "publish" else publication.rollback(args.attempt_id)
    print(json.dumps(outcome.as_dict(), indent=1) if args.json else publication.summary(outcome))
    return publication.exit_code(outcome)


if __name__ == "__main__":
    sys.exit(main())
