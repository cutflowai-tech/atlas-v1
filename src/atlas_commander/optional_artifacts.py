"""Validation of the optional artifacts a site build may contain (``site_layout.optional_files``), one checker per file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from atlas_commander.investigation.site import INTELLIGENCE_JSON
from atlas_commander.investigation.site import site_problems as intelligence_problems
from atlas_commander.verdict.site import VERDICTS_JSON
from atlas_commander.verdict.site import site_problems as verdict_problems

CHECKERS = {INTELLIGENCE_JSON: intelligence_problems, VERDICTS_JSON: verdict_problems}


def problems(name: str, path: Path, contract_version: str, retrieved_at: Any) -> list[str]:
    """Why the optional artifact ``name`` at ``path`` may not be published (empty when it may)."""
    return CHECKERS[name](path, contract_version, retrieved_at)
