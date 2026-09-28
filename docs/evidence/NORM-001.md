# NORM-001 — Normalize Monday status events (candidate: builder-3)

Mode: fixture. Risk: critical. Affected contract: `contracts/normalized-status-event.schema.json` (read-only, not modified).

## Deliverables

- `src/atlas_commander/normalization.py`: `normalize_events(raw_events, status_mapping, actor_mapping=None) -> NormalizationResult`
- `tests/test_normalization.py`: 33 tests
- `fixtures/monday/activity-status-events.json`: raw Monday `activity_logs` fixture with explicit status and actor mappings. It is not referenced by `fixtures/manifest.json` because it is raw input, not a contract instance.

## Behavior

- **Input:** Monday activity-log entries (`id`, `event`, `user_id`, `created_at`, `data`). `data` can be a JSON string, as returned by the Monday API, or an already-decoded object.
- **Status mapping (explicit, versioned):** `{"version", "status_column_ids": {board_id: [column_id]}, "labels": {monday_label_text: canonical_status}}`. Labels must match exactly. Unmapped `value` or `previous_value` labels and cleared statuses are quarantined as `UNKNOWN_STATUS`. A mapping that is missing a version or targets a non-canonical status raises `ValueError`.
- **Actor mapping (optional, versioned):** `{"version", "actors": {monday_person_id: actor_id}}`. A mapped actor becomes `canonical_monday_id`. Any other actor becomes `unresolved_waset_co`, with `actor_monday_id` preserved and `actor_id = null`. The event is still accepted, and its ID is listed in `unresolved_actor_event_ids` for the exception queue.
- **Duplicates:** repeated IDs whose decoded payloads are identical are deduplicated and recorded in `duplicate_event_ids`. Repeated IDs with conflicting payloads have **every** copy quarantined as `DUPLICATE_EVENT_CONFLICT`, because the normalizer cannot know which copy is true.
- **Other quarantine reasons:** `MISSING_EVENT_ID`, `MALFORMED_EVENT`, `INVALID_TIMESTAMP` (naive or unparseable), `NON_STATUS_EVENT` (another event type or an unmapped column), and `SCHEMA_INVALID` (a defensive contract check on every accepted event).
- **Fidelity:** board, item and column IDs come from `data.board_id`, `data.pulse_id` and `data.column_id`, converted to strings. Monday `created_at` ticks (100 ns) are rendered in UTC with all 7 sub-second digits kept exactly, never rounded. ISO inputs with an offset are converted to UTC and keep their source fraction digits.
- **Raw source:** accepted events hold only contract fields. `raw_sources[event_id]` and `quarantined[*].raw` hold deep copies of the untouched input, and the caller's input is never changed.
- **Determinism:** accepted events are sorted by exact instant, then board, item and event ID. Quarantined records are sorted by input index. Reordering the input gives identical accepted output, and a test checks this.

## Assumptions and decisions for the arbiter

1. **Unresolved actors are accepted, not quarantined.** The status transition is a Monday fact, and the task says to "leave unresolved mapping explicit". The contract's semantic layer still reports `UNRESOLVED_ACTOR` for these events, and they are exposed through `unresolved_actor_event_ids`. Downstream attribution must not credit them to an Editor.
2. For unresolved actors, `mapping_version` is the actor mapping version that was consulted, or `null` if no mapping was supplied, so the evidence shows which mapping failed to resolve the actor.
3. Label mapping is keyed by label text, which is what activity logs carry reliably. Renaming a Monday label therefore needs a new mapping version.
4. If `data.column_type` is present, it must be `color`. If it is absent, the board-specific column-ID allowlist decides.

## Contract impact

None. No schema changes. Every accepted event passes `schema_errors(..., "normalized-status-event.schema.json") == []`.

## Test evidence

`PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_normalization.py' -v`: **Ran 26 tests, OK**. This includes the acceptance test `test_duplicate_and_unknown_events_quarantined`.

`make test`: ruff "All checks passed!", mypy "Success: no issues found in 4 source files", unit 11 OK, contract 6 OK, integration 2 OK, e2e 2 OK, JSON well-formedness check passed.

