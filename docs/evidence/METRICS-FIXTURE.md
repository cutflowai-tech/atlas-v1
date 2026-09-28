# METRICS-FIXTURE — builder-2

Implemented deterministic `derive_speed`, `derive_deadline`, and `derive_quality`
in `src/atlas_commander/metrics.py`, with contract assertions on every emitted
metric. Inputs and outputs do not share mutable dictionaries. No clock, network,
AI inference, or service is used; local frozen schemas validate inputs/outputs.

## API assumptions

- Inputs are canonical WorkCycle dictionaries and common-schema Monday evidence.
  Upstream normalization owns canonical Editor/Video Type IDs and source field
  extraction. These functions do not infer aliases or resolve editor identities.
- Source evidence must match the subject board/item. The caller supplies truthful
  Monday source values, event IDs, timestamps, and deterministic `calculated_at`.
  The module validates evidence shape/source/ownership; it does not independently
  fetch or authenticate Monday records.
- Speed accepts an explicit iterable of `(cycle, evidence)` cohort pairs. Caller
  chooses the cohort window and whether the subject belongs in it. Only exact
  matching Video Type IDs contribute; duplicate matching cycle identities fail.
  Different editor IDs may contribute to the same Video Type cohort.
- Quality requires `QualityMapping(board, column, version, labels, approved)`.
  The caller is responsible for approval authority and supplying the approved
  Monday Performance Label column. `labels` maps exact source label IDs/values
  to approved display text; evidence `source_values[column_id]` supplies the raw
  value. No label, column, board, approval, or version is guessed. Unknown or
  missing labels raise `MetricInputError` rather than producing inferred quality.
- WorkCycle duration must exactly match the positive status interval, including
  microseconds. Missing ETA remains valid for speed/quality and yields no deadline
  metric. Revisions are copied as display context and never modify the label.

## Metric output evidence

Tests use the repository's good WorkCycle and metric evidence fixtures, with
explicit deterministic cohort variants:

| Case | Observed result |
| --- | --- |
| Short-form durations 7200 and 7800; long-form duration 1 | Median 7500; long-form excluded |
| Empty or exclusively different/case-different Video Type cohort | Null benchmark; no global fallback |
| Durations 1 and 2 | Explicit unsupported fractional-median error; no rounding |
| Ready 11:00Z; ETA 11:00Z or 13:00+02:00 | on_time |
| Ready 11:00Z; ETA 10:59:59Z | late |
| Missing ETA, even with unrelated due-date evidence | No deadline metric |
| Approved Meets Expectations; revision count 0 or 999 | Meets Expectations in both cases |
| Unapproved/unversioned/wrong-board mapping or unmapped label | Explicit input error |

Each metric's `evidence.source_values.subject` retains the full input work cycle
and original source evidence. Speed also includes sorted contributing cohort
cycles and their complete source evidence, preserving board/item IDs, columns,
events, timestamps, source values, and original rule versions. Quality records
the approved mapping version, source label, column, board, and selected display
label. Output rule versions are speed-v1, deadline-v1, and quality-v1; calculation
timestamps come from supplied evidence. Reversed cohort input order yields the
same output.

## Validation

- `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_metrics.py' -v`:
  **14 tests passed**. Tests validate outputs against frozen schemas, check
  acceptance boundaries, evidence inclusion, invalid inputs, determinism, and
  input/output mutation isolation.
- `make test`: **passed** (ruff, mypy, 11 commander tests, 6 contract tests,
  2 integration tests, 2 E2E tests, JSON syntax checks).
- Initial `make test` identified an import-location lint issue; fixed before the
  successful run.
- Existing Makefile enumerates legacy test modules, so the new metric suite is
  run explicitly in addition to `make test`; no unrelated build edits made.

## Contract impact

No contracts, DAG, fixtures, or unrelated modules changed. Output schemas stay
at 1.0.0. Detailed derivation provenance uses the existing open `source_values`
object. Fractional cohort medians cannot be represented by the frozen integer
contract and are explicitly rejected with `MetricInputError`. No schema extension
or lossy rounding is introduced.
