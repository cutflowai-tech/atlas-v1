# Reasoning V3 — monitoring checklist (Phase 20-B, prepared)

This checklist defines what to watch during and after each rollout stage ([`REASONING-V3-PRODUCTION-ROLLOUT.md`](REASONING-V3-PRODUCTION-ROLLOUT.md) §5). It
creates **no new metric definition**. Every item is a field of an existing canonical report:

- the Phase 18-C **reliability report**, `reliability-metrics-v1`, from `python -m atlas_reasoning.reliability_report --run RUN_ID` or `--latest N`. It reads PostgreSQL only and contains no content or credentials (`REASONING-V3-TELEMETRY.md`);
- the Phase 19 **evaluation report**, from `python -m atlas_reasoning evaluate run` on a disposable database (`REASONING-V3-EVALUATION.md`, `REASONING-V3-EVALUATION-RUNNER.md`);
- `db-health` and the per-process breaker snapshot that the runtime logs.

Paths below are `RunMetrics` fields (`runs[i]` or `aggregate`), except `backlog.*`, which is top-level in the report. External alert delivery does not exist (`PRODUCTION-RUNBOOK.md` §5).
Until an approved destination is implemented, operators review these reports after every run.

| # | Item | Canonical field | Review trigger (starting values; approve per stage) |
|---|---|---|---|
| 1 | Logical provider calls | `provider_calls.total.logical_calls`, `provider_calls.by_purpose` | Above the run budget's expectation, or unexpected purposes |
| 2 | Attempts and retries | `provider_calls.total.attempts`, `provider_calls.total.retries`, `provider_calls.total.retried_calls` | Retries above 10% of logical calls |
| 3 | Tokens (cost proxy) | `provider_calls.total.input_tokens`, `provider_calls.total.output_tokens`, `provider_calls.total.total_tokens`, `provider_calls.total.calls_without_usage` | Above the approved per-run token budget; any `calls_without_usage` |
| 4 | Latency | `provider_calls.total.latency` (`p50_ms`, `p95_ms`, `max_ms`) | p95 above `ATLAS_REASONING_LLM_TIMEOUT_SECONDS` / 2 |
| 5 | Provider failures | `provider_calls.total.failed`, `provider_calls.total.failures_by_class`, `work.failures_by_class` | Any `authentication` or `quota_exceeded` (non-retryable: operator action); repeated outage classes |
| 6 | Circuit breaker | `work.refused_before_call`, `status_inputs.refused_work_items`; the runtime's breaker snapshot (`state`, open count) | Breaker open in two consecutive runs |
| 7 | Budget exhaustion | `orchestration.budget_limit`, `orchestration.budget_calls_used`, `orchestration.deferred`, `orchestration.last_reasons` (`work_deferred`) | Deferral in two consecutive runs (re-plan the budget with approval; never raise it ad hoc) |
| 8 | Run status | `run.status`, `orchestration.last_status`, `orchestration.last_reasons`, `orchestration.passes`, `orchestration.interrupted_passes` | Any `failed`; `degraded` twice in a row; any interrupted pass |
| 9 | Validation rejection | `validation.refused_candidates`, `validation.corrective_reasks`, `validation.failed_work_items`, `validation.codes`; Phase 19 `validation_rejection_rate` | Release threshold 0.05 exceeded; a new refusal code |
| 10 | Skipped unchanged cases | `gate.skipped_unchanged`, `gate.by_action` | Unchanged evidence that still produced LLM work (must be 0 by construction) |
| 11 | Result and card churn | `work.new_results`, `work.updates`, `work.no_change_reviews`; Phase 19 `unnecessary_new_card_rate`, `unnecessary_field_rewrite_rate`, `lifecycle_churn_rate`, `case_identity_stability` | Release thresholds (0 / 0 / 0 / 1) |
| 12 | Duplicate questions | Phase 19 `duplicate_question_rate` | Release threshold 0 |
| 13 | ExecutiveBrief synthesis calls | `executive.synthesis_runs`, `executive.by_decision`, `executive.model_calls`, `executive.unchanged_zero_call`, `executive.failures_by_class` | Calls on unchanged input (must be 0); a failure trend |
| 14 | Memory | `memory.injected_calls`, `memory.degraded_calls`, `status_inputs.memory_degraded_calls`; `memory_sync_log` pending/failed (dashboard data health) | Degraded memory in two consecutive runs; unsynced copies after `memory-sync` |
| 15 | Backlog | `backlog.open_llm_work_items`, `backlog.unreasoned_cases` | Growing across three runs |
| 16 | Phase 19 evaluation threshold status | Evaluation report `result`, `code`, `report.threshold_results`; also `grounding_failure_rate` and `expectation_failure_rate` | Anything but `PASS` on the release SHA blocks the release |

Notes:
- Run status meanings are Phase 18-A's (`REASONING-V3-ORCHESTRATION.md` §4). This checklist does not redefine them.
- The breaker is per process. A report covers all processes; the breaker snapshot covers one.
- Monitoring output contains identifiers, counts and codes only. Never paste prompts, responses or credentials into incident records.
