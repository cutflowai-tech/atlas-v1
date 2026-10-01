# Atlas Reasoning V3 — Phase 13: Add Atlas Questions and Management Answers

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
Allow Atlas to request missing business context rather than inventing it.

## Scope
Structured questions, answers, persistence, deduplication, UI, and memory reuse.

## Required implementation
1. Extend reasoning output with structured management questions.
2. Each question stores ID, case/result ID, text, reason, expected context type, state, and timestamps.
3. Persist questions to `atlas_questions`.
4. Persist answers to `atlas_answers`.
5. Add UI controls to answer or dismiss.
6. Mark answer source as `manager_answer`.
7. Sync answers to Honcho after canonical persistence.
8. Feed relevant answered questions into later reasoning context.
9. Do not ask for information already present in deterministic evidence.
10. Deduplicate the same unresolved question across runs.
11. Preserve conflicting historical answers and flag the conflict instead of silently replacing history.

## Required deliverables
Question/answer services, UI, persistence, Honcho sync, deduplication, and conflict history.

## Required tests
No duplicate open question, answer reuse, dismissal behavior, answer attribution, and conflict preservation.

## Acceptance criteria
Atlas can ask, receive, remember, and reuse bounded management context.

## Explicit non-goals
No general chat. No autonomous action.

## Stop condition
Stop when Q&A is persistent, non-duplicative, and safely reusable.
