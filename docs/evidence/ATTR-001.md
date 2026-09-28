# ATTR-001 evidence: resolve transition actors deterministically

Candidate: builder-3 · Risk: critical · Mode: fixture

## Change

- `src/atlas_commander/attribution.py`: resolves a status-transition actor to an Atlas actor ID using only the canonical Monday `(kind, monday_id)` pair (`kind` is `person` or `team`) and an explicit mapping carrying a required `mapping_version`.
- Resolution order: missing ID or kind → `missing_actor`; configured Waset Co shared actor → `waset_co_shared_actor`, even when it also has a mapping entry; no entry → `unknown_actor`; more than one distinct actor ID → `ambiguous_mapping`; otherwise resolved.
- Display names are stored as evidence only. IDs are compared exactly, with no case, whitespace or numeric normalisation, no fuzzy matching and no AI.
- `ActorResolution.event_fields()` produces the actor fields for `NormalizedStatusEvent`. `ActorResolution.evidence()` keeps the source ID, kind, display name, mapping version and candidate actor IDs.
- Mapping parsing is order-independent: entries are sorted and deduplicated. Malformed config raises `ValueError`.

## Fixtures

- `fixtures/attribution/actor-mapping-v1.json`: versioned mapping `actor-v1`, including an ambiguous ID (`person-77`) and a Waset Co shared person who also has a mapping entry.
- `fixtures/attribution/unresolved-actors.json`: the required unresolved actor fixture. It has 9 cases: 2 resolved; 7 unresolved covering Waset Co team, Waset Co shared person, unknown ID, ambiguous mapping, person/team kind mismatch, null actor and name-only actor.

## Tests

`PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_attribution.py' -v`: 15 tests, OK. The tests check:

- every fixture case gets the expected status, reason, actor ID and contract `actor_resolution`
- every generated event validates against `normalized-status-event.schema.json`; unresolved events produce the `UNRESOLVED_ACTOR` semantic code
- acceptance "Waset Co mapping uses canonical IDs only": a shared actor never implies an Editor; names never affect the result; IDs match exactly; person and team IDs are separate namespaces
- source IDs and mapping version are preserved; results are order-independent; the version is required; malformed config is rejected

`make test`: lint, mypy, unit, contract, integration, e2e and JSON validation all pass.

Note: the `make test` discovery patterns do not include `test_attribution.py`. The Makefile is outside this task's scope, so it was not changed. Integration should add the file to a make target.

## Contract impact

None. `contracts/normalized-status-event.schema.json` 1.0.0 is used unchanged. The contract's only non-resolved value is `unresolved_waset_co`, so every unresolved reason maps to that value. The specific reason is kept in `ActorResolution.evidence()`, not in the event. A future contract version could add a reason field.

## Assumptions

- Canonical Monday IDs arrive as non-empty strings. Non-string IDs, such as raw integers, are treated as missing and are not coerced.
- A mapping entry may map a team ID to an actor. Whether that actor counts as an Editor is decided downstream.
- Identical duplicate entries are not ambiguous. Distinct actor IDs for the same canonical ID are ambiguous.
