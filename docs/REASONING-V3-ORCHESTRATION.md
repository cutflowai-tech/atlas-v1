# Atlas Reasoning V3 — Phase 18-A: run orchestration

Specification: [`REV/18`](../REV/18-add-cost-concurrency-retry-and-reliability-controls.md) #2–#7 and #9. Phase 18-A owns run orchestration:
deterministic work priority, the per-pass reasoning-call budget, run status, bounded idempotent resume, duplicate-work protection and
failure isolation. Provider transport (retry, backoff, timeouts, concurrency limits, circuit breaking) is 18-B's; reliability
analytics and reporting are 18-C's. Nothing here changes reasoning semantics, memory behaviour, case identity, the Change Gate,
lifecycle rules, the Phase 15 guardrails or ExecutiveBrief synthesis.

```
Change Gate (run gated) ─► RunOrchestrator.run(run_id)                       one engine at a time (session advisory lock)
                             │ open pass (reasoning_run_passes; one open pass per run)
                             │ abandoned claims (older than the longest possible call) → failed work:STALE_CLAIM (resumable)
                             │ lifecycle sweep (Phase 09, no model call)
                             │ pending LLM work in work_priority order; admit ≤ remaining budget; the rest stays pending
                             │ ReasoningEngine.process_work(admitted, budget=PassBudget)   every provider call reserves 1 unit atomically
                             ▼
                           classify run → reasoning_runs.status + pass (reasons, counts) → PassReport (executive_ready)
later: RunOrchestrator.resume(run_id) — same pass, plus bounded retry work for eligible failures of the run
```

## 1. Modules

| Module | Role |
|---|---|
| `work_priority` | Deterministic priority from canonical V2 data on the work item's case document (`priority`, `prioritize`, `high_importance`) |
| `run_control` | `RunOrchestrator` (`run`, `resume`, `incomplete_runs`), `OrchestrationPolicy`, `ReliabilityPolicy` protocol, `PassBudget`, `PassReport` |
| `store/run_control` | All orchestration SQL: passes, atomic budget, retry candidates and lineage, run status |
| `engine` (changed) | `process_work(items, budget=)`, the `CallBudget` protocol, `BUDGET_EXHAUSTED`, public `fail`; `process_run` unchanged |
| migration `0600_run_control.sql` | `reasoning_run_passes`, `reasoning_work_retries` (additive; health lists both) |

## 2. Priority (`work_priority`)

Importance comes only from the work item's canonical `ReasoningCase` document: Intelligence V2's own `category`, `direction` and
deterministic importance `rank` (1 = most important) on the supporting findings. The LLM never takes part (test: the module imports no
gateway, provider or analyst).

- **High importance**: adverse orientation and an adverse `needs_attention` or `emerging_risk` supporting finding.
- **Tiers**: 1 = updated (`gate_action = updated`) high-importance; 2 = new high-importance; 3 = everything else.
- **Tie-breaks**: best V2 rank (lower first; none last), `updated` before `new`, `case_id`, `work_item_id` — a total order.

## 3. Budget

`ReliabilityPolicy.reasoning_call_budget() -> int | None` (protocol; `OrchestrationPolicy.max_calls_per_pass` when none is injected;
`None` = unlimited). The budget belongs to one **pass** (the initial pass or one resume), stored in `reasoning_run_passes.call_budget`:
REV/18's "per-run call budget" is applied to every orchestration of a run, and a resume — an explicit operator or scheduler action —
opens a new budget window (otherwise a run whose budget ran out could never progress). A pass spends its budget on all pending work in
priority order, including older runs' pending work.

- Admission: pending work in priority order, at most as many items as calls remain; the rest stays `pending` (deferred, resumable).
- Each provider call of the engine (`gateway.call`: first call, corrective re-asks and the optional Phase 15 reviewer) first reserves one
  unit: `UPDATE … SET calls_used = calls_used + 1 WHERE calls_used < call_budget` — atomic in PostgreSQL, and `calls_used <= call_budget`
  is a CHECK, so threads or processes can never overspend. A refused reservation returns the claimed item to `pending` (outcome error
  `work:BUDGET_EXHAUSTED`) before anything about the call is recorded: deferred, not failed, so it spends no retry attempt.
- Budget exhaustion never touches a committed result; unchanged cases have no work, so they cost nothing.

## 4. Run status

| Status | Meaning (precedence top-down) | Reason codes |
|---|---|---|
| `failed` | no usable reasoning run: never gated; an orchestration error (sweep, store); or every attempt of the pass failed at the provider, none committed, and no case of the run has a usable open result | `not_gated`, `orchestration_error:<class>`, `provider_outage` |
| `partial` | useful state kept, work remains resumable: LLM work of the run still pending, or a failure resume will retry (the same predicate resume uses: still eligible, retryable, attempts left) | `work_deferred`, `resumable_failures` |
| `degraded` | all the run's work attempted, but a case's latest work failed for good (not retryable, out of attempts, or superseded by newer work), a follow-up (questions / memory) failed in any pass, or a reasoning call of the run ran with degraded memory | `unresolved_failures`, `followup_failed`, `memory_degraded` |
| `complete` | every LLM item of the run done or legitimately closed — also a run with zero work | — |

