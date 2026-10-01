"""The evidence fingerprint of a case (``REV/05`` #1–#3).

Case identity (``case_identity``) says *which issue*; the evidence fingerprint says *what the deterministic evidence about it is
right now*. A case keeps its ``case_id`` while its fingerprint changes with its evidence.

``canonical_evidence(case)`` derives, **from a ReasoningCase document alone**, the canonical form the fingerprint hashes:

- included: the case orientation and, per contributing finding (keyed by member key): type, direction, category, evidence level,
  upstream confidence level, sample size, limitation codes, every statement's parameters, every evidence block's sample,
  comparison and exclusions, and every evidence record (Monday item, cycle, Editor, Video Type, event IDs, source timestamps and
  the values used);
- excluded: generated prose, Intelligence V2 ``finding_id`` and rank (window- and run-dependent), the analysis-window dates, the
  snapshot and release IDs, ``created_at`` and other operational timestamps, request IDs, display names (``VOLATILE_KEYS``),
  previous LLM wording, manager and memory context;
- normalized: mappings by key, unordered lists (event IDs, timestamps, limitations, exclusions) sorted, repeated statement or block
  names numbered in content order, floats rounded to 6 decimals, ``-0.0`` as ``0.0``; serialized as compact, key-sorted JSON.

``evidence_fingerprint = "ef1_" + sha256(canonical JSON)``. Because it is computed from the case document, anyone holding a case can
verify it (``contracts.CASE_CHECKS``: ``FINGERPRINT_MISMATCH``). The same snapshot, or the same evidence in any input order, always
gives the same fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from typing import Any

FINGERPRINT_VERSION = "evidence-fingerprint-v1"
FINGERPRINT_PREFIX = "ef1_"
# Parameter and value keys that are operational metadata or display text, never evidence: removed at any depth before hashing.
VOLATILE_KEYS = frozenset({"retrieved_at", "generated_at", "as_of", "calculated_at", "calculation_time", "start_date", "end_date_exclusive",
                           "editor_name", "display_name", "group_label"})


class EvidenceError(ValueError):
    pass


def canonical_value(value: Any) -> Any:
    """Deterministic, metadata-free copy of a deterministic value."""
    if isinstance(value, Mapping):
        return {str(key): canonical_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0])) if str(key) not in VOLATILE_KEYS}
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise EvidenceError("evidence values must be finite numbers")
        rounded = round(value, 6)
        return 0.0 if rounded == 0 else rounded
    return value


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _keyed(rows: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    """Rows keyed by name; repeated names get ``#2``, ``#3`` in canonical-content order (so input order never matters)."""
    grouped: dict[str, list[Any]] = {}
    for key, value in rows:
        grouped.setdefault(key, []).append(value)
    keyed: dict[str, Any] = {}
    for key, values in grouped.items():
        for index, value in enumerate(sorted(values, key=_dumps), start=1):
            keyed[key if index == 1 else f"{key}#{index}"] = value
    return keyed


def canonical_evidence(case: Mapping[str, Any]) -> dict[str, Any]:
    """The canonical deterministic evidence of a case document: exactly what the fingerprint hashes."""
    findings: dict[str, dict[str, Any]] = {}
    for ref in [*case["supporting_findings"], *case["contradicting_findings"]]:
        findings[ref["member_key"]] = {"finding_type": ref["finding_type"], "direction": ref["direction"], "category": ref["category"],
                                       "evidence_level": ref["evidence_level"], "confidence": ref["confidence"], "sample_size": ref["sample_size"],
                                       "limitations": sorted(set(ref["limitations"])), "statements": [], "blocks": [], "records": {}}
    evidence = case["current_evidence"]
    for statement in evidence["statements"]:
        findings[statement["member_key"]]["statements"].append((f"{statement['level']}:{statement['code']}", canonical_value(statement["params"])))
    for block in evidence["blocks"]:
        exclusions = sorted((canonical_value(row) for row in block["exclusions"]), key=_dumps)
        findings[block["member_key"]]["blocks"].append((f"{block['role']}:{block['evidence_code']}", {"sample": canonical_value(block["sample"]),
                                                       "comparison": canonical_value(block["comparison"]), "exclusions": exclusions}))
    for ref in evidence["references"]:
        findings[ref["member_key"]]["records"][ref["ref_id"]] = {
            "role": ref["role"], "evidence_code": ref["evidence_code"], "monday_item_id": ref["monday_item_id"], "cycle_id": ref["cycle_id"],
            "editor_id": ref["editor_id"], "video_type_key": ref["video_type_key"], "event_ids": sorted(ref["event_ids"]),
            "source_timestamps": sorted(ref["source_timestamps"]), "values": canonical_value(ref["values"])}
    for row in findings.values():
        row["statements"] = _keyed(row["statements"])
        row["blocks"] = _keyed(row["blocks"])
    return {"fingerprint_version": FINGERPRINT_VERSION, "orientation": case["orientation"], "findings": findings}


def evidence_fingerprint(canonical: Mapping[str, Any]) -> str:
    return FINGERPRINT_PREFIX + hashlib.sha256(_dumps(canonical).encode()).hexdigest()


def fingerprint_errors(case: Mapping[str, Any]) -> list[str]:
    """Contract check (``contracts.CASE_CHECKS``): the fingerprint is the hash of the case's own canonical evidence."""
    try:
        expected = evidence_fingerprint(canonical_evidence(case))
    except (KeyError, EvidenceError) as error:
        return [f"FINGERPRINT_MISMATCH: canonical evidence cannot be built: {error}"]
    if case["evidence_fingerprint"] != expected:
        return [f"FINGERPRINT_MISMATCH: evidence_fingerprint should be {expected}"]
    return []
