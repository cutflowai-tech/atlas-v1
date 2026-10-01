# Atlas Reasoning V3 — Phase 17: Build the Executive Intelligence Synthesis Layer

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
Create an executive home view generated only from validated canonical reasoning results.

## Scope
Higher-level synthesis after individual case reasoning is complete.

## Required implementation
1. Define `ExecutiveBrief` schema.
2. Input only canonical active/new/updated/resolved reasoning results, their confidence, significance, lifecycle, and open questions.
3. Create a versioned synthesis prompt.
4. Output sections: what changed, top concerns, important improvements, system patterns, editor-specific context, unresolved questions, uncertainty/not-enough-evidence, and what to inspect next.
5. Every statement MUST reference one or more canonical result IDs.
6. No new metric or factual claim may be invented.
7. Persist brief versions by run.
8. If nothing material changed, allow policy to preserve the prior brief without a new LLM call.
9. Validate every brief statement resolves to canonical results.
10. Render brief as home/overview with drill-down to result cards.

## Required deliverables
ExecutiveBrief schema, prompt, persistence, validator, and executive home view.

## Required tests
Missing result reference rejection, unchanged preserve behavior, resolved-result accuracy, card linking, and no raw detector references.

## Acceptance criteria
Executive summary is stable, traceable, and downstream of canonical reasoning only.

## Explicit non-goals
No direct raw Monday analysis. No autonomous actions.

## Stop condition
Stop when executive synthesis is fully reference-grounded and versioned.
