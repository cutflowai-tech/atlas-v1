# Reasoning V3 — release verification checklist (Phase 20-B, prepared)

**This checklist does not authorize deployment.** A complete record is input to the separately gated live-rollout approval for one
named stage ([`REASONING-V3-PRODUCTION-ROLLOUT.md`](REASONING-V3-PRODUCTION-ROLLOUT.md) §5).

The machine-readable form is `deploy/production/reasoning_ops/release_checklist.py`:

```sh
PYTHONPATH=src:deploy/production python3 deploy/production/reasoning_ops/release_checklist.py template > release-verification.json
PYTHONPATH=src:deploy/production python3 deploy/production/reasoning_ops/release_checklist.py validate release-verification.json
```

`validate` reports field and item names only, never values. `authorizes_deployment` is always `false`.

| Exit | Meaning |
|---|---|
| 0 | The whole record is complete. This is impossible before Phase 20-A reconciliation |
| 3 | Every Phase 20-B item is complete (`b_independent_complete: true`). Only the Phase 20-A items are pending |
| 1 | A Phase 20-B item is incomplete |
| 2 | The record cannot be read |

## 1. Acceptance contract (PM final decision: Phase 20-B merges first, then Phase 20-A)

```text
B_INDEPENDENT_ACCEPTANCE              = PASS only after every Phase 20-B gate passes (docs/evidence/REASONING-V3-PHASE-20B.md)
A_DEPENDENT_ACCEPTANCE                = PENDING_PHASE20A_RECONCILIATION
P20A_RELEASE_METADATA_COMPLETE        = PENDING
P20A_REPOSITORY_ELIGIBILITY_CONTRACT  = PENDING
P20A_ROLLOUT_STAGE_MATCH              = PENDING
P20_ACTUAL_RELEASE_READY              = FALSE   (always, from this tool; fail-closed)
P20_ROLLOUT_AUTHORIZED                = FALSE
```

**Repository eligibility is separate from actual release readiness.** Actual release readiness requires four things:
- repository eligibility;
- live-provider Phase 19 evaluation evidence;
- human management review evidence;
- explicit approvals.

No live evaluation is required for the repository-preparation merge. The live evaluation and the human review are a separate,
explicitly authorized pre-rollout gate. The validator always reports `actual_release_ready: false` and `rollout_authorized: false`.

The three Phase 20-A-dependent items are **not PASS when Phase 20-B merges**. The validator reports them as
`PENDING_PHASE20A_RECONCILIATION` whatever status or evidence a record carries, so no record is `complete` before reconciliation. It
imports no Phase 20-A code. Phase 20-A outputs an operator attaches (`release_metadata`, `release_eligibility`, `rollout`) are **opaque
review evidence only**: they are scanned for credentials and never counted as a pass.

| Item | Acceptance key | Mandatory automatic gate on the reconciled Phase 20-A head (each blocking) |
|---|---|---|
| `release_metadata_complete` | `P20A_RELEASE_METADATA_COMPLETE` | Phase 20-A's real `release-metadata` is complete for the release commit |
| `phase19_release_thresholds` | `P20A_REPOSITORY_ELIGIBILITY_CONTRACT` | Phase 20-A's real repository eligibility contract holds: a Phase 19 release PASS of this software, complete metadata, a valid rollout. **It is fail-closed:** with live-provider evaluation and/or human-review evidence missing, actual release readiness is FALSE. This covers the PR #45 review's M-1: an offline PASS alone can never make a release ready |
| `phase20a_rollout_configuration_valid` | `P20A_ROLLOUT_STAGE_MATCH` | The six Phase 20-A stages (`rollout.STAGES`) match Phase 20-B's configuration exactly: every stage's variables pass through `compose.reasoning.yaml`, and `reasoning.env.example` is stage 0 |

Reconciliation order:
1. Phase 20-B merges first and records `POST_PHASE20B_INTEGRATION_SHA`.
2. Phase 20-A merges that SHA into `reasoning-v3/phase20-rollout-controls` by **merge commit**, with no rebase and no force-push.
3. On the reconciled head, Phase 20-A wires the three gates as automatic tests. They use real Phase 20-A code and real Phase 20-B artifacts, with no mocks and no opaque evidence. Phase 20-B reviews them.
4. The full combined local gate passes, then exact-head CI.
5. Phase 20-B performs the final delta review. Only then may Phase 20-A merge.

