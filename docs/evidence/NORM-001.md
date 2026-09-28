# NORM-001 candidate evidence

Implemented deterministic `normalize_events(raw_events, status_mapping)` in
`src/atlas_commander/normalization.py`. No frozen contracts or other modules changed.
Accepted events match normalized-status-event contract 1.0.0; raw input is retained
separately and deeply copied. No metrics or inferred business facts are produced.

## API assumptions

- Inputs are a list (or JSON list string) of Monday activity objects or canonical
  contract-shaped records. Monday `data` may be an object or JSON object string,
  with `pulse_id`, `column_id`, `previous_value`, and `value`. Labels may be strings
  or nested `label.text` objects. Supplied event types must be `update_column_value`.
- Mapping configuration is `{"version":"status-v1","statuses":{"Working":"In Progress"}}`.
  Canonical input labels also require explicit mapping. Unknown previous or next
  statuses are quarantined. Missing previous status is allowed by the contract.
- The result exposes `accepted`, `quarantined`, `raw_sources`, and
  `status_mapping_version`; two-value unpacking yields accepted and quarantined.
  Raw sources retain input order. Quarantine records include source index and reason.
- Exact repeated records accept the first occurrence and quarantine later copies.
  Any differing raw records with the same ID quarantine every occurrence, including
  the first. JSON object key order is ignored; JSON-string payload formatting is
  preserved and therefore counts as a difference (conservative conflict handling).
- Numeric Monday IDs become decimal strings; source timestamp strings, including
  fractional seconds and timezone offsets, are preserved. Inputs require RFC3339
  timestamps with an explicit offset; numeric epoch timestamps are quarantined
  because no epoch/unit conversion contract was supplied.
- Canonical actor attribution is preserved only when the input explicitly supplies
  resolution, Monday ID, actor ID, and mapping version. Otherwise the source Monday
  user ID remains available and actor resolution is explicitly unresolved; names
  never infer an actor. Status mapping version is separate from actor mapping version.

## Validation output

Command: `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_normalization.py' -v`

```
Ran 12 tests in 0.012s
OK
```

Coverage: good status fixtures and schema validity, raw source isolation, Monday
JSON input, ID/timestamp fidelity, unresolved actors, incomplete canonical mapping,
identical duplicates, conflicting duplicate fixture in both orders, unknown status
fixture, unknown previous status, malformed previous status, invalid records mixed
with valid records, explicit alias mapping, version requirements, determinism.

Command: `make test`

```
ruff check src tests: All checks passed!
mypy src: Success: no issues found in 4 source files
commander: 11 tests OK
contracts: 6 tests OK
integration: 2 tests OK
e2e: 2 tests OK
JSON syntax validation: passed
```

The existing Makefile selects named suites and does not include normalization tests;
the separate explicit command above is required. Total executed: 33 passing tests.
