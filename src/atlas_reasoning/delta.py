"""The material delta between two evidence states of one case (``REV/05`` #4).

``material_delta(before, after)`` compares two canonical evidence documents (``fingerprint.canonical_evidence``) and lists exactly
what changed — never just ``changed = true``:

| List | Content |
|---|---|
| ``added_findings`` / ``removed_findings`` | member keys of findings that joined or left the case |
| ``added_evidence`` / ``removed_evidence`` | supporting and context evidence records (Monday item, cycle, evidence kind, ``ref_id``) |
| ``changed_values`` | every other changed leaf: statement parameters (metric values), block samples and comparisons, record values, limitations, direction, category, evidence level, sample size — each with its path, before and after |
| ``changed_confidence`` | upstream confidence level changes per finding |
| ``added_contradictions`` / ``removed_contradictions`` | contradicting evidence records, and findings that started or stopped opposing the case orientation |
| ``orientation_change`` | the case orientation before and after, when it flipped |

Every difference between the two canonical documents appears in at least one list (a finding whose direction flips appears both
as a changed value and as a contradiction change), so a delta is empty exactly when the two fingerprints are equal
(``tests/test_reasoning_change_gate.py``). Lists are sorted, so the delta is deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from atlas_reasoning.fingerprint import evidence_fingerprint

DELTA_VERSION = "material-delta-v1"
_OPPOSITE = {"adverse": "favourable", "favourable": "adverse"}
_MISSING = object()


def _opposed(direction: str, orientation: str) -> bool:
    return _OPPOSITE.get(orientation) == direction


def _evidence_key(member_key: str, ref_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    return {"ref_id": ref_id, "member_key": member_key, "role": record["role"], "evidence_code": record["evidence_code"],
            "monday_item_id": record["monday_item_id"], "cycle_id": record["cycle_id"]}


def _same(before: Any, after: Any) -> bool:
    return type(before) is type(after) and before == after


def _leaves(path: str, before: Any, after: Any, member_key: str | None, out: list[dict[str, Any]]) -> None:
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        for key in sorted(set(before) | set(after)):
            _leaves(f"{path}/{key}" if path else str(key), before.get(key, _MISSING), after.get(key, _MISSING), member_key, out)
    elif before is _MISSING or after is _MISSING or not _same(before, after):
        out.append({"member_key": member_key, "path": path, "before": None if before is _MISSING else before,
                    "after": None if after is _MISSING else after})


def _records(member_key: str, finding: Mapping[str, Any], added: bool, delta: dict[str, list[dict[str, Any]]]) -> None:
    for ref_id, record in sorted(finding["records"].items()):
        if record["role"] == "contradicting":
            delta["added_contradictions" if added else "removed_contradictions"].append({"kind": "evidence", "member_key": member_key, "ref_id": ref_id})
        else:
            delta["added_evidence" if added else "removed_evidence"].append(_evidence_key(member_key, ref_id, record))


def material_delta(before: Mapping[str, Any], after: Mapping[str, Any], *, fingerprint_before: str | None = None,
                   fingerprint_after: str | None = None) -> dict[str, Any]:
    """The material delta from canonical evidence ``before`` to ``after`` (a ``material_delta`` contract object). Known
    fingerprints may be passed; they must be the fingerprints of the two documents."""
    delta: dict[str, list[dict[str, Any]]] = {name: [] for name in ("added_evidence", "removed_evidence", "changed_values", "changed_confidence",
                                                                    "added_contradictions", "removed_contradictions")}
    added_findings: list[str] = []
    removed_findings: list[str] = []
    old_orientation, new_orientation = before["orientation"], after["orientation"]
    old, new = before["findings"], after["findings"]
    for key in sorted(set(before) | set(after)):
        if key not in ("findings", "orientation"):
            _leaves(key, before.get(key, _MISSING), after.get(key, _MISSING), None, delta["changed_values"])
    for member in sorted(set(new) - set(old)):
        added_findings.append(member)
        if _opposed(new[member]["direction"], new_orientation):
            delta["added_contradictions"].append({"kind": "finding", "member_key": member, "ref_id": None})
        _records(member, new[member], True, delta)
    for member in sorted(set(old) - set(new)):
        removed_findings.append(member)
        if _opposed(old[member]["direction"], old_orientation):
            delta["removed_contradictions"].append({"kind": "finding", "member_key": member, "ref_id": None})
        _records(member, old[member], False, delta)
    for member in sorted(set(old) & set(new)):
        b, a = old[member], new[member]
        was, now = _opposed(b["direction"], old_orientation), _opposed(a["direction"], new_orientation)
        if now and not was:
            delta["added_contradictions"].append({"kind": "finding", "member_key": member, "ref_id": None})
        elif was and not now:
            delta["removed_contradictions"].append({"kind": "finding", "member_key": member, "ref_id": None})
        if b["confidence"] != a["confidence"]:
            delta["changed_confidence"].append({"member_key": member, "before": b["confidence"], "after": a["confidence"]})
        for ref_id in sorted(set(a["records"]) - set(b["records"])):
            _records(member, {"records": {ref_id: a["records"][ref_id]}}, True, delta)
        for ref_id in sorted(set(b["records"]) - set(a["records"])):
            _records(member, {"records": {ref_id: b["records"][ref_id]}}, False, delta)
        for ref_id in sorted(set(a["records"]) & set(b["records"])):
            _leaves(f"records/{ref_id}", b["records"][ref_id], a["records"][ref_id], member, delta["changed_values"])
        for key in sorted((set(a) | set(b)) - {"confidence", "records"}):
            _leaves(key, b.get(key, _MISSING), a.get(key, _MISSING), member, delta["changed_values"])
    return {
        "delta_version": DELTA_VERSION,
        "fingerprint_before": fingerprint_before or evidence_fingerprint(before),
        "fingerprint_after": fingerprint_after or evidence_fingerprint(after),
        "orientation_change": {"before": old_orientation, "after": new_orientation} if old_orientation != new_orientation else None,
        "added_findings": added_findings,
        "removed_findings": removed_findings,
        **delta,
    }


def is_empty(delta: Mapping[str, Any]) -> bool:
    return delta["orientation_change"] is None and not any(delta[name] for name in ("added_findings", "removed_findings", "added_evidence",
                                                                                     "removed_evidence", "changed_values", "changed_confidence",
                                                                                     "added_contradictions", "removed_contradictions"))


def summary(delta: Mapping[str, Any]) -> dict[str, Any]:
    """Counts per list, for gate reasons and debug output."""
    return {"orientation_changed": delta["orientation_change"] is not None,
            **{name: len(delta[name]) for name in ("added_findings", "removed_findings", "added_evidence", "removed_evidence", "changed_values",
                                                   "changed_confidence", "added_contradictions", "removed_contradictions")}}
