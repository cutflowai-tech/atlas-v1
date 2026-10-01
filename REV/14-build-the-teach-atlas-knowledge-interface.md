# Atlas Reasoning V3 — Phase 14: Build the Teach Atlas Knowledge Interface

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
Create a controlled management interface for durable or temporary business teachings.

## Scope
Teaching model, scope, validity, UI, persistence, memory sync, expiration, and auditability.

## Required implementation
1. Create Teaching with ID, body, scope type, scope ID, teaching type, validity mode, valid_from, valid_until, status, author, and timestamps.
2. Support scopes: company, editor, video_type, workflow, client, specific_result.
3. Support types: business_rule, context, correction, interpretation, temporary_situation.
4. Support validity: until changed, explicit date range, current period only.
5. Persist teachings locally first.
6. Sync active teachings to relevant Honcho sessions.
7. Exclude expired teachings from future contexts.
8. Support enable, disable, and archive.
9. Add a `Teach Atlas` UI.
10. Show source, scope, type, and validity clearly.
11. Teaching MUST NOT rewrite historical Monday evidence or deterministic metrics.
12. A correction implying bad upstream source data MUST be surfaced for engineering review instead of silently changing truth.

## Required deliverables
Teaching model, persistence, UI, scope/validity logic, Honcho sync, expiration, and audit history.

## Required tests
Expiration, scope isolation, archive behavior, temporary validity, and deterministic-evidence immutability.

## Acceptance criteria
Management can explicitly teach Atlas reusable context with clear scope and lifetime.

## Explicit non-goals
No automatic teaching extraction from casual notes. No source-data editing.

## Stop condition
Stop when teachings are explicit, scoped, expirable, auditable, and reusable.
