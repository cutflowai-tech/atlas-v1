"""Operator report of reasoning reliability telemetry (``atlas_reasoning.reliability_metrics``). Read-only; JSON on stdout.

    python -m atlas_reasoning.reliability_report --run <run_id> [--run <run_id> ...]   these runs and their aggregate
    python -m atlas_reasoning.reliability_report [--latest N]                         the N most recent runs (default 1)

The database comes from ATLAS_REASONING_DATABASE_URL (or ATLAS_REASONING_DATABASE_URL_FILE) and is never printed. The report holds
identifiers, statuses, codes, counts, tokens and timings only: no prompt, response, candidate, note, memory text or credential.
Exit 0 with a report, 1 when a run does not exist or the database cannot be read.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from atlas_reasoning import settings
from atlas_reasoning.store.db import Database, DatabaseError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m atlas_reasoning.reliability_report", description=__doc__.split("\n\n")[0])
    parser.add_argument("--run", dest="runs", action="append", metavar="RUN_ID", help="a run to report (repeatable)")
    parser.add_argument("--latest", type=int, default=1, metavar="N", help="report the N most recent runs (when no --run is given)")
    args = parser.parse_args(argv)
    if args.latest < 1:
        parser.error("--latest must be at least 1")
    from atlas_reasoning.store.reliability_metrics import reliability_report
    from atlas_reasoning.store.repository import ReasoningStore

    try:
        report = reliability_report(ReasoningStore(Database(settings.database_url())), args.runs, latest=args.latest)
    except (DatabaseError, settings.ReasoningConfigError) as error:
        json.dump({"ok": False, "error": f"{type(error).__name__}: {error}"}, sys.stdout, sort_keys=True)
        print()
        return 1
    json.dump(report.to_dict(), sys.stdout, indent=1, sort_keys=True, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
