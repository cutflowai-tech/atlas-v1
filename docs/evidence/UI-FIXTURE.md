## UI-FIXTURE — Editor Profile against mock API (candidate builder-2)

Development mode: **fixture**. Risk: normal. Affected contract: `contracts/editor-profile.schema.json` (read-only; plus `common.schema.json` and the referenced identity, work-cycle, speed, deadline and quality schemas).

## What was built

- `web/profile.js` — fetches `/api/editors/<editor_id>`, rejects responses that do not match the EditorProfile shape, and renders:
  - **Quality**: approved Monday Performance Label verbatim, label column, label mapping version, revision context tagged "context only".
  - **Speed**: grouped by canonical `video_type`; shows API `duration_seconds` and `cohort_median_seconds`. A null median is shown as "Not available for this Video Type cohort". A `cohort_video_type` ≠ `video_type` is flagged, and no comparison is shown.
  - **Deadline**: API `result` (on_time / late) with Ready For Approval and Requested ETA. Work cycles with a null Requested ETA are listed as "Not evaluated"; nothing is estimated.
  - **Work cycles & revision context**: In Progress → Ready For Approval timestamps and revision context, stated to be context only.
  - **Evidence**: each metric has an expandable `<details>` block with the Monday board/item, columns, events, source timestamps, source values, rule version and calculated_at. If a metric has no evidence or non-Monday evidence, its value is withheld.
  - **States**: loading, missing ID, invalid ID, not found (404), HTTP/network/JSON error, contract error, empty sections.
  - **Fixture labeling**: the mock sets `X-Atlas-Data-Mode: fixture`, and the UI shows a "FIXTURE DATA — … Not real Monday data" banner. If the header is missing, the UI says the data mode is undeclared.
  - `ai_annotation` is never rendered. The UI shows no composite rating, percentages, averages or rankings.
- `web/app.js`, `web/index.html`, `web/styles.css` — page shell.
- `web/mock-server.mjs` — Node stdlib mock API and static server (`make web-demo`).
- `web/mock/editors/editor-42.json` (3 cycles, 2 Video Types, on-time + late + missing-ETA, 2 quality labels) and `editor-empty.json`.
- `Makefile` — new targets `ui-fixture` (added to `make test`), `ui-fixture-evidence` and `web-demo`.

## Acceptance tests

| Acceptance test | Covered by |
| --- | --- |
| UI displays evidence-backed fields | `profile.test.mjs`: quality/speed/deadline/revision display tests; "every displayed metric has an expandable Monday evidence block" (7 metrics → 7 evidence blocks); "metric with missing or non-Monday evidence is withheld" |
| UI does not calculate metrics | `profile.test.mjs`: "trusts API values even when inputs would disagree" (tampered result/duration displayed verbatim); "no aggregates, composite score, rankings or AI text"; static check that `profile.js` has no `new Date`, `Date.parse`, `.reduce(`, `Math.max/min/round/abs` or `.ai_annotation` |

Isolation: the UI tests live under `web/tests/` and use only the mock fixtures in `web/mock/`. The E2E server binds to an ephemeral `127.0.0.1` port and shuts down inside the test process. No services are left running.

## Test results (2026-09-28, Node v26.8.2, Python 3 + jsonschema 4.26.0)

- `make ui-fixture`: Node 21/21 pass (17 renderer unit tests, 4 E2E); Python 3/3 pass (mock fixtures validate against `editor-profile.schema.json` and the nested schema/semantic invariants; missing-ETA cycles have no deadline metric).
- `make test`: lint ✔, mypy ✔, unit 11 OK, contract 6 OK, integration 2 OK, e2e 2 OK, ui-fixture 21 + 3 OK, JSON well-formedness ✔.

## Fixture E2E artifact

- `docs/evidence/UI-FIXTURE-e2e.html` — the rendered output for 5 scenarios, fetched over real HTTP from the mock API. Open it in a browser; the evidence blocks expand.
- `docs/evidence/UI-FIXTURE-e2e.json` — transcript: request, view status, data mode, SHA-256 of the rendered HTML and evidence-block count for each scenario.

`e2e.test.mjs` regenerates both files and asserts they match the committed copies byte for byte, so a stale artifact fails the test. Run `make ui-fixture-evidence` to refresh them.

## Assumptions

- Duration formatting (`7200` → `2h 00m (7,200 s)`) is a display unit conversion, not metric computation. The raw seconds are always shown.
- Grouping speed rows by `video_type` is presentation only. Groups are sorted alphabetically so output is deterministic.
- Timestamps are shown exactly as the API sends them (UTC ISO-8601) to avoid locale-dependent output.
- The fixture quality labels ("Meets Expectations", "Exceeds Expectations") are placeholders. The approved Monday label set is owned upstream, and the UI shows whatever label the API returns.
- The existing contracts define no HTTP error body or data-mode field. The `X-Atlas-Data-Mode` header and 404 semantics are mock conventions, and the real API should adopt or replace them.
- The page is served at `/`, with the API at `/api/editors/<id>` on the same origin.

## Contract / schema impact

None. No contract, DAG or source module was edited. The contract shape is consumed as-is. The UI's structural guard (`contractProblems`) mirrors the required fields of `editor-profile.schema.json` and `editor-identity.schema.json`.

Integration notes:
- `.github/workflows/ci.yml` calls individual make targets, so it does not run `ui-fixture` yet. Wiring that in is left to the integrator; `ubuntu-latest` already has Node.
- `ruff` covers `src` and `tests` only, so `web/tests/test_mock_contract.py` is not linted.
