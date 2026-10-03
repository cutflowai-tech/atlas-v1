"""Intelligence V2 snapshots for Reasoning V3 tests, built once per process from the synthetic showcase extract.

``reasoning_input(at)`` is the boundary payload of the showcase site built at ``at`` (the analysis windows move with it, so
Intelligence V2 finding IDs change while the underlying management issues mostly do not): the replay used by the case-identity
and Change Gate tests.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta
from functools import cache
from typing import Any

from atlas_commander.demo import GENERATED_AT, showcase_extract
from atlas_commander.investigation.engine import build_intelligence
from atlas_commander.profile import build_editor_profile, profiled_editors
from atlas_commander.profile_cli import reconstruct_extract
from atlas_commander.publication import site_publication
from atlas_commander.runtime import load_contract_version
from atlas_reasoning.reasoning_input_boundary import ReasoningInput, build_reasoning_input

CONTRACT = load_contract_version("1.5.0")


def shifted(days: int) -> str:
    return (datetime.fromisoformat(GENERATED_AT.replace("Z", "+00:00")) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


@cache
def _reconstruction() -> Any:
    return reconstruct_extract(showcase_extract(), CONTRACT)


@cache
def documents(at: str = GENERATED_AT) -> tuple[dict[str, Any], dict[str, Any], tuple[dict[str, Any], ...]]:
    result = _reconstruction()
    profiles = {row["editor_id"]: build_editor_profile(result, CONTRACT, row["editor_id"], at) for row in profiled_editors(result)}
    intelligence = build_intelligence(result, CONTRACT, at, profiles=profiles)
    publication = site_publication(result, CONTRACT, at)
    assert publication is not None
    return intelligence, publication, tuple(profiles.values())


def reasoning_input(at: str = GENERATED_AT, intelligence: dict[str, Any] | None = None) -> ReasoningInput:
    base, publication, profiles = documents(at)
    return build_reasoning_input(intelligence=intelligence or base, publication=publication, profiles=profiles)


def intelligence_copy(at: str = GENERATED_AT) -> dict[str, Any]:
    return copy.deepcopy(documents(at)[0])
