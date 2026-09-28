# Atlas V1 contracts

The JSON Schemas under `contracts/` are the machine-readable V1 boundary. Fixture examples under `fixtures/` are tested against them and against semantic invariants that JSON Schema cannot express, such as end-after-start.

| Contract | Purpose | Key invariants |
|---|---|---|
| `editor-identity` | Canonical Editor mapping | Monday person ID is required; ambiguous identities are unresolved |
| `normalized-status-event` | Immutable Monday status transition | Canonical status enum, unique event ID, canonical actor or explicit unresolved Waset Co actor |
| `work-cycle` | Editor work interval | `In Progress` to `Ready For Approval`; end strictly follows start |
| `speed-metric` | Same-type duration comparison | cohort Video Type equals subject Video Type; evidence is mandatory |
| `deadline-metric` | Deadline result | compares Ready For Approval with Monday Requested ETA |
| `quality-metric` | Quality result | value originates from an approved Monday Performance Label |
| `editor-profile` | Evidence API response | Editor is the subject; metrics retain their own evidence; AI annotation is optional |

All contracts use `contract_version: "1.0.0"`. `evidence` always names Monday as source and retains board ID, item ID, column IDs, event IDs, source timestamps, source values, rule version, and calculation time. Empty evidence is invalid.

Contract-owner approval is required for compatibility-affecting changes. No schema may introduce a composite score, revision penalty, global speed cohort, AI-authored fact, or substitute another field when Requested ETA is missing.
