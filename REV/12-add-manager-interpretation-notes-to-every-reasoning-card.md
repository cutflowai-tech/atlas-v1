# Atlas Reasoning V3 — Phase 12: Add Manager Interpretation Notes to Every Reasoning Card

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
Allow management to attach interpretations to each result without converting those interpretations into facts.

## Scope
Result-card notes, persistence, audit history, and Honcho sync.

## Required implementation
1. Add a manager-note service/API.
2. Store note ID, result ID, case ID, author identity when available, body, source type=`manager_interpretation`, and timestamps.
3. Support create and update with audit history.
4. Add a text box to every reasoning card.
5. Persist to PostgreSQL first.
6. Sync to the result-scoped Honcho context after local persistence.
7. Honcho failure MUST NOT lose the note.
8. Future reasoning may consume the note only as attributed management context.
9. Label manager interpretation separately from Atlas reasoning and deterministic evidence.
10. Escape/sanitize rendered user text.

## Required deliverables
Note backend, card text box, persistence, audit trail, Honcho sync, and source labeling.

## Required tests
Create/edit persistence, restart persistence, Honcho failure, correct-result isolation, HTML escaping, and evidence-source separation.

## Acceptance criteria
Every reasoning card has a durable, clearly attributed manager interpretation field.

## Explicit non-goals
No questions. No Teach Atlas. No automatic promotion of note to rule.

## Stop condition
Stop when notes are safely persisted, displayed, and available as future context.
