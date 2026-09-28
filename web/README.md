# Editor Profile fixture

Dependency-free browser UI and Python standard-library mock API. From the repository root, run `make -C web demo`, then open http://127.0.0.1:8080/?editor_id=editor-42. Stop with Ctrl-C. This command is provided for manual use; no server was started during implementation.

The page fetches `/api/editors/<encoded editor_id>`. Unknown IDs return 404. Reload retries the request. The banner always identifies synthetic fixture data. The populated fixture copies the existing good identity, metric and cycle fixtures without deriving metrics.

Run `make -C web test` for isolated Node tests and Python contract/handler tests (the latter use the repository's existing validation dependencies). Run `make test` from the repository root for the repository checks. No package installation is needed.

Open `web/evidence/fixture-e2e.html` for the deterministic fetch-to-render artifact. Native details/summary elements expose every metric's complete source evidence. This artifact comes from a simulated fetch and a minimal render target, not a real browser E2E runner. Browser visual/accessibility and live HTTP smoke checks remain manual; no browser or service was started.

The server remains responsible for canonical Video Type IDs, approved Monday label mappings, metric arithmetic and full schema validation. The UI checks identity/version, evidence presence, mapping presence and cohort consistency; it is not a replacement contract validator. The current contract has no Video Type mapping-version field, so the UI uses its canonical IDs verbatim. Missing ETA cannot appear as a valid deadline metric and is displayed as unknown in cycle context. Missing context and missing metrics are not zero scores.
