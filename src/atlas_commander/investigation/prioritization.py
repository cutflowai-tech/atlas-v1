"""Importance, severity, duplicate suppression and management sections (Tasks 40-42, 50).

**Importance** (Task 40) is kept separate from confidence. A high-impact finding can have moderate evidence, and the reader sees
both. It is a *lexicographic* ordering, with no weighted sum, so ``importance.basis`` shows exactly why one finding precedes
another:

1. tier:
   1. time-sensitive or fairness-critical: an open-work risk signal, adverse needs-attention change, or a finding that contradicts
      a published headline;
   2. adverse system pattern;
   3. adverse Editor-specific pattern;
   4. other hidden context, and historical-similarity base rates (hypotheses about open work, not facts about it);
   5. favourable finding (improvement, strength);
   6. neutral system description;
   7. data warning;
2. evidence level: strong, then moderate, then weak;
3. worsening (the adverse side grew) before not known;
4. affected projects (more first);
5. affected Editors (more first);
6. magnitude in the finding's own unit (larger first);
7. recency: current window or snapshot before whole history;
8. persistence: persistent before not known before not persistent;
9. ``finding_id`` (a deterministic tie-break).

**Severity** is a display grouping derived from tier and direction (``high`` / ``medium`` / ``low`` / ``info``). It is never
a score.

**Duplicates** (Task 41). Two findings with the same direction and the same Video Types, whose affected projects overlap at
least ``prioritization.duplicate_overlap`` (Jaccard), form a cluster. Every member stays in ``findings`` for audit, and
sections list only the highest-ranked member. When the parameter is not approved, nothing is clustered, so nothing is hidden.

**Sections** (Tasks 42, 50). A run can have zero findings: every section may be empty.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from atlas_commander.investigation.confidence import LEVELS
from atlas_commander.investigation.models import (
    ADVERSE,
    DATA_WARNING,
    EDITOR_SPECIFIC_PATTERN,
    EMERGING_RISK,
    FAVOURABLE,
    HIDDEN_CONTEXT,
    IMPORTANT_IMPROVEMENT,
    NEEDS_ATTENTION,
    NEUTRAL,
    SYSTEM_PATTERN,
    Finding,
)
from atlas_commander.investigation.policy import IntelligencePolicy

TIERS = ("time_sensitive_or_fairness", "adverse_system_pattern", "adverse_editor_pattern", "hidden_context", "favourable", "neutral_description", "data_warning")
SEVERITY = {0: "high", 1: "medium", 2: "medium", 3: "low", 4: "info", 5: "info", 6: "low"}
METHOD = ("lexicographic: tier, evidence level, worsening, affected projects, affected Editors, magnitude, recency, persistence, finding_id; "
          "no weighted sum")


def tier(finding: Finding) -> int:
    if finding.category == DATA_WARNING:
        return 6
    if finding.finding_type == "risk.historical_similarity":
        return 3                                   # a historical base rate (hypothesis), not a fact about the open work
    if finding.category == EMERGING_RISK or (finding.category == NEEDS_ATTENTION and finding.direction == ADVERSE) or finding.headline_contradiction:
        return 0
    if finding.direction == ADVERSE and finding.category == SYSTEM_PATTERN:
        return 1
    if finding.direction == ADVERSE and finding.category == EDITOR_SPECIFIC_PATTERN:
        return 2
    if finding.category == HIDDEN_CONTEXT:
        return 3
    if finding.direction == FAVOURABLE:
        return 4
    return 5


def _recency(finding: Finding) -> int:
    window = finding.time_window or {}
    return 1 if window.get("window") in ("current", "snapshot") else 0


def _key(finding: Finding) -> tuple[Any, ...]:
    level = LEVELS.index((finding.confidence or {}).get("level", "weak"))
    persistent = {True: 2, None: 1, False: 0}[finding.persistent]
    return (tier(finding), -level, 0 if finding.worsening else 1, -len(finding.affected_projects), -len(finding.affected_editors),
            -(finding.magnitude or 0.0), -_recency(finding), -persistent, finding.finding_id)


def rank(findings: Sequence[Finding]) -> list[Finding]:
    ordered = sorted(findings, key=_key)
    for position, finding in enumerate(ordered, start=1):
        t = tier(finding)
        finding.severity = SEVERITY[t] if finding.direction != FAVOURABLE else "info"
        finding.importance = {
            "rank": position, "tier": TIERS[t],
            "basis": {"tier": TIERS[t], "evidence": (finding.confidence or {}).get("level"), "worsening": finding.worsening,
                      "affected_projects": len(finding.affected_projects), "affected_editors": len(finding.affected_editors),
                      "magnitude": round(finding.magnitude, 4) if finding.magnitude is not None else None, "recent": bool(_recency(finding)),
                      "persistent": finding.persistent, "headline_contradiction": finding.headline_contradiction},
            "method": METHOD,
        }
    return ordered


def cluster(findings: Sequence[Finding], policy: IntelligencePolicy) -> None:
    """Mark duplicate clusters in rank order (``findings`` must already be ranked)."""
    overlap = policy.use("prioritization.duplicate_overlap")
    if overlap is None:
        return
    threshold = float(overlap.value)
    primaries: list[Finding] = []
    for finding in findings:
        projects = set(finding.affected_projects)
        match = None
        for primary in primaries:
            other = set(primary.affected_projects)
            union = projects | other
            if (primary.direction == finding.direction and primary.affected_video_types == finding.affected_video_types and union
                    and len(projects & other) / len(union) >= threshold):
                match = primary
                break
        if match is None:
            primaries.append(finding)
            continue
        cluster_id = match.cluster["cluster_id"] if match.cluster else f"cluster:{match.finding_id}"
        match.cluster = {"cluster_id": cluster_id, "primary": match.finding_id,
                         "members": sorted({*(match.cluster or {}).get("members", [match.finding_id]), finding.finding_id}),
                         "rule": f"same direction, same Video Types, affected-project Jaccard >= {threshold}", "parameter_status": overlap.status}
        finding.cluster = {"cluster_id": cluster_id, "primary": match.finding_id, "suppressed_in_sections": True, "parameter_status": overlap.status}


def primary(finding: Finding) -> bool:
    return not (finding.cluster or {}).get("suppressed_in_sections")


def sections(findings: Sequence[Finding], policy: IntelligencePolicy, examined: Sequence[dict[str, Any]]) -> dict[str, Any]:
    shown = [finding for finding in findings if primary(finding)]
    limit = policy.use("prioritization.top_findings")
    top = shown[: int(limit.value)] if limit is not None else list(shown)

    def ids(rows: Sequence[Finding]) -> list[str]:
        return [finding.finding_id for finding in rows]

    insufficient: dict[str, dict[str, int]] = {}
    for row in examined:
        for reason in row["reasons"]:
            insufficient.setdefault(row["detector"], {}).setdefault(reason, 0)
            insufficient[row["detector"]][reason] += 1
    investigations = []
    for finding in top:
        for statement in finding.investigations:
            investigations.append({"finding_id": finding.finding_id, **statement.to_dict()})
    return {
        "top_findings": {"finding_ids": ids(top), "limit": limit.to_dict() if limit else None,
                         "note": None if limit else "prioritization.top_findings is not approved: every ranked finding is listed"},
        "needs_attention": ids([f for f in shown if f.category == NEEDS_ATTENTION]),
        "important_improvements": ids([f for f in shown if f.category == IMPORTANT_IMPROVEMENT]),
        "system_patterns": ids([f for f in shown if f.category == SYSTEM_PATTERN]),
        "editor_specific_patterns": ids([f for f in shown if f.category == EDITOR_SPECIFIC_PATTERN]),
        "hidden_context": ids([f for f in shown if f.category == HIDDEN_CONTEXT]),
        "emerging_risk_signals": ids([f for f in shown if f.category == EMERGING_RISK]),
        "data_warnings": ids([f for f in shown if f.category == DATA_WARNING]),
        "suggested_investigations": investigations,
        "insufficient_evidence": [{"detector": detector, "reasons": dict(sorted(reasons.items()))} for detector, reasons in sorted(insufficient.items())],
        "neutral_descriptions": ids([f for f in shown if f.direction == NEUTRAL and f.category not in (DATA_WARNING,)]),
    }
