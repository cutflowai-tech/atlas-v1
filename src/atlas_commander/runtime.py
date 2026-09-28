from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from atlas_commander.identity import IdentityMapping, Resolution, resolve_editor
from atlas_commander.normalization import NormalizationResult, normalize_events, status_mapping_config
from atlas_commander.video_type import VideoTypeMapping, VideoTypeResolution, resolve_video_type

ROOT = Path(__file__).resolve().parents[2]
# Every approved executable contract stays loadable so historical results remain reproducible.
CONTRACT_PATHS = {
    "1.0.0": ROOT / "config" / "monday-contract-v1.0.json",
    "1.1.0": ROOT / "config" / "monday-contract-v1.1.json",
    "1.2.0": ROOT / "config" / "monday-contract-v1.2.json",
}
ACTIVE_CONTRACT_VERSION = "1.2.0"
CONFIG_PATH = CONTRACT_PATHS[ACTIVE_CONTRACT_VERSION]


def load_contract(path: Path = CONFIG_PATH) -> dict[str, Any]:
    config = json.loads(path.read_text())
    return config


def load_contract_version(version: str) -> dict[str, Any]:
    """Load an approved executable contract by its contract version."""
    if version not in CONTRACT_PATHS:
        raise KeyError(f"unknown Monday contract version {version!r}")
    return load_contract(CONTRACT_PATHS[version])


def normalize_contract_events(raw_events: Any, config: dict[str, Any] | None = None) -> NormalizationResult:
    contract = config or load_contract()
    return normalize_events(raw_events, status_mapping_config(contract))


def resolve_contract_editor(observation: Any, config: dict[str, Any] | None = None) -> Resolution:
    contract = config or load_contract()
    mapping = IdentityMapping.from_dict(
        {
            "mapping_version": contract["editor_attribution"]["mapping_version"],
            "entries": contract["editor_attribution"]["entries"],
        }
    )
    return resolve_editor(observation, mapping)


def resolve_contract_video_type(ids: Any = None, labels: Any = None, config: dict[str, Any] | None = None) -> VideoTypeResolution:
    """Resolve Monday Video Type label IDs and/or texts with the contract's versioned mapping."""
    contract = config or load_contract()
    return resolve_video_type(VideoTypeMapping.from_contract(contract), ids, labels)


def video_type_cohort(labels: Any, config: dict[str, Any] | None = None) -> str | None:
    """Return the exact sorted canonical cohort key for label texts, or None when unresolved."""
    if isinstance(labels, str):
        labels = [labels]
    if not isinstance(labels, (list, tuple)) or not labels:
        return None
    return resolve_contract_video_type(labels=labels, config=config).cohort_key
