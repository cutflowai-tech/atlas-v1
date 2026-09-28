# DATA-001 evidence — real Monday probe for one known Editor

Candidate: Atlas Builder Claude M · branch `agent/atlas-builder-claude-m/7ebeefdd6794` · contract `contracts/normalized-status-event.schema.json` v1.0.0 (not edited).

## Access

| Path | Result |
|---|---|
| Existing raw snapshot `raw/monday/2026-07-25` (Second Brain) | Customer Projects `5091110326` present, 959 items, **no activity logs** (manifest: "not requested in this pass"). Used as the label baseline only. |
| `MONDAY_API_TOKEN` in runtime env | **Not set.** The repo adapter's `capture` command exits `2` with `MISSING_ACCESS: MONDAY_API_TOKEN is not set`. No token or secret was read, printed or stored. |
| Monday MCP connector (claude.ai monday.com, `all_api_read`) | **Authorized, read-only**. The same integration produced the 2026-07-25 snapshot. The connector rejects mutations before sending. This path was used for the real pull. |

No mutation was issued: the three GraphQL requests were all `query` operations (activity logs, items, users + column settings).

## Probe scope

- Board `5091110326` (Customer Projects), status column `project_status`.
- Known Editor: Editor Name dropdown `dropdown_mm1emgt8` label id `6`. It is the most frequent editor in the 2026-07-25 snapshot (121 items). The label is a raw source ID, and no canonical editor identity was assigned.
- Items: the 5 most recently updated items with that label: `3236714197`, `3241413361`, `3241464823`, `3243581913`, `3246525128`.
- Activity window `2026-09-15T00:00:00Z` – `2026-09-28T23:59:59Z`. Result: 58 `update_column_value` status logs, 0 undo actions.

## Raw retention (outside git, immutable)

The raw store is `~/.atlas/raw/monday/DATA-001/2026-09-28/` on the Claude M runtime host. Files are mode `0444` and write-once (`raw_store.write_immutable` refuses different bytes and refuses any path inside a git worktree).

| File | sha256 | Bytes | Provenance |
|---|---|---|---|
| `activity_logs.json` | `88447f27496a7ff4267f6279ff8a1b326a1b02abce17bfc3c6cb1cad4a5c89b0` | 56266 | Byte-for-byte MCP response persisted by the harness |
| `items.json` | `50b4065d15f8ce0d132bf30b399f4ada918e61a3f422cb8dc22722f026b829e6` | 3310 | MCP response text, written verbatim by the agent |
| `users_columns.json` | `d7f9506270320ec78b0dd37652d43db6470ceb1566f7550b014aea65f5f7a8b6` | 4424 | MCP response text, written verbatim by the agent (includes staff display names, which is why it stays out of git) |

## Evidence artifacts (in git, redacted)

- `docs/evidence/DATA-001/sample-manifest.json` is the redacted sample manifest. It lists all 58 status changes with raw `log_id`, `board_id`, `item_id`, `user_id`, `account_id`, raw 17-digit `created_at_raw`, converted `occurred_at`, and label index/text. Item names, people names, emails, links, update bodies and colours are excluded by a field whitelist.
- `docs/evidence/DATA-001/drift-report.json` is the schema drift report against `normalized-status-event.schema.json` v1.0.0.

Regenerate both from the sealed raw dir:

```
PYTHONPATH=src python3 -m atlas_monday_probe report --raw-dir ~/.atlas/raw/monday/DATA-001/2026-09-28 \
  --baseline-snapshot "<Second Brain>/raw/monday/2026-07-25/boards/customer-projects--5091110326.md" \
  --access "..." --scope '{...}' --manifest-out docs/evidence/DATA-001/sample-manifest.json --drift-out docs/evidence/DATA-001/drift-report.json
```

## Drift findings (real data)

Blocking findings mean the contract cannot be populated from Monday without an owner decision.

