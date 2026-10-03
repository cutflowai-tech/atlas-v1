# Reasoning V3 — evaluation runner (Phase 19-B)

Phase 19-A ([`REASONING-V3-EVALUATION.md`](REASONING-V3-EVALUATION.md)) defines the parts of the evaluation that are frozen:

- the 20 published golden cases and their closed scenario vocabulary;
- what is observed, every metric and the release thresholds;
- the canonical `EvaluationReport`.

Phase 19-B is the production-supported **runner** that executes those cases, plus the **human management-quality review** that sits next to the report. The runner uses the real Change Gate, `ReasoningEngine`, the Phase 15 guardrails, the Phase 18 `RunOrchestrator`/`ProviderControls`, and PostgreSQL. It does not change any Phase 19-A file, metric, threshold or expectation. It computes no metric and decides no outcome.

Review record: [`evidence/REASONING-V3-PHASE-19B.md`](evidence/REASONING-V3-PHASE-19B.md).

## 1. Modules

| Module | Role |
|---|---|
| `atlas_reasoning/evaluation_runner.py` | Runs every published golden case on a fresh disposable database. Implements the whole vocabulary, enforces the database guard and the audit-consistency boundary, and returns the result codes and the deterministic JSON envelope. |
| `atlas_reasoning/evaluation_offline_model.py` | The deterministic offline model: a `provider.Transport` with per-case fault queues. It is byte-equivalent to the Phase 19-A golden driver's model. |
| `atlas_reasoning/evaluation_live.py` | Optional live mode. It is explicit opt-in only, with call budgets, and uses the existing OpenRouter gateway and the pinned model. The `OpenRouterTransport` is injected by `__main__`, still the only module that wires OpenRouter; without it, live mode refuses to start. |
| `atlas_reasoning/evaluation_review.py` | The human review checklist and its record validation. The review is release input only. |
| `atlas_reasoning/evaluation_cli.py` | `python -m atlas_reasoning evaluate …`. |
| `atlas_reasoning/store/evaluation_audit.py` | Read-only audit-consistency SQL. |
| `atlas_reasoning/store/evaluation_scenario.py` | The runner's scenario SQL (schema reset, focus case, open question, ageing claims) and libpq URL resolution. SQL and the driver stay in `store/`. |
| `reasoning_input_boundary.showcase_documents()` | The golden dataset (`showcase-v1`: the synthetic showcase), read through the one module allowed to import `atlas_commander`. |

Runtime code never imports test modules. A test proves that the runner's canonical report for all 20 cases is byte-identical to the Phase 19-A golden driver's report.

## 2. Running it

```bash
ATLAS_REASONING_EVALUATION_DATABASE_URL=postgresql://atlas@127.0.0.1:5432/atlas_reasoning_eval_test \
  python -m atlas_reasoning evaluate run [--case FIXTURE_ID ...] [--output run.json]
```

**Offline is the default.** It uses the deterministic offline model and `FakeHoncho`. It needs no credentials and makes no network call, and it is reproducible: two runs give byte-identical output. `--case` runs a subset. A subset never PASSes, because coverage 1–20 is required.

**Database guard.** The runner drops and re-migrates the `atlas_reasoning` schema once per case. It therefore refuses, with `EVALUATION_CONFIGURATION_INVALID` before touching anything:

- a database whose name (as libpq resolves it, so `?dbname=` and `?host=` overrides count) does not contain `test` as a word: `atlas_reasoning_test` and `eval_test2` are accepted, `latest` and `contest` are not;
- a URL that uses a libpq `service` (its target must be explicit);
- the database `ATLAS_REASONING_DATABASE_URL` (or `_FILE`) names. The comparison is conservative: same database name, same port, and hosts that are equal or unstated. Every local address (socket directory, `localhost`, loopback) counts as the same host;
- a URL that is not `postgresql://`;
- a missing URL.

