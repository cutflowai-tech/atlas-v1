# API-FIXTURE candidate evidence

Implemented `src/atlas_commander/api.py` with stdlib HTTP transport and injected
`ProfileRepository.get(editor_id)` lookup. GET `/api/editors/<editor_id>` returns
the frozen profile document directly. Host/port are configurable through
`create_server` or `python -m atlas_commander.api --host HOST --port PORT`;
default binding is 127.0.0.1:8000. Importing the module starts no service.

Fixture provenance is explicit in the CLI description/startup output and every
response's `X-Atlas-Provenance: fixture` header. The repository combines the
checked-in good profile, cycle, and three metric records without recomputation.
The response is validated against the frozen schema, nested semantic checks,
and consistent canonical editor IDs. Invalid data or repository failures return
a sanitized JSON 500; unknown routes/editors return 404 and unsupported common
methods return 405. Output JSON ordering is deterministic; generated_at and
calculated_at are preserved. No AI fields or facts are generated.

## Tests run

- `make test`: PASS (ruff, mypy, 11 unit, 6 contract, 2 integration,
  2 E2E tests, and JSON syntax checks).
- `PYTHONPATH=src:tests python3 -m unittest test_api.ProfileValidationTests -v`:
  PASS, 2 tests. Validates the assembled profile and exact equality of every
  metric to its fixture, including evidence; rejects missing evidence for all
  three metric families and mismatched speed cohort.
- `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_api.py' -v`:
  8 tests attempted, 2 passed, 6 errors. All six HTTP tests are blocked during
  setup by sandbox `PermissionError: [Errno 1] Operation not permitted` at
  localhost socket bind. No HTTP test is claimed as passing. The tests retain
  actual loopback HTTP requests, deterministic body comparisons, schema and
  evidence assertions, malformed/unknown routes, unsupported methods, invalid
  profiles, missing ETA without fallback, and repository failure coverage.
  Test listeners have bounded lifetimes and cleanup. No persistent service ran.

The existing Makefile selects specific test modules and does not discover
`test_api.py`; integration must run the explicit API command in a socket-enabled
environment. The Makefile was left unchanged to keep this candidate scoped.

## Metric evidence and assumptions

The fixture speed is 7200 seconds against a 7500-second short-form median,
with events event-100/event-101 and speed-v1 evidence. Deadline is on_time for
11:00Z readiness against 11:30Z requested ETA, backed by event-101/deadline-v1.
Quality is the supplied Meets Expectations label with quality-label-v1 mapping
and event-102/quality-v1 evidence; revision count 3 remains context only.
All records refer to editor-42 and Monday board-1/item-1. No metric value,
label, timestamp, canonical mapping, or source evidence is recalculated.

Repository implementations are responsible for upstream approved label mappings
and Monday authenticity; this transport cannot verify those against live Monday.
Nullable cycle ETA is allowed by the frozen contract and is preserved; a
returned deadline metric must have its own requested ETA. Query strings do not
change profile selection. No authentication or live Monday integration is added
in this fixture-only task.

## Contract impact

None. Frozen contracts and fixtures are unchanged. Provenance and transport
errors live outside the successful editor-profile JSON schema. Changes are
limited to the API module, its tests, and this evidence note. Acceptance remains
partially unverified until real HTTP tests run in an environment permitting bind.

## Commit handoff limitation

`git add` and `git commit` were attempted with the configured identity but both
failed because the sandbox prohibits creating the linked worktree Git metadata
`index.lock` outside this writable worktree. No candidate commit SHA exists;
changes remain in the supplied worktree for integration to stage and commit.
`git diff --check` passed. No merge or push was attempted.
