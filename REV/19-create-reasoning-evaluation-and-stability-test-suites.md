# Atlas Reasoning V3 — Phase 19: Create Reasoning Evaluation and Stability Test Suites

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
Demonstrate that Reasoning V3 is grounded, stable, update-oriented, and resistant to unnecessary churn.

## Scope
Automated evaluation harness, fixtures, repeated-run measurements, and human review gates.

## Required implementation
1. Build golden cases for unchanged, updated, new, disappeared, contradiction added/removed, insufficient evidence, manager note, manager answer, teaching added/expired, memory unavailable, and provider failure.
2. Define expected structural outcomes rather than hidden chain-of-thought.
3. Measure case identity stability, unnecessary new-card rate, unnecessary field rewrite rate, grounding failures, validation rejection rate, lifecycle stability, and duplicate-question rate.
4. Add deterministic unit tests for all non-LLM layers.
5. Add fake-provider integration tests.
6. Add an optional live-model evaluation command that is not required in normal CI unless explicitly configured.
7. Define release thresholds.
8. Create a human management-review checklist for reasoning quality.

## Required deliverables
Evaluation fixtures, stability suite, fake-provider integration suite, optional live runner, report output, human checklist, and release thresholds.

## Required tests
The evaluation suite itself must be reproducible and produce machine-readable results.

## Acceptance criteria
Same evidence preserves cards, material changes update cards, irrelevant changes do not trigger rewrites, and grounding thresholds are met.

## Explicit non-goals
No production deployment. No threshold changes solely to force a pass.

## Stop condition
Stop when release thresholds are met and stability/grounding reports are acceptable.
