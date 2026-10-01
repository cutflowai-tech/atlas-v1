# Atlas Reasoning V3 — Phase 09: Implement Reasoning Result Lifecycle

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
Prevent result cards from flickering, disappearing immediately, or being replaced unnecessarily.

## Scope
Deterministic lifecycle transitions around persisted results.

## Required implementation
1. Implement lifecycle states: `new`, `active`, `updated`, `cooling`, `resolved`, `superseded`.
2. Define an explicit transition table.
3. New validated results move from `new` to `active`.
4. Accepted updated versions may pass through `updated` then return to `active`.
5. A disappeared case moves to `cooling`, not directly to deletion.
6. Resolve cooling cases only after an explicit configured persistence rule.
7. Allow immediate resolution only for approved direct-fact case types whose observed condition is no longer true.
8. `superseded` requires a reference to the replacement case/result.
9. Persist transition reason and run ID.
10. The LLM MUST NOT have final authority over lifecycle transitions.

## Required deliverables
Lifecycle policy module, transition table, transition history, cooling config, and lifecycle debug output.

## Required tests
Invalid transition, cooling persistence, reappearance, resolution, superseded linkage, and direct-fact resolution.

## Acceptance criteria
Cards remain stable across temporary evidence fluctuations.

## Explicit non-goals
No memory. No executive layer.

## Stop condition
Stop when lifecycle behavior is deterministic and fully test-covered.
