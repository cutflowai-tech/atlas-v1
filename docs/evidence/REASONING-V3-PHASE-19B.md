# Reasoning V3 — Phase 19-B evidence (evaluation runner and human review)

**Scope.** Phase 19-B only: the evaluation runner, optional live mode and the human review checklist ([`REASONING-V3-EVALUATION-RUNNER.md`](../REASONING-V3-EVALUATION-RUNNER.md)). Phase 20 has not started.

**What was not done.**
- Nothing was deployed.
- No credential, access, permission, authentication, CSRF or other security setting was changed.
- No live-provider evaluation call was made. Live mode was exercised only against a local fake HTTP endpoint.
- None of the following was touched: `main`, production databases, production Reasoning V3 state, the production Honcho workspace, nginx, systemd, Docker deployment, backups, rollout, shadow mode, canary, release activation or provider configuration.

**Base.** `e73baa31fa52d84a46550ad5f914341b00f480d1` (POST_PHASE19A_INTEGRATION_SHA). The Phase 19-A reviewed head was `4354708`.

## 1. Frozen Phase 19-A interfaces are preserved

`git diff e73baa3` touches none of these:

- `evaluation.py`, `evaluation_types.py`, `evaluation_metrics.py`, `evaluation_thresholds.py`, `store/evaluation_read.py`
- the golden fixtures, `release-thresholds-v1.json` and `PUBLISHED_FIXTURE_DIGEST`
- `tests/test_reasoning_evaluation.py` (still 60 tests, all green) and `tests/reasoning_evaluation_driver.py`

There is no migration (range 0750–0799 unused) and no frozen-interface blocker was found.

Changed existing files (both additive):
- `reasoning_input_boundary.py`: `showcase_documents()` / `showcase_reasoning_input()`. This is the golden dataset, read through the only module allowed to import `atlas_commander`. A test proves it equals the test snapshot.
- `__main__.py`: the `evaluate` command. It delegates to `evaluation_cli` and injects `OpenRouterTransport`. `reason`, `provider-health` and `memory-health` are unchanged.

New files:
- `evaluation_runner.py`, `evaluation_offline_model.py`, `evaluation_live.py`, `evaluation_review.py`, `evaluation_cli.py`
- `store/evaluation_audit.py`, `store/evaluation_scenario.py`
- the two test modules and two documents

## 2. Offline release evaluation

Command: `ATLAS_REASONING_EVALUATION_DATABASE_URL=…/atlas_reasoning_eval19b_test python -m atlas_reasoning evaluate run --output run.json`, run twice. No credentials were present.

**Result.** Exit 0, `PASS`, `release_conformant=true`, coverage 1–20 with nothing missing. The two outputs are **byte-identical**. `report_sha256` is `3b8e9781d39f444b1c38940d5a03bf27ac65bacfcb4b9d36ff09b6a7ae64a44a`, with environment `{dataset: showcase-v1, mode: offline, provider: offline-model, runner: evaluation-runner-v1}`.

**Fidelity to the 19-A driver.** With the same environment, the runner's canonical report for all 20 cases is byte-identical to the Phase 19-A golden driver's (sha256 `013b0027f701a1948ffea5769d874b2ef4d8c8942928278fb458858a0a6b3dd5` for both, environment `{provider: scripted-fake}`). `ReleaseEvaluationTests.test_canonical_report_is_byte_identical_to_the_golden_driver` asserts this on every run.

The metrics are identical to the independent Phase 19-A run:

| Metric | Value |
|---|---|
| case_identity_stability | 323/323 |
| unnecessary_new_card_rate | 0/408 |
| unnecessary_field_rewrite_rate | 0/4908 |
| grounding_failure_rate | 0/147 |
| validation_rejection_rate | 0/130 |
| lifecycle_churn_rate | 0/547 |
| duplicate_question_rate | 0/545 |
| expectation_failure_rate | 0/320 |

### Runner output examples (envelope fields; `report` omitted)