Scope during reconciliation:
- **Ownership.** Phase 20-B fixes deployment, runbook, backup/restore and ops-test issues. Phase 20-A fixes rollout state, metadata and eligibility.
- **Wrong-scope contracts.** A contract in the wrong scope is fixed by its owner, never worked around, and reconciliation reruns.
- **What the final merge authorizes.** After the repository-preparation merge, the report is exactly:
  `POST_PHASE20_PREP_INTEGRATION_SHA=<merge SHA>`, `PHASE20_REPOSITORY_PREP=PASS`, `P20_ACTUAL_RELEASE_READY=FALSE`,
  `P20_ROLLOUT_AUTHORIZED=FALSE`, `PHASE20_COMPLETE=FALSE`. Repository-preparation PASS does not authorize Stage 1 or any rollout. It
  authorizes no deployment, live evaluation, provider call, network spend, credential, permission or security-setting change.

The commands that produce these outputs are Phase 20-A interfaces (PR #45), planned on this branch:
- `python -m atlas_reasoning release-metadata --commit SHA`
- `python -m atlas_reasoning release-eligibility --evaluation RUN.json --commit SHA`
- `python -m atlas_reasoning rollout`

## 2. What Phase 20-B adds

Deployment identities, which are not part of Phase 20-A's metadata:

| Field | Format |
|---|---|
| `ci_run_id` | digits |
| `app_image`, `web_image`, `reasoning_image` | `<repo>@sha256:<64 hex>` |

The items (Phase 20-B owns all but the three pending ones):

| Item | Requirement | Evidence |
|---|---|---|
| `reviewed_integration_sha` | The release is an independently reviewed integration SHA | SHA and review record |
| `exact_head_ci` | Atlas CI `verify` succeeded on exactly that SHA | CI run ID and conclusion |
| `full_tests` | `ATLAS_REASONING_REQUIRE_DB_TESTS=1 make test` passed; only the Docker image tests may skip | Exit code and count |
| `migrations_healthy` | `db-health` ok on the target database (no pending or changed migration); replay applies nothing | `db-health` JSON |
| `phase19_closure` | Phase 19 closure is PASS | Closure record |
| `phase19_release_thresholds` | **PENDING_PHASE20A_RECONCILIATION** (§1, `P20A_REPOSITORY_ELIGIBILITY_CONTRACT`) | Automatic gate on the reconciled head |
| `phase20a_rollout_configuration_valid` | **PENDING_PHASE20A_RECONCILIATION** (§1, `P20A_ROLLOUT_STAGE_MATCH`) | Automatic gate on the reconciled head |
| `release_metadata_complete` | **PENDING_PHASE20A_RECONCILIATION** (§1, `P20A_RELEASE_METADATA_COMPLETE`) | Automatic gate on the reconciled head |
| `backup_target_approved` | The pre-enable backup target is approved (encrypted, access-controlled) | Approval reference |
| `isolated_restore_drill` | `restore_drill.py drill` passed on this SHA (`REASONING-V3-RECOVERY.md` §2.2) | Drill JSON, `ok: true` |
| `provider_outage_test` | `test_reasoning_ops_recovery.ProviderOutageTests` passed | Test result |
| `honcho_outage_test` | `test_reasoning_ops_recovery.HonchoOutageTests` passed | Test result |
| `deterministic_atlas_regression` | Deterministic Atlas suites passed, and outputs are unchanged with Reasoning V3 off | Test results |
| `credential_scan` | `secret_scan.py` passed on the diff, deployment artifacts and captured outputs | `pass` / `fail` only |
| `rollback_plan_reviewed` | The rollback plan for the target stage (`REASONING-V3-RECOVERY.md` §3) was reviewed | Reviewer and date |

Release eligibility evaluates the **pinned** model only. A model override (`REASONING-V3-RECOVERY.md` §3) is an incident measure,
never a releasable configuration.

## 3. Credential scan

```sh
PYTHONPATH=src python3 deploy/production/reasoning_ops/secret_scan.py                       # the tracked deployment and docs surface
PYTHONPATH=src python3 deploy/production/reasoning_ops/secret_scan.py captured-output/      # generated artifacts and captured logs
```

The scan reports `path:line pattern-name` only. Placeholders (`REPLACE_WITH_…`, `*_FILE` paths, `***`) are allowed.
