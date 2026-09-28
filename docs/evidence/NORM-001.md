# NORM-001 — builder-2 candidate evidence

Implemented `src/atlas_commander/normalization.py` and fixture tests in
`tests/test_normalization.py`. No frozen contracts, DAG, or unrelated modules changed.

## API and assumptions

`normalize_events(raw_events, status_mapping)` returns a `NormalizationResult`.
Unpack it as `accepted, quarantined = result`; raw evidence is available separately
as `result.raw_sources`, with every input snapshot preserved in original order.
`result.status_mapping_version` records the supplied status mapping version.
Accepted entries conform to the frozen normalized-status-event schema, without
adding source fields. Quarantine entries have `source_index`, `event_id`, `reason`,
and a detached `raw_source`. Neither inputs nor mappings are mutated.

- Mapping shape: `{"version": "status-v1", "statuses": {"Working": "In Progress"}}`.
  Every source status, even a canonical label, needs an explicit mapping. Mapping
  targets must be canonical contract values. Invalid configuration raises an error.
- Input is an iterable of JSON-compatible records or a serialized JSON array.
  Supports contract-shaped source records and Monday activities with `id`,
  `created_at`, `user_id`, and `data` as an object or JSON string. Activity data
  supplies `board_id`, `pulse_id`, `column_id`, `previous_value`, and `value`.
  Status values may be strings, integer indices, or label objects with text/index.
  Indices require explicit string mapping keys. Missing previous value means null;
  a supplied unknown previous value is quarantined. Missing destination is invalid.
- Activity type, when supplied, must be `update_column_value`. Other activity
  types are quarantined. The caller supplies the relevant status-column mapping;
  this function does not infer board/column mappings or download Monday metadata.
- ISO timestamps retain their exact offset and precision. Numeric activity timestamps
  are interpreted explicitly as Unix 100-nanosecond ticks, using integer arithmetic;
  seconds/milliseconds are not auto-detected. Original values remain in raw evidence.
- String IDs, including leading zeroes, are preserved; integer IDs become strings.
  Canonical actor attribution is retained only when the source explicitly supplies
  `canonical_monday_id`, `actor_monday_id` (activity `user_id`), `actor_id`, and a
  nonempty actor `mapping_version`. This function does not resolve display names.
  Incomplete mappings preserve the source Monday ID but emit null internal actor ID
  and `unresolved_waset_co`. Such entries are schema-valid but must still be excluded
  from actor-dependent metrics by downstream consumers (`UNRESOLVED_ACTOR` semantics).
- Identical JSON records with the same event ID retain the first event, with later
  copies quarantined as `DUPLICATE_EVENT`. Object key ordering does not matter.
  Any source difference for the same ID quarantines the entire group as
  `CONFLICTING_DUPLICATE_ID`, including a valid event paired with an invalid one.
  Results follow source order and use no wall clock, random values, network, or AI.

## Fixture evidence

| Input | Accepted | Quarantined / outcome |
| --- | --- | --- |
| good/status-in-progress.json + good/status-ready.json | 2, unchanged | 0 |
| bad/unknown-transition.json | 0 | UNKNOWN_STATUS |
| bad/duplicate-event.json, both input orders | 0 | Both CONFLICTING_DUPLICATE_ID |
| Two identical good/status-ready.json records | 1 | Second DUPLICATE_EVENT |
| bad/unresolved-waset-co.json | 1, unchanged | Explicit unresolved actor |
| Inline Monday JSON activity with custom labels | 1 | Exact board/item/column/offset preservation |
| Inline tick timestamp 17882532001234567 | 1 | 2026-09-01T09:00:00.1234567Z |

Additional tests cover detached raw snapshots, repeat determinism, canonical output
schema validation, missing actor mapping version, unknown previous statuses,
malformed JSON/records/timestamps/IDs, explicit index mapping, null origin,
unsupported activity types, and invalid configuration.

## Executed verification

```
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_normalization.py' -v
Ran 16 tests in 0.015s
OK

make test
ruff check src tests: All checks passed!
mypy src: Success: no issues found in 4 source files
commander: Ran 11 tests — OK
contracts: Ran 6 tests — OK
integration: Ran 2 tests — OK
e2e: Ran 2 tests — OK
JSON validation: exit 0
```

Initial lint/type failures were corrected before the final successful runs.
The existing Makefile names individual test modules, so it does not execute the new
normalization suite; run the explicit command above in addition to `make test`.
No metric values are calculated by this task. Source snapshots and canonical event
IDs provide evidence for downstream calculations; no deadline fallback, cohort,
quality, or revision rules are introduced. Contract/schema impact: none.
