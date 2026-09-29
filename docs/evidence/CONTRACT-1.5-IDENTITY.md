# Contract 1.5 configuration and identity evidence

## Scope

This change adds the immutable `config/monday-contract-v1.5.json` candidate and its loader schema. It encodes decisions D20–D50
without activating 1.5 for production or changing prior contract files. `ACTIVE_CONTRACT_VERSION` remains `1.4.0`; activation is
an integration decision after the separate metric/profile/UI seams are composed and tested.

No metric output is recalculated by this atomic change. Contract assertions instead verify the configuration inputs that later
metric engines must consume: Cairo windows, label classes, leave-one-out populations, non-scoring revision/current-work semantics,
evidence/coverage requirements, and explicit unapproved-threshold states.

## Deterministic identity result

`monday-editor-v1.2` uses the exact tuple `(source_label_id, logged_name)`. The implementation has no ID-only fallback in this
mapping mode. A new name under a known label ID returns `UNMAPPED_EDITOR`; it cannot inherit the known name's Editor mapping.

The seven named unresolved identities and the three earlier reused-name identities in D49 remain unmapped. No person is newly
attested. D50 is represented exactly:

| Historical identity | Quarantine code |
|---|---|
| `(11, "New")` | `invalid_identity_value` |
| `(2, "Done")` | `invalid_identity_value` |
| `(1, "El Baz")` | `unresolved_historical_identity` |

Every identity exception retains board, item and column IDs, the source label ID, logged name, mapping version, source event ID,
and observed timestamp. The raw Monday record remains the source evidence outside this normalized diagnostic.

## Configuration evidence

- The positive registry contains `1- Exceptional Quality`, `Client Praise`, `On Time Delivery`, and `Saved Rush Project`.
- The context registry contains `High Workload` and `Additional Revisions`.
- The negative registry retains all seven Performance Issues labels.
- `Late Delivery` and `On Time Delivery` stay visible but have `scored_quality: false`; Context labels are also non-scoring.
- Speed and Deadline comparator populations are leave-one-out. Their bands and comparator minimums are `null` with
  `rule_not_approved`.
- Quality N/P/minimum sample, Overall Status lookup, Trend material-change/minimum sample, finding/change thresholds, and capacity
  threshold are all `null` with `rule_not_approved`.
- The current window is the last 30 completed `Africa/Cairo` days, excluding the current Cairo day; the comparison window is the
  immediately preceding 30 completed Cairo days.

## Contract/schema impact

- Added `contracts/monday-contract-v1.5.schema.json`; contract 1.5 configs now fail closed at load time when this boundary is
  violated.
- Added `1.5.0` to the versioned loader map without changing the active pointer.
- Extended the internal identity exception diagnostic with `logged_names`, `event_id`, and `observed_at`. This diagnostic still has
  no public persistence schema. The existing `editor-identity.schema.json` output stays unchanged for compatibility.
- Prior `monday-contract-v1.0.json` through `v1.4.json` are unchanged and remain reproducible through the legacy identity path.

## Verification

Focused deterministic tests are in `tests/test_contract_v15.py`; legacy identity and runtime contract tests are also run to prove
backward compatibility.

- `make contract-v15 identity runtime profile lint typecheck json`: passed.
- `make test`: passed (exit 0); three Docker-daemon-gated runtime tests were skipped by the repository's existing opt-in guard.