The status is written to `reasoning_runs.status` (reason codes in `error`, `finished_at` set to the latest pass; the gate's `counts` and
`gated_at` kept) and to the pass. Older runs whose pending work a pass finished are re-classified too. A status never invalidates a
committed result; a no-op resume never turns a degraded run complete (degradation carries across passes). `incomplete_runs()` lists gated
`partial` and `failed` runs that resume can still advance (an outage run included; a `degraded` run's failures are final).

## 5. Resume (`RunOrchestrator.resume`)

Same pass steps, plus retry work. A case of the run is retried only when it is present, its current evidence is still unreasoned,
it has no open LLM work, and its latest LLM item failed **on that same evidence state** with a retryable error
(`OrchestrationPolicy.retryable`: transient provider classes, `work:INTERRUPTED`, `work:STALE_CLAIM`, `work:BUDGET_EXHAUSTED`, `store:*`;
never validation refusals — Phase 15 already re-asked — nor authentication, quota, bad request, content filter, truncation,
configuration, contract or internal errors). The retry is a pending copy of the failed item (same run, case, kind, gate action, evidence
state, base, case document) with a lineage row, created under the Change Gate's transaction lock with eligibility re-checked in the same
transaction (a concurrent gate run can never be raced into stale or duplicate work); `max_attempts` (default 3) bounds attempts per (case, evidence state). Unique keys make a
second retry of the same failed item, or of the same attempt, impossible. Completed work is never redone (it is not unreasoned); the
engine's stable result IDs, patch-not-regenerate rule, question deduplication and memory sync make questions, versions and memory copies
duplicate-free (tested). Repeated resume with nothing eligible makes no call and creates nothing.

Interrupted processes: an LLM item `in_progress` for longer than the longest possible call (`ReasoningEngine.stale_claim_seconds`, from
the gateway limits) belongs to a dead worker and is failed `work:STALE_CLAIM` at the start of the next pass (resumable); a younger claim may
still be live — for example a worker whose engine-lock connection dropped — so it is never taken over early. A pass left open by a dead
process is closed `interrupted`.

## 6. Duplicate protection

- One engine at a time: the existing session advisory lock (`ENGINE_LOCK_KEY`), now also taken by every pass.
- One open pass per run: partial unique index.
- One open LLM work item per case (existing partial unique index); claims are guarded status transitions (`pending → in_progress`).
- One retry per failed item, one per (case, evidence state, attempt): unique keys.

## 7. Interfaces for the rest of Phase 18

**Required from 18-B (provider reliability)** — consumed through narrow seams, no configuration name invented here:

| Need | Seam |
|---|---|
| The per-pass reasoning-call budget | an object with `reasoning_call_budget() -> int | None`, passed as `RunOrchestrator(..., reliability=)` |
| Executive-synthesis budget | not consumed here; executive synthesis is scheduled by the integration (below) |
| Error taxonomy | `ProviderError.error_class` stays the retry key (`provider:<class>`); a new class (e.g. circuit open / paused) must be added to `OrchestrationPolicy.retryable` if work failed by it should be resumed |
| Circuit-breaker pause | when the breaker opens, the gateway should fail fast with a provider error class; the pass then ends `partial` (retryable) or `failed` (`provider_outage`) and `resume` continues later |

**Provided to 18-C (analytics/reporting)** — read-only: `reasoning_run_passes` (kind, policy version, budget, calls used, admitted, deferred,
retries, run status, reasons, counts incl. `unchanged_cases`, `high_priority_admitted`, `recovered`, outcome, times),
`reasoning_work_retries` (lineage, attempt, failure), `reasoning_runs.status`/`error`, existing `llm_calls`, and `PassReport.to_dict()`.

**Executive handoff**: `PassReport.executive_ready` is true when the run is `complete` or `degraded` and no LLM work is open anywhere —
the point at which `ExecutiveSynthesizer.synthesize(run_id)` (unchanged) should run. A `partial` or `failed` run is not ready; resume
first. The final Phase 18 integration wires it (with 18-B's executive budget).

## 8. Tests

`tests/test_reasoning_run_control.py`: priority tiers and tie-breaks under shuffled input, model-free priority, retry policy; with
PostgreSQL — complete pass and zero-call unchanged snapshot, admission order, high-importance first under a budget, budget → partial →
resume → complete → idempotent resume, budget spent by a corrective re-ask (never overspent), resume after process interruption,
retryable vs non-retryable and bounded attempts, retried failure keeps stable IDs and the previous result, per-case failure isolation,
provider outage → failed → resume, never-gated run, memory degradation, concurrent orchestrators, database refusal of a second open pass /
second retry / overspending, migration repeatability and health; duplicate-free versions, questions, memory copies and open work.

## 9. Known limitations

- Retry attempts are counted per (case, evidence state) over all time: evidence that returns to an earlier state inherits that state's
  attempts.
- An orchestration error (e.g. a failing lifecycle sweep) marks the run `failed` even when its committed results still stand (by the
  documented precedence).

- The budget counts the engine's logical provider calls (one per `gateway.call`, corrective re-asks included); the gateway's own
  transport retries inside one call are 18-B's to bound and count. Calls of the optional Phase 15 reviewer are not counted.
- With a budget, a re-ask can be refused after the first call of an admitted item succeeded; the item is then failed resumably.
- No CLI command yet: the final Phase 18 integration wires `RunOrchestrator` into `python -m atlas_reasoning reason`.