The guard runs inside `run_evaluation` and `observe_cases` too, so a hand-built plan cannot skip it. The CLI reads only `ATLAS_REASONING_EVALUATION_DATABASE_URL` (or `_FILE`). It never falls back to the canonical or test database variables. Messages show redacted URLs only.

## 3. Result codes

`run` always prints **one JSON object** on stdout and exits with its code. It never prints a traceback.

| Code | Exit | Meaning |
|---|---|---|
| `PASS` | 0 | The Phase 19-A report passes: the published cases and thresholds, full coverage 1–20, every threshold met. |
| `EVALUATION_FAILED` | 1 | A valid evaluation that fails a threshold, an expectation, coverage or release conformance; the report says which. Also used, with `report: null`, when Reasoning V3 never reaches the state a step needs (for example no open question to answer); the `runtime:` failure names it. |
| `EVALUATION_CONFIGURATION_INVALID` | 2 | The evaluation could not start: an unsafe database, or one unreachable at preflight; an invalid golden case or threshold file; an invalid live configuration. |
| `EVALUATION_AUDIT_INCONSISTENCY` | 3 | The canonical audit trail is inconsistent. No metric value is produced (§4). |
| `EVALUATION_BUDGET_EXHAUSTED` | 4 | Live mode only: the call budget ran out and the run stopped safely (§5). |
| `EVALUATION_INTERNAL_ERROR` | 5 | An unexpected exception (a bug), or a database failure after the run started. It is reported with its class and a redacted message (known key patterns and URL passwords are removed), and is never a PASS. An unwritable `--output` never exits 0. |

The envelope (`reasoning-evaluation-run-v1`) is key-sorted and carries no timestamps. It has these fields:

- `schema`, `runner`, `mode`
- `result` (`PASS`/`FAIL`), `code`, `exit_code`
- `failures`, `audit`, `budget`
- `report_sha256`: the sha256 of the canonical JSON
- `report`: the frozen Phase 19-A `EvaluationReport.canonical_json()`, embedded unchanged

The report's `environment` records `dataset`, `mode`, `runner` and `provider` (plus `model` in live mode).

## 4. Audit inconsistency (Phase 19-A finding L4)

Phase 19-A metrics assume a consistent audit trail. The runner checks that assumption at its own boundary and never repairs the data: no clipping, no dropped rows, no extra denominator.

- **Refusal without its call.** After each step, `store.evaluation_audit.refusals_without_call` lists refused candidates without a **succeeded** `llm_calls` row matched by `request_id`. A candidate is only ever refused after the provider answered. Any such candidate gives `kind: refusal_without_call`.
- **Impossible metric count.** The frozen `MetricCount` raises `ValueError("invalid metric count n/d")` when the numerator exceeds the denominator (for example, more refusals than answered calls in one step). The runner catches **only** that message from `observe_step` and reports `kind: invalid_metric_count`. Any other `ValueError` is a bug: it propagates and the CLI reports `EVALUATION_INTERNAL_ERROR`.

The result has code `EVALUATION_AUDIT_INCONSISTENCY` (exit 3), `report: null` and `audit: {kind, fixture_id, step_id, detail}`. The run stops at the first inconsistent step.

## 5. Optional live mode

```bash
ATLAS_REASONING_EVALUATION_LIVE=on \
ATLAS_REASONING_EVALUATION_DATABASE_URL=postgresql://…/atlas_reasoning_eval_test \
OPENROUTER_API_KEY_FILE=/run/secrets/openrouter \
  python -m atlas_reasoning evaluate run --live --max-calls 400 --max-executive-calls 0
```

Live mode is never automatic. All of the following are required, or the run refuses before any call (exit 2):

