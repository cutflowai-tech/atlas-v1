# Atlas Reasoning V3 — Phase 18: Add Cost, Concurrency, Retry, and Reliability Controls

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
Make Reasoning V3 safe under provider latency, rate limits, partial failure, and increasing case volume.

## Scope
Operational controls around existing reasoning behavior.

## Required implementation
1. Configure maximum concurrent calls, per-run call budget, retry count, timeout, backoff, prompt/context size, and executive synthesis budget.
2. Prioritize updated high-importance active cases, then new high-importance cases, then lower-priority work.
3. Unchanged cases remain zero-call.
4. Isolate failures per case.
5. Preserve last valid result on failure.
6. Add run status: complete, partial, degraded, failed.
7. Add idempotent resume of incomplete runs.
8. Track calls, tokens, latency, failures, retries, skipped unchanged cases, and validation failures.
9. Prevent duplicate concurrent processing of the same case/run.
10. Add circuit-breaker or pause behavior after repeated provider failures.

## Required deliverables
Reliability config, orchestration controls, run status, resume logic, metrics/logging, and duplicate-work protection.

## Required tests
Provider outage, restart/resume, duplicate prevention, budget enforcement, zero-call unchanged, bounded retry, and partial-run behavior.

## Acceptance criteria
Provider problems cannot corrupt canonical reasoning state or erase valid results.

## Explicit non-goals
No new reasoning semantics or memory behavior.

## Stop condition
Stop when partial failures are recoverable and operational limits are enforced.