```json
{"schema":"reasoning-evaluation-run-v1","runner":"evaluation-runner-v1","mode":"offline","result":"PASS","code":"PASS","exit_code":0,
 "failures":[],"audit":null,"budget":null,"report_sha256":"3b8e9781…a44a"}
```

`--case unchanged-evidence` (exit 1):

```json
{"code":"EVALUATION_FAILED","exit_code":1,"failures":["coverage: golden cases [2, 3, …, 20] not observed in full",
 "threshold: grounding_failure_rate <= 0 (value no data)", …]}
```

A non-test database (exit 2; the password is redacted):

```json
{"code":"EVALUATION_CONFIGURATION_INVALID","exit_code":2,"result":"FAIL","report":null,
 "failures":["EvaluationConfigurationError: refusing postgresql://atlas:***@127.0.0.1:54329/atlas_reasoning: an evaluation database name must contain the word 'test' …"]}
```

An audit inconsistency (exit 3; from `AuditInconsistencyTests`):

```json
{"code":"EVALUATION_AUDIT_INCONSISTENCY","exit_code":3,"result":"FAIL","report":null,"report_sha256":null,
 "audit":{"kind":"refusal_without_call","fixture_id":"unchanged-evidence","step_id":"…","detail":"1 refused candidate(s) without their provider call"}}
```

## 3. Audit-inconsistency regression proof (Phase 19-A finding L4)

| Test | Injected state | Result |
|---|---|---|
| `test_a_refusal_without_its_provider_call` | A refused candidate whose `request_id` has no `llm_calls` row | `EVALUATION_AUDIT_INCONSISTENCY`, exit 3, `kind=refusal_without_call`, `report=None`, no traceback |
| `test_more_refusals_than_answered_calls` | A refusal citing an earlier call in a step with 0 answered calls, so the frozen `MetricCount` gets 1/0 | Same code; `kind=invalid_metric_count`, detail `invalid metric count 1/0`; no clipping, no dropped row |
| `test_other_value_errors_are_not_audit_results` | Any other `ValueError` from `observe_step` | Propagates; it is not mapped to an audit result |
| `test_the_cli_reports_an_audit_inconsistency_without_a_traceback` | The same through the CLI | Exit 3, JSON on stdout, no traceback |

## 4. Gates (exact counts, at the final tree)

The environment was PostgreSQL 17 (local, disposable `atlas_reasoning_eval19b_test` / `atlas_reasoning_eval19b_driver_test`), `ATLAS_REASONING_REQUIRE_DB_TESTS=1`, with no `OPENROUTER*` / `HONCHO_API*` variables.

| Gate | Result |
|---|---|
| `ATLAS_REASONING_REQUIRE_DB_TESTS=1 make test` | **exit 0, 1665 tests** in 41 suites. Only the **3 Docker image tests** are skipped (`ATLAS_RUN_DOCKER_TESTS`). |
| `make reasoning` (inside `make test`) | **740 tests OK**: the 681 Reasoning V3 tests from 19-A plus 59 new |
| `test_reasoning_evaluation_runner` (new) | **42 OK**, including all 20 golden cases end to end and byte-equality with the driver |
| `test_reasoning_evaluation_live` (new) | **17 OK**, fake HTTP only |
| `test_reasoning_evaluation` (19-A golden evaluation, unchanged) | **60 OK** |
| Phase 18 / 17 / 15 suites | `test_reasoning_run_control` 26, `test_reasoning_reliability` 59, `test_reasoning_executive` 106, `test_reasoning_guardrails` 60: all OK |
| Migration health / replay | All OK, including `test_migration_is_clean_repeatable_and_healthy` (×2), `test_migrations_are_repeatable`, `test_a_changed_applied_migration_is_refused`, `test_concurrent_bootstraps_apply_each_migration_once`, `test_every_required_table_exists_and_health_is_ok` and `test_historical_replay`. No new migration. |
| Architecture boundaries | `ImportDirectionTests`, `IsolationTests.test_only_the_gateway_layer_knows_openrouter` and `ConfigTests.test_sql_and_the_driver_stay_inside_the_store`: OK |
| `ruff check src tests` | All checks passed |
| `mypy src` | no issues, 183 source files |
| Golden determinism | Two CLI runs byte-identical; `test_runs_are_reproducible`; byte-equality with the driver |

