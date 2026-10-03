# Reasoning V3 — Evaluation Harness (Phase 19-A)

`REV/19`: show that Reasoning V3 is grounded, stable, update-oriented and resistant to unnecessary churn. Phase 19-A owns the
evaluation **foundation**: the data model, the golden cases and their structural expectations, the stability metrics, the
machine-readable report and the release-threshold mechanism. Phase 19-B builds the runner on top of it: the optional live-model
command, repeated-run measurements and the human management-review checklist (`REV/19` #6 and #8). Phase 19-B must not change the
meaning of anything frozen here.

Base: Phase 18 integration `4e419f40265ca86a6c5cf3bf1ca6939003837cfc`.

Phase 19-A changes no reasoning behaviour. It adds **no migration** and no table. It does not modify the engine, the Phase 18
orchestration, budgets, breaker, retries or run-status policy, the Phase 15 guardrails, case identity, the result contracts, the
executive synthesis or any UI. Evaluation reads canonical rows and Phase 18 telemetry and writes nothing.

## 1. Modules

| Module | Role |
|---|---|
| `src/atlas_reasoning/evaluation_types.py` | Frozen data model and closed vocabulary (scenario ops, evidence variants, faults, facts). |
| `src/atlas_reasoning/evaluation.py` | Golden-case parsing and validation, `capture`, `observe_step`, `check_case`, `evaluate`. |
| `src/atlas_reasoning/evaluation_metrics.py` | Metric definitions (`METRICS`) and their only implementation (pure functions of two states). |
| `src/atlas_reasoning/evaluation_thresholds.py` | Threshold file loading and validation, and exact evaluation. |
| `src/atlas_reasoning/store/evaluation_read.py` | Read-only SQL for `capture` (one `REPEATABLE READ READ ONLY` transaction). |
| `src/atlas_reasoning/evaluation_golden/case-*.json` | The 20 golden cases (`reasoning-golden-case-v1`). |
| `src/atlas_reasoning/evaluation_golden/release-thresholds-v1.json` | Release thresholds v1 (`reasoning-release-thresholds-v1`). |
| `tests/reasoning_evaluation_driver.py` | Test support: executes golden cases with an offline model (not a product runner). |
| `tests/test_reasoning_evaluation.py` | Phase 19-A tests (unit and golden suite). |

## 2. Frozen interfaces (for Phase 19-B)

Names, fields and meanings below do not change within `reasoning-evaluation-v1`. A change requires a new schema version.

```python
from atlas_reasoning.evaluation import load_golden_cases, capture, observe_step, check_case, evaluate
from atlas_reasoning.evaluation_thresholds import release_thresholds

cases = load_golden_cases()                         # tuple[EvaluationCase], validated, ordered by number
before = capture(store)                             # CanonicalState: content-free, read only
passes = [...]                                      # the step's RunOrchestrator PassReports, in order
after = capture(store)
step = observe_step(case, before, after, step_id="...", passes=passes,
                    telemetry=reliability_report(store, step_run_ids),   # Phase 18-C
                    controls=runtime.controls)                         # Phase 18-B (breaker state)
report = evaluate(cases, [EvaluationObservation(case.fixture_id, (step, ...)), ...],
                  thresholds=release_thresholds(), environment={"provider": "..."}, metadata={...})
report.passed; report.canonical_json(); report.to_json()
```

| Type | Meaning |
|---|---|
| `EvaluationCase` | One golden case: `fixture_id`, `number` (1–20), `title`, `requirement`, `category`, `focus` (identity key), `runtime`, `metric_exclusions`, `steps`. |
| `Step` / `Action` | Ordered declarative actions. A step with `expect` is **evaluated**; a step without it is setup (executed, never checked or measured). |
| `ExpectedOutcome` | Fact name → expectation. An expectation is an exact value, an int range `{"min", "max"}`, or a list `{"includes", "excludes"}`. |
| `CanonicalState` | PostgreSQL at one instant. It holds identifiers (only for diffing), statuses, counts, field **hashes** and grounding codes. It never holds text. |
| `StepObservation` | `facts` (every name of `FACTS`) and `counts` (`MetricCount` per step metric) of one evaluated step. |
| `EvaluationObservation` | Every evaluated step of one golden case. |
| `CheckResult` | One expectation compared with its observation. |
| `MetricCount` / `EvaluationMetric` | Exact numerator / denominator. The value is a `Fraction`, or `None` when the denominator is 0. |
| `Threshold` / `ThresholdSet` / `ThresholdResult` | Versioned bounds (decimal strings parsed exactly) and their exact result. |
| `EvaluationReport` | The report. `canonical_json()` excludes only `metadata`. |

**Scenario vocabulary** (closed; a runner implements every term exactly as `evaluation_types` documents it):
`gate {evidence}`, `orchestrate {budget?, max_attempts?}`, `orchestrate_while_busy`, `resume {budget?, max_attempts?}`,
`fault {kind, target, count?}`, `human {kind}`, `claim {target}`, `age_claims {seconds}`, `advance_clock {seconds}`.

Evidence variants:

- `showcase`
- `non_material`: same evidence, new snapshot ID, renamed finding IDs
- `material_change` and `material_change_2`: the focus Editor's current late rate moves
- `focus_removed`
- `new_topic`
- `without_contradiction`

Faults:

- `provider_outage`
- `provider_auth`
- `overclaim`
- `memory_outage` and `memory_restore`

Human context: `note`, `answer`, `teaching`, `expired_teaching`.

Runtime keys: `breaker_threshold`, `breaker_cooldown_seconds`, `gateway_concurrency`, `validation_retries`.

**What is observed.** Only canonical outputs and Phase 18 interfaces:

- PostgreSQL rows, through `capture`
- `RunOrchestrator` `PassReport`s (status, reasons, admitted, deferred, retries, recovered, calls used, skipped, executive readiness)
- the 18-C `reliability_report`: refusals before a call, corrective re-asks, interrupted passes, retries, skipped unchanged cases
- `ProviderControls.snapshot()`: the breaker state

The harness never decides a run status. It never prioritises, budgets, retries or resumes. It records what Reasoning V3 did.

## 3. Golden cases

All cases run on the synthetic showcase dataset (`showcase-v1`: 17 cases). Every expectation is structural: same `case_id`, card kept
or created, content versions, change kinds, lifecycle state, model calls, work remaining, run status and reasons, question counts,
validation refusals, memory status, injected context source types, breaker state and duplicate count. No expectation names model text,
and the harness has no field for hidden reasoning.

| # | fixture_id | Covers | Key structural expectations |
|---|---|---|---|
| 1 | `unchanged-evidence` | unchanged; non-material change | 0 calls, 17 unchanged, card kept, 0 content versions, lifecycle active |
| 2 | `updated-material-evidence` | updated material evidence (twice) | gate `updated`, card kept, exactly 1 patch, lifecycle `updated`, 1 call |
| 3 | `new-case` | new case | 1 new card, existing cards untouched, lifecycle `new` |
| 4 | `disappeared-case` | disappeared, then back | `cooling` without a call; returns `active` on the same card, 0 calls |
| 5 | `contradiction-added` | contradiction added | gate `updated`, 1 contradicting finding, same card patched |
| 6 | `contradiction-removed` | contradiction removed | 0 contradicting findings, same card patched |
| 7 | `insufficient-evidence` | weak evidence / confidence ceiling | an overclaiming answer is refused (1 refusal, 1 corrective re-ask); the card is published at `weak` |
| 8 | `manager-note-added` | manager note | 0 calls on the same evidence; the next update injects `manager_interpretation` |
| 9 | `manager-answer-added` | manager answer | its question closes (0 open); the next update injects `manager_answer` |
| 10 | `teaching-added` | teaching added | 0 calls on the same evidence; the next update injects `management_teaching` |
| 11 | `teaching-expired` | teaching expired | an expired teaching is never injected; a valid one is |
| 12 | `memory-unavailable` | memory unavailable | run `degraded` / `memory_degraded`, cards still created, memory status `degraded` |
| 13 | `provider-failure` | provider failure | run `partial` / `resumable_failures`, card kept unchanged; resume patches it exactly once |
| 14 | `partial-run` | partial run | budget 3: `partial` / `work_deferred`, 3 calls, 14 open, executive not ready |
| 15 | `degraded-run` | degraded run | one auth failure isolated: `degraded` / `unresolved_failures`, 16 cards; resume does not retry |
| 16 | `resume-after-interruption` | resume after an interrupted claim | a young claim is not taken over (`partial`); a stale one is recovered once (`complete`) |
| 17 | `budget-exhaustion-then-resume` | budget exhaustion, then resume | `partial`, then `complete` with 14 more calls; earlier cards untouched; an idle resume costs 0 |
| 18 | `circuit-breaker-outage` | breaker / provider outage | `failed` / `provider_outage`, breaker `open`, 16 refused before a call; after cooldown it is `closed`, with 16 retries |
| 19 | `duplicate-work-prevention` | duplicate-work prevention | busy engine is skipped (`engine_busy`); repeated passes admit 0; 0 duplicates |
| 20 | `zero-call-unchanged` | zero-call unchanged processing | 0 calls charged, 0 admitted, 17 skipped as unchanged (telemetry), `complete` |

The exact expectations are in the JSON files. The golden suite checks 321 structural expectations across 30 evaluated steps.

## 4. Metrics

Every metric is counted per evaluated step from the canonical state before and after the step. It is summed over the suite as one
exact fraction, never as an average of averages. Setup steps are never measured. A case that lists a metric in
`metric_exclusions` does not contribute to that metric, and each exclusion needs a written reason. A zero denominator means
**no data**: the value is `null`, never 0 and never 1, and the release threshold fails.

### Case identity stability (`case_identity_stability`, higher is better)

- **Numerator:** Change Gate observations of the step whose identity key was known before the step, that resolved to the same
  `case_id`, and that were not **split**. A split is a known case that disappeared while a never-seen case about the same subject and
  topic (`subject_type|subject_id|topic_key`) appeared in the same step.
- **Denominator:** Change Gate observations of the step whose identity key was known before the step.
- **Exclusions:** cases first seen in the step.
- **Why splits:** `case_id` is a hash of the unique identity key, so a key always maps to the same `case_id`. A lost identity therefore
  shows up as a split: the old case disappears and a new one appears. `focus.case_id_stable` uses the same rule.

### Unnecessary new-card rate (`unnecessary_new_card_rate`)

- **Numerator:** cases in the denominator for which the step created a `result_id` that did not exist before.
- **Denominator:** cases that had a reusable (not superseded) card before the step and are present after it.
- **Exclusions:** new cases, absent cases, and cases whose only earlier cards were superseded.

### Unnecessary field rewrite rate (`unnecessary_field_rewrite_rate`)

- **Numerator:** patchable fields whose value changed across the step although the card's evidence fingerprint did not change, or
  that an accepted update changed without declaring them in `changed_fields`. Fields are compared by sha256 hash, never by text.
- **Denominator:** 12 patchable fields × every card that existed before the step.
- **Exclusions:** cards created in the step.

### Grounding failure rate (`grounding_failure_rate`)

- **Numerator:** committed `created` or `patched` versions of the step for which the Phase 15 validator reports a grounding code.
  The validator is re-run on the stored version and the case document it was reasoned on. For a patch, the case is rebuilt exactly as
  `ReasoningEngine._update_case` builds it: the work item's case document, the previous result, and the material delta from the
  previous version's evidence to the patched version's. So a patch that quotes the value it moved from, which exists only in the
  delta, is graded as it was at call time.
  The grounding codes are `UNKNOWN_EVIDENCE`, `WRONG_EVIDENCE_ROLE`, `COUNTER_EVIDENCE_MISSING`, `NO_SUPPORTING_EVIDENCE`,
  `UNSUPPORTED_NUMBER`, `UNSUPPORTED_METRIC`, `CAUSAL_OVERCLAIM` and `CONFIDENCE_EXCEEDED`. A version without its case document
  counts as a failure (`NO_CASE_DOCUMENT`).
- **Denominator:** `created` and `patched` versions committed in the step.
- **Exclusions:** `no_change_review` and `lifecycle` versions, which copy content. Entity codes and human-context codes are also
  excluded: their vocabulary includes the call's human context, which is not stored with the case. They are checked at call time
  and counted by the validation rejection rate.

### Validation rejection rate (`validation_rejection_rate`)

- **Numerator:** candidates refused in the step by the Phase 15 guardrails or by the optional reviewer
  (`reasoning_failed_candidates` rows).
- **Denominator:** `analyst` and `update` calls of the step that returned an answer (succeeded `llm_calls`). Every such answer is
  validated.
- **Exclusions:** failed calls, executive calls and reviewer calls. `insufficient-evidence` is excluded because it injects an
  overclaiming answer on purpose.

### Lifecycle churn rate (`lifecycle_churn_rate`)

- **Numerator:** cards that did any of the following in the step:
  - returned to a state already left, within a run of lifecycle-only moves (a flip-flop). A `created` or `patched` version starts
    a new run;
  - moved to `cooling` or `resolved` while their case was present;
  - when the card moved or its case's presence changed in the step: ended the step as `new`, `active` or `updated` while their case
    was absent, or as `cooling` while their case was present. This way a persistent state is counted in the step that could cause it,
    not again in every later step.
- **Denominator:** cards that exist after the step.
- **Exclusions:** superseded cards. A move made by a `created` or `patched` version is justified by its content change, so
  `updated → active` (settle) followed by `→ updated` (a new patch) is not churn.

### Duplicate-question rate (`duplicate_question_rate`)

- **Numerator:** open Atlas questions that duplicate another open question of the same case (same dedup key), plus questions
  opened in the step that repeat an answered or dismissed question of the same case. Each question counts at most once.
- **Denominator:** open Atlas questions after the step.
- **Exclusions:** superseded questions.

### Structural expectation failure rate (`expectation_failure_rate`)

- **Numerator:** structural expectations of the golden cases that were not met.
- **Denominator:** structural expectations evaluated.
- **Exclusions:** never excluded per case.

`integrity.duplicates` is an observed fact, not a rate. It counts:

- more than one open card per case
- a gap in a card's version sequence
- more than one open LLM work item per case
- more than one open question per case and dedup key
- more than one synced memory copy of the same content in the same session

## 5. Release thresholds

Thresholds are stored in `evaluation_golden/release-thresholds-v1.json` (schema `reasoning-release-thresholds-v1`, version
`release-thresholds-v1`). Bounds are decimal strings, parsed as exact fractions. A value equal to its bound passes.

| Metric | Bound | On no data |
|---|---|---|
| `case_identity_stability` | ≥ 1 | fail |
| `unnecessary_new_card_rate` | ≤ 0 | fail |
| `unnecessary_field_rewrite_rate` | ≤ 0 | fail |
| `grounding_failure_rate` | ≤ 0 | fail |
| `validation_rejection_rate` | ≤ 0.05 | fail |
| `lifecycle_churn_rate` | ≤ 0 | fail |
| `duplicate_question_rate` | ≤ 0 | fail |
| `expectation_failure_rate` | ≤ 0 | fail |

Each threshold carries its rationale in the file. Every metric must have exactly one threshold, so a metric cannot silently stop
gating a release.

**Integrity rules.**

- A changed bound or rule is a **new version** with a written rationale. An existing version is never edited.
- A threshold is never lowered because the current implementation fails it. A legitimate failure is a valid Phase 19 result: the
  report says FAIL, and the release stays blocked until the product is fixed in its own phase.
- `validation_rejection_rate ≤ 0.05` is the only non-zero bound. A refused candidate is safe, because it is never committed. Even
  so, more than 1 refusal in 20 answers means the prompt or model does not fit the contract.

**Overall result.** PASS requires all of the following:

1. **Release conformance** (`release_conformance`): the golden cases are the published set (same `fixture_digest`), the thresholds
   are the published `release-thresholds-v1`, and the required coverage is cases 1–20. An edited fixture, a laxer threshold set or a
   narrowed coverage can only produce FAIL. Release threshold files must fail on no data.
2. Every required golden case (1–20) was observed in full.
3. Every release threshold passes, including `expectation_failure_rate ≤ 0`, so every structural expectation is met.

Final release approval still needs the combined Phase 19 evaluation after Phase 19-B (including the live-model run).

## 6. Report

`EvaluationReport.to_json()` and `canonical_json()` contain:

- `schema`
- `result` (PASS/FAIL)
- `failures`: coverage gaps, failed thresholds with exact `numerator/denominator`, failed expectations
- `versions`: evaluation and golden schema, reasoning package and contract, identity, fingerprint, change gate, engine, prompts,
  guardrails, lifecycle policy, run control, reliability metrics, pinned model
- `environment`
- `fixtures`
- `observations`
- `checks`
- `metrics`
- `thresholds`
- `threshold_results`
- `coverage`, including the sha256 `fixture_digest` of the golden cases

`canonical_json()` excludes only `metadata` (timestamps, host, notes). The same inputs give a byte-identical canonical report.
Facts never carry identifiers, timestamps or model text.

## 7. Offline golden suite

`make reasoning` (`tests/test_reasoning_evaluation.py`) runs all 20 golden cases on PostgreSQL. It uses the real Change Gate,
engine, guardrails and Phase 18 orchestration, with `ScriptedAnalyst` and `FakeHoncho`. It needs no network and no OpenRouter or
Honcho key.

The driver's offline model (`GoldenModel`) answers updates by changing exactly the fields the updater requires
(`fields_requiring_change`), and otherwise changes only the confidence rationale. The shared test fake's default update answer
reads a stale key (`fields_citing_removed_evidence`) and repeats a confidence patch. The Phase 15 guardrails correctly refuse that
answer (`UNCHANGED_PATCH_VALUE`, `REQUIRED_CHANGE_MISSING`). The golden driver does not use it. The product is unchanged.

Result on the offline model at the Phase 18 base: **PASS**.

| Metric | Value |
|---|---|
| Identity | 323/323 |
| New cards | 0/408 |
| Rewrites | 0/4908 |
| Grounding | 0/147 |
| Validation rejection | 0/130 |
| Lifecycle churn | 0/547 |
| Duplicate questions | 0/545 |
| Expectations | 0/321 failed |

These numbers measure the harness and the deterministic layers with a well-behaved offline model. They say nothing about the live
model's reasoning quality, which is Phase 19-B's live run.

## 8. Known limitations

- **The grounding re-check does not cover entities or human-context attribution.** Names that came from the call's human context
  are not stored with the case, so re-checking them later would flag them falsely. Entity and attribution refusals at call time are
  counted by the validation rejection rate.
- **There is one dataset (`showcase-v1`).** Counts such as "17 unchanged" are specific to it.
- **Duplicate-work prevention is observed deterministically.** The golden case uses a held engine lock, and repeated passes on the
  same run. Real thread races are covered by `tests/test_reasoning_run_control.py`. A race inside a golden case would make its report
  non-reproducible.
- **`telemetry.*` facts are cumulative over the step's runs.** For a resume step, that includes the run's earlier passes.
- **Split detection matches on subject and topic.** A split that changes the subject ID or topic itself is not detected, and a
  legitimate change of an identity dimension (for example `signal=`) within one step would count as a split. The showcase variants
  trigger neither.
- **Release conformance pins the golden set.** `PUBLISHED_FIXTURE_DIGEST` (in `evaluation.py`) and `release-thresholds-v1` are what
  a release result is compared with. Changing a golden case means changing the digest constant in review, with the reason.
- **Some terms are defence in depth.** A partial unique index already makes a second open copy of a question impossible, so the
  "second open copy" term of `duplicate_question_rate` and the open-question term of `integrity.duplicates` can only become
  non-zero if that constraint is removed. The term that carries real signal is "re-asks an answered or dismissed question".
- **Some offline metrics are 0 by construction.** On the offline model, `validation_rejection_rate` is 0 because the only refusing
  case is excluded and the well-behaved fake model is never refused. The metric is meant for the live run.
- **A broken audit trail aborts the evaluation.** If a refusal row exists without its call row, the numerator would exceed the
  denominator, and `MetricCount` raises an error instead of reporting a value.
- **Expectations avoid choices the model is free to make.** The number of questions a card asks, and whether a material change is
  answered with a patch or a `no_change_review`, are left open. Instead the cases assert `focus.questions_opened`,
  `focus.reasked_answered`, content versions and `excludes: ["created"]`. Exact patches are asserted only where the updater
  requires a change (cases 5 and 6, where a contradiction is added or removed).
- **Review findings fixed before the Draft PR:**

  | Finding | Fix |
  |---|---|
  | H1 | identity splits |
  | H2 | patch re-graded with its material delta |
  | M1 | release conformance |
  | M2 | model-independent expectations |
  | L1 | a repeated step observation is refused |
  | L2 | vacuous expectations are refused |
  | L3 | gate observations ordered by time |
  | L5 | the driver's overclaim answer also covers update calls |
  | L7 | churn end-state terms and flip-flop runs |
  | L8 | byte-identical canonical report |
