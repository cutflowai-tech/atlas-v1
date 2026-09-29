"""Person vs system (Tasks 31-33): is a late-delivery gap specific to one Editor once the work they were given is accounted for?

**Mix-adjusted comparison (Task 31).** For each of the Editor's deadline-classifiable projects, the *expected* late probability
is the other Editors' late rate in the same exact Video Type (leave-one-out, D36, over the whole ingested history; a Video Type
counts only when the others have at least ``evidence.minimum_group_projects`` classifiable projects in it). Then:

- ``observed`` = the Editor's late projects;
- ``expected`` = the sum of those per-project probabilities;
- ``excess`` = (observed - expected) / projects.

This is indirect standardisation: it answers "would the other Editors have been late this often on the same mix of Video
Types?"

**Same conditions (Task 33).** The same calculation again, stratified by Video Type x runway band (short / adequate, under
``runway.short_rule``). This asks whether the gap survives when projects are compared under similar available runway.

Outcomes:

- **editor-specific pattern**: |excess| >= ``evidence.material_rate_difference``, adverse or favourable;
- **mix explains the headline** (hidden context): the raw gap to the other Editors is material but the mix-adjusted excess
  is not. The raw number reflects the work mix more than the Editor.

The Editor sample must meet the approved Deadline minimum (``deadline.minimum_editor_projects``, D52).
"""

from __future__ import annotations

from collections.abc import Callable
from fractions import Fraction
from typing import Any

from atlas_commander.investigation import common as cm
from atlas_commander.investigation.confidence import assess
from atlas_commander.investigation.context import Detector, DetectorResult, RunContext, uses
from atlas_commander.investigation.facts import ProjectFact
from atlas_commander.investigation.models import (
    ADVERSE,
    EDITOR_SPECIFIC_PATTERN,
    FAVOURABLE,
    HIDDEN_CONTEXT,
    HYPOTHESIS,
    INTERPRETATION,
    METRIC,
    PATTERN,
    Finding,
    Scope,
    Statement,
)
from atlas_commander.investigation.policy import INSUFFICIENT_COMPARISON_GROUP, INSUFFICIENT_SAMPLE, NO_EFFECT
from atlas_commander.investigation.stats import exact, shown

VERSION = "person-system-v1.0"


def expected_late(ctx: RunContext, editor: str, stratum: Callable[[ProjectFact], Any], minimum_peers: int) -> dict[str, Any]:
    """Indirect standardisation of one Editor's late rate against the other Editors in the same strata."""
    classifiable = [p for p in ctx.facts.attributed if p.deadline_classifiable]
    mine = [p for p in classifiable if p.editor_id == editor]
    peers = [p for p in classifiable if p.editor_id != editor]
    peer_rates: dict[Any, tuple[int, int]] = {}
    for project in peers:
        key = stratum(project)
        if key is None:
            continue
        late, total = peer_rates.get(key, (0, 0))
        peer_rates[key] = (late + bool(project.late), total + 1)
    covered, uncovered, expected = [], [], Fraction(0)
    per_project = {}
    for project in mine:
        key = stratum(project)
        late, total = peer_rates.get(key, (0, 0)) if key is not None else (0, 0)
        if total >= minimum_peers:
            covered.append(project)
            probability = Fraction(late, total)
            expected += probability
            per_project[project.monday_item_id] = probability
        else:
            uncovered.append(project)
    observed = sum(bool(p.late) for p in covered)
    peer_total = [p for p in peers]
    return {"covered": covered, "uncovered": uncovered, "observed": observed, "expected": expected, "per_project": per_project,
            "strata": {str(key): {"late": late, "projects": total} for key, (late, total) in sorted(peer_rates.items(), key=lambda pair: str(pair[0])) if total >= minimum_peers},
            "raw_editor_rate": Fraction(sum(bool(p.late) for p in mine), len(mine)) if mine else None,
            "raw_peer_rate": Fraction(sum(bool(p.late) for p in peer_total), len(peer_total)) if peer_total else None, "editor_projects": len(mine)}


