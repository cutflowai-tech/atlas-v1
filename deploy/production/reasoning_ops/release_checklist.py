"""The Reasoning V3 release-verification checklist and a validator for a filled-in release verification record (Phase 20-B).

    python deploy/production/reasoning_ops/release_checklist.py template            > release-verification.json
    python deploy/production/reasoning_ops/release_checklist.py validate release-verification.json

**PM final decision (B-first integration).** Three items depend on Phase 20-A, which is merged after this branch. They are **not**
passable here: whatever status or evidence a record carries, they are reported as ``PENDING_PHASE20A_RECONCILIATION`` and a record is
never ``complete`` while they are pending. **Repository eligibility is separate from actual release readiness:** actual release readiness
= repository eligibility + live Phase 19 evaluation evidence + human management review + explicit approvals. This tool can establish none
of the last three, so it always reports ``actual_release_ready: false`` and ``rollout_authorized: false`` (fail-closed); the live
evaluation and the human review are a separate, explicitly authorized pre-rollout gate.

======================================  ===============================  =====================================================================
item                                    acceptance key                   mandatory automatic gate on the reconciled Phase 20-A head (real code,
                                                                         real Phase 20-B artifacts, no mocks or opaque evidence; each blocking)
======================================  ===============================  =====================================================================
``release_metadata_complete``           P20A_RELEASE_METADATA_COMPLETE   Phase 20-A release metadata is complete for the release commit
``phase19_release_thresholds``          P20A_REPOSITORY_ELIGIBILITY_     Phase 20-A's real repository eligibility contract holds (Phase 19
                                        CONTRACT                         offline release PASS of this software, complete metadata, valid
                                                                         rollout); and fail-closed: missing live-provider evaluation and/or
                                                                         human-review evidence => actual release ready FALSE
``phase20a_rollout_configuration_valid`` P20A_ROLLOUT_STAGE_MATCH        the six Phase 20-A stages match Phase 20-B's configuration exactly
======================================  ===============================  =====================================================================

This validator imports no Phase 20-A code and assumes nothing about its outputs. Phase 20-A outputs (``release_metadata``,
``release_eligibility``, ``rollout``) may be attached as **opaque review evidence only**: they are scanned for credentials and never
counted as a pass.

It checks what Phase 20-B owns — the deployment identities (CI run, image digests) and the operational items (backup, restore drill,
outage tests, credential scan, rollback review) — and derives no release metadata itself. ``b_independent_complete`` reports those.
``validate`` exits 0 only when the whole record is complete (impossible before reconciliation), 3 when every Phase 20-B item is complete
and only the Phase 20-A items are pending, 1 when a Phase 20-B item is incomplete, 2 when the record cannot be read. **A complete record never
authorizes deployment** (``authorizes_deployment`` is always ``false``): it is input to the separately gated live-rollout approval.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RECORD_SCHEMA = "reasoning-release-verification-v1"


@dataclass(frozen=True)
class Item:
    item_id: str
    requirement: str
    evidence: str


CHECKLIST: tuple[Item, ...] = (
    Item("reviewed_integration_sha", "The release is an independently reviewed integration SHA", "the SHA and the review record"),
    Item("exact_head_ci", "Atlas CI `verify` succeeded on exactly that SHA", "the CI run ID and conclusion"),
    Item("full_tests", "`ATLAS_REASONING_REQUIRE_DB_TESTS=1 make test` passed (only Docker tests may skip)", "exit code and test count"),
    Item("migrations_healthy", "`db-health` ok with no pending/changed migration on the target database; replay applies nothing",
         "db-health JSON (ok, pending=[], problems=[])"),
    Item("phase19_closure", "Phase 19 closure is PASS", "the closure record"),
    Item("phase19_release_thresholds", "Repository eligibility contract: Phase 19 offline release PASS of this software accepted by Phase 20-A "
         "`release-eligibility` (no live evaluation required; actual release readiness is separate)", "report_sha256 and the eligibility output"),
    Item("phase20a_rollout_configuration_valid", "`rollout` validates the target configuration and reports the target stage",
         "the `rollout` output"),
    Item("release_metadata_complete", "Phase 20-A `release-metadata` is complete for the release commit", "the `release-metadata` output"),
    Item("backup_target_approved", "A pre-enable backup target (encrypted, access-controlled) is approved", "approval reference"),
    Item("isolated_restore_drill", "The isolated restore drill passed on this SHA", "restore_drill JSON (ok=true)"),
    Item("provider_outage_test", "The offline provider-outage scenario passed", "test name and result"),
    Item("honcho_outage_test", "The offline Honcho-outage scenario passed", "test name and result"),
    Item("deterministic_atlas_regression", "Deterministic Atlas tests passed and its outputs are unchanged with Reasoning V3 off", "test results"),
    Item("credential_scan", "The credential scan passed on the diff, deployment artifacts and captured outputs", "secret_scan result (pass/fail only)"),
    Item("rollback_plan_reviewed", "The rollback plan for the target stage was reviewed", "reviewer and date"),
)
ITEM_IDS = tuple(item.item_id for item in CHECKLIST)

# Deployment identities (not part of Phase 20-A's release metadata). Values are identifiers only.
DEPLOYMENT_FIELDS: Mapping[str, str] = {
    "ci_run_id": r"^[0-9]{1,20}$",
    "app_image": r"^[^\s@]+@sha256:[0-9a-f]{64}$",
    "web_image": r"^[^\s@]+@sha256:[0-9a-f]{64}$",
    "reasoning_image": r"^[^\s@]+@sha256:[0-9a-f]{64}$",
}
_SECRET_LIKE = re.compile(r"(?i)(://[^/\s]*:[^@/\s]*@|sk-or-|bearer\s|-----BEGIN|password=|api[_-]?key=)")
A_DEPENDENT_ACCEPTANCE = "PENDING_PHASE20A_RECONCILIATION"
# Items that depend on Phase 20-A: never passable before reconciliation (PM decision), and their acceptance keys.
A_DEPENDENT_ITEMS: Mapping[str, str] = {"release_metadata_complete": "P20A_RELEASE_METADATA_COMPLETE",
                                        "phase19_release_thresholds": "P20A_REPOSITORY_ELIGIBILITY_CONTRACT",
                                        "phase20a_rollout_configuration_valid": "P20A_ROLLOUT_STAGE_MATCH"}
# Fail-closed: this tool never establishes live evaluation evidence, human review or approvals, so never release readiness or rollout.
NOT_RELEASE_READY: Mapping[str, Any] = {"actual_release_ready": False, "rollout_authorized": False,
                                        "release_readiness_requires": ["repository eligibility (Phase 20-A, reconciled)",
                                                                       "live-provider Phase 19 evaluation evidence (separately authorized)",
                                                                       "human management review evidence", "explicit stage approval"]}
# Phase 20-A outputs an operator may attach: opaque review evidence only (credential-scanned, never a pass).
OPAQUE_A_OUTPUTS = ("release_metadata", "release_eligibility", "rollout")


def _strings(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, Mapping):
        for key, inner in value.items():
            yield from _strings(inner, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            yield from _strings(inner, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def template() -> dict[str, Any]:
    return {"schema": RECORD_SCHEMA, "target_stage": "", "authorizes_deployment": False,
            "a_dependent_acceptance": A_DEPENDENT_ACCEPTANCE, "release_metadata": {}, "release_eligibility": {}, "rollout": {},
            "deployment": {name: "" for name in DEPLOYMENT_FIELDS},
            "checks": {item.item_id: {"status": A_DEPENDENT_ACCEPTANCE if item.item_id in A_DEPENDENT_ITEMS else "pending", "evidence": "",
                                      "requirement": item.requirement, "expected_evidence": item.evidence} for item in CHECKLIST}}


def _section(record: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = record.get(name)
    return value if isinstance(value, Mapping) else {}


def validate(record: Any) -> dict[str, Any]:
    """Phase 20-B items: complete when the deployment identities are well formed and every Phase 20-B item passed with evidence
    (``b_independent_complete``). The three Phase 20-A items are always ``PENDING`` here, so ``complete`` is false until the reconciled
    gates replace them. Problems name fields and items only — never a value."""
    pending = {key: "PENDING" for key in A_DEPENDENT_ITEMS.values()}
    if not isinstance(record, Mapping) or record.get("schema") != RECORD_SCHEMA:
        return {"complete": False, "b_independent_complete": False, "a_dependent_acceptance": A_DEPENDENT_ACCEPTANCE, "pending": pending,
                **NOT_RELEASE_READY, "authorizes_deployment": False, "problems": [f"the record must be a {RECORD_SCHEMA} object"], "missing_metadata": [],
                "incomplete_items": [item for item in ITEM_IDS if item not in A_DEPENDENT_ITEMS]}
    problems: list[str] = [f"{path} looks like it carries a credential (value not shown)" for path, text in _strings(record)
                           if _SECRET_LIKE.search(text)]
    if record.get("authorizes_deployment") not in (False, None):
        problems.append("authorizes_deployment must be false: this checklist never authorizes deployment")
    if not str(record.get("target_stage") or ""):
        problems.append("target_stage is required (one REV/20 stage)")
    for section in OPAQUE_A_OUTPUTS:
        if section in record and not isinstance(record[section], Mapping):
            problems.append(f"{section} must be a JSON object (opaque Phase 20-A review evidence)")

    missing_metadata: list[str] = []
    deployment = _section(record, "deployment")
    for name, pattern in DEPLOYMENT_FIELDS.items():
        value = deployment.get(name)
        if not isinstance(value, str) or not value.strip():
            missing_metadata.append(f"deployment.{name}")
        elif not re.match(pattern, value):
            problems.append(f"deployment.{name} is not well formed")

    checks = _section(record, "checks")
    incomplete = []
    for item_id in ITEM_IDS:
        if item_id in A_DEPENDENT_ITEMS:
            continue                                           # never passable before reconciliation, whatever the record says
        entry = checks.get(item_id)
        if not isinstance(entry, Mapping) or entry.get("status") != "pass" or not str(entry.get("evidence") or "").strip():
            incomplete.append(item_id)
    problems.extend(f"checks.{name}: unknown item" for name in sorted(set(checks) - set(ITEM_IDS)))
    b_complete = not problems and not missing_metadata and not incomplete
    return {"complete": False, "b_independent_complete": b_complete, "a_dependent_acceptance": A_DEPENDENT_ACCEPTANCE, "pending": pending,
            **NOT_RELEASE_READY, "authorizes_deployment": False, "problems": problems, "missing_metadata": missing_metadata, "incomplete_items": incomplete}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="release_checklist", description="Reasoning V3 release verification (never authorizes deployment)")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("template")
    check = sub.add_parser("validate")
    check.add_argument("record", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.action == "template":
        print(json.dumps(template(), indent=1, sort_keys=True))
        return 0
    try:
        record = json.loads(args.record.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(json.dumps({"complete": False, "authorizes_deployment": False, "problems": [f"cannot read the record: {type(error).__name__}"]}))
        return 2
    result = validate(record)
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0 if result["complete"] else 3 if result["b_independent_complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