1. **STATUS_LABEL_VOCABULARY_DRIFT (blocking).** Only `In Progress` (idx 9) and `Ready For Approval` (idx 3) match the contract enum exactly. Twelve Monday labels have no contract value: Internal Revisions, Done, Revisions, Ready To Send, Waiting, Sent, Captions Revisions, Captions In Progress, Create File, Waiting For Captions, TOPAZ, Captions Done. Four contract values have no Monday label: Backlog, Revision, Approved, Delivered. Transitions observed in real data include `Sent -> Revisions`, `Ready For Approval -> Ready To Send` and `Create File -> In Progress`, so `from_status` for real In Progress events is usually outside the enum. The raw logs also contain an empty label (idx 5 `""`) and null labels.
2. **ACTOR_IS_NOT_EDITOR (blocking).** Log `user_id` is the Monday account that clicked the status, while the evaluated Editor is a dropdown label on the item and not a Monday user. 32 of 58 changes were made by user `99154021`, the board-owner account. Every status change on the sample cycle item was made by that account. No versioned actor or editor mapping exists, so no event can be `canonical_monday_id`. Classifying `99154021` as the shared Waset Co account needs an owner-approved mapping; it was not hard-coded.
3. **VIDEO_TYPE_MULTI_VALUE (blocking for speed cohorts).** Video Type is a multi-select (item `3243581913` = ids `[5,16]` "Class B, Ai"). A single same-Video-Type cohort needs an approved rule.
4. **TIMESTAMP_ENCODING.** `activity_logs.created_at` is a 17-digit count of 100 ns ticks (e.g. `17906001359122650` → `2026-09-28T12:55:35.912265Z`). The adapter converts losslessly to microseconds and rejects any other shape.
5. **TIMESTAMP_CROSS_CHECK.** The latest log per item agrees with the items API status label (5/5). The log time is −13 ms to +694 ms from the column `changed_at`. The log timestamp is the event time, and `changed_at` is kept only as a cross-check.
6. **COLUMN_TYPE_ALIAS.** Logs call the status column type `color`; the columns API calls it `status`.
7. **REQUESTED_ETA_TIMEZONE.** The `date` value is UTC date+time; `text` is account-local (+3 h on all 5 items). Deadline logic must use `value`. Items with an empty ETA stay missing and are not guessed.
8. **LABEL_DRIFT_SINCE_BASELINE (vs 2026-07-25 snapshot).** New status label `8 Captions Revisions`. Editor labels 12–18 were added (Ahmed, Michael, Mansour, Sobhy, Ezz, Ali, Mohamed Mansour (Office)). Samra (id 8) is now deactivated. Status and editor label IDs must be versioned, not treated as static.

Observed, not decided: item `3246525128` has `Sent -> In Progress` right after creation (the item appears to be copied from a sent item), then In Progress ⇄ Create File three times, then `In Progress -> Ready For Approval` (`1093f34d-…`, 2026-09-28T12:55:35.912265Z). Which `In Progress` event starts the work cycle is a rule decision for the contract owner. No work-cycle or metric was computed.

## Implementation

`src/atlas_monday_probe/`:

- `client.py`: `ReadOnlyMondayClient` rejects `mutation` and `subscription` operations (comments and string literals stripped first) before calling the transport. The token comes only from `MONDAY_API_TOKEN`, and `repr` redacts it. Missing access raises `MissingAccess` with the exact missing item.
- `raw_store.py`: write-once `0444` retention outside git, with sha256 records.
- `adapter.py`: `parse_status_changes` keeps every raw identifier and timestamp. `normalize` emits a `NormalizedStatusEvent` only when an explicit `StatusMapping` (board+column scoped, versioned) and `ActorMapping` (versioned, with declared Waset Co accounts → `unresolved_waset_co`) are supplied. Otherwise it returns reason codes. Output is validated against the frozen contract.
- `report.py`: redacted manifest (field whitelist) and drift report.
- `__main__.py`: `capture` (live, needs token) and `report` (from a sealed raw dir).

## Tests

- `make monday-probe`: 19 tests, OK (timestamp conversion, raw ID/timestamp retention, write-once/outside-git raw store, mutation rejection before transport, read-only capture path, missing-token handling, mapping-gated normalization incl. Waset Co unresolved, scope mismatch, undo, redaction, drift detection, CLI end-to-end).
- `make test`: lint OK, mypy OK (9 files), unit 11, contract 6, integration 2, e2e 2, monday-probe 19. All pass, exit 0.

Fixtures in `fixtures/monday/` are synthetic and shaped like the real payloads. They contain no real names or IDs.

## Assumptions

- The Monday MCP connector counts as the authorized read-only access. It is the integration that produced the existing immutable snapshot.
- "One known Editor" = Editor Name label id 6 on board `5091110326`, chosen by frequency. The label is not mapped to any person or Atlas ID.
- Raw payloads live on the runtime host. A shared or durable raw location, such as the Second Brain `raw/monday/` tree, is for the owner to choose; nothing was written there.

## Contract impact

No contract edited. The findings above show that `normalized-status-event.schema.json` v1.0.0 cannot be populated from real Monday data until the owner approves:

- a versioned status-label mapping, or an enum change covering Create File, Sent, Ready To Send, Revisions, Internal Revisions, the captions states and TOPAZ;
- a versioned actor mapping, including the Waset Co account;
- a separate editor-attribution source, because the actor is not the Editor;
- a multi-value Video Type cohort rule;
- a cycle-start rule when an item has repeated In Progress entries.
