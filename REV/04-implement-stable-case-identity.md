# Atlas Reasoning V3 — Phase 04: Implement Stable Case Identity

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
Ensure the same management issue maps to the same case across runs even when its evidence changes.

## Scope
Deterministic case identity only. The LLM MUST NOT create or alter case identity.

## Required implementation
1. Implement a deterministic `case_id` builder.
2. Build identity from stable semantic dimensions: subject type, stable subject ID, topic key, and only the optional dimensions explicitly required by that case type.
3. Possible optional identity dimensions include canonical Video Type, workflow stage, or detector family when they are part of the topic itself.
4. Exclude rates, counts, timestamps, confidence, generated wording, current evidence values, and request IDs.
5. Normalize identity components before hashing/encoding.
6. Define collision handling and validation.
7. Map one or more Intelligence V2 findings into one stable case when they represent the same management issue.
8. Define when a new topic MUST create a new case instead of updating an existing one.
9. Persist the identity dimensions for debugging.

## Required deliverables
`case_identity.py`, identity rules documentation, fixtures for same-case versus new-case behavior, and persisted identity dimensions.

## Required tests
Ordering independence, evidence-change stability, distinct editor separation, distinct topic separation, historical replay stability, and collision tests.

## Acceptance criteria
Changing evidence does not change `case_id`; changing the actual management topic does.

## Explicit non-goals
No evidence fingerprinting. No LLM. No lifecycle.

## Stop condition
Stop when identity is deterministic and stable across historical fixture replay.
