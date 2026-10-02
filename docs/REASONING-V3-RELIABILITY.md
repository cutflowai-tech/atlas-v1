# Reasoning V3 — Phase 18-B: provider reliability and budget controls

Specification: [`REV/18`](../REV/18-add-cost-concurrency-retry-and-reliability-controls.md) #1 (configured limits) and #10 (circuit
breaker). Owner: Phase 18-B. Orchestration, run status and resume (18-A) and telemetry/reporting (18-C) are not built here. This document
is the interface 18-A consumes at reconciliation.

Base: `4c973998288f33ddfab0997e34aead987d842af3` (POST_PHASE17). No migration: all state here is in-process.

## 1. Configuration (`settings.ReliabilitySettings`, `settings.reliability_settings(env)`)

Existing gateway limits are unchanged and still in `settings.GatewaySettings` (timeout, retries, backoff, max backoff, concurrency). Phase
18 adds the following. Every default reproduces the behaviour before Phase 18: there is no run budget, and the size limits equal the old
constants.

| Variable | Default | Range | Meaning |
|---|---|---|---|
| `ATLAS_REASONING_LLM_CONCURRENCY` (existing) | 4 | 1–32 | Provider attempts in flight per gateway, or per shared `ProviderControls` |
| `ATLAS_REASONING_LLM_TIMEOUT_SECONDS` (existing) | 120 | 5–600 | Per attempt |
| `ATLAS_REASONING_LLM_MAX_RETRIES` (existing) | 3 | 0–6 | Transport retries inside one logical call |
| `ATLAS_REASONING_LLM_BACKOFF_SECONDS` / `_MAX_BACKOFF_SECONDS` (existing) | 2 / 60 | 0–60 / 0–600 | Exponential backoff, capped; `Retry-After` honoured up to the cap |
| `ATLAS_REASONING_RUN_CALL_BUDGET` | unset (unlimited) | 1–100000 | Logical provider calls one run may start |
| `ATLAS_REASONING_EXECUTIVE_CALL_BUDGET` | 3 | 1–10 | Logical provider calls the executive synthesis may start within a run budget |
| `ATLAS_REASONING_MAX_INPUT_CHARS` | 400000 | 20000–2000000 | Analyst / update / reviewer input; larger is refused (`analyst.CaseTooLarge`), never truncated |
| `ATLAS_REASONING_MAX_OUTPUT_TOKENS` | 16000 | 1000–64000 | Analyst / update output budget sent to the provider |
| `ATLAS_REASONING_EXECUTIVE_MAX_INPUT_CHARS` | 300000 | 20000–2000000 | Executive input; larger is refused (`executive.InputTooLarge`), never truncated |
| `ATLAS_REASONING_EXECUTIVE_MAX_OUTPUT_TOKENS` | 16000 | 1000–64000 | Executive output budget |
| `ATLAS_REASONING_BREAKER_THRESHOLD` | 5 | 1–100 | Consecutive provider-outage failures that open the circuit |
| `ATLAS_REASONING_BREAKER_COOLDOWN_SECONDS` | 60 | 1–3600 | Open-circuit pause before one half-open probe |

Out-of-range or non-numeric values raise `ReasoningConfigError`, naming the variable and never echoing a secret. No reliability setting
is, or holds, a credential.

## 2. Public interfaces for 18-A (`atlas_reasoning.reliability`)

| Interface | Use |
|---|---|
| `ProviderControls.from_settings(gateway_settings(), reliability_settings())` | **One per process.** Pass it as `ReasoningGateway(..., controls=controls)` to every gateway (case reasoning, reviewer, executive) so they share one capacity semaphore and one breaker |
| `CallBudget.from_settings(reliability_settings())` / `CallBudget(limit, executive_limit=…)` | **One per run.** `acquire(purpose) -> BudgetDecision`, `check(purpose)` (planning only), `used`, `remaining`, `snapshot()` (counters for 18-C) |
| `ReasoningGateway.with_budget(budget)` | The same gateway (transport, settings, recorder, controls) charging `budget`: e.g. `ReasoningEngine(store, gateway.with_budget(budget))` |
| `ExecutiveSynthesizer(..., budget=budget)` | Charges the run budget **and** its executive limit for every executive model call |
| `BudgetDecision` | `ALLOWED`, `BUDGET_EXHAUSTED`, `EXECUTIVE_BUDGET_EXHAUSTED` |
| `CallRefused` → `CircuitOpen` (`circuit_open`), `BudgetExhausted` (`budget_exhausted`), `ExecutiveBudgetExhausted` (`executive_budget_exhausted`) | Typed refusals: `ProviderError` subclasses, `retryable = False`, `provider_called = False` |
| `CircuitBreaker` (`admit`, `release`, `record`, `state`, `snapshot`), `BreakerState`, `OUTAGE_CLASSES` | The breaker (normally used only through the gateway) |
| `ProviderControls.snapshot()`, `CallBudget.snapshot()` | Content-free counters for metrics |
| `analyst.max_input_chars()`, `analyst.max_output_tokens()`, `analyst.bounded_json(payload, limit=None)` | Configured size limits |

