# Atlas V1 deterministic rules

These rules are the authoritative baseline until superseded by a later approved
contract version. The approved executable configuration is
`config/monday-contract-v1.1.json`: it preserves the v1.0 status and Editor
registries and adds the approved `monday-video-type-v1.1` mapping. Any label
absent from the active explicit registries is unresolved and must quarantine
records rather than infer mappings. `config/monday-contract-v1.0.json` remains
the historical baseline for reproducibility.

1. **Monday is authoritative.** Persist every raw Monday label plus board/item/column/event identifiers and source timestamps. Each normalized event carries `mapping_version`.
2. **Status mappings are explicit.** Use the v1.0 phase mapping in the executable configuration. Unmapped, deprecated, and newly introduced labels are quarantined; no silent inference.
3. **Editor is the evaluated entity.** The item `Editor Name` field is authoritative. Activity-log `user_id` is audit metadata only. Use a versioned person/label-ID mapping, including historical and deactivated identities; unresolved identities are quarantined. Account `99154021` never infers an Editor.
4. **Work duration is exact.** Only the first transition into `In Progress` starts the cycle, and only the first qualifying transition into `Ready For Approval` ends it. Repeated `In Progress`/`Create File` and post-revision transitions stay in the original cycle.
5. **Anomalies and open cycles are retained safely.** Duplicate or reversed transitions are ignored for timing and flagged. Incomplete cycles are retained as open/right-censored records and excluded from completed-cycle duration aggregates.
6. **Comparable benchmarks only.** Normalize multi-select Video Type values using the versioned v1.1 registry, key cohorts by sorted canonical IDs, and compare only within the same resolved cohort. Blank, unknown, or new types are quarantined; there is no global fallback.
7. **Deadline uses Requested ETA.** Compare the `Ready For Approval` timestamp with the Monday `Requested ETA`. On time means `Ready For Approval <= Requested ETA`; a missing ETA yields no result and must not be replaced by another field.
8. **Revisions are context.** Revision counts and notes can explain outcomes but cannot directly lower a quality score without an explicit deterministic business rule.
9. **Quality is label-derived.** Quality values come from approved Monday labels and a versioned label mapping.
10. **Evidence is mandatory.** Every metric stores source record IDs, event IDs, field values, formula/rule version, and calculation time.
11. **AI is not authoritative.** AI can summarize, investigate, recommend, or flag anomalies. It cannot invent facts or overwrite deterministic source-derived values.

## Contract ownership

Changes under `contracts/` require a designated contract owner review plus compatibility tests. Builders may propose contract changes; the arbiter cannot waive contract review.
