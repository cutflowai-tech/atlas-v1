## Atlas Editor Profile UI (fixture mode)

Single-editor profile page. Plain ES modules, no build step, no dependencies.

- `index.html`, `app.js` — page and bootstrap (`?editor=<editor_id>`).
- `profile.js` — fetches `GET /api/editors/<editor_id>`, checks the EditorProfile contract shape, renders loading / missing / invalid / not-found / error / contract-error / ready states. It displays API values verbatim and never derives a metric.
- `mock-server.mjs` — fixture mock of the API plus static files. Every API response carries `X-Atlas-Data-Mode: fixture`, which the UI shows as a **FIXTURE DATA** banner.
- `mock/editors/*.json` — fixture profiles, validated against the frozen contracts by `tests/test_mock_contract.py`.

Demo (foreground; Ctrl+C to stop):

```sh
make web-demo   # http://127.0.0.1:8787/?editor=editor-42
```

Fixture IDs: `editor-42` (populated), `editor-empty`, any unknown ID (404), `fixture-server-error` (500), `fixture-bad-contract` (contract rejection).

Tests: `make ui-fixture`. Regenerate the E2E evidence artifact after an intended UI change with `make ui-fixture-evidence`.
