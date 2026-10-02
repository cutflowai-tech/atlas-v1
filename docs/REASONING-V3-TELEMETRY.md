# Reasoning V3 — Reliability Telemetry (Phase 18-C)

`REV/18` item 8: track calls, tokens, latency, failures, retries, skipped unchanged cases and validation failures. This document
describes the metrics, the report model, and the interface that the Phase 18-A run-status policy uses.

Phase 18-C changes no reasoning behaviour or orchestration. It adds no migration and no aggregate table, and it does not change
`store/calls.py`, `store/health.py`, the engine, the gateway or the executive synthesizer. Every metric is a read of rows that
Phases 03–17 already write.

## 1. Modules

| Module | Role |
|---|---|
| `src/atlas_reasoning/reliability_metrics.py` | Pure model: `RunRows` → `RunMetrics` / `ReliabilityReport`. No I/O, no clock. |
| `src/atlas_reasoning/store/reliability_metrics.py` | Read-only SQL. It builds `RunRows` from canonical tables in one `REPEATABLE READ READ ONLY` transaction. |
| `src/atlas_reasoning/reliability_report.py` | Operator entry: `python -m atlas_reasoning.reliability_report`. |
| `tests/test_reasoning_reliability_metrics.py` | Tests for the pure model and for the PostgreSQL pipeline. |

## 2. Sources

| Metric group | Canonical source | Notes |
|---|---|---|
| Provider calls, attempts, retries, tokens, latency, provider failures | `llm_calls` | One row is one **logical** gateway call. `attempts` counts provider attempts. `retries = attempts − 1`. |
| LLM work by status, failures by class, work closed without a call | `reasoning_work_items` (+ `EXISTS llm_calls`) | Only the class before `:` in `last_error` is read. |
| Successful new results / updates / no-change reviews | `reasoning_result_versions` (`created` / `patched` / `no_change_review`) joined to the work item | Counted for the run that created the work item. |
| Validation failures, codes, corrective re-asks | `reasoning_failed_candidates`, `llm_calls` | Re-asks are reasoning calls (`analyst` / `update`) of a work item beyond the first. |
| Skipped unchanged cases | `reasoning_case_observations.action = 'unchanged'` | Zero LLM work by construction (Change Gate). |
| Executive synthesis calls / zero-call preserve | `executive_brief_runs` (`decision`, `llm_calls`, failure class) | `unchanged` runs always have `llm_calls = 0` (a database CHECK enforces this). |
| Memory degraded | `memory_injections.memory_status` | `degraded` or `unavailable` counts as a degraded call. |
| Backlog (read time, all runs) | open LLM `reasoning_work_items`, `StoreTransaction.unreasoned_cases()` | |

**Attribution.** Work items, result versions, refusals and reasoning calls belong to the run whose Change Gate **created the
work item**. The engine passes `item.run_id` to every call, so this holds even when a later `process_run` processed older work.
Executive rows belong to the run passed to `ExecutiveSynthesizer.synthesize`. Calls without a run, such as
`provider-health --record`, belong to no run.

## 3. What telemetry never contains

- Prompts, responses, refused candidates, violation messages, notes, answers, teachings, memory text, case documents or result
  text. The SQL names its columns, and every column is an identifier, status, code, count, token count or timing.
- Credentials. The database URL is never printed. Error output uses `Database.display_url` and redaction.
- Hidden reasoning. None exists to store.

A test runs a full pipeline that includes a refused candidate and an executive brief. It then checks that the serialized report
contains no content keys, no refused text, no result titles, no prompt text, and not the database password.

Telemetry is operational only. It is never part of a `ReasoningResult`, an `ExecutiveBrief` or any model input. It also never
writes `reasoning_runs.status`.

## 4. Report model (`metrics_version = "reliability-metrics-v1"`)

`ReliabilityReport.to_dict()` (`to_json()` produces compact output with sorted keys):

