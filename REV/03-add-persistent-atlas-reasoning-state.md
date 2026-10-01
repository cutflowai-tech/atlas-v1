# Atlas Reasoning V3 — Phase 03: Add Persistent Atlas Reasoning State

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
Introduce durable canonical application state for Reasoning V3.

## Scope
Add a relational persistence layer for reasoning runs, cases, results, history, notes, questions, answers, teachings, LLM metadata, and memory sync metadata.

## Required implementation
1. Use PostgreSQL for production.
2. Add migrations for: `reasoning_runs`, `reasoning_cases`, `reasoning_results`, `reasoning_result_versions`, `reasoning_evidence_links`, `manager_notes`, `atlas_questions`, `atlas_answers`, `teachings`, `llm_calls`, and `memory_sync_log`.
3. Define primary keys, foreign keys, uniqueness rules, indexes, and version constraints.
4. Store canonical identifiers and statuses relationally.
5. Use JSON only for document-like fields.
6. Implement repository/data-access classes. SQL MUST NOT leak into rendering code.
7. Use transactions for result creation and result-version updates.
8. Add database health checks and migration bootstrap.
9. Add local-development configuration without weakening production expectations.
10. Monday raw operational data MUST NOT be copied into this store unless a later approved phase requires it.

## Required deliverables
Migrations, repository layer, configuration, health check, setup documentation, and a debug command for retrieving case/result state.

## Required tests
Migration tests, referential integrity, uniqueness, rollback, restart persistence, and concurrent update protection.

## Acceptance criteria
Reasoning state survives restart, supports version history, and cannot be partially corrupted by a failed write.

## Explicit non-goals
No OpenRouter. No GPT calls. No Honcho. No public reasoning UI.

## Stop condition
Stop when durable reasoning state is reliable and fully test-covered.
