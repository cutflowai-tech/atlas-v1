"""Which behaviour an executable Monday contract version enables.

Every version-dependent branch reads this one table instead of comparing version strings
locally, so a contract version either has a capability everywhere or nowhere. Contracts
through 1.4.0 keep their original output byte for byte; the capabilities below exist
only from 1.5.0 (D20--D50).

- ``label_taxonomy``: Quality labels carry a Positive / Negative / Context class from the
  contract's per-label registries (D28--D30); For Bonus is parsed per label.
- ``editor_intelligence``: the D23--D47 interpretation layer (evaluation windows, component
  states, Overall Status, Recent Change / Trend, Active Work, Cairo monthly history).
- ``publication_identity``: every public route carries one release / source-snapshot
  identity (``publication.json``, page meta tags), and validation requires it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

INTELLIGENCE_VERSION = (1, 5, 0)


@dataclass(frozen=True)
class ContractCapabilities:
    contract_version: str
    label_taxonomy: bool
    editor_intelligence: bool
    publication_identity: bool


def _version_tuple(version: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return None


def capabilities(contract: Mapping[str, Any] | str | None) -> ContractCapabilities:
    """Capabilities of a contract (or of a bare contract version string, e.g. a build's metadata)."""
    version = str((contract.get("contract_version") if isinstance(contract, Mapping) else contract) or "")
    parsed = _version_tuple(version)
    enabled = parsed is not None and parsed >= INTELLIGENCE_VERSION
    return ContractCapabilities(version, label_taxonomy=enabled, editor_intelligence=enabled, publication_identity=enabled)
