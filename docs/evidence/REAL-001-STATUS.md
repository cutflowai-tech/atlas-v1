# REAL-001: status, identity and Video Type evidence from full Monday history

- Board: `5091110326` (Customer Projects)
- Access: authorized read-only Monday MCP connector (GraphQL `query` operations only; each script refused any `mutation`). No Monday data was modified.
- Retrieved: 2026-09-28T17:45Z
- Raw extract: kept outside git (`atlas-real extract`, SHA-256 `d38c848d4a9c4b1611509ab378775df631e38af1f7db969231c971e8aa1df9c2`). It holds only log/board/item/column/user IDs, timestamps, label texts and indexes, dropdown IDs and names, and date values. Item names, people names, links and free text were stripped at extraction.
- Analysis: `PYTHONPATH=src python3 scripts/real_data_analysis.py <extract>` runs the production `reconstruct_cycles()` path with contract 1.2.0.

## Coverage

| Source | Scope | Records |
|---|---|---:|
| `update_column_value` logs for Status, Editor Name, Video Type, Requested ETA, Performance Issues, For Bonus | 2026-02-02 → 2026-09-28; monthly windows, all pages read, every window below the 10,000-log API cap | 27,183 |
| `create_pulse` logs (initial column values) | weekly windows 2026-02-01 → 2026-09-29, all events read, every week below the cap | 1,505 (1,286 of the 1,291 current items) |
| Current items (items API) | all pages | 1,291 |

The earliest log (2026-02-02 13:07Z) precedes the earliest item (2026-02-02 17:42Z). For these columns the extract therefore spans every current item's lifetime. The Editor Name column only begins logging on 2026-03-14, so items worked before then have no Editor Name event history.

## Status labels: index history

Monday keeps a status label's index when its text is renamed, and sometimes reuses an index for a new label.

| Index | Texts over time | Treatment in `monday-status-v1.1` |
|---:|---|---|
| 4 | `Ready To Sent` (02-02→05-12), `ready to sent` (05-12→06-07), `Ready To Send` (06-07→) | **alias** to `Ready To Send` (same index, consecutive periods, spelling only) |
| 13 | `Creat File` (once, 02-18), `Create File` | **alias** to `Create File` |
| 8 | `Uploading` (02-03→07-03), then `Captions In Progress` / `Captions Revisions` | not aliased: index reused for a different state |
| 10 | `Coloring` (02-03→06-20), then `Captions In Progress` | not aliased (reused) |
| 12 | `Downloaded` (02-10→05-26), `Ready For Review` (06-07→06-14) | not aliased (reused; removed from the board) |
| 14 | `Editing Now` (02-17→05-21), then `Waiting For Captions` | not aliased (reused) |
| 11, 15, 17, 5, 2 | `Downloading`, `For Social Media`, `Captions` (→ `Captions Done`), `Archived` / `Not Started` / blank, `Stuck` | unmapped (retired), except the current labels |

## Normalization result (contract 1.2.0)

- 17,808 status transitions accepted. Before the aliases and the unresolved-previous policy, 4,388 of 18,831 status logs were quarantined.
- 219 transitions into a cleared status are quarantined as `STATUS_CLEARED`. They are flag-only, because a cleared status cannot be a cycle boundary.
- 804 transitions into a retired label are quarantined as `UNKNOWN_STATUS`: `Uploading` 627, `Editing Now` 51, no label 34, `Downloaded` 22, `Downloading` 22, `For Social Media` 22, `Ready For Review` 17, `Coloring` 6, `Captions` 2, `Not Started` 1.
- 137 completed cycles contain an entry into a mapped status from an unmapped previous label. The raw previous text is kept and `from_status` is null (`UNRESOLVED_PREVIOUS_STATUS`).

## Cycles (first completed cycle per item)

| | Count |
|---|---:|
| Completed | 861 |
| Open (no Ready For Approval yet) | 306 |
| Invalid (Ready For Approval without In Progress, or non-positive duration) | 102 |
| Completed and eligible for every metric | **147** |
| Completed with valid timing and Video Type, if Editor identity were resolved | 740 |

