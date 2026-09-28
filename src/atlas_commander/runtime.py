from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from atlas_commander.identity import IdentityMapping, Resolution, resolve_editor
from atlas_commander.normalization import NormalizationResult, normalize_events

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "monday-contract-v1.0.json"


def load_contract(path: Path = CONFIG_PATH) -> dict[str, Any]:
    config = json.loads(path.read_text())
    return config


def normalize_contract_events(raw_events: Any, config: dict[str, Any] | None = None) -> NormalizationResult:
    contract = config or load_contract()
    return normalize_events(
        raw_events,
        {
            "version": contract["status_mapping_version"],
            "statuses": contract["status_mapping"],
        },
    )


def resolve_contract_editor(observation: Any, config: dict[str, Any] | None = None) -> Resolution:
    contract = config or load_contract()
    mapping = IdentityMapping.from_dict(
        {
            "mapping_version": contract["editor_attribution"]["mapping_version"],
            "entries": contract["editor_attribution"]["entries"],
        }
    )
    return resolve_editor(observation, mapping)


def video_type_cohort(labels: Any, config: dict[str, Any] | None = None) -> str | None:
    """Return the exact sorted canonical cohort key, or None when unresolved."""
    contract = config or load_contract()
    mapping = contract["video_type_cohorts"]["label_to_id"]
    if isinstance(labels, str):
        labels = [labels]
    if not isinstance(labels, (list, tuple)) or not labels:
        return None
    ids: list[str] = []
    for label in labels:
        if not isinstance(label, str) or label not in mapping:
            return None
        ids.append(str(mapping[label]))
    if len(set(ids)) != len(ids):
        return None
    return ":".join(sorted(ids))
