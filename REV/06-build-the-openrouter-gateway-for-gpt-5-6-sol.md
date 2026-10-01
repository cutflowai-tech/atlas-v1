# Atlas Reasoning V3 — Phase 06: Build the OpenRouter Gateway for GPT-5.6 Sol

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
Create one isolated provider gateway for GPT-5.6 Sol through OpenRouter.

## Scope
Transport, configuration, retries, structured output, observability, and failure isolation only.

## Required implementation
1. Add `reasoning/openrouter_client.py`.
2. Read API credentials only from environment/configuration.
3. Pin the production model explicitly to GPT-5.6 Sol through OpenRouter.
4. Support structured JSON output matching Reasoning V3 schemas.
5. Implement timeout, bounded retries, exponential backoff, and rate-limit handling.
6. Implement a provider error taxonomy.
7. Add request IDs and safe logs that never leak secrets.
8. Add configurable concurrency limits.
9. Persist call metadata to `llm_calls`: run ID, case ID, request ID, model, prompt version, token counts if available, latency, status, retries, and error class.
10. Add a fake provider for tests.
11. Domain models MUST remain provider-neutral.

## Required deliverables
OpenRouter client, fake client, config/env docs, error taxonomy, call logging, and a provider health-check command.

## Required tests
Success, timeout, retry, rate limit, invalid structured response, concurrency limit, secret redaction, and one-case failure isolation.

## Acceptance criteria
Provider failures are contained and observable; no domain logic depends directly on OpenRouter SDK details.

## Explicit non-goals
No production reasoning prompts. No Honcho. No result merge.

## Stop condition
Stop when transport is reliable and fully testable without live external calls.