Exclusions among the 861 completed cycles (a cycle can have several):

| Reason | Cycles |
|---|---:|
| `UNMAPPED_EDITOR` (Editor Name label not in `monday-editor-v1.0`) | 518 |
| `MISSING_EDITOR_EVENT` (no Editor Name observation at or before Ready For Approval; mostly work before the column existed) | 162 |
| `UNMAPPED_STATUS_WITHIN_CYCLE_WINDOW` (a retired status occurs at or before Ready For Approval) | 120 (23 excluded for this reason alone) |
| `EDITOR_CHANGED_WITHIN_CYCLE` | 11 |
| `MISSING_EDITOR` (empty Editor Name) | 10 |
| `MISSING_VIDEO_TYPE_EVENT` | 1 |

Retired labels behind the 120 window exclusions: `Uploading` 109, `Editing Now` 20, `Coloring` 2, no label 2, `Downloaded` 1, `Ready For Review` 1.

Video Type: 633 completed cycles take their Video Type from the item's creation value (`create_pulse`) and 227 from a later change. Every Video Type ID observed resolves under `monday-video-type-v1.2`.

## Editor Name labels in completed cycles

| Label ID | Live name | In `monday-editor-v1.0` | Completed cycles | First → last Ready For Approval | Also listed in |
|---:|---|:---:|---:|---|---|
| 6 | Will (registry display name: "Synthetic Editor") | yes | 157 | 2026-04-03 → 2026-09-28 | — |
| 4 | Mario | no | 143 | 2026-04-03 → 2026-09-27 | Backup Editor |
| 9 | Ibrahim | no | 107 | 2026-03-17 → 2026-09-26 | Backup Editor, Captions Editor |
| 8 | Samra (deactivated label) | no | 62 | 2026-04-02 → 2026-07-30 | Backup Editor |
| 10 | Amir | no | 60 | 2026-04-22 → 2026-09-26 | Reviewer |
| 5 | Anas | no | 55 | 2026-03-14 → 2026-09-26 | — |
| 7 | Martin | no | 46 | 2026-05-13 → 2026-09-26 | Backup Editor |
| 11 | Refaat | no | 45 | 2026-07-01 → 2026-09-28 | Captions Editor |
| 15 | Sobhy | yes | 5 | 2026-09-17 → 2026-09-26 | — |
| 16 | Ezz | yes | 4 | 2026-09-21 → 2026-09-26 | — |
| 17 | Ali | yes | 2 | 2026-09-21 → 2026-09-26 | — |
| 18 | Mohamed Mansour (Office) | yes | 2 | 2026-09-25 → 2026-09-27 | — |
| 12, 13, 14 | Ahmed, Michael, Mansour | yes | 0 | — | Reviewer |

Activity-log actors cannot identify Editors. `In Progress → Ready For Approval` was recorded under the shared Waset Co account (`99154021`) for 540 of 665 transitions.

## Transition evidence for the conceptual states

"Ready to Edit" is a Monday **group** (`new_group29179`), not a status label. Items move from that group into the "In Progress" group through logged `move_pulse_from_group` events.

| Transition | Count | Most frequent actor accounts |
|---|---:|---|
| `Create File → In Progress` | 1,230 | shared `99154021` (519), `101273903` (268), `105392408` (189), `99988743` (185) |
| `Ready For Approval → Ready To Send` (incl. aliased texts) | 1,861 | `99154857` (836), shared (632), `99154858` (250) |
| `Ready For Approval → Sent` | 545 | `99988743` (179), `101273903` (108), shared (104), `105392408` (101) |
| `Ready For Approval → Internal Revisions` | 560 | — |
| `Ready To Send → Sent` | 1,518 | `101273903` (602), `105392408` (444), `99988743` (440) |

The accounts that move items from `Create File` to `In Progress` are the same accounts that later mark them `Sent`. This is consistent with a Production Manager role. It does not prove that the `Create File` status is the conceptual "Ready to Edit" state, nor that `Ready To Send` means "Approved". Those remain decisions (`docs/DECISIONS.md`).
