"""``verdicts.json`` as an optional site artifact, like ``intelligence-v2.json``: validated whenever present, never required, so builds
with and without it validate, publish and roll back."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from atlas_commander.capabilities import capabilities
from atlas_commander.contracts import schema_errors
from atlas_commander.verdict.config import VerdictConfig, load_config
from atlas_commander.verdict.engine import SCHEMA, build_verdicts

VERDICTS_JSON = "verdicts.json"


def build_site_verdicts(dashboard: Mapping[str, Any], intelligence: Mapping[str, Any] | None, generated_at: str,
                        config: VerdictConfig | None = None, monday_item_url: str | None = None) -> dict[str, Any] | None:
    """The verdict document when ``config/verdict-v1.json`` includes it in site builds and the contract has Editor intelligence
    (1.5.0+); otherwise None."""
    config = config or load_config()
    if not config.include_in_site_build or not capabilities(dashboard["source"]["executable_contract_version"]).editor_intelligence:
        return None
    return build_verdicts(dashboard, intelligence, generated_at, config, monday_item_url)


def write_document(site: Path, document: Mapping[str, Any]) -> Path:
    path = site / VERDICTS_JSON
    path.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def site_problems(path: Path, contract_version: str, retrieved_at: Any) -> list[str]:
    """Why a ``verdicts.json`` found in a build may not be published (empty when it may)."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"{VERDICTS_JSON} is not valid JSON"]
    if not isinstance(document, dict):
        return [f"{VERDICTS_JSON} is not a document"]
    problems = [f"{VERDICTS_JSON}: {error}" for error in schema_errors(document, SCHEMA)]   # the publisher caps the list it reports
    if problems:
        return problems
    if (document.get("source") or {}).get("retrieved_at") != retrieved_at:
        problems.append(f"{VERDICTS_JSON} does not come from this build's Monday snapshot")
    if document.get("executable_contract_version") != contract_version:
        problems.append(f"{VERDICTS_JSON} was built with another contract")
    return problems
