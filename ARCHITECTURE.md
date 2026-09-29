# Atlas V1 architecture

## Data path

1. **Monday adapter** stores raw board, item, column, event, actor, and timestamp identifiers without rewriting source values.
2. **Normalizer** emits idempotent `NormalizedStatusEvent` records. Duplicate Monday event IDs are rejected or deduplicated explicitly.
3. **Identity and attribution** resolve Editor identity and transition actors through versioned canonical-ID maps. Ambiguity enters an exception queue.
4. **Cycle builder** pairs `In Progress` with the next valid `Ready For Approval` event for the same item and Editor. Missing endpoints and negative intervals are invalid cycles.
5. **Metric engine** derives speed, deadline, and quality independently and emits evidence with each result.
5a. **Interpretation layer (contract 1.5.0 only)** — `interpretation_policy.py` reads the contract's rules and their approval state (D25); `intelligence.py` builds Cairo windows, component states, Overall Status (lookup), Recent Change and Trend, each with a reconstructable evidence block. What a contract version enables is decided in one place, `capabilities.py`; contracts up to 1.4.0 produce their original output byte for byte (`fixtures/golden`).
5b. **Investigation layer (Intelligence V2, optional)** — `atlas_commander/investigation/` reads the cycle reconstruction and the
finished 1.5 profiles and builds a separately versioned `intelligence-v2` document of findings (patterns, contradictions,
context, investigations), each with Monday evidence, confidence and limitations. It never feeds back into any metric, state,
status, profile or dashboard; new thresholds stay `rule_not_approved` until decided (D53). It is published only as an optional,
feature-gated artifact (`docs/INTELLIGENCE-V2.md`).
6. **Evidence API** returns contract-versioned Editor Profile data. The UI does not recalculate metrics. Under 1.5.0 the Overview and Profile render one language-neutral interpretation view model (`dashboard.interpretation_view`, `interpretation_html.py`) in English and Arabic.
7. **Optional AI explanation** reads deterministic outputs and evidence; it cannot mutate or supply them.

## Boundaries

- Raw Monday data is immutable input; derived records always point back to it.
- Deadline performance is derived only by comparing `Ready For Approval` with the source `Requested ETA`; missing ETA produces no result and enters data-quality handling.
- Benchmark cohorts are keyed by canonical Video Type. No global fallback is permitted in V1.
- Contract changes require compatibility tests and contract-owner approval.
- Publication identity (contract 1.5.0): `publication.json` and page meta tags give `/`, `/en` and `/ar` one release and source snapshot; `site_layout.publication_problems` enforces it for 1.5 builds only, so builds made under 1.4.0 keep publishing, status-checking and rolling back unchanged.
- Fixture-backed adapters unblock normalization, metrics, API, and UI before live Monday access.

## Delivery architecture

Candidate work is isolated on `task/<id>/<slot>` branches/worktrees based on `integration`. Builders return independent candidates. Reviewers and validators do not share candidate conclusions. The arbiter selects or composes; the integrator alone merges accepted work into `integration`. A pull request with required CI is the only promotion path from `integration` to protected `main`.

Hermes audits contracts, research, and documentation on a schedule. Hermes is never a dependency of ingestion, implementation, validation, integration, or release.