What the engines see: a refused call raises its `CallRefused` subclass from `gateway.call`. `ReasoningEngine` fails only that work item
(`provider:budget_exhausted`, `provider:executive_budget_exhausted` or `provider:circuit_open`); the open result and its lifecycle stay
as they were. Resuming those items is 18-A's job (they are reported by `EngineReport.unreasoned`). `ExecutiveSynthesizer` records a
`failed` run with `llm_calls = 0` and no request ID; the current brief stays current. Nothing new is written to canonical state by a
refusal.

## 3. Semantics

**Admission order** (`ReasoningGateway.call`, before any provider request):

1. Breaker `admit()`: refuses with `CircuitOpen` while open, or while the half-open probe is in flight.
2. Budget `acquire(purpose)`: refuses with `BudgetExhausted` or `ExecutiveBudgetExhausted`. A probe reserved in step 1 is released.
3. Attempts, each holding one capacity slot. A slot is released while waiting to retry.

A refused call sends nothing, consumes no budget unit, writes no `llm_calls` row (there was no attempt) and logs one line:
`call refused before any attempt … error_class=<class>`, with no prompt, response or credential.

**Budget accounting.**
- One unit per logical call (one `gateway.call`).
- Transport retries inside it cost no extra unit. The worst case is `units × (1 + max_retries)` provider attempts.
- A Phase 15 corrective re-ask is a new logical call and costs one unit.
- An `executive` call costs one run unit and one executive unit.
- `acquire` is atomic, so concurrent workers can never overspend.
- The same executive input as the current brief causes no call and spends no unit (`executive.decide` runs first).

**Circuit breaker.**
- **What counts:** consecutive outage failures of logical calls, after the gateway's retries. `OUTAGE_CLASSES` = timeout, rate limited,
  provider unavailable, network error, malformed provider envelope, quota exceeded, authentication.
- **Opening:** `threshold` of them open the circuit for `cooldown_seconds`. Then exactly one probe is admitted.
- **Probe result:** a success, or any non-outage answer (bad request, content filter, truncation, invalid structured output: the
  provider is reachable), closes it. An outage re-opens it for another cooldown.
- **Validation refusals** never reach the breaker: to the gateway they are provider successes.
- **State:** a state name, a counter, a timestamp, a probe flag and an open count. It is bounded and content-free.
- **Scope:** per process. There is no persistence and no cross-process semantics.

**Concurrency guarantee.** At most `concurrency` provider attempts are in flight across all gateways that share one
`ProviderControls`, in one process. Gateways built without shared controls each have their own bound, which is the previous behaviour.
Separate processes are not coordinated.

**Retries.** These are unchanged from Phase 06:
- Only retryable errors are retried, at most `max_retries` times.
- Backoff doubles and is capped by `max_backoff_seconds`, including `Retry-After`.
- Non-retryable errors (authentication, quota, bad request, content filter, truncation, configuration) and all refusals fail at once.
- Phase 15 validation re-asks remain a separate, engine-level loop (`ATLAS_REASONING_VALIDATION_RETRIES`). They are never transport
  retries.

**Sizes.**
- Inputs above the configured limit are refused with a typed error before any request is built: `analyst.CaseTooLarge` for case,
  update and reviewer input, and `executive.InputTooLarge` for executive input. The engines record the refusal as an isolated
  failure. Input is never truncated.
- Output is bounded by the configured `max_output_tokens`. A provider stop at the limit is `ProviderTruncated`: it is not retried, is
  not an outage, and the candidate is never committed.

**Model identity.** This is unchanged. `settings.model_identity_matches` (verified live in Phase 15) still accepts only the pinned slug
or its dated canonical slug. The Phase 15 guardrails refuse a substitution, and the breaker does not treat one as an outage.

## 4. Tests

`tests/test_reasoning_reliability.py`:

| Area | Tests |
|---|---|
| Settings | Defaults are backward-compatible; every value is configured and bounded; settings hold no credential |
| Budget | Checked before the call, and a refusal costs nothing; the executive budget is separate and also charges the run; retries of one logical call cost one unit; thread-safe and exact under contention; `with_budget` shares everything else |
| Concurrency | Gateways sharing controls share one bound (reasoning plus executive bursts); the documented scope without shared controls |
| Retries | Timeouts use capped exponential backoff; `Retry-After` is capped; non-retryable errors and refusals are not retried |
| Breaker | Repeated outages open it and it then blocks calls (with no request and no record); a half-open probe success recovers; a probe failure re-opens; one probe at a time; a budget refusal never holds the probe; non-outage failures and would-be validation refusals do not trip it; a non-outage answer resets the count; outage classes; bounded, content-free state; safe logs |
| Sizes | Oversized case input is refused (before any call) and never truncated; configured limits reach the analyst, update and executive requests; oversized executive input is refused; an oversized output is a non-retryable truncation that does not trip the breaker |
| Identity | The Phase 15 model-identity semantics are unchanged |
| DB | Budget exhaustion fails only unfunded items and keeps every result; an outage opens the circuit and stops sending, with nothing half-written; an open circuit keeps every valid card; the executive budget and unchanged input (0 calls, no unit); executive with an open circuit keeps the brief |
