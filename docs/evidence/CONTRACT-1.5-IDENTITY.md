# Contract 1.5 configuration and identity evidence

## Scope

This change adds the immutable `config/monday-contract-v1.5.json` candidate and its loader schema. It encodes decisions D20–D50
without activating 1.5 for production or changing prior contract files. `ACTIVE_CONTRACT_VERSION` remains `1.4.0`; activation is
an integration decision after the separate metric/profile/UI seams are composed and tested.

The integrated 1.5 runtime consumes this contract for Cairo-windowed component facts, per-label quality parsing, leave-one-out
comparators, non-scoring revision/current-work semantics, evidence/coverage output, and explicit unapproved-threshold states.
Contracts 1.0–1.4 keep their historical code paths and outputs.

## Deterministic identity result

`monday-editor-v1.2` uses the exact tuple `(source_label_id, logged_name)`. The implementation has no ID-only fallback in this
mapping mode. A new name under a known label ID returns `UNMAPPED_EDITOR`; it cannot inherit the known name's Editor mapping.
Cycle reassignment detection uses that same tuple: two observations with the same source label ID but different logged names
inside one work cycle add `EDITOR_CHANGED_WITHIN_CYCLE` and prevent attribution. The legacy ID-only comparison remains limited to
older contracts whose identity mapping does not enable the strict tuple key.

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
- Added `contracts/editor-profile-v1.5.schema.json`. The 1.5 evidence API adds publication identity, exact Active Work and
  Awaiting Approval groups, separate Client/Internal Revision evidence, metric coverage, Cairo window metadata, factual Recent
  Change, component states, and the explicit unapproved Overall Status result.
- Quality coverage now treats every eligible completed project as part of the denominator, including zero-label projects, while
  reporting quarantined label occurrences separately. Speed coverage requires both a valid first-pass duration and a confirmed
  benchmark-eligible Video Type.
- Recent Change includes Speed as separate per-Video-Type median changes; durations are never pooled or averaged across types.
- The dashboard and both profile renderers preserve Positive, Negative and Context groups separately. Timeline evidence labels
  each occurrence by class instead of describing every quality label as an issue.
- The 1.5 interpreter consumes the canonical config vocabulary (`*_sample_size`, named bands, `lookup_table`, and trend threshold
  names); approved-rule tests prove those paths without adding any production threshold value.
- The shared 1.5 profile is rendered into Arabic and English without recalculating business logic. Each route embeds the same
  release and snapshot identifiers; build and publish validation reject disagreement.

## Verification

Focused deterministic tests are in `tests/test_contract_v15.py`, `tests/test_intelligence_v15.py`, and
`tests/test_profile_publication_v15.py`; legacy identity, runtime, profile, dashboard, publication, and localization tests are also
run to prove backward compatibility.

- The actual `monday-contract-v1.5.json` is exercised end to end through cycle reconstruction, For Bonus parsing, Editor Profile,
  bilingual site generation, and publication parity—not only through synthetic configuration copies.
- `make test`: passed (exit 0); three Docker-daemon-gated runtime tests were skipped by the repository's existing opt-in guard.
