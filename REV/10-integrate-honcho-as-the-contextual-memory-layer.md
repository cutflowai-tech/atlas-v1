# Atlas Reasoning V3 — Phase 10: Integrate Honcho as the Contextual Memory Layer

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
Add Honcho as long-term contextual memory without making it the canonical data store.

## Scope
Memory infrastructure and synchronization only.

## Required implementation
1. Add `reasoning/honcho_client.py`.
2. Configure one workspace per environment.
3. Define peers for Atlas and management users.
4. Define session naming conventions: `global:teachings`, `team:editors`, `editor:<id>`, `video-type:<id>`, `result:<id>`.
5. Support memory writes and context retrieval.
6. Tag every memory item with source type such as management teaching, manager interpretation, manager answer, Atlas question, or prior reasoning summary.
7. Persist synchronization state in `memory_sync_log`.
8. Canonical PostgreSQL write MUST happen before memory sync.
9. Honcho failure MUST NOT lose or roll back canonical application state.
10. Do not upload raw Monday event history wholesale.
11. Do not use Honcho identifiers as Atlas canonical identifiers.

## Required deliverables
Honcho client, session policy, sync service, source taxonomy, failure behavior, and credential documentation.

## Required tests
Mock write/read, duplicate handling, outage behavior, source preservation, wrong-session prevention, and raw-data leakage prevention.

## Acceptance criteria
Atlas can store and retrieve scoped memory while canonical state remains independent.

## Explicit non-goals
No automatic memory selection. No Teach Atlas UI. No notes UI.

## Stop condition
Stop when memory infrastructure is safe, scoped, and failure-tolerant.
