# ATTR-001: deterministic transition actor resolution

Candidate: builder-1. Fixture development; no live Monday calls.

## Implementation and assumptions

`resolve_transition_actor(actor_kind, actor_monday_id, mapping)` returns the four
actor fields of a normalized status event. Exact canonical IDs are matched in
separate person/team namespaces against an explicit versioned mapping snapshot.
There is no display-name input, normalization, fuzzy matching, AI, or implicit
identity mapping. The caller retains the original event and merges these fields.

Mapping configuration is trusted, curated input: callers must obtain actor kind
and ID from Monday and register shared accounts, including Waset Co, with
`shared=True`. No production Waset Co ID is guessed or hardcoded. A shared entry
blocks resolution even when another matching entry names an Editor. Teams only
resolve with an explicit unique Editor mapping; membership is never inferred.
Unknown IDs, missing IDs/kinds/mappings, unassigned entries and conflicting Editor
IDs remain unresolved. Duplicate identical targets are unambiguous. Reordering
entries cannot change attribution. The mapping snapshots caller-owned sequences.
Invalid mapping configuration and invalid source ID types/empty strings raise;
valid source ID strings are preserved byte-for-byte, including unmatched IDs.

## Evidence

- `fixtures/good/status-in-progress.json`: person-42 resolves to editor-42 under
  actor-v1, exactly reproducing the fixture's actor fields; resulting event passes
  normalized-status-event schema validation.
- `fixtures/bad/unresolved-waset-co.json`: missing source actor remains null and
  unresolved, exactly reproducing the fixture; event is schema-valid but remains
  semantically flagged by the existing contract validator.
- Tests cover synthetic shared canonical ID `waset-id` in person and team
  namespaces: even explicit conflicting Editor assignments stay unresolved and
  retain the source ID. Names such as `Waset Co` cannot match that ID.
- Tests permute conflicting/unassigned entries, verify duplicate-target behavior,
  repeated-call equality, version provenance, mapping snapshots, exact matching,
  person/team ID collisions, and missing/unknown inputs.
- This task emits actor attribution, not metric values; no duration, deadline,
  speed, quality or revision calculations are changed.

## Contract impact

No frozen contract/schema changes. The v1 enum only provides
`canonical_monday_id` and `unresolved_waset_co`; all unresolved reasons use the
latter, including actors unrelated to Waset Co. `actor_id` is null for every
unresolved result. `actor_monday_id` preserves source evidence; `mapping_version`
records the attempted mapping version even on unresolved output, or null when no
mapping exists. Actor kind and shared-account registration remain resolver inputs
because the frozen event schema has no corresponding fields.

## Validation

- `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_attribution.py' -v`:
  PASS, 9 tests.
- `make test`: PASS, Ruff, mypy, 21 existing tests across unit/contract/integration/
  E2E targets, and JSON parsing checks. The first run found a Ruff exception-type
  issue, corrected before the passing run.
- The existing Makefile enumerates test modules and does not discover
  `test_attribution.py`; run the explicit attribution command above at handoff.

## Handoff limitation

Commit attempted using the configured Git identity, but sandbox filesystem
permissions rejected creation of the worktree Git metadata `index.lock` outside
the writable worktree. `git add` and `git commit` both failed; no candidate commit
was created. The three candidate files remain untracked in the assigned worktree
for integration handoff. No merge, push, or service/background work was performed.
