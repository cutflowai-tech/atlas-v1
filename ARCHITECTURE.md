# Atlas V1 architecture

## Data path

1. **Monday adapter** stores raw board, item, column, event, actor, and timestamp identifiers without rewriting source values.
2. **Normalizer** emits idempotent `NormalizedStatusEvent` records. Duplicate Monday event IDs are rejected or deduplicated explicitly.
3. **Identity and attribution** resolve Editor identity and transition actors through versioned canonical-ID maps. Ambiguity enters an exception queue.
4. **Cycle builder** pairs `In Progress` with the next valid `Ready For Approval` event for the same item and Editor. Missing endpoints and negative intervals are invalid cycles.
5. **Metric engine** derives speed, deadline, and quality independently and emits evidence with each result.
6. **Evidence API** returns contract-versioned Editor Profile data. The UI does not recalculate metrics.
7. **Optional AI explanation** reads deterministic outputs and evidence; it cannot mutate or supply them.

## Boundaries

- Raw Monday data is immutable input; derived records always point back to it.
- Deadline performance is derived only by comparing `Ready For Approval` with the source `Requested ETA`; missing ETA produces no result and enters data-quality handling.
- Benchmark cohorts are keyed by canonical Video Type. No global fallback is permitted in V1.
- Contract changes require compatibility tests and contract-owner approval.
- Fixture-backed adapters unblock normalization, metrics, API, and UI before live Monday access.

## Delivery architecture

Candidate work is isolated on `task/<id>/<slot>` branches/worktrees based on `integration`. Builders return independent candidates. Reviewers and validators do not share candidate conclusions. The arbiter selects or composes; the integrator alone merges accepted work into `integration`. A pull request with required CI is the only promotion path from `integration` to protected `main`.

Hermes audits contracts, research, and documentation on a schedule. Hermes is never a dependency of ingestion, implementation, validation, integration, or release.