- `--live` **and** `ATLAS_REASONING_EVALUATION_LIVE=on`. A credential alone changes nothing: without the flags the run is offline.
- No CI environment: `CI`, `GITHUB_ACTIONS`, `BUILDKITE`, `GITLAB_CI`, `JENKINS_URL`, `TF_BUILD`, `CIRCLECI`, `TEAMCITY_VERSION`, `CODEBUILD_BUILD_ID`, `TRAVIS`, `BITBUCKET_BUILD_NUMBER` and `DRONE` are all refused. Neither `make` nor `.github` references live mode, and a test asserts this.
- Explicit budgets:
  - `--max-calls`: total provider requests, retries included, in 1..5000.
  - `--max-executive-calls`: requests with the `executive` purpose, in 0..5000.
- The pinned model only. `ATLAS_REASONING_MODEL` is refused even when `ATLAS_REASONING_ALLOW_MODEL_OVERRIDE=on`.
- The disposable-database guard (§2).
- The existing credential handling (`OPENROUTER_API_KEY` or `_FILE`), the existing `OpenRouterTransport` and the `ATLAS_REASONING_LLM_*` gateway settings.

How a live run behaves:

- **Data.** Only the synthetic golden dataset is sent. Contextual memory is always `FakeHoncho`, so no Honcho workspace is touched.
- **Phase 18 controls.** Each case uses its own concurrency and circuit breaker, and the gateway's retry policy applies.
- **Scripted faults.** Outages, authentication refusals and overclaims are injected locally. They never reach the provider and are not charged to the budget. A provider outage covers every gateway retry.
- **Budget.** The budget is charged per provider request, below the gateway, so no gateway view or retry escapes it. A request over budget is refused before any I/O (`LiveBudgetExhausted`, not retryable). The run then stops after the current action with `EVALUATION_BUDGET_EXHAUSTED`, no report, and the budget counters.
- **Secrets.** The key goes to the gateway for redaction only. The output carries counters, never headers or bodies.

Live results measure the model. They may FAIL thresholds, for example `validation_rejection_rate`. That is the purpose of the run, and nothing relaxes a threshold for it.

## 6. Human management-quality review

```bash
python -m atlas_reasoning evaluate review-template --run run.json > review.json   # fill in, then:
python -m atlas_reasoning evaluate review-validate review.json --run run.json       # exit 0 when complete
```

The checklist (`reasoning-management-review-v1`) has 12 items. Each is rated `meets`, `concern`, `fails` or `not_applicable`, and every rating other than `meets` needs notes.

1. Factual grounding
2. Proportionality
3. Management usefulness
4. Uncertainty and calibration
5. Unnecessary churn
6. Lifecycle correctness
7. Atlas Questions quality
8. Duplicate questions
9. HR, blame or personality language
10. Evidence traceability
11. ExecutiveBrief usefulness
12. Visibility of limitations and counter-evidence

Each item names the Phase 19-A metrics that measure part of it. The record is bound to one run's `report_sha256`.

The review is **release input only**. The runner never reads it, and it changes no metric, threshold, report or result code.

## 7. Limitations

- **One dataset** (`showcase-v1`), as in Phase 19-A. Offline metrics measure the deterministic layers with a well-behaved model. Model quality is measured only by a live run plus the human review.
- **Runtime.** An offline release run takes about 90 s on a local PostgreSQL: 20 fresh schemas, each migrated.
- **Executive budget.** No golden flow makes an `executive` call today, so `--max-executive-calls` is enforced and tested at the transport but not exercised by the cases. Any refused request, executive or not, stops the whole run.
- **Endpoint.** `OPENROUTER_BASE_URL` is honoured as in every other Reasoning V3 command (existing behaviour, unchanged here).
- **Live budget accounting.** A refused over-budget request is recorded by the gateway as a failed `llm_calls` row with the class `evaluation_budget_exhausted`. That row is on the disposable database, and the run reports no metrics.
- **Inherited from Phase 19-A, unchanged here:**
  - L1: thresholds are not runtime-pinned.
  - L3: churn would count operator-enabled direct-fact resolutions.
