# NORM-001 candidate evidence

Implemented `normalize_events(raw_events, status_mapping)` in fixture mode.
No contracts, DAG, or unrelated modules changed.

## API and assumptions

- Returns `NormalizationResult`, unpackable as `(accepted, quarantined)`.
  Its separate `raw_sources` field contains deep copies of every source record,
  including accepted events. Quarantine records also include the source, input
  index, event ID and stable reason code. Input objects are never mutated.
- Input is an array or JSON-encoded array. Each event may use canonical fixture
  fields or Monday activity fields (`id`, `board_id`, `user_id`, `created_at`,
  and `data`). Activity `data` may be a JSON object or JSON string containing
  `board_id`, `pulse_id`/`item_id`, `column_id`, `previous_value` and `value`.
  Status objects use `label.text` or a string `label`; direct status strings
  are also supported. An explicit activity kind must be `update_column_value`.
- Status mapping is an exact source-label-to-contract-status dictionary. Both
  transition endpoints require explicit entries, except an absent/null previous
  status. No unknown label is inferred, even if it resembles a canonical label.
  Status mapping is caller-supplied configuration; the frozen event contract has
  no status-mapping-version field. The caller must retain its configuration version.
- Canonical actor attribution is retained only with explicit canonical resolution,
  a Monday ID, an actor ID and a mapping version. Otherwise Monday IDs remain
  available and resolution is explicitly `unresolved_waset_co`, with no actor ID.
  No Waset Co/display-name inference or external actor lookup occurs.
- Timestamps must be RFC3339 strings and are preserved verbatim, including offset
  and fractional precision. Numeric timestamps are quarantined because this API
  does not define their units. IDs expressed as JSON integers become decimal
  strings; string IDs remain unchanged. Boolean IDs are invalid.
- Duplicate identity is global event ID. Equality compares complete raw JSON
  records ignoring object key order. Encoded `data` strings retain exact content.
  Identical repeats keep the first and quarantine later copies. Conflicting IDs
  quarantine every occurrence, including the first, regardless of input order.
  Accepted and quarantine lists preserve their respective source order.
- Invalid batch/configuration raises an exception; invalid individual records
  are quarantined without preventing unrelated valid records from being accepted.

## Fixture evidence and test output

Command: `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_normalization.py' -v`

```text
test_bad_configuration ... ok
test_conflicts_quarantine_every_occurrence_in_any_order ... ok
test_good_fixtures_preserve_contract_and_raw ... ok
test_identical_duplicates ... ok
test_invalid_records_are_isolated ... ok
test_monday_json_and_explicit_mapping ... ok
test_unknown_status_never_guessed ... ok
test_unresolved_and_unversioned_actor_mapping ... ok
Ran 8 tests in 0.053s
OK
```

Observed fixture outputs asserted by tests:

- `good/status-in-progress.json` and `good/status-ready.json`: two accepted,
  zero quarantined, output exactly equals contract fixtures.
- Two identical event records: one accepted, one `DUPLICATE_EVENT` quarantine.
- `bad/duplicate-event.json`: zero accepted, both occurrences
  `CONFLICTING_DUPLICATE_EVENT`; reversed input and repeated copies also tested.
- `bad/unknown-transition.json`: zero accepted, one `UNKNOWN_STATUS` quarantine.
- `bad/unresolved-waset-co.json`: retained explicitly unresolved, schema valid.
- Monday activity JSON: IDs 100/7/9 become strings, column `status_2` and timestamp
  `2026-09-01T12:00:00.123456+03:00` remain intact, `Working` maps explicitly to
  `In Progress`, Monday user 42 remains unresolved. Repeated runs compare equal.

`make test`: PASS. Ruff passed; mypy passed for four source files; 11 commander,
6 contract, 2 integration and 2 E2E tests passed; JSON syntax validation passed.
The existing Makefile selects named test files and does not run the new
normalization suite, so its separate command above is required at handoff.
Initial lint findings (Iterator import and exception types) were fixed before
these successful runs. `git diff --check` passed.

## Contract and metric impact

No schema changes. Accepted records contain only frozen normalized-status-event
contract fields and are schema-checked with date-time format validation.
Unresolved actors are deliberately retained as unresolved facts, not asserted to
be resolved editor identities. No metrics are computed or modified; raw event
sources and quarantine provenance remain available as downstream evidence.
