# METRICS-FIXTURE candidate evidence

Implemented `src/atlas_commander/metrics.py` with pure `derive_speed`,
`derive_deadline`, and `derive_quality` functions. No services, AI inputs,
clock reads, network calls, or schema changes are involved.

## Inputs and assumptions

- Inputs are contract-valid work cycles and common-schema source evidence from
  trusted Monday normalization. Canonical editor, Video Type, event, column,
  board, item, and label IDs are supplied upstream; display-name resolution is
  outside this task. Full schema validation remains at the input boundary.
- Source evidence carries the caller's deterministic `calculated_at`; derivation
  checks Monday origin, board/item association, nonempty evidence, and the
  required status event references. It preserves original source values.
- `CycleSource` pairs each cohort cycle with its evidence. Cohort membership is
  explicitly supplied, with exact canonical Video Type equality. The target is
  included only when explicitly supplied. Repeated cycle IDs are rejected.
- `QualityMapping` is explicit caller-supplied approval for a board's Performance
  Label column, including mapping version and canonical label-ID-to-value map.
  The observed ID is read only from `evidence.source_values[column_id]`.
  Unknown labels, missing columns, wrong boards, and unapproved/unversioned
  mappings raise `ValueError`; no quality is inferred from revision counts.

## Metric evidence and observed outputs

- Fixture target duration: 7,200 seconds, from In Progress to Ready For Approval.
  Same-type cohort durations 7,000 and 8,000 produce median 7,500. A different
  type's 90,000 seconds is excluded. Odd cohort [1, 8, 99] produces median 8.
- No same-type cohort produces null median, with no global fallback. Speed
  evidence includes the target cycle and every contributing cycle with its full
  Monday evidence under `source_values.cohort`, sorted by cycle ID. Reordering
  cohort inputs produces identical output.
- Cohort [7,200, 7,201] raises `UnsupportedMetricValue`, since 7,200.5 cannot be
  represented by the frozen integer median contract. Fractional durations also
  fail explicitly; inconsistent duration/status boundaries are rejected.
- Ready For Approval at 11:00Z is on time against 11:30Z, 11:00Z, and
  13:00+02:00; against 10:59:59Z it is late. Missing ETA returns `None`.
  Deadline evidence includes the exact cycle timestamps used for comparison.
- Approved `label-1` maps to `Meets Expectations` at version `quality-label-v1`.
  Revision context null or count 1,000 leaves the label and all other quality
  fields unchanged. Quality evidence records the source ID and approved mapping
  entry/version. No score or revision penalty is introduced.
- Returned metrics are validated against the named frozen contracts in tests.
  Inputs are not mutated and returned nested evidence is copied.

## Validation

- `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_metrics.py' -v`:
  **PASS, 9 tests**.
- `make test`: **PASS**, Ruff, mypy, 11 commander tests, 6 contract tests,
  2 integration tests, 2 E2E tests, and JSON validation.
- Initial lint run found an import-style issue; corrected to `collections.abc`
  before the successful full run.
- `git diff --check`: **PASS**.
- Existing Makefile test discovery names individual test files and does not
  include `test_metrics.py`; the explicit command above is required in handoff.
  Makefile was left unchanged to preserve task scope.

## Contract impact

None. Frozen contracts and unrelated modules remain unchanged. Additional
provenance is stored inside the existing unrestricted `evidence.source_values`
object. Unsupported fractional medians fail explicitly instead of rounding or
misrepresenting an available cohort as missing.

## Commit handoff blocker

The requested `git add` and `git commit` were attempted using the configured Git
identity. Both failed because the linked worktree's Git metadata resides outside
the writable sandbox, and creation of `worktrees/builder-14/index.lock` was denied
with `Operation not permitted`. Approval escalation is unavailable. No candidate
commit was created; the three candidate files remain untracked in this worktree.
The existing base HEAD is `a035a2eb7039a71cc758744a7b05d6b1d16a7912` (not a candidate
commit). An authorized integration environment must stage and commit these files.
