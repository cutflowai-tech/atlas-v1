"""Atlas production sync commands.

    PYTHONPATH=src python3 -m atlas_sync run-once [--json]

``run-once`` performs one sync attempt (see :mod:`atlas_sync.run`) and stages a build; it never publishes.
Exit status: 0 only for a verified, validated, completed staged build; 2 configuration or Monday access;
3 Monday read or ingestion; 4 production verification; 5 build (reconstruction, profiles, dashboard,
validation, metadata); 6 time budget exhausted.
"""

from __future__ import annotations

import argparse
import json
import sys

from .run import exit_code, run_once, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas_sync", description="Atlas production sync (read-only Monday; staged builds only).")
    sub = parser.add_subparsers(dest="command", required=True)
    once = sub.add_parser("run-once", help="one sync attempt: Monday -> verified raw run -> staged build (not published)")
    once.add_argument("--json", action="store_true", help="print the full attempt result as JSON instead of the summary")
    args = parser.parse_args(argv)
    result = run_once()
    print(json.dumps(result.as_dict(), indent=1) if args.json else summary(result))
    return exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
