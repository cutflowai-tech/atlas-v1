# Atlas Reasoning V3 — Phase 20: Production Rollout and Controlled Migration

## Document purpose
This file is an implementation specification for the code builder. Treat every MUST/MUST NOT statement as binding. Do not infer additional product behavior that is not written here.

## Global architectural rules
- The existing deterministic Atlas pipeline remains the source of truth.
- Monday data, cycle reconstruction, metrics, Interpretation 1.5, Intelligence V2, confidence, and evidence remain upstream and must not be weakened.
- LLM output MUST NOT become the source of truth for metrics, source events, actor attribution, sample sizes, deadlines, or evidence identity.
- PostgreSQL is the canonical store for Reasoning V3 application state.
- Honcho is contextual memory, not the canonical database.
- The UI may display LLM reasoning summaries, but MUST NOT expose raw hidden chain-of-thought.
- All new outputs MUST remain traceable to upstream deterministic evidence.
- Existing behavior MUST remain unchanged when Reasoning V3 is disabled.

## Objective
Deploy Reasoning V3 progressively with feature flags, rollback, monitoring, and preservation of the existing deterministic Atlas path.

## Scope
Shadow mode through full management rollout.

## Required implementation
1. Stage rollout:
   - Stage 1: shadow reasoning, invisible to users;
   - Stage 2: internal review page;
   - Stage 3: management beta;
   - Stage 4: reasoning-first cards become primary;
   - Stage 5: notes, Q&A, and Teach Atlas enabled;
   - Stage 6: executive synthesis becomes the primary home view.
2. Keep major V3 capabilities independently feature-flagged.
3. Apply database migrations before enabling writes.
4. Verify OpenRouter and Honcho configuration without exposing credentials.
5. Verify degraded-mode behavior.
6. Back up canonical reasoning state before major migration/enablement.
7. Confirm deterministic Atlas outputs remain unchanged.
8. Update runbooks for reasoning execution, partial-run recovery, disabling LLM, disabling Honcho, rollback, database restore, and prompt/model rollback.
9. Monitor cost, failures, validation rejection, and result churn.
10. Do not remove legacy Intelligence V2 technical views until management explicitly approves.
11. Record model version, prompt versions, contract versions, and migration version with each release.

## Required deliverables
Rollout plan, runbook updates, feature flags, backup/restore process, monitoring checklist, rollback procedure, and release verification checklist.

## Required tests
Shadow-mode no-UI-change verification, feature-flag rollback, database restore drill, provider outage, Honcho outage, deterministic-core regression, and release metadata completeness.

## Acceptance criteria
Reasoning V3 can be enabled gradually and reversed safely without losing historical state or breaking deterministic Atlas.

## Explicit non-goals
No additional features. No removal of evidence layers. No autonomous business actions.

## Stop condition
Stop only after staged production verification, rollback validation, and monitoring are complete.
