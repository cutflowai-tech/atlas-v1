"""The finding relationship graph and investigation chains (Tasks 43, 44).

Edges come only from explicit, deterministic rules over structured fields. No text is compared. Two findings are linked only
when an explicit rule names their pair of finding types **and** they share at least one Monday project. The link is therefore
always about the same underlying work:

- ``context_for``: a system-level finding (team, stage or Video Type) gives context to an Editor-level finding. For example,
  short runway across the team gives context to one Editor's questioned late-rate headline. The allowed pairs are in
  ``CONTEXT_RULES``.
- ``explains_breadth``: a system-level pattern speaks to another system-level observation about the same Video Type. For
  example, lateness shared across Editors in Premium Short relates to a repeated delay combination in Premium Short.
- ``supports``: two findings about the same Editor and outcome family point the same way.
- ``contradicts``: two findings about the same Editor and outcome family point opposite ways. It also covers the whole-history
  speed reading of a questioned headline set against the current window's approved Slower verdict.
- ``qualifies``: a mixed hidden-context finding about an Editor (a conflict or a questioned headline) set against an adverse
  finding about the same Editor and outcome family.

A chain starts at a finding and repeatedly follows its highest-ranked unvisited neighbour on the same subject (the starting
Editor plus system-level context, or system-level findings only), up to five findings. For example:
questioned late-rate headline, then short runway across the team, then lateness shared across Editors in one Video Type.
Every edge names its rule, so a reader can check why two findings are linked.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from atlas_commander.investigation.models import ADVERSE, FAVOURABLE, MIXED, Finding

SYSTEM_SCOPES = frozenset({"team", "stage", "video_type"})
MAX_CHAIN = 5

# system finding type -> Editor-level finding types it can give context to (always also requiring shared projects).
CONTEXT_RULES: dict[str, frozenset[str]] = {
    "bottleneck.pre_editor_runway": frozenset({"contradiction.bad_headline", "person.mix_adjusted_deadline", "editor.label_pattern", "change.editor",
                                               "workload.overload_pattern", "pattern.shared_across_editors"}),
    "bottleneck.post_editor": frozenset({"editor.label_pattern", "contradiction.bad_headline"}),
    "pattern.shared_across_editors": frozenset({"contradiction.bad_headline", "person.mix_adjusted_deadline", "concentration.negative", "change.editor"}),
    "pattern.repeated_delay": frozenset({"contradiction.bad_headline", "person.mix_adjusted_deadline"}),
    "change.video_type": frozenset({"change.editor", "editor.speed_pattern"}),
    "change.team": frozenset({"change.editor"}),
    "workload.association": frozenset({"workload.overload_pattern", "change.editor"}),
    "pattern.repeated_quality": frozenset({"editor.label_pattern", "concentration.negative", "change.editor"}),
    "concentration.negative": frozenset({"concentration.negative", "contradiction.bad_headline"}),
    "concentration.positive": frozenset({"concentration.positive", "editor.label_pattern"}),
}
BREADTH_RULES: frozenset[tuple[str, str]] = frozenset({
    ("pattern.shared_across_editors", "pattern.repeated_delay"), ("pattern.shared_across_editors", "concentration.negative"),
    ("bottleneck.pre_editor_runway", "pattern.shared_across_editors"), ("bottleneck.pre_editor_runway", "pattern.repeated_delay"),
    ("change.video_type", "pattern.repeated_delay"), ("workload.association", "pattern.repeated_delay"),
})


def family(finding: Finding) -> str:
    """The outcome a finding is about: deadline, speed, quality, stage or data."""
    kind = finding.finding_type
    key = dict(finding.key)
    measure = str(key.get("measure") or key.get("outcome") or key.get("code") or key.get("label_class") or "")
    if kind.startswith("data."):
        return "data"
    if kind == "workflow.time_map":
        return "stage"
    if kind == "editor.speed_pattern" or "execution" in measure:
        return "speed"
    if kind == "editor.label_pattern":
        return "deadline" if any(s.code == "negative_signals_concentrated_in_deadline" for s in finding.statements) else "quality"
    if kind == "pattern.repeated_quality" or "label" in measure:
        return "quality"
    if kind == "contradiction.hidden_risk":
        return "quality"
    return "deadline"


def _shares_projects(a: Finding, b: Finding) -> bool:
    return bool(set(a.affected_projects) & set(b.affected_projects))


def _edge(a: Finding, b: Finding) -> str | None:
    """The rule linking a -> b, or None."""
    fa, fb = family(a), family(b)
    if "data" in (fa, fb) or not _shares_projects(a, b):
        return None
    system_a, system_b = a.scope.kind in SYSTEM_SCOPES, b.scope.kind in SYSTEM_SCOPES
    if system_a and b.scope.kind == "editor" and fa == fb and b.finding_type in CONTEXT_RULES.get(a.finding_type, frozenset()):
        return "context_for"
    if (system_a and system_b and (a.finding_type, b.finding_type) in BREADTH_RULES and set(a.affected_video_types) & set(b.affected_video_types)
            and (fa == fb or "speed" in (fa, fb) and "deadline" in (fa, fb) and a.finding_type.startswith(("change.video_type", "workload")))):
        return "explains_breadth"
    if a.scope.kind != "editor" or b.scope.kind != "editor" or a.scope.editor_id != b.scope.editor_id:
        return None
    if a.finding_type == "contradiction.bad_headline" and b.finding_type == "editor.speed_pattern" and b.direction == ADVERSE:
        return "contradicts"
    if fa != fb or a.finding_type == b.finding_type and a.key == b.key:
        return None
    if a.direction == MIXED and b.direction == ADVERSE:
        return "qualifies"
    if a.direction == b.direction and a.direction in (ADVERSE, FAVOURABLE) and a.finding_id < b.finding_id:
        return "supports"
    if {a.direction, b.direction} == {ADVERSE, FAVOURABLE} and a.finding_id < b.finding_id:
        return "contradicts"
    return None


def build(findings: Sequence[Finding]) -> dict[str, Any]:
    """Edges between findings (ranked order) and one chain per finding; also fills each finding's ``related``."""
    edges = []
    for a in findings:
        for b in findings:
            if a is not b and (rule := _edge(a, b)):
                edges.append({"from": a.finding_id, "to": b.finding_id, "relation": rule})
    rank = {finding.finding_id: position for position, finding in enumerate(findings)}
    neighbours: dict[str, list[tuple[int, str, str]]] = {finding.finding_id: [] for finding in findings}
    for edge in edges:
        neighbours[edge["from"]].append((rank[edge["to"]], edge["to"], edge["relation"]))
        neighbours[edge["to"]].append((rank[edge["from"]], edge["from"], edge["relation"]))
    for finding in findings:
        finding.related = [{"finding_id": other, "relation": relation} for _, other, relation in sorted(set(neighbours[finding.finding_id]))]
    by_id = {finding.finding_id: finding for finding in findings}

    def on_subject(start: Finding, other: str) -> bool:
        """A chain stays on one subject: the starting Editor plus system-level context, or system-level findings only."""
        candidate = by_id[other]
        if candidate.scope.kind in SYSTEM_SCOPES:
            return True
        return start.scope.kind == "editor" and candidate.scope.editor_id == start.scope.editor_id

    chains = []
    for finding in findings:
        path = [{"finding_id": finding.finding_id, "relation": None}]
        seen = {finding.finding_id}
        current = finding.finding_id
        while len(path) < MAX_CHAIN:
            step = next(((other, relation) for _, other, relation in sorted(neighbours[current]) if other not in seen and on_subject(finding, other)), None)
            if step is None:
                break
            path.append({"finding_id": step[0], "relation": step[1]})
            seen.add(step[0])
            current = step[0]
        if len(path) > 1:
            chains.append({"start": finding.finding_id, "path": path})
    return {"edges": sorted(edges, key=lambda e: (rank[e["from"]], rank[e["to"]], e["relation"])), "chains": chains,
            "rules": {"context_for": "a system-level finding and an Editor-level finding of an allowed type pair that share Monday projects",
                      "explains_breadth": "two system-level findings of an allowed type pair about the same Video Type that share Monday projects",
                      "supports": "same Editor, same outcome family, same direction, shared Monday projects",
                      "contradicts": "same Editor and outcome family in opposite directions (or whole-history speed vs the current Slower verdict), shared projects",
                      "qualifies": "a mixed hidden-context finding about an Editor set against an adverse finding about the same Editor and outcome, shared projects"}}
