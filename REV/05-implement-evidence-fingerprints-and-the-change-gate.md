# Atlas Reasoning V3 — Phase 05: Implement Evidence Fingerprints and the Change Gate

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
Determine whether each case is unchanged, updated, new, or disappeared before spending any LLM call.

## Scope
Deterministic evidence comparison and work-item creation.

## Required implementation
1. Compute `evidence_fingerprint` from canonicalized deterministic evidence and material values.
2. Sort unordered inputs before hashing.
3. Exclude generated prose, operational timestamps, request IDs, and previous LLM wording.
4. Compute `material_delta` listing added evidence, removed evidence, changed metric values, changed upstream confidence, added contradictions, and removed contradictions.
5. Implement gate actions: `unchanged`, `new`, `updated`, `disappeared`.
6. `unchanged` MUST create zero LLM work.
7. `new` creates a new-case reasoning work item.
8. `updated` creates an update work item carrying the exact delta.
9. `disappeared` MUST NOT immediately delete or resolve the existing result.
10. Persist the gate decision and its reason for every case in every run.

## Required deliverables
Fingerprint module, delta module, Change Gate service, persisted gate decisions, and debug inspection output.

## Required tests
Reordering stability, unchanged zero-call behavior, material metric change, contradiction change, new case, disappeared case, and irrelevant metadata change.

## Acceptance criteria
Running the same source snapshot twice produces no reasoning work on the second run.

## Explicit non-goals
No provider call. No lifecycle policy. No memory.

## Stop condition
Stop when all gate decisions are reproducible and unchanged cases generate zero LLM work.
