# VERIFY-002 evidence

- Mode: fixture; risk: simple. Base: integration at `e5f6898`.
- Affected contract: verification targets and CI execution only. No product, metric, schema, or DAG changes.
- Added the phony `ui-fixture` target, invoking `$(MAKE) -C web test`. The root `make test` now requires this target, so both the Node renderer tests and Python UI fixture contract tests are mandatory locally.
- CI explicitly configures Node 22 with `actions/setup-node@v4` and runs `make ui-fixture` after its existing verification steps. UI tests have no npm dependencies to install.
- Existing dynamic Python unit discovery and dedicated contract, integration, and E2E targets are unchanged. The root gate runs each module once; UI Python tests are discovered separately from `web/tests`.
- Validation: `make test` passed lint, mypy (8 source files), 59 existing Python tests, 9 Node UI tests, 2 Python UI tests, and JSON validation. `git diff --check` passed.
- Local Node version was `v26.8.2`; the configured Node 22 CI run has not been executed by this builder. CI evidence will be collected through the normal integration workflow.