Note: the `make test` targets only discover `test_commander.py`, `test_contracts.py`, `test_integration.py` and `test_e2e.py`, so `tests/test_normalization.py` is **not** run by `make test`. The Makefile was left unchanged because it is outside this task's scope. The integrator should add a target, or widen `unit` discovery, so these tests run in CI.


## Independent review repair

Strict event and actor IDs now accept only nonempty strings or integers (excluding booleans), rejecting objects, lists and floats without fabricating attribution. Missing actors remain explicitly unresolved. Mapping containers, label types, actor keys and actor values are validated before processing; malformed configuration raises ValueError.

Out-of-range ticks, oversized numeric values and ISO timezone conversions across datetime bounds quarantine as INVALID_TIMESTAMP while subsequent valid events continue. Native 100 ns precision remains unchanged.

`raw_input_snapshots` is an additional tuple containing every raw occurrence in input order, including identical duplicates and malformed/quarantined records. JSON objects are recursively read-only mapping proxies and JSON arrays become tuples; JSON strings remain exact strings. Existing `raw_sources` retains its accepted-event lookup behavior. Snapshots detach from both caller inputs and mutable result evidence.

Added seven regression tests covering malformed IDs/configuration, timestamp overflow, immutable complete raw evidence, duplicate preservation, raw attribution claims and status-column scoping. Validation: module suite 26 tests passed; `make test` passed (ruff, mypy, 11 unit, 6 contract, 2 integration, 2 e2e, JSON checks). Frozen schemas and DAG unchanged. Fixture mode only; no real Monday data used.


## Typed duplicate comparison repair

Decoded duplicate content now uses recursively typed fingerprints: objects ignore key order, arrays retain order, and booleans, integers and floats remain distinct. Equivalent JSON-string versus decoded-object `data` still deduplicates. Same-ID actor 42/42.0, board 1/true and item 11/11.0 pairs now quarantine both occurrences as DUPLICATE_EVENT_CONFLICT in either input order. Board, item and column IDs share the strict ID parser used by event and actor IDs, including blank-string rejection.

Validation after this repair: 28 normalization tests passed; `make test` passed (ruff, mypy, 11 unit, 6 contract, 2 integration, 2 e2e, JSON checks). No schema or DAG changes.


## Board scope and strict input repair

The versioned input configuration now requires an explicit board-to-column map; the previous global column list is rejected. Example:

```python
status_mapping = {
    "version": "status-map-v2",
    "status_column_ids": {"100": ["status"], "200": ["workflow"]},
    "labels": {"Working on it": "In Progress"},
}
result = normalize_events(raw_events, status_mapping)
```

A `status` update on board `999` or `200` is quarantined for that configuration; only board `100` may use `status`, and board `200` may use `workflow`. Board/column mapping keys and label keys must be nonblank. Numeric Monday IDs cannot be negative integers; opaque nonblank string IDs are retained. Native tick strings must consist of ASCII digits.

`raw_input_snapshots` is the authoritative immutable evidence collection, indexed by original input position. Accepted event IDs link to every corresponding snapshot's original `id` (integer IDs are normalized to strings for this linkage); quarantined records expose `input_index` directly. Identical duplicate occurrences remain separately retained. `raw_sources[event_id]` remains the compatible first accepted source lookup, while derived output dictionaries remain mutable.

Validation: 32 normalization tests passed; `make test` passed (ruff, mypy, 11 unit, 6 contract, 2 integration, 2 e2e, JSON checks). Fixture input configuration updated. No contract schemas or DAG changed.


## RFC3339 offset range repair

Explicit offset hours must be 00–23 and offset minutes 00–59 before ISO parsing. Invalid offsets such as +00:99 and +01:60 now quarantine as INVALID_TIMESTAMP instead of being silently normalized by datetime. Regression covers positive and negative invalid offsets and both positions beside a valid event; batch processing continues. Validation: 33 normalization tests passed, and `make test` passed all lint, typing, unit, contract, integration, e2e and JSON checks. No wider code or schema changes.