```text
{
  "metrics_version": "reliability-metrics-v1",
  "run_ids":   [ ... ]                         # in (started_at, run_id) order; duplicates removed
  "runs":      [ RunMetrics, ... ]             # the same order
  "aggregate": RunMetrics                      # computed from the UNION of the runs' rows ("run": null)
  "backlog":   {"open_llm_work_items", "open_by_status": {"pending", "in_progress"}, "unreasoned_cases"}
}

RunMetrics = {
  "run": {"run_id", "status", "started_at", "gated_at", "finished_at", "wall_ms"} | null,
  "provider_calls": {
     "total":      CallMetrics,
     "by_purpose": {"analyst" | "update" | "review" | "executive" | ...: CallMetrics}   # only purposes present
  },
  "work": {"llm_work_items", "lifecycle_work_items",
           "by_status": {"pending", "in_progress", "done", "failed", "superseded", "cancelled", <any new status>},
           "open", "done", "failed", "closed_without_call",
           "new_results", "updates", "no_change_reviews",
           "failures_by_class": {"provider" | "validation" | "work" | "store" | "contract" | "internal": n}},
  "validation": {"refused_candidates", "corrective_reasks", "failed_work_items", "codes": {CODE: n}},
  "gate": {"observed_cases", "skipped_unchanged", "by_action": {"unchanged", "new", "updated", "disappeared"}},
  "executive": {"synthesis_runs", "by_decision": {"synthesized", "synthesized_empty", "unchanged", "failed"},
                "model_calls", "unchanged_zero_call", "failures_by_class": {...}},
  "memory": {"injected_calls", "degraded_calls", "degraded", "by_status": {...}},
  "status_inputs": StatusInputs
}

CallMetrics = {"logical_calls", "attempts", "retries", "retried_calls", "succeeded", "failed",
               "input_tokens", "output_tokens", "total_tokens", "calls_without_usage",
               "latency": {"total_ms", "max_ms", "mean_ms", "p50_ms", "p95_ms"},
               "failures_by_class": {error_class: n}}
```

**Determinism.** The report has no generated-at timestamp, no clock and no randomness. Mappings are emitted with sorted keys, and
fixed groups (work statuses, gate actions, executive decisions) always list every known key, with 0 where nothing happened.
Latency values are integers: the mean is a floor, and p50 and p95 use the nearest rank. `None` means "no calls". The same rows
always produce the same JSON, byte for byte, whatever the row or `run_ids` order.

**Empty run.** All counts are 0, latency statistics are `null`, `by_purpose` is `{}`, and every `status_inputs` value is 0.

## 5. Interface for 18-A (run status)

Phase 18-A owns the meaning of `complete`, `partial`, `degraded` and `failed`. Telemetry exposes only facts:

```python
from atlas_reasoning.store.reliability_metrics import reliability_report

inputs = reliability_report(store, [run_id]).run(run_id).status_inputs      # StatusInputs (frozen dataclass)
```

| `StatusInputs` field | Meaning (for the run's LLM work items unless stated) |
|---|---|
| `llm_work_items` | LLM work items the run's gate created |
| `open_work_items` | still `pending` or `in_progress` (not yet reasoned, deferred or interrupted) |
| `done_work_items` | `done` (committed, or closed without a call) |
| `failed_work_items` | `failed` |
| `provider_failed_work_items` | failed with `provider:<class>` |
| `validation_failed_work_items` | failed with `validation:<codes>` (Phase 15 refusal after re-asks) |
| `other_failed_work_items` | failed with any other class (`work:`, `store:`, `contract:`, `internal:`) |
| `committed_versions` | new results + updates + no-change reviews committed for the run's work |
| `provider_failed_calls` | `llm_calls` of the run with `status = 'failed'` (all purposes) |
| `executive_failed_runs` / `executive_ok_runs` | executive synthesis runs that failed (the current brief is preserved) / that did not fail |
| `memory_degraded_calls` | reasoning calls whose contextual memory was `degraded` or `unavailable` |

Notes for 18-A:

- `RunMetrics.status_inputs` is computed from the same snapshot as the rest of the report. The report reads, never writes. If
  18-A stores a status, it does so in its own transaction after it reads the report.
- Any new work status that 18-A or 18-B adds (for example a deferred or budgeted status) appears automatically in
  `work.by_status`. It counts towards `open` only if it is `pending` or `in_progress`. If 18-A adds a status that should count as
  open, `OPEN_WORK` in `reliability_metrics.py` is the single place to change.
- `failures_by_class` keys are the stable prefixes produced by `engine.error_code`.

## 6. Operator use

```bash
python -m atlas_reasoning.reliability_report --run run_<32 hex> [--run ...]
python -m atlas_reasoning.reliability_report --latest 5
```

The command prints JSON on stdout. It exits 0 when it prints a report, and 1 (with `{"ok": false, "error": ...}`) when a run does
not exist or the database cannot be read. The database URL comes from `ATLAS_REASONING_DATABASE_URL` or `_FILE` and is never
printed.
