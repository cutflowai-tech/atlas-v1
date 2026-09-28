# DATA-001 evidence — real Monday probe for one known Editor

Candidate: Atlas Builder Claude M · branch `agent/atlas-builder-claude-m/7ebeefdd6794` · approved contract `contracts/normalized-status-event.schema.json` v1.0.0 and executable configuration `config/monday-contract-v1.0.json`.

## Access

| Path | Result |
|---|---|
| Monday MCP connector | Authorized read-only (`all_api_read`); the three requests were GraphQL `query` operations only. |
| `MONDAY_API_TOKEN` in runtime env | Not set. The repository `capture` command exits `2` with `MISSING_ACCESS`; no token or secret was read, printed, or stored. |
| Raw retention | The raw payloads are sealed outside git at `~/.atlas/raw/monday/DATA-001/2026-09-28/`. |

## Probe scope

- Board `5091110326` (Customer Projects), status column `project_status`.
- Known Editor: `Editor Name` dropdown `dropdown_mm1emgt8`, label id `6` (`Will` in the raw Monday response). This label is resolved through the approved `monday-editor-v1.0` mapping; activity-log `user_id` remains audit metadata only.
- Items: `3236714197`, `3241413361`, `3241464823`, `3243581913`, `3246525128`.
- Activity window: `2026-09-15T00:00:00Z`–`2026-09-28T23:59:59Z`.
- Result: 58 `update_column_value` status logs, including 0 undo actions.

## Raw retention

The raw store is write-once and read-only (`0444`), and the implementation refuses paths inside a git worktree.

| File | SHA-256 | Bytes |
|---|---|---:|
| `activity_logs.json` | `88447f27496a7ff4267f6279ff8a1b326a1b02abce17bfc3c6cb1cad4a5c89b0` | 56266 |
| `items.json` | `50b4065d15f8ce0d132bf30b399f4ada918e61a3f422cb8dc22722f026b829e6` | 3310 |
| `users_columns.json` | `d7f9506270320ec78b0dd37652d43db6470ceb1566f7550b014aea65f5f7a8b6` | 4424 |

## Evidence artifacts

- `sample-manifest.json` is regenerated from the sealed raw payloads. It retains raw log, board, item, column, actor, account, label, and timestamp identifiers while excluding item names, people names, emails, links, update bodies, and label colours.
- `drift-report.json` is regenerated against the approved v1.0 schema **and** `config/monday-contract-v1.0.json`. It reports whether live labels and observed values are covered by the approved registries; it does not treat known v1.0 mappings as unresolved drift.

Regenerate both from the sealed raw directory:

```text
PYTHONPATH=src python3 -m atlas_monday_probe report \
  --raw-dir ~/.atlas/raw/monday/DATA-001/2026-09-28 \
  --access "authorized read-only Monday MCP connector (all_api_read)" \
  --scope '{"board_id":"5091110326","status_column_id":"project_status","editor_column_id":"dropdown_mm1emgt8","known_editor_label_id":"6","item_ids":["3236714197","3241413361","3241464823","3243581913","3246525128"],"activity_window":{"since":"2026-09-15T00:00:00Z","until":"2026-09-28T23:59:59Z"}}' \
  --manifest-out docs/evidence/DATA-001/sample-manifest.json \
  --drift-out docs/evidence/DATA-001/drift-report.json
```

## Findings against approved v1.0

1. **Status vocabulary: resolved.** All live status labels observed in the probe are present in the approved status registry and carry `monday-status-v1.0`. No status label is silently inferred or quarantined. Contract enum values not observed in this sample are not evidence of drift.
2. **Editor attribution: resolved for the probed items.** The activity-log `user_id` values are recorded as audit metadata and are not used as Editor identity. The `Editor Name` label id `6` is covered by `monday-editor-v1.0`; the shared account `99154021` is not used to infer an Editor. No unresolved Editor label was found in the probed items.
3. **Video Type cohorts: policy approved; one label remains unmapped.** Item `3243581913` has the multi-select value `[5,16]` (`Class B`, `Ai`). It is handled with the approved `exact-normalized-full-set` policy; no primary type or global fallback is inferred. The probe also observes Video Type label id `8` (`Class A+`), which is absent from the approved `monday-video-type-v1.0` label registry. Records containing id `8` remain quarantined from cohort comparisons until the mapping is explicitly added in a later contract version.
4. **Cycle rules: approved and unchanged.** The probe observed repeated `In Progress`/`Create File` transitions and `Sent -> In Progress`. The approved v1.0 rules remain authoritative: the first transition into `In Progress` starts the cycle, repeated `In Progress`/`Create File` transitions stay in the same cycle, post-revision transitions stay in the original cycle, and the first qualifying `Ready For Approval` ends it. This probe computes no work-cycle metric.
5. **Timestamp encoding: informational.** `activity_logs.created_at` is a 17-digit count of 100 ns ticks. The adapter converts it to RFC 3339 UTC while retaining the raw value.
6. **Timestamp cross-check: informational.** The latest log label agrees with the items API status label for all five items; log-vs-column `changed_at` deltas are -13 ms to +694 ms.
7. **Column type alias: informational.** Activity logs report the status column type as `color`; the columns API reports `status`.
8. **Requested ETA timezone: informational.** Deadline logic must use the UTC `value`, not the account-local display text. The five populated ETAs show a consistent +3 hour display offset.

`drift-report.json` has `contract_change_required: true` solely because Video Type label id `8` is not present in the approved v1.0 registry. The status vocabulary, Editor attribution, cycle rules, and multi-select policy are aligned with v1.0; only the unmapped `Class A+` label remains a data-coverage blocker.

## Tests

- `make monday-probe`: read-only enforcement, timestamp conversion, immutable raw retention, redaction, approved-config coverage, drift detection, and CLI end-to-end behavior.
- `make test`: lint, typecheck, unit, contract, integration, E2E, runtime normalization, identity, and Monday-probe suites.

Fixtures are synthetic and contain no real names or IDs. No contract schema was changed by DATA-001.
