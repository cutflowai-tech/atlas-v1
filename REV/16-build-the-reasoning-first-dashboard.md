# Atlas Reasoning V3 — Phase 16: Build the Reasoning-First Dashboard

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
Make canonical LLM reasoning the primary management experience while preserving technical evidence drill-down.

## Scope
Presentation only. Upstream metrics and reasoning logic remain server-side.

## Required implementation
1. Build reasoning-result cards.
2. Show title, lifecycle, Atlas reasoning summary, what changed, supporting evidence summary, counter-evidence, alternative explanations, confidence, limitations, management significance, questions, manager interpretation, and suggested investigations.
3. Add expandable drill-down:
   ReasoningResult → ReasoningCase → Intelligence V2 findings → metrics/projects → Monday evidence IDs.
4. Show version history.
5. Clearly mark new, updated, cooling, resolved, and superseded.
6. Do not display raw chain-of-thought.
7. Keep Intelligence V2 technical output accessible under diagnostics/evidence.
8. Preserve EN/AR parity if both languages remain required.
9. The frontend MUST NOT calculate metrics or reasoning.
10. Add degraded, empty, and error states.

## Required deliverables
Reasoning-first dashboard, result card, evidence drill-down, history, lifecycle display, notes/Q&A integration, diagnostics path.

## Required tests
Canonical rendering, evidence-link resolution, zero frontend calculations, lifecycle rendering, text escaping, and language parity where applicable.

## Acceptance criteria
Management sees reasoning first; engineers can still audit every card back to deterministic evidence.

## Explicit non-goals
No executive home yet. No raw chain-of-thought.

## Stop condition
Stop when the primary result experience is reasoning-first and fully auditable.
