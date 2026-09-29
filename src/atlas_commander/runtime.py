from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from atlas_commander.contracts import schema_errors
from atlas_commander.identity import IdentityMapping, Resolution, resolve_editor
from atlas_commander.normalization import NormalizationResult, normalize_events, status_mapping_config
from atlas_commander.video_type import VideoTypeMapping, VideoTypeResolution, resolve_video_type

ROOT = Path(__file__).resolve().parents[2]
# Every approved executable contract stays loadable so historical results remain reproducible.
CONTRACT_PATHS = {
    "1.0.0": ROOT / "config" / "monday-contract-v1.0.json",
    "1.1.0": ROOT / "config" / "monday-contract-v1.1.json",
    "1.2.0": ROOT / "config" / "monday-contract-v1.2.json",
    "1.3.0": ROOT / "config" / "monday-contract-v1.3.json",
    "1.4.0": ROOT / "config" / "monday-contract-v1.4.json",
    "1.5.0": ROOT / "config" / "monday-contract-v1.5.json",
}
CONTRACT_SCHEMAS = {"1.5.0": "monday-contract-v1.5.schema.json"}
ACTIVE_CONTRACT_VERSION = "1.4.0"
CONFIG_PATH = CONTRACT_PATHS[ACTIVE_CONTRACT_VERSION]


class ContractConfigError(ValueError):
    """A versioned executable contract does not satisfy its own immutable schema."""


def contract_config_errors(config: Any) -> list[str]:
    if not isinstance(config, dict):
        return ["contract config must be an object"]
    version = config.get("contract_version")
    schema = CONTRACT_SCHEMAS.get(version) if isinstance(version, str) else None
    if schema is None:
        return []
    errors = schema_errors(config, schema)
    if version == "1.5.0":
        expected = {f"D{number}" for number in range(20, 51)}
        authority_value = config.get("authority")
        authority: dict[str, Any] = authority_value if isinstance(authority_value, dict) else {}
        raw_decisions_value = authority.get("settled_decisions")
        raw_decisions: list[Any] = raw_decisions_value if isinstance(raw_decisions_value, list) else []
        decisions = {value for value in raw_decisions if isinstance(value, str)}
        if decisions != expected:
            errors.append("settled_decisions must contain D20 through D50 exactly")
        attribution_value = config.get("editor_attribution")
        attribution: dict[str, Any] = attribution_value if isinstance(attribution_value, dict) else {}
        raw_entries_value = attribution.get("entries")
        raw_entries: list[Any] = raw_entries_value if isinstance(raw_entries_value, list) else []
        mapped = [(entry.get("source_label_id"), entry.get("logged_name")) for entry in raw_entries if isinstance(entry, dict)]
        if len(mapped) != len(set(mapped)):
            errors.append("editor_attribution entries contain duplicate historical identity keys")
        raw_reasons_value = attribution.get("quarantine_reasons")
        raw_reasons: list[Any] = raw_reasons_value if isinstance(raw_reasons_value, list) else []
        quarantined = {(entry.get("source_label_id"), entry.get("logged_name")): entry.get("code")
                       for entry in raw_reasons if isinstance(entry, dict)}
        expected_quarantine = {("11", "New"): "invalid_identity_value", ("2", "Done"): "invalid_identity_value",
                               ("1", "El Baz"): "unresolved_historical_identity"}
        if quarantined != expected_quarantine:
            errors.append("D50 quarantine reasons must match the three approved historical identity tuples exactly")
        if set(mapped) & set(quarantined):
            errors.append("a quarantined historical identity cannot also be mapped")
        governance = config.get("threshold_governance") if isinstance(config.get("threshold_governance"), dict) else {}
        blockers_value = governance.get("blocking_identity_keys") if isinstance(governance, dict) else []
        blockers = {tuple(value) for value in blockers_value if isinstance(value, list) and len(value) == 2 and
                    all(isinstance(part, str) for part in value)} if isinstance(blockers_value, list) else set()
        expected_blockers = {("4", "Mario"), ("5", "Anas"), ("7", "Martin"), ("8", "Samra"), ("9", "Ibrahim"),
                             ("10", "Amir"), ("11", "Refaat")}
        if blockers != expected_blockers:
            errors.append("D44 threshold blockers must be the seven approved unresolved historical identities")
    return errors


def load_contract(path: Path = CONFIG_PATH) -> dict[str, Any]:
    config = json.loads(path.read_text())
    errors = contract_config_errors(config)
    if errors:
        raise ContractConfigError(f"invalid Monday contract {path.name}: " + "; ".join(errors))
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
    mapping = IdentityMapping.from_contract(contract)
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
