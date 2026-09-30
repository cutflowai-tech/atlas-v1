"""The verdict configuration (``config/verdict-v1.json``): every threshold and weight of the judgment layer, approved by D54.

No number that changes a verdict lives outside this file (``tests/test_redesign_verdict_config.py`` checks the engine's source).
Values that the redesign shares with Intelligence V2 (materiality) are read from ``config/intelligence-v2.json``, where D53 approved
them, never copied.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from atlas_commander.investigation.policy import CONFIG_PATH as INTELLIGENCE_CONFIG_PATH

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "verdict-v1.json"
APPROVING_DECISIONS = frozenset({"D54"})
SHARED_DECISIONS = frozenset({"D53"})   # values read from config/intelligence-v2.json


class ConfigError(ValueError):
    """The verdict configuration is incomplete or not approved; the verdict layer refuses to run."""


@dataclass(frozen=True)
class VerdictConfig:
    version: str
    decision_id: str
    include_in_site_build: bool
    values: Mapping[str, float]

    def __getitem__(self, name: str) -> float:
        try:
            return self.values[name]
        except KeyError:
            raise ConfigError(f"verdict parameter {name!r} is not configured") from None

    def as_document(self) -> dict[str, Any]:
        return {"version": self.version, "decision_id": self.decision_id, "values": dict(sorted(self.values.items()))}


def _shared(reference: str, intelligence: Mapping[str, Any]) -> float:
    file, name = reference.split(":", 1)
    if file != INTELLIGENCE_CONFIG_PATH.name:
        raise ConfigError(f"unknown shared configuration {file!r}")
    parameter = intelligence["parameters"].get(name) or {}
    if parameter.get("status") != "approved" or parameter.get("decision_id") not in SHARED_DECISIONS:
        raise ConfigError(f"shared parameter {name!r} is not approved in {file}")
    return float(parameter["value"])


def config_from(document: Mapping[str, Any], intelligence: Mapping[str, Any]) -> VerdictConfig:
    governance = document.get("governance") or {}
    if governance.get("decision_id") not in APPROVING_DECISIONS:
        raise ConfigError("the verdict configuration is not approved by a recorded decision")
    values: dict[str, float] = {}
    for name, parameter in (document.get("parameters") or {}).items():
        if "from_config" in parameter:
            if parameter.get("decision_id") not in SHARED_DECISIONS:
                raise ConfigError(f"{name}: a shared value must name the decision that approved it")
            values[name] = _shared(parameter["from_config"], intelligence)
        else:
            if parameter.get("decision_id") not in APPROVING_DECISIONS:
                raise ConfigError(f"{name}: not approved by {sorted(APPROVING_DECISIONS)}")
            if not isinstance(parameter.get("value"), (int, float)) or isinstance(parameter.get("value"), bool):
                raise ConfigError(f"{name}: value must be a number")
            values[name] = parameter["value"]
        if not parameter.get("meaning"):
            raise ConfigError(f"{name}: every parameter states its meaning")
    publication = document.get("publication") or {}
    return VerdictConfig(version=document["verdict_config_version"], decision_id=governance["decision_id"],
                         include_in_site_build=bool(publication.get("include_in_site_build")), values=values)


@lru_cache(maxsize=1)
def load_config() -> VerdictConfig:
    return config_from(json.loads(CONFIG_PATH.read_text()), json.loads(INTELLIGENCE_CONFIG_PATH.read_text()))
