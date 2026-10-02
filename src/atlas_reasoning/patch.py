"""Deterministic patch merge and version diffs (``REV/08`` #5–#10). No LLM, no database.

``merge(previous, update, provenance)`` applies a validated ``ReasoningUpdate`` to the result version it was produced against:

- only the fields the update lists in ``changed_fields`` are replaced, each by its complete new value (the field is the unit of
  change: a list field is replaced as a whole);
- every other patchable field keeps its previous value **object for object** (it is copied, never re-serialized from model text),
  so untouched wording is byte-identical;
- identity and history never change: ``contract_version``, ``result_id``, ``case_id``, ``created_at`` and ``superseded_by`` are
  copied from the previous version (the update cannot even name them: ``contracts.IMMUTABLE_RESULT_FIELDS``);
- provenance of the new version is set by Python: version + 1, the evidence fingerprint and snapshot it was reviewed against, the
  model metadata and prompt version of the review, ``updated_at``. The lifecycle status is the caller's (``lifecycle``), never the
  model's.

A ``no_change`` update produces a version whose patchable fields are all identical to the previous version (a recorded review);
the previous version itself is never touched (versions are append-only).

``diff(previous, new)`` lists, per field, what a new version changed: the before/after of every changed patchable field and of every
provenance field (version, fingerprint, snapshot, lifecycle, model, prompt). It is persisted with every appended version
(``reasoning_result_diffs``).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from atlas_reasoning.contracts import IMMUTABLE_RESULT_FIELDS, PATCHABLE_FIELDS, ContractViolation
from atlas_reasoning.enums import UpdateAction

PATCH_VERSION = "patch-merge-v1"
# Fields a new version carries over unchanged, whatever the update says.
PRESERVED_IDENTITY = ("contract_version", "result_id", "case_id", "created_at", "superseded_by")
# Fields Python sets for each new version.
VERSION_PROVENANCE = ("version", "lifecycle_status", "source_snapshot_id", "evidence_fingerprint", "model_metadata", "prompt_version", "updated_at")


@dataclass(frozen=True)
class VersionProvenance:
    source_snapshot_id: str
    evidence_fingerprint: str
    model_metadata: Mapping[str, Any]
    prompt_version: str
    updated_at: str
    lifecycle_status: str


def merge(previous: Mapping[str, Any], update: Mapping[str, Any], provenance: VersionProvenance) -> dict[str, Any]:
    """The next version of ``previous`` with ``update`` applied. Raises ``ContractViolation`` when the update targets another result
    or version, or names a field that is not patchable (the contract validators reject both earlier; this is the last line)."""
    errors = []
    if (update["case_id"], update["result_id"]) != (previous["case_id"], previous["result_id"]):
        errors.append("IMMUTABLE_FIELD: the update targets another case or result")
    if update["base_version"] != previous["version"]:
        errors.append(f"STALE_BASE_VERSION: the update targets version {update['base_version']}, the result is at {previous['version']}")
    changed = {row["field"]: row["value"] for row in update["changed_fields"]}
    for name in changed:
        if name not in PATCHABLE_FIELDS:
            errors.append(f"IMMUTABLE_FIELD: {name} is not patchable" if name in IMMUTABLE_RESULT_FIELDS else f"UNKNOWN_FIELD: {name}")
    if (update["action"] == UpdateAction.NO_CHANGE) != (not changed):
        errors.append("ACTION_MISMATCH: a no_change update changes nothing; a patch changes at least one field")
    if errors:
        raise ContractViolation("ReasoningUpdate", errors)
    document: dict[str, Any] = {name: copy.deepcopy(previous[name]) for name in PRESERVED_IDENTITY}
    for name in PATCHABLE_FIELDS:
        document[name] = copy.deepcopy(changed[name]) if name in changed else copy.deepcopy(previous[name])
    document.update(version=previous["version"] + 1, lifecycle_status=provenance.lifecycle_status, source_snapshot_id=provenance.source_snapshot_id,
                    evidence_fingerprint=provenance.evidence_fingerprint, model_metadata=copy.deepcopy(dict(provenance.model_metadata)),
                    prompt_version=provenance.prompt_version, updated_at=provenance.updated_at)
    return {name: document[name] for name in previous}   # the result's own field order


def diff(previous: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    """What ``new`` changed relative to ``previous``: ``{"changed_fields": [...], "fields": {name: {before, after}},
    "provenance": {name: {before, after}}}``. Unchanged fields are not listed."""
    fields = {name: {"before": previous[name], "after": new[name]} for name in PATCHABLE_FIELDS if previous[name] != new[name]}
    provenance = {name: {"before": previous[name], "after": new[name]} for name in VERSION_PROVENANCE if previous[name] != new[name]}
    for name in PRESERVED_IDENTITY:
        if previous[name] != new[name]:
            provenance[name] = {"before": previous[name], "after": new[name]}
    return {"patch_version": PATCH_VERSION, "changed_fields": [name for name in PATCHABLE_FIELDS if name in fields], "fields": fields,
            "provenance": provenance}
