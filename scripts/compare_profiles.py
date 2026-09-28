"""Compare two Editor Profile JSON files project by project (read-only, no Monday access).

Usage: PYTHONPATH=src python3 scripts/compare_profiles.py <reference_profile.json> <new_profile.json>

Prints JSON: projects only in one profile, and for projects in both, every field whose value
differs (Editor evidence, work start, Ready For Approval, Video Type cohort, Requested ETA,
deadline result, quality labels, revision count, exclusions and flags). Each difference must
then be traced to Monday evidence; this script only finds them.
"""

from __future__ import annotations

import json
import sys
from typing import Any

FIELDS = ["state", "in_progress_at", "ready_for_approval_at", "duration_seconds", "cohort_key", "speed_eligible", "requested_eta",
          "requested_eta_issue", "deadline_result", "deadline_delta_seconds", "quality_labels", "client_revision_events", "exclusions",
          "flags", "evidence_event_ids"]


def compare(reference: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_rows = {row["cycle_id"]: row for row in reference["projects"]}
    new_rows = {row["cycle_id"]: row for row in new["projects"]}
    changed = {}
    for cycle_id in sorted(old_rows.keys() & new_rows.keys()):
        diff = {field: {"reference": old_rows[cycle_id].get(field), "new": new_rows[cycle_id].get(field)}
                for field in FIELDS if old_rows[cycle_id].get(field) != new_rows[cycle_id].get(field)}
        if diff:
            changed[cycle_id] = diff
    return {
        "reference": {"generated_at": reference["generated_at"], "retrieved_at": reference["source"]["retrieved_at"], "projects": len(old_rows)},
        "new": {"generated_at": new["generated_at"], "retrieved_at": new["source"]["retrieved_at"], "projects": len(new_rows)},
        "only_in_reference": sorted(old_rows.keys() - new_rows.keys()),
        "only_in_new": sorted(new_rows.keys() - old_rows.keys()),
        "changed": changed,
        "unchanged": len(old_rows.keys() & new_rows.keys()) - len(changed),
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    with open(sys.argv[1]) as a, open(sys.argv[2]) as b:
        print(json.dumps(compare(json.load(a), json.load(b)), indent=1))
