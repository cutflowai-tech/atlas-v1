# Atlas Reasoning V3 — Phase 02: Define Reasoning Contracts and Schemas

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
Define exact, versioned machine contracts for ReasoningCase, ReasoningResult, and ReasoningUpdate before provider or persistence work begins.

## Scope
Contracts only. Every later phase depends on these contracts.

## Required implementation
1. Create `ReasoningCase` with stable identity, subject, topic, scope, source snapshot, upstream contract version, evidence references, previous result reference, evidence fingerprint, material delta, manager context, and memory context.
2. Create `ReasoningResult` with title, observation, reasoning summary, supporting evidence, counter-evidence, interpretation, alternative explanations, confidence, limitations, management significance, management questions, suggested investigations, lifecycle status, model metadata, prompt version, and timestamps.
3. Create `ReasoningUpdate` as a patch contract. It MUST describe changed fields, preserved fields, and change rationale.
4. `case_id` MUST be immutable.
5. Every visible conclusion MUST reference deterministic evidence.
6. Create strict enums for lifecycle status, confidence, action type, subject type, note source, and question state.
7. Reject unknown or structurally invalid fields where practical.
8. Add semantic validation for cross-field invariants.
9. Version the contract, initially as `reasoning-v1`.

## Required deliverables
Three JSON schemas, typed Python models, semantic validators, valid/invalid examples, and contract documentation.

## Required tests
- Schema round-trip tests.
- Invalid payload rejection tests.
- `case_id` mutation rejection.
- Result without evidence rejection.
- Update patch targeting immutable fields rejection.
- Enum validation.

## Acceptance criteria
A builder can construct, validate, store, and later render the three objects without reading any prompt implementation.

## Explicit non-goals
No LLM calls. No persistence. No memory. No UI.

## Stop condition
Stop when all three contracts are explicit, versioned, documented, and test-covered.
