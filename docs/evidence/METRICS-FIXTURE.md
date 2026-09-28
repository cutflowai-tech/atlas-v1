# METRICS-FIXTURE evidence (builder-3)

Task: implement deterministic speed / deadline / quality metrics against fixtures.
Mode: fixture. Risk: critical. Contract owner gate: approved.

## Deliverables

- `src/atlas_commander/metrics.py`: pure derivation functions (no clock, no I/O beyond contract schema loading, no AI).
  - `derive_speed_metrics(sources, calculated_at)`
  - `derive_deadline_metric(source, calculated_at)` / `derive_deadline_metrics(sources, calculated_at)`
  - `derive_quality_metric(source, observation, mapping, calculated_at)`
  - Inputs: `CycleSource` (contract-valid WorkCycle + Monday status / video type / requested ETA column IDs), `PerformanceLabelObservation`, `QualityLabelMapping` (explicit version, label column, `approved` flag, value map).
  - Refusals raise `MetricError` with a stable `code`.
- `tests/test_metrics.py`: 19 metric contract tests.
- `Makefile`: new `metrics` target, added to `test` so `make test` runs the metric suite.

## Acceptance tests → tests

| Acceptance test | Tests |
| --- | --- |
| same Video Type speed cohort | `test_same_video_type_speed_cohort`, `test_video_type_is_not_normalized_or_globally_pooled`, `test_fractional_median_is_not_rounded`, `test_even_cohort_with_integer_median`, `test_deterministic_regardless_of_input_order` |
| deadline compares Ready For Approval with Requested ETA | `test_deadline_compares_ready_for_approval_with_requested_eta`, `test_late_when_ready_after_eta`, `test_equality_is_on_time`, `test_equality_across_offsets_is_on_time`, `test_missing_requested_eta_yields_no_metric` |
| quality label only | `test_quality_label_only`, `test_mapping_translates_monday_label_value`, `test_unapproved_or_unknown_labels_rejected`, `test_missing_label_yields_no_metric` |
| revisions neutral | `test_revisions_neutral`, `test_revision_context_is_copied_not_shared` |

Every derived metric is checked with `contracts.validate` (schema + semantic codes) inside the tests, and `assert_valid` inside the module before it is returned.

## Test results

- `make metrics`: `Ran 19 tests ... OK`
- `make test` (ruff, mypy, unit 11, contract 6, metrics 19, integration 2, e2e 2, JSON well-formedness): exit 0.

Python 3.13.5 locally.

## Rules as implemented

- **Duration**: taken from the WorkCycle (`In Progress` → `Ready For Approval`), which must pass the work-cycle schema and the `END_BEFORE_START` / `DURATION_MISMATCH` semantic checks.
- **Speed cohort**: grouped by the exact `video_type` string (the canonical value is taken as given, with no case folding or aliasing). There is no global or cross-type fallback, so `cohort_video_type == video_type` always holds. `source_values.cohort_sources` lists every contributing cycle (cycle, editor, board, item, both event IDs, duration), sorted by `cycle_id`.
- **Fractional median**: an even cohort whose median is `x.5` cannot be stored in the integer `cohort_median_seconds`. It is **not rounded**. The field is `null` (allowed by the contract), `cohort_median_status = "unsupported_fractional"`, and the exact decimal is kept as a string in `cohort_median_exact`. Integer medians report `exact_integer`.
- **Deadline**: `on_time` iff `ready_for_approval_at <= requested_eta`, compared as timezone-aware instants, so equality counts as on time. A null Requested ETA returns `None` (no metric, no fallback). A null ETA does not block speed or quality.
- **Quality**: the value comes only from a Monday Performance Label observation. That observation must be on the mapping's label column and the same board/item as the cycle. The mapping must be approved and versioned, and the label must be in it. Any other label raises `UNSUPPORTED_PERFORMANCE_LABEL`. An absent or empty label returns `None`.
- **Revisions**: `revision_context` is copied (as a new dict) into the quality metric for display only. Speed, deadline and quality values stay the same whether revisions are absent, null, or heavy.
- **Editor**: `editor_id` is always the WorkCycle's canonical editor ID.
- **Determinism**: outputs are sorted by `cycle_id`, `calculated_at` is supplied by the caller, and rule versions are `speed-v1`, `deadline-v1` and `quality-v1` (matching the fixtures).

## Assumptions

1. "Source evidence" for a cycle means the Monday column IDs of the status, Video Type and Requested ETA columns. Event IDs and timestamps already come from the WorkCycle.
2. A cohort includes the evaluated cycle itself and has no minimum size, because none is declared in V1. A single-cycle cohort's median is its own duration.
3. Speed evidence `event_ids` hold only the evaluated cycle's own events, as in the fixture. Cohort events are cited in `source_values.cohort_sources`.
4. `MISSING_REQUESTED_ETA` is tolerated as a WorkCycle semantic code, since it only suppresses the deadline metric. Every other semantic code rejects the cycle.
5. A quality mapping maps raw Monday label values to approved performance labels. An identity mapping reproduces every top-level field of `fixtures/good/quality-metric.json`. Its evidence adds `cycle_id` to `source_values`.

## Contract impact

None. No contract, schema, fixture or DAG file was modified. Outputs conform to `speed-metric`, `deadline-metric` and `quality-metric` 1.0.0 and `common.schema.json#/$defs/evidence`. The fractional-median case uses the contract's existing nullable `cohort_median_seconds`, and the reason is recorded in evidence `source_values` (an open object in the contract).