def run(ctx: RunContext) -> DetectorResult:
    values, used = uses(ctx, "deadline.minimum_editor_projects", "evidence.minimum_group_projects", "evidence.material_rate_difference")
    result = DetectorResult()
    minimum_editor, minimum_peers = values["deadline.minimum_editor_projects"], values["evidence.minimum_group_projects"]
    material = exact(values["evidence.material_rate_difference"])
    runway_rule = ctx.policy.use("runway.short_rule")
    for editor in ctx.facts.editors():
        scope = Scope("editor", editor_id=editor)
        adjusted = expected_late(ctx, editor, lambda p: p.cohort_key, minimum_peers)
        n = len(adjusted["covered"])
        facts = {"editor_projects": adjusted["editor_projects"], "covered_projects": n, "observed_late": adjusted["observed"],
                 "expected_late": shown(adjusted["expected"], 2)}
        if n < minimum_editor:
            result.skip("person.mix_adjusted_deadline", scope, [INSUFFICIENT_SAMPLE if adjusted["editor_projects"] < minimum_editor else INSUFFICIENT_COMPARISON_GROUP],
                        facts, ("deadline.minimum_editor_projects", "evidence.minimum_group_projects"))
            continue
        excess = Fraction(adjusted["observed"], n) - adjusted["expected"] / n
        raw_gap = (adjusted["raw_editor_rate"] - adjusted["raw_peer_rate"]) if adjusted["raw_editor_rate"] is not None and adjusted["raw_peer_rate"] is not None else None
        same = None
        if runway_rule is not None:
            same_conditions = expected_late(ctx, editor, lambda p: (p.cohort_key, cm.short_runway(p, ctx.baselines)) if cm.short_runway(p, ctx.baselines) is not None else None,
                                            minimum_peers)
            if len(same_conditions["covered"]) >= minimum_editor:
                m = len(same_conditions["covered"])
                same = {"covered_projects": m, "observed_late": same_conditions["observed"], "expected_late": shown(same_conditions["expected"], 2),
                        "excess": shown(Fraction(same_conditions["observed"], m) - same_conditions["expected"] / m)}
        params = {**facts, "editor_id": editor, "editor_name": ctx.name(editor), "observed_rate": shown(Fraction(adjusted["observed"], n)),
                  "expected_rate": shown(adjusted["expected"] / n), "excess": shown(excess), "raw_editor_rate": shown(adjusted["raw_editor_rate"]),
                  "raw_peer_rate": shown(adjusted["raw_peer_rate"]), "raw_gap": shown(raw_gap), "same_conditions": same,
                  "video_types": sorted({p.cohort_key for p in adjusted["covered"] if p.cohort_key})}
        records = [p.record("deadline_result", "cohort_key", "runway_seconds", extra={"expected_late_probability": shown(adjusted["per_project"][p.monday_item_id])})
                   for p in adjusted["covered"]]
        evidence = ctx.evidence("supporting", "mix_adjusted_late_rate",
                                ("expected late probability of each project = other Editors' late rate in the same exact Video Type (leave-one-out, whole history); "
                                 "excess = (observed late - sum of expected) / projects; compared exactly with evidence.material_rate_difference"),
                                {"editor_projects": n, "peer_strata": len(adjusted["strata"])}, records, columns=("status", "requested_eta", "video_type", "editor"),
                                comparison={"observed": adjusted["observed"], "expected": shown(adjusted["expected"], 2), "peer_strata": adjusted["strata"],
                                            "same_conditions": same}, time_window=ctx.history_window,
                                exclusions=[{"monday_item_id": p.monday_item_id, "reason": "no_comparable_peer_sample_in_video_type"} for p in adjusted["uncovered"]])
        limitations = [cm.VIDEO_TYPE_ONLY, cm.ATTRIBUTED_ONLY, cm.NO_CAUSE_EVIDENCE, cm.INGEST_WINDOW]
        if abs(excess) >= material:
            adverse = excess > 0
            statements = [Statement(METRIC, "mix_adjusted_late_rate", params), Statement(PATTERN, "editor_differs_from_peers_on_same_mix", params)]
            if same is not None:
                statements.append(Statement(METRIC, "same_conditions_late_rate", params))
            statements += [Statement(INTERPRETATION, "difference_persists_after_mix" if adverse else "better_than_peers_after_mix", params),
                           Statement(HYPOTHESIS, "editor_specific_factor_possible" if adverse else "working_practice_worth_understanding", params)]
            finding = Finding("person.mix_adjusted_deadline", VERSION, EDITOR_SPECIFIC_PATTERN, ADVERSE if adverse else FAVOURABLE, scope, statements, [evidence],
                              used, ctx.history_window, limitations, Statement(INTERPRETATION, "significance_editor_specific", params),
                              [Statement(HYPOTHESIS, "review_editor_specific_deadline" if adverse else "recognise_evidence", params)],
                              key={"test": "mix_adjusted"}, magnitude=float(abs(excess)))
            replication = []
            if same is not None:
                replication.append({"slice": "same_runway_conditions", "holds": (Fraction(str(same["excess"])) > 0) == adverse and abs(Fraction(str(same["excess"]))) >= material})
            finding.confidence = assess(ctx.policy, groups={"editor": (n, minimum_editor)}, replication=replication, projects=n, editors=1)
            result.add(finding)
        elif raw_gap is not None and abs(raw_gap) >= material:
            # The raw gap is material but the mix-adjusted one is not. Only when the mix accounts for more than half of the raw gap
            # is it said to *largely* reflect the work mix; otherwise the finding only states that the adjusted gap fell just below
            # the material difference, so a small adjustment is never presented as an explanation.
            explained = (abs(raw_gap) - abs(excess)) / abs(raw_gap)
            largely = explained > Fraction(1, 2)
            params["share_of_gap_explained_by_mix"] = shown(explained)
            statements = [Statement(METRIC, "raw_late_rate_gap", params), Statement(METRIC, "mix_adjusted_late_rate", params),
                          Statement(INTERPRETATION, "raw_gap_largely_reflects_work_mix" if largely else "adjusted_gap_just_below_material", params),
                          Statement(HYPOTHESIS, "check_assignment_mix" if largely else "gap_remains_worth_review", params)]
            finding = Finding("person.mix_adjusted_deadline", VERSION, HIDDEN_CONTEXT, (FAVOURABLE if raw_gap > 0 else ADVERSE) if largely else ADVERSE if raw_gap > 0 else FAVOURABLE,
                              scope, statements, [evidence], used, ctx.history_window, limitations,
                              Statement(INTERPRETATION, "significance_mix_explains" if largely else "significance_adjusted_gap_below_material", params),
                              [Statement(HYPOTHESIS, "review_assignment_mix" if largely else "review_editor_specific_deadline", params)],
                              key={"test": "mix_explains_raw_gap" if largely else "adjusted_gap_below_material"},
                              magnitude=float(abs(raw_gap)), headline_contradiction=largely and raw_gap > 0)
            finding.confidence = assess(ctx.policy, groups={"editor": (n, minimum_editor)}, projects=n, editors=1)
            result.add(finding)
        else:
            result.skip("person.mix_adjusted_deadline", scope, [NO_EFFECT], {**facts, "excess": shown(excess), "raw_gap": shown(raw_gap)},
                        ("evidence.material_rate_difference",))
    return result


