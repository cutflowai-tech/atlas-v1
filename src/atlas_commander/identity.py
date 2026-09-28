"""Resolve evidenced Monday Editor values using a pinned mapping snapshot.

Callers must extract Editor-field evidence for the evaluated event/cycle, never
substitute a current assignee. No mapping version is selected implicitly.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class EditorEvidence:
    """Historical Monday Editor-field value and the event that supports it."""

    monday_board_id: str
    monday_item_id: str
    column_id: str
    event_id: str
    monday_person_ids: tuple[str, ...]
    source: str = "monday"


class IdentityResolutionError(ValueError):
    """Quarantined resolution; exception_output is suitable for an exception sink."""

    def __init__(self, code: str, mapping_version: str, evidence: EditorEvidence, candidates: Iterable[str] = ()) -> None:
        super().__init__(code)
        self.code = code
        self.exception_output = {
            "code": code,
            "mapping_version": mapping_version,
            "evidence": asdict(evidence),
            "candidate_editor_ids": sorted(set(candidates)),
        }


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def resolve_editor(
    evidence: EditorEvidence,
    mappings: Iterable[Mapping[str, Any]],
    mapping_version: str,
) -> dict[str, str]:
    """Return EditorIdentity or raise IdentityResolutionError for quarantine.

    Mapping rows use editor-identity.schema.json. Rows are indexed strictly by
    (mapping_version, monday_person_id); duplicate identical rows are harmless,
    while conflicting rows are ambiguous. Names are output metadata only.
    """
    def reject(code: str, candidates: Iterable[str] = ()) -> None:
        raise IdentityResolutionError(code, mapping_version, evidence, candidates)

    if not _nonempty(mapping_version):
        reject("MISSING_MAPPING_VERSION")
    if evidence.source != "monday" or not all(_nonempty(value) for value in (
        evidence.monday_board_id, evidence.monday_item_id, evidence.column_id, evidence.event_id,
    )):
        reject("MISSING_EDITOR_EVIDENCE")
    if not isinstance(evidence.monday_person_ids, tuple) or any(not _nonempty(value) for value in evidence.monday_person_ids):
        reject("INVALID_EDITOR")
    person_ids = set(evidence.monday_person_ids)
    if not person_ids:
        reject("MISSING_EDITOR")
    if len(person_ids) != 1:
        reject("AMBIGUOUS_EDITOR")
    person_id = next(iter(person_ids))
    fields = {"contract_version", "editor_id", "monday_person_id", "display_name", "mapping_version", "resolution"}
    index: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in mappings:
        # Other snapshots and people cannot supply or invalidate this identity.
        if row.get("mapping_version") != mapping_version or row.get("monday_person_id") != person_id:
            continue
        if (set(row) != fields or any(not _nonempty(row.get(key)) for key in fields)
                or row.get("contract_version") != "1.0.0" or row.get("resolution") != "canonical_monday_id"):
            reject("INVALID_IDENTITY_MAPPING")
        identity = {key: row[key] for key in sorted(fields)}
        index.setdefault((mapping_version, person_id), []).append(identity)
    matches = index.get((mapping_version, person_id), [])
    if not matches:
        reject("UNMAPPED_EDITOR")
    first = matches[0]
    if any(row != first for row in matches[1:]):
        reject("AMBIGUOUS_EDITOR", (row["editor_id"] for row in matches))
    return dict(first)
