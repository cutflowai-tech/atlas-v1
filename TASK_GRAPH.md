# Atlas V1 execution graph

The executable graph is `tasks/dag.json`. The graph is arranged for fixture-first parallel development while the real Monday probe runs independently.

```text
ARCH-001 contracts ─┬─> NORM-001 ─┬─> CYCLE-001 ─┐
ARCH-002 adapters ──┼─> ID-001 ───┤              ├─> REAL-001 -> API-REAL -> E2E-001
                    ├─> ATTR-001 ──┘              │
                    ├─> METRICS-FIXTURE ──────────┤
                    ├─> API-FIXTURE ──────────────┤
                    └─> UI-FIXTURE ───────────────┘

DATA-001 real Monday probe ───────────────────────> REAL-001
```

`DATA-001`, normalization, identity, attribution, fixture metrics, fixture API, and fixture UI can proceed as soon as their declared contract/adapter dependencies are satisfied. UI and AI work may not delay the real-data critical path. Real-data work enters through `integration`; promotion to `main` requires the complete CI gate and E2E.
