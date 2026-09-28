# METRICS-FIXTURE evidence

Implemented pure `derive_speed`, `derive_deadline`, and `derive_quality` in
`src/atlas_commander/metrics.py`; contract tests are in `tests/test_metrics.py`.

## Rules and observed outputs

- Fixture cycle: Editor `editor-42`, canonical Video Type `short-form`, In Progress
  09:00Z to Ready For Approval 11:00Z gives 7200 seconds.
- Supplied same-type cohort durations 7000 and 8000 yield 7500 seconds; adding
  9000 yields 8000. Different canonical types contribute neither values nor
  evidence. An empty matching cohort yields null, without global fallback.
- Cohort durations 1 and 2 raise `MetricInputError`: the integer contract cannot
  represent 1.5. Fractional timestamp durations are also rejected, not truncated.
- Deadline uses Ready For Approval versus Requested ETA: 11:00Z equality is
  on_time, ETA 10:59:59Z is late, and 13:00+02:00 equality is on_time.
  A null ETA returns no metric.
- Quality maps the Monday Performance Label through explicit board/column-scoped,
  approved versioned configuration. Unknown labels and unapproved mappings fail.
  Revision counts 0 and 999 and null context leave the label unchanged.
- Source evidence must be Monday, match the subject board/item, and contain the
  required cycle event IDs for speed/deadline. Deadline source values must match
  the supplied cycle. Every output is validated against its frozen schema.
- Speed evidence embeds the target cycle and sorted contributing cycles with
  their complete validated source evidence under source_values.speed_derivation.
  Quality evidence retains the raw label and the mapping version/result.
- Tests verify no mutation or shared mutable output, deterministic cohort order,
  duplicate cohort rejection, unsupported medians, and invalid evidence rejection.

## Assumptions and API boundary

Canonical Editor/Video Type resolution and Monday ingestion are upstream.
Inputs are cycle dictionaries and common-contract evidence dictionaries. Evidence
rule_version and calculated_at are supplied by the caller; no clock, network,
AI inference, or implicit mapping is used. The caller is responsible for source
provenance authenticity and mapping approval authority; approved=True is explicit
configuration, not an authorization system.

The caller supplies the benchmark population as (cycle, evidence) pairs. The
target participates only if explicitly included. Duplicate board/item/cycle
identities are rejected. Invalid cycles fail rather than being silently omitted.
QualityMapping.labels maps exact Monday raw labels to approved display labels;
no fuzzy matching or inferred labels are supported. Quality absence/unsupported
configuration raises an error, while missing ETA intentionally returns None.

## Validation and contract impact

- Focused unittest discovery for test_metrics.py: 14 tests passed.
- make test: passed (ruff, mypy, 11 unit, 6 contract, 2 integration, 2 E2E tests,
  and JSON syntax checks). Initial lint findings were fixed before the passing run.
- The existing Makefile names individual suites, so the new metric suite is run
  separately; no unrelated build changes were made.
- No frozen contracts, DAG, existing fixtures, or unrelated modules changed.
  Cohort/mapping detail uses the existing unrestricted source_values object.
- This is an independent fixture candidate for arbitration; no integration,
  merge, main push, service, or live Monday access was performed.

## Commit handoff

The user authorized the cutflowai-tech GitHub account. Its authenticated account
ID is 327503789; the task-local Git identity is cutflowai-tech with GitHub noreply
address 327503789+cutflowai-tech@users.noreply.github.com. Global identity is unchanged.
The prior attached candidate was restored into this run's isolated worktree.
The 14 metric tests and make test were rerun successfully before committing.
