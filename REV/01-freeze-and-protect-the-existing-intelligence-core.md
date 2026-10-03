# Atlas Reasoning V3 — Phase 01: Freeze and Protect the Existing Intelligence Core

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
Create a hard boundary around the existing deterministic Atlas intelligence pipeline before adding any LLM behavior.

## Scope
This phase is defensive only. It adds protection, documentation, feature gating, and regression tests. It does not add OpenRouter, Honcho, PostgreSQL reasoning state, or new management UI.

## Required implementation
1. Identify the exact outputs produced by cycle reconstruction, metrics, Interpretation 1.5, Intelligence V2, and evidence serialization.
2. Create a single internal boundary named `reasoning_input_boundary` or an equivalently explicit module.
3. Define a typed immutable payload that Reasoning V3 will be allowed to consume.
4. Mark which fields are source facts, deterministic derived values, and evidence references.
5. Add a Reasoning V3 feature flag. The default MUST be OFF.
6. When the feature flag is OFF, site build behavior MUST remain equivalent to the current production path.
7. Add regression protection proving Reasoning V3 code cannot mutate existing editor profiles, component states, Overall Status, Trend, Recent Change, or Intelligence V2 output.
8. Persist or expose the upstream contract version and source snapshot ID that future reasoning runs will need.
9. Document the new boundary in architecture documentation.

## Required deliverables
- Reasoning input boundary module.
- Typed immutable upstream payload.
- Feature flag with default OFF.
- Architecture documentation.
- Golden/regression tests protecting current outputs.

## Required tests
- Existing full test suite passes.
- V3 disabled build matches current expected artifacts.
- Attempted mutation of the reasoning input fails or cannot affect upstream objects.
- Historical supported contracts still build.
- Intelligence V2 output remains identical before and after importing the new boundary.

## Acceptance criteria
- No user-visible production change with V3 disabled.
- There is exactly one approved input path from deterministic Atlas into Reasoning V3.
- Existing intelligence behavior is protected by tests.

## Explicit non-goals
No LLM calls. No memory provider. No new database. No dashboard redesign.

## Stop condition
Stop when the boundary and regression protection are complete and green.
