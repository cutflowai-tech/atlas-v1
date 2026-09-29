"""Language-neutral identity for one generated Atlas site.

The static site is published as one directory, so every route must identify the same
source snapshot and release.  These identifiers are derived only from shared build
inputs; locale is deliberately absent.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from atlas_commander.capabilities import capabilities
from atlas_commander.pipeline import CycleReconstruction

PUBLICATION_VIEW_VERSION = "atlas-publication-view-v1"


def _digest(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(data).hexdigest()[:20]


def build_publication_view(result: CycleReconstruction, contract: Mapping[str, Any], generated_at: str) -> dict[str, Any]:
    """Return the one snapshot/release identity embedded in every public route."""
    snapshot_source = {
        "retrieved_at": result.ingestion.get("retrieved_at"),
        "activity_log_window": result.ingestion.get("activity_log_window"),
        "source_run_id": result.ingestion.get("run_id"),
        "item_snapshots": result.item_snapshots,
        "cycles": [
            {
                "cycle_id": cycle.cycle_id,
                "state": cycle.state,
                "editor_id": cycle.editor_id,
                "in_progress_at": cycle.in_progress_at,
                "ready_for_approval_at": cycle.ready_for_approval_at,
                "exclusions": list(cycle.exclusions),
                "flags": list(cycle.flags),
            }
            for cycle in sorted(result.cycles, key=lambda row: row.cycle_id)
        ],
    }
    snapshot_id = str(snapshot_source["source_run_id"] or f"snapshot-{_digest(snapshot_source)}")
    release_id = f"release-{_digest({'snapshot_id': snapshot_id, 'generated_at': generated_at, 'contract_version': contract['contract_version']})}"
    route_state = {"release_id": release_id, "snapshot_id": snapshot_id}
    return {
        "publication_view_version": PUBLICATION_VIEW_VERSION,
        "release_id": release_id,
        "snapshot_id": snapshot_id,
        "generated_at": generated_at,
        "executable_contract_version": contract["contract_version"],
        "source": {
            "system": "monday",
            "retrieved_at": result.ingestion.get("retrieved_at"),
            "activity_log_window": result.ingestion.get("activity_log_window"),
            "source_run_id": result.ingestion.get("run_id"),
        },
        "routes": {
            "/": {"entry": "index.html", **route_state},
            "/en": {"entry": "en/index.html", **route_state},
            "/ar": {"entry": "ar/index.html", **route_state},
        },
    }


def site_publication(result: CycleReconstruction, contract: Mapping[str, Any], generated_at: str) -> dict[str, Any] | None:
    """The publication identity of a site built under ``contract``, or None for contracts without publication identity
    (through 1.4.0), whose sites keep their original files and pages."""
    return build_publication_view(result, contract, generated_at) if capabilities(contract).publication_identity else None