## 5. Adversarial self-review

An independent read-only review agent and I reviewed the full diff. Every finding below that has a fix also has a regression test.

| # | Severity | Finding | Resolution |
|---|---|---|---|
| C1 | Critical | **DB-guard bypass.** The test-name check read the URL path, but libpq lets `?dbname=` override it, so `postgresql://db/x_test?dbname=atlas_reasoning` would reset a real schema. | **Fixed.** The URL is resolved with libpq's parser, `service` is refused, and hosts and ports are compared conservatively (local addresses are equal). `test_libpq_query_parameters_cannot_redirect_the_target`. |
| M1 | Medium | Mid-run `DatabaseError`s and product misbehaviour were reported as configuration errors (exit 2). | **Fixed.** A database preflight gives 2; a database failure mid-run gives `EVALUATION_INTERNAL_ERROR` (5); a step Reasoning V3 cannot reach gives `EVALUATION_FAILED` (1, `runtime:`). Three tests. |
| M2 | Medium | A hand-built `EvaluationPlan` skipped the guard. | **Fixed.** `run_evaluation` and `observe_cases` check it themselves. `test_a_hand_built_plan_cannot_bypass_the_guard`. |
| M3 | Medium | `"test"` was a substring match, so `latest` and `contest` passed. | **Fixed.** `test` must be a word of the name. `test_test_must_be_a_word_of_the_name`. |
| L1 | Low | `ModelSetup.secrets` and `EvaluationPlan.database_url` appeared in `repr`. | **Fixed** (`repr=False`, tested). |
| L2 | Low | CLI error messages were redacted by pattern only. | **Fixed.** URL passwords are also scrubbed. |
| L3 | Low | An unwritable `--output`, or a non-object review JSON, gave a traceback. | **Fixed.** An unwritable output never exits 0, and both cases have tests. |
| L4 | Low | The audit check accepted a refusal citing a *failed* call. | **Fixed.** A **succeeded** call is required (the full golden run is still PASS, so there are no false positives). |
| L5 | Low | A missing psycopg was reported as an unparseable URL. | **Fixed.** `ImportError` is re-raised. |
| L6 | Low | The live budget was checked only between steps. | **Fixed.** It is checked after every action. |
| L8 | Low | The CI detection list was short. | **Fixed.** CircleCI, TeamCity, CodeBuild, Travis, Bitbucket and Drone were added. |
| L9 | Low | The CI-wiring scan missed `*.yaml`. | **Fixed.** |
| L7 | Low | No golden flow makes an `executive` call. | Documented. The executive budget is enforced and unit-tested at the transport. |
| L10 | Low | Nits: JSON encoding differed between paths, `report_sha256` was not checked as hex, a review could be bound to a FAIL run. | Encoding made uniform; the rest are accepted (the review is release input only). |
| G1 | High (found by the gate) | `evaluation_live` imported `openrouter_client`, though only `__main__` may wire it, and the runner contained SQL and psycopg outside `store/`. Two existing architecture tests failed. | **Fixed in my code, tests unchanged.** The transport factory is injected by `__main__`, and the SQL moved to `store/evaluation_scenario.py`. Tested. |

## 6. Limitations

- One dataset (`showcase-v1`). Offline metrics measure the deterministic layers with a well-behaved model. Model quality needs an explicit operator live run plus the human review, and neither is part of this phase's evidence.
- An offline release run takes about 90 s, and the new test modules add about 4 minutes to `make reasoning` (two full 20-case runs: the runner and the driver).
- `test_no_network_is_used` proves no Python-level socket or OpenRouter HTTP call is made. The database uses libpq, which is out of its scope.
- 19-A L1 (thresholds are not runtime-pinned) and L3 (churn would count direct-fact resolutions) are inherited and unchanged. L2 (doc counts) belongs to the 19-A docs, which this phase does not edit.
