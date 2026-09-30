"""Build the ``intelligence-v2`` document from one Monday reconstruction.

``build_intelligence`` is deterministic: the same reconstruction, contract, configuration, mode and ``generated_at`` give
byte-identical JSON. It reads the engine's results and never writes back into a profile, the dashboard or any contract
document. It refuses contracts without the ``editor_intelligence`` capability, because it relies on Cairo windows,
leave-one-out comparison and the label taxonomy.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from atlas_commander.capabilities import capabilities
from atlas_commander.contracts import schema_errors
from atlas_commander.intelligence import completed_day_windows
from atlas_commander.interpretation_policy import InterpretationPolicy
from atlas_commander.investigation import INTELLIGENCE_V2_VERSION, graph, narrative, prioritization
from atlas_commander.investigation.baselines import Baselines, baselines_document
from atlas_commander.investigation.catalog import DETECTORS
from atlas_commander.investigation.confidence import WEAK
from atlas_commander.investigation.context import RunContext, run_guarded
from atlas_commander.investigation.editor import fairness_context
from atlas_commander.investigation.facts import build_facts
from atlas_commander.investigation.models import DATA_WARNING, FACT, Finding, Scope, finding_errors, not_evaluated, plain
from atlas_commander.investigation.policy import APPROVED_ONLY, WEAK_NOT_PUBLISHED, IntelligencePolicy
from atlas_commander.investigation.workload import workload_model
from atlas_commander.pipeline import CycleReconstruction, reconstruct_quality
from atlas_commander.profile import build_editor_profile, profiled_editors

DOCUMENT_VERSION = "2.0.0"
SCHEMA = "intelligence-v2.schema.json"


class IntelligenceError(ValueError):
    pass


def build_intelligence(result: CycleReconstruction, contract: Mapping[str, Any], generated_at: str, *, mode: str = APPROVED_ONLY,
                       profiles: Mapping[str, Mapping[str, Any]] | None = None, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not capabilities(contract).editor_intelligence:
        raise IntelligenceError(f"Intelligence V2 needs a contract with editor_intelligence (1.5.0+), not {contract.get('contract_version')}")
    policy = IntelligencePolicy.load(contract, mode, config)
    interpretation = InterpretationPolicy.from_contract(contract)
    windows = completed_day_windows(generated_at, interpretation.window_days, interpretation.comparison_days)
    quality = reconstruct_quality(result, contract, generated_at)
    facts = build_facts(result, contract, quality, windows, generated_at)
    if profiles is None:
        profiles = {row["editor_id"]: build_editor_profile(result, contract, row["editor_id"], generated_at) for row in profiled_editors(result)}
    baselines = Baselines(facts, policy.value("speed.minimum_comparator_projects"), policy.value("speed.minimum_comparator_editors"))
    ctx = RunContext(facts, baselines, policy, dict(profiles), generated_at)

    findings: list[Finding] = []
    examined: list[dict[str, Any]] = []
    runs = []
    for detector in DETECTORS:
        outcome = run_guarded(detector, ctx)
        for finding in outcome.findings:
            errors = finding_errors(finding)
            if errors:
                raise IntelligenceError(f"{detector.detector_id} produced an invalid finding: {errors}")
        findings.extend(outcome.findings)
        examined.extend(outcome.not_evaluated)
        runs.append({**detector.catalog_entry(), "analyses_run": outcome.analyses_run, "findings": len(outcome.findings),
                     "examined_without_finding": len(outcome.not_evaluated),
                     "rule_not_approved": any("rule_not_approved" in row["reasons"] for row in outcome.not_evaluated)})
    findings, withheld = publication_filter(findings, policy)
    examined.extend(withheld)
    ranked = prioritization.rank(findings)
    prioritization.cluster(ranked, policy)
    relations = graph.build(ranked)
    for finding in ranked:
        finding.text = narrative.finding_text(finding)
    sections = prioritization.sections(ranked, policy, examined)
    by_id = {finding.finding_id: finding for finding in ranked}
    document = {
        "document_version": DOCUMENT_VERSION,
        "intelligence_version": INTELLIGENCE_V2_VERSION,
        "generated_at": generated_at,
        "mode": policy.mode,
        "publishable": policy.publishable,
        "executable_contract_version": contract["contract_version"],
        "source": {"system": "monday", "monday_board_id": facts.board_id, "retrieved_at": facts.retrieved_at,
                   "run_id": result.ingestion.get("run_id"), "activity_log_window": result.ingestion.get("activity_log_window")},
        "windows": windows.to_dict(),
        "video_types": {project.cohort_key: " + ".join(project.cohort_labels) for project in facts.projects if project.cohort_key and project.cohort_labels},
        "parameters": policy.to_dict(),
        "coverage": facts.coverage,
        "baselines": baselines_document(facts, baselines),
        "workload_model": workload_model(ctx),
        "findings": [finding.to_dict() for finding in ranked],
        "examined_without_finding": sorted(examined, key=lambda row: (row["detector"], str(row["scope"]), row["reasons"])),
        "sections": sections,
        "executive_brief": narrative.executive_brief([by_id[i] for i in sections["top_findings"]["finding_ids"]], ctx),
        "investigation_graph": relations,
        "editors": [_editor_block(ctx, editor, ranked) for editor in facts.editors()],
        "detectors": runs,
        "language_rules": narrative.LANGUAGE_RULES,
        "note": ("Deterministic investigation layer. Findings are never inputs to any metric, component state, Overall Status or Trend. "
                 + ("Parameters marked proposed_not_approved were used for management review only; this document must not be published."
                    if not policy.publishable else "Only approved parameters were used.")),
    }
    document = plain(document)
    errors = schema_errors(document, SCHEMA) + consistency_errors(document)
    if errors:
        raise IntelligenceError(f"intelligence-v2 document violates {SCHEMA}: {errors[:10]}")
    return document


def publishable_finding(finding: Finding) -> bool:
    """D53.11: a publishable document shows strong and moderate findings; a weak one only when it is a direct fact or a data warning."""
    return (finding.confidence or {}).get("level") != WEAK or finding.evidence_level == FACT or finding.category == DATA_WARNING


def publication_filter(findings: list[Finding], policy: IntelligencePolicy) -> tuple[list[Finding], list[dict[str, Any]]]:
    """In a publishable run, weak findings leave the document's findings and are listed under examined_without_finding with
    their facts (never silently dropped). Review mode keeps every finding."""
    if not policy.publishable:
        return findings, []
    kept, withheld = [], []
    for finding in findings:
        if publishable_finding(finding):
            kept.append(finding)
            continue
        scope = finding.scope if isinstance(finding.scope, Scope) else Scope("team")
        withheld.append(not_evaluated(finding.finding_type, scope, [WEAK_NOT_PUBLISHED],
                                      {"finding_id": finding.finding_id, "confidence": (finding.confidence or {}).get("level"),
                                       "confidence_why": (finding.confidence or {}).get("why"), "sample_size": finding.sample_size,
                                       "category": finding.category, "direction": finding.direction}))
    return kept, withheld


def _editor_block(ctx: RunContext, editor: str, findings: list[Finding]) -> dict[str, Any]:
    mine = [finding for finding in findings if editor in finding.affected_editors and finding.scope.kind in ("editor", "project")]
    return {"editor_id": editor, "display_name": ctx.name(editor),
            "finding_ids": [finding.finding_id for finding in mine],
            "strengths": [f.finding_id for f in mine if f.direction == "favourable"],
            "attention": [f.finding_id for f in mine if f.direction == "adverse"],
            "context": [f.finding_id for f in mine if f.direction in ("mixed", "neutral")],
            "fairness_context": fairness_context(ctx, editor)}


def consistency_errors(document: Mapping[str, Any]) -> list[str]:
    """Checks the schema cannot express: sections and relations name existing findings; samples match their records."""
    problems: list[str] = []
    ids = {finding["finding_id"] for finding in document["findings"]}
    if len(ids) != len(document["findings"]):
        problems.append("duplicate finding_id")
    for name, value in document["sections"].items():
        listed = value["finding_ids"] if isinstance(value, Mapping) and "finding_ids" in value else value if isinstance(value, list) and value and isinstance(value[0], str) else []
        problems += [f"section {name} names unknown finding {item}" for item in listed if item not in ids]
    for edge in document["investigation_graph"]["edges"]:
        if edge["from"] not in ids or edge["to"] not in ids:
            problems.append(f"graph edge {edge} names an unknown finding")
    for finding in document["findings"]:
        records = {(record["monday_item_id"], record["cycle_id"]) for block in finding["supporting_evidence"] for record in block["records"]}
        if finding["sample_size"] != len(records):
            problems.append(f"{finding['finding_id']}: sample_size {finding['sample_size']} != {len(records)} supporting records")
        if document["publishable"] and finding["parameter_status"] != "approved":
            problems.append(f"{finding['finding_id']}: a publishable document contains a finding built on unapproved parameters")
    return problems
