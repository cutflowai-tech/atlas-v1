"""Intelligence V2 as an optional, feature-gated site artifact (Tasks 65-68).

- **Gate.** ``config/intelligence-v2.json`` → ``publication.include_in_site_build`` (default ``false``). When true, a site build
  for a contract with ``editor_intelligence`` also writes ``intelligence-v2.json``, built in ``approved_only`` mode only.
- **Optional, never required.** ``site_layout.optional_files`` lists it, so a build with or without the file validates,
  publishes and rolls back. Turning the gate off needs no code change and no history rewrite.
- **Validated when present.** The file must satisfy ``contracts/intelligence-v2.schema.json``, be ``publishable`` (never review
  output) and come from the same Monday snapshot and contract as the rest of the site.
- **Not served publicly.** Like ``dashboard.json``, it sits beside the site; nginx serves only ``/``, ``/en`` and ``/ar``. The
  UI/UX branch decides how to present it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from atlas_commander.capabilities import capabilities
from atlas_commander.contracts import schema_errors
from atlas_commander.investigation.engine import SCHEMA, build_intelligence, consistency_errors
from atlas_commander.investigation.policy import APPROVED_ONLY, CONFIG_PATH
from atlas_commander.pipeline import CycleReconstruction

INTELLIGENCE_JSON = "intelligence-v2.json"


def enabled(config: Mapping[str, Any] | None = None) -> bool:
    data = config if config is not None else json.loads(CONFIG_PATH.read_text())
    return bool((data.get("publication") or {}).get("include_in_site_build"))


def write_site_intelligence(result: CycleReconstruction, contract: Mapping[str, Any], site: Path, generated_at: str,
                            profiles: Iterable[Mapping[str, Any]], config: Mapping[str, Any] | None = None) -> Path | None:
    """Write ``intelligence-v2.json`` into a site build when the gate is on and the contract supports it; otherwise nothing."""
    if not enabled(config) or not capabilities(contract).editor_intelligence:
        return None
    by_editor = {profile["editor"]["editor_id"]: profile for profile in profiles}
    document = build_intelligence(result, contract, generated_at, mode=APPROVED_ONLY, profiles=by_editor, config=config)
    path = site / INTELLIGENCE_JSON
    path.write_text(json.dumps(document, indent=1) + "\n")
    return path


def site_problems(path: Path, contract_version: str, retrieved_at: Any) -> list[str]:
    """Why an ``intelligence-v2.json`` found in a build may not be published (empty when it may)."""
    try:
        document = json.loads(path.read_text())
    except (OSError, ValueError):
        return [f"{INTELLIGENCE_JSON} is not valid JSON"]
    if not isinstance(document, dict):
        return [f"{INTELLIGENCE_JSON} is not a document"]
    problems = [f"{INTELLIGENCE_JSON}: {error}" for error in schema_errors(document, SCHEMA)[:5]]
    if problems:
        return problems
    problems += [f"{INTELLIGENCE_JSON}: {error}" for error in consistency_errors(document)[:5]]
    if document.get("publishable") is not True or document.get("mode") != APPROVED_ONLY:
        problems.append(f"{INTELLIGENCE_JSON} was built in review mode and must never be published")
    if (document.get("source") or {}).get("retrieved_at") != retrieved_at:
        problems.append(f"{INTELLIGENCE_JSON} does not come from this build's Monday snapshot")
    if document.get("executable_contract_version") != contract_version:
        problems.append(f"{INTELLIGENCE_JSON} was built with another contract")
    return problems
