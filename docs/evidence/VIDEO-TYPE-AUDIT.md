# Video Type coverage audit (live Monday, read-only)

- Date: 2026-09-28
- Board: `5091110326` (Customer Projects)
- Column: `dropdown_mm062ga0` (Video Type)
- Access: authorized read-only Monday MCP connector (`all_api_read` GraphQL queries and `board_insights` aggregations). No mutation was performed.

These counts use each item's **current** Video Type value. Cycle-level cohorts use the value in effect at Ready For Approval, taken from activity logs (`cycle-attributes-v1.0`), so per-cycle exclusions can differ slightly.

## Label registry (column `settings_str`)

| ID | Label (verbatim) | Active | Mapped in v1.1 | Mapped in v1.2 | Items containing label |
|---:|---|:---:|:---:|:---:|---:|
| 1 | Reel (Less Than 1 min) | no | no | yes | 30 |
| 2 | Short Video (Less Than 30 sec) | no | no | yes | 0 |
| 3 | Long Video (More Than 1 min) | no | no | yes | 5 |
| 4 | Class A | yes | no | yes | 519 |
| 5 | Class B | yes | yes | yes | 237 |
| 6 | Simple Short | yes | no | yes | 309 |
| 7 | Video (Less Than 1 min) | no | no | yes | 9 |
| 8 | Class A+ | yes | yes | yes | 112 |
| 9 | Short Reel (Less Than 30 sec) | no | no | yes | 5 |
| 10 | 2* | yes | no | yes | 66 |
| 11 | Reel | no | no | yes | 7 |
| 12 | Video | no | no | yes | 4 |
| 15 | Premium Capions | yes | no | yes | 0 |
| 16 | Ai | yes | yes | yes | 73 |
| 17 | SUPER CLASS A | no | no | yes | 9 |
| 18 | Teaser | yes | no | yes | 7 |
| 19 | 4* | yes | no | yes | 2 |
| 20 | 3 Short reel - (Less Than 20 sec) | no | no | yes | 1 |
| 21 | 10 Clips Export | no | no | yes | 1 |
| 22 | Reels Boost Pack | yes | no | yes | 11 |
| 23 | Special Requests | yes | no | yes | 9 |
| 24 | Walkthrough Reel | yes | no | yes | 2 |
| 25 | 3* | yes | no | yes | 0 |
| 26 | Unbranded | yes | no | yes | 4 |
| 27 | Premium Short | yes | no | yes | 98 |

- Deactivated IDs: `1, 2, 3, 7, 9, 11, 12, 17, 20, 21`. They are mapped in v1.2 because historical items still carry them and Monday gives each an authoritative ID and name.
- IDs 13 and 14 do not exist in the registry.
- "Items containing label" counts a multi-select item once under each of its labels, so the column does not sum to the item total.
- A `not_any_of` query over all 25 registered IDs returned **no** non-empty item. Every item's IDs are in the registry, so no orphan IDs exist.

## Resolution coverage

Board total: **1,291 items** (Archived 996, Finished 156, Sent 122, Revisions 14, In Progress 1, Ready to Edit 1, Ready to Send 1).

| Current value vs mapping | v1.1 (Class B, Ai, Class A+) all | v1.1 not archived | v1.2 all | v1.2 not archived |
|---|---:|---:|---:|---:|
| Resolved: all IDs mapped | 316 | 64 | 1,289 | 295 |
| Mixed: a mapped plus an unmapped ID (quarantined) | 89 | 17 | 0 | 0 |
| Only unmapped IDs (quarantined) | 884 | 214 | 0 | 0 |
| Blank (quarantined, `MISSING_VIDEO_TYPE`) | 2 | 0 | 2 | 0 |

Under v1.1, the mixed items combine the mapped labels (`Class B` ×17, `Class A+` ×19, `Ai` ×60) with unmapped ones. The most frequent unmapped companions are `2*` (39 items) and `Class A` (54 items). Under v1.1 these are quarantined, never reduced to their mapped part.

Under v1.2 every combination resolves to its exact full-set cohort key, for example `[10,4]` → `10:4` and `[4,16]` → `16:4`. Different combinations are never merged. Whether modifier labels such as `2*` or `Ai` should form their own cohorts is an open management decision (`docs/DECISIONS.md`).

## Reproduction

The queries below are read-only.

```graphql
query { boards(ids: ["5091110326"]) { items_count columns(ids: ["dropdown_mm062ga0"]) { settings_str } } }
```

`board_insights` on board `5091110326`, grouped by `group`, `COUNT_ITEMS`, with filters on `dropdown_mm062ga0`:

- v1.1 resolved: `is_not_empty` AND `not_any_of` [every ID except 5, 8, 16]
- v1.1 mixed: `any_of` [5, 8, 16] AND `any_of` [every other ID]
- blank: `is_empty`
- orphan check: `is_not_empty` AND `not_any_of` [all 25 registered IDs]; returns no rows