def shared_breadth(ctx: RunContext, key: str, outcome: Callable[[ProjectFact], bool | None], minimum_per_editor: int) -> list[dict[str, Any]]:
    """For each Editor with enough projects inside and outside Video Type ``key``: their outcome rate inside vs outside it."""
    rows = []
    for editor in ctx.facts.editors():
        mine = [p for p in ctx.facts.attributed if p.editor_id == editor and outcome(p) is not None]
        inside = [p for p in mine if p.cohort_key == key]
        outside = [p for p in mine if p.cohort_key != key]
        if len(inside) >= minimum_per_editor and len(outside) >= minimum_per_editor:
            rate_in = Fraction(sum(bool(outcome(p)) for p in inside), len(inside))
            rate_out = Fraction(sum(bool(outcome(p)) for p in outside), len(outside))
            rows.append({"editor_id": editor, "inside": len(inside), "outside": len(outside), "rate_inside": rate_in, "rate_outside": rate_out,
                         "elevated": rate_in > rate_out, "projects": inside})
    return rows


DETECTORS = [
    Detector("person.mix_adjusted_deadline", VERSION, "31, 33", "Whether an Editor's late rate differs from what the other Editors show on the same mix of "
             "Video Types (and under similar runway), or whether the raw gap is explained by the mix",
             ("editor_identity", "video_type", "deadline_result", "execution_runway"),
             ("deadline.minimum_editor_projects", "evidence.minimum_group_projects", "evidence.material_rate_difference"),
             "Editor projects covered by a comparable peer Video Type >= deadline.minimum_editor_projects (D52); peers per Video Type >= evidence.minimum_group_projects",
             "editor-specific pattern (adverse or favourable) or hidden context (raw gap explained by mix), with every project's expected probability",
             "Editor sample vs the approved minimum; replication = the excess survives the same-runway stratification",
             (cm.VIDEO_TYPE_ONLY, cm.NO_CAUSE_EVIDENCE), run),
]
