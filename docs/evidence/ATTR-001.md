# ATTR-001 — builder-2 evidence

Implemented `src/atlas_commander/attribution.py` with immutable versioned mapping
snapshots and exact `(actor_kind, actor_monday_id)` rule matching. A unique Editor
target resolves; absent rules, absent source IDs/kinds, unknown IDs/kinds, and
conflicting targets remain unresolved. Duplicate identical assignments are not
ambiguous. Mapping order cannot select a winner. Previous attribution is cleared
before resolution. Event source IDs, timestamps and transition fields are retained.

## Tests and observed results

- `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_attribution.py' -v`:
  PASS, 14 tests (rerun after the import lint fix).
- `make test`: PASS, exit 0. Ruff, mypy (4 source files), 11 commander tests,
  6 contract tests, 2 integration tests, 2 E2E tests, and repository JSON parsing.
- Initial `make test` found a Mapping import-style issue; corrected to
  `collections.abc.Mapping` before the successful run.
- The existing Makefile selects named suites and does not discover the new
  attribution suite; the explicit development command above runs that suite.

## Fixture and deterministic evidence

`fixtures/good/status-in-progress.json` resolves exactly to its existing expected
output: source `person-42`, Editor `editor-42`, version `actor-v1`, resolution
`canonical_monday_id`. The test validates the result against the frozen contract.

`fixtures/bad/unresolved-waset-co.json` is reproduced exactly with no mapping:
source ID null, Editor null, mapping version null, resolution
`unresolved_waset_co`. It is schema-valid and produces semantic diagnostic
`UNRESOLVED_ACTOR`. Unknown source IDs remain present in unresolved output.

A synthetic shared source `shared-7` has no Editor without an explicit rule.
With one explicit versioned person-ID rule it resolves to `editor-42`; the display
name `Waset Co` cannot match that rule. A synthetic team rule resolves only in the
team namespace. Two different Editor targets for `person-42` remain unresolved in
all six rule permutations, retaining the attempted version `conflict-v1`.

## Assumptions and contract impact

- The caller supplies canonical IDs and person/team kind obtained from Monday.
  Canonical provenance cannot be inferred from an ID's spelling; this module does
  not query Monday or convert display names into IDs.
- Shared/team attribution requires an authoritative explicit unique mapping;
  shared identity or team membership alone never establishes the Editor.
- Mapping configuration owners must change the version when assignments change.
  The module takes an immutable snapshot but does not maintain a version registry.
- The frozen event schema lacks actor kind and a generic unresolved enum. Kind is
  a resolver argument; all unresolved cases use existing `unresolved_waset_co`.
  `mapping_version` records the attempted snapshot even for unresolved output.
- Malformed source values are preserved rather than repaired; normalized-event
  schema validation remains the caller's responsibility.
- No contracts, DAG, unrelated modules, or metric calculations changed. Existing
  Monday source/Editor semantics and timing, ETA, cohort, revision and quality
  rules are unaffected. Attribution adds no AI or fuzzy matching facts.
