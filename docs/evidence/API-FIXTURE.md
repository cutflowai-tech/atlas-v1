# API-FIXTURE evidence — builder-2

Task: Build evidence API against fixtures. Risk: normal. Mode: fixture. Affected contract: `contracts/editor-profile.schema.json` (frozen, unchanged).

## Deliverable

`src/atlas_commander/api.py` — stdlib (`http.server`) read-only evidence API.

- `GET /api/editors/<editor_id>` returns the stored `EditorProfile` exactly as held by the injected repository. The API performs **no metric recalculation**; it only validates and serializes.
- `ProfileRepository` protocol (`get_profile`, `data_mode`, `provenance`) is injected via `create_server(repository, host, port)`.
- `FixtureProfileRepository` loads one or more profile JSON files, validates each at load (fail-fast), rejects duplicate `editor_id`s, and returns deep copies.
- Every profile is validated again at serve time (`profile_errors`): full JSON Schema validation against the frozen contract (with `$ref`s to identity, work-cycle, speed, deadline, quality, common evidence), plus the nested semantic invariants from `contracts.semantic_codes` (duration consistency, end-after-start, same-Video-Type cohort, deadline `Ready For Approval <= Requested ETA`), plus `editor_id` consistency between the profile editor, its work cycles and metrics, and the requested path. A profile that fails any check is **not served** (500 `PROFILE_CONTRACT_VIOLATION`; details only in the server log).
- Fixture provenance: every response (success and error) carries `X-Atlas-Data-Mode: fixture` and `X-Atlas-Provenance: fixture:<paths>`; `Cache-Control: no-store`. The startup line states `data mode: FIXTURE`. Provenance is in headers because the frozen profile contract forbids additional body properties.
- Errors: 400 `INVALID_EDITOR_ID` (id must match `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$` after percent-decoding, so `/`, `..`, empty are rejected), 404 `EDITOR_NOT_FOUND`, 404 `ROUTE_NOT_FOUND`, 405 `METHOD_NOT_ALLOWED` (`Allow: GET`) for POST/PUT/PATCH/DELETE. Error body: `{"error": {"code", "message"}}`.
- Server: host/port configurable (`--host`, `--port`, repeatable `--fixture`), default `127.0.0.1:8000`, default fixture `fixtures/good/editor-profile.json`. Run: `PYTHONPATH=src python3 -m atlas_commander.api`. No service was started during this task outside the unit tests' in-process ephemeral-port servers.

## Tests

`tests/test_api.py` — 25 tests, real HTTP over loopback against in-process servers on ephemeral ports.

| Acceptance test | Covering tests |
| --- | --- |
| profile response validates | `test_profile_response_validates`, `test_response_is_stored_profile_without_recalculation`, `test_injected_repository_is_used`, `test_query_string_is_ignored` |
| all metrics retain evidence | `test_all_metrics_retain_evidence`, `test_metric_without_evidence_is_refused`, `test_ai_sourced_evidence_is_refused` |

Additional: provenance headers, 400/404/405 cases, refusal of cross-Video-Type cohorts, deadline-result mismatch, foreign-editor metrics/profile, composite `score` field, duration mismatch, invalid fixture at load and in `main` (before binding), duplicate fixtures, localhost default, defensive copies.

Commands and results (2026-09-28):

- `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_api.py' -v` — `Ran 25 tests ... OK`
- `make test` — ruff `All checks passed!`; mypy `Success: no issues found in 4 source files`; unit 11 OK; contract 6 OK; integration 2 OK; e2e 2 OK; JSON validation OK.

## Assumptions

- A work cycle with `requested_eta: null` is valid profile content (the schema permits it); `MISSING_REQUESTED_ETA` is therefore non-blocking at the profile level. No deadline metric is fabricated for it — the API never computes metrics.
- The populated test profile is assembled verbatim from the existing good fixtures (`work-cycle`, `speed-metric`, `deadline-metric`, `quality-metric`); the committed `fixtures/good/editor-profile.json` (empty metrics) is left unchanged.
- `make test` has no target for `test_api.py` (Makefile not edited to stay within task scope); the integrator should add e.g. `api: PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_api.py' -v` to `test`. `test_api.py` is covered by `make lint`.

## Contract impact

None. No contract, schema, fixture, DAG, or existing module was modified. The API only consumes `contracts.schema_errors` / `contracts.semantic_codes`.
