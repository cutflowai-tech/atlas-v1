# VERIFY-001 evidence

- Mode: fixture; risk: simple.
- Base: integration at `a035a2e`.
- Affected contract: Makefile verification targets only. No product, schema, frozen contract, or DAG changes; no metric output changes.
- Change: discover all top-level `tests/test_*.py` unit modules using the standard unittest discovery command. Exclude the three explicitly named contract, integration, and E2E modules because their existing dedicated targets run them. Make expands files in deterministic sorted order; shell `set -e` preserves failure exit status.
- CI coverage: `.github/workflows/ci.yml` already invokes `make unit`, so newly added unit modules run there without workflow edits.
- Validation: `make test` passed lint, mypy, 21 baseline tests (11 unit, 6 contract, 2 integration, 2 E2E), and JSON parsing.
- Discovery regression experiment: temporarily created `tests/test_verify001_probe.py`; `make test` passed and executed its new test exactly once. Representative tests from each dedicated suite also appeared exactly once.
- Failure regression experiment: changed the temporary probe to fail; `make unit` returned nonzero and reported the probe failure. Removed the temporary module after validation.
- Scope: matches the current flat tests directory convention; nested unit packages are outside this change.
