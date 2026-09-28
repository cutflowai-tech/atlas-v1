# REAL-004: live operational validation (2026-09-28)

This is the first live read-only ingestion of board `5091110326` ("Customer Projects"), run from `main` at `5b48e3d` (contract 1.4.0, editor-profile 1.4.0). All Monday access used `ReadOnlyMondayClient`, which sends GraphQL `query` operations only. The token was never printed or stored. Raw files stay outside git under `~/.atlas/raw/monday/`.

## 1. Runs

| | Run A (pre-fix code) | Run B (with the section 4 fix) |
|---|---|---|
| Raw directory | `20260928T192149Z` | `20260928T192920Z` |
| Window | 2026-02-01T00:00:00Z .. 2026-09-28T19:21:50Z | 2026-02-01T00:00:00Z .. 2026-09-28T19:29:20Z |
| Retrieved at | 2026-09-28T19:24:52Z | 2026-09-28T19:32:21Z |
| `extract.json` SHA-256 | `39f401b4cb149641…` | `51c6e96fd4a2a62f…` |
| `manifest.json` SHA-256 | `2024ed52cf54be5a…` | `5fb8dbb991970355…` |
| `ingest_verify` (code at the time) | passed | passed |
| `ingest_verify` (fixed code) | **fails**: complete-history claim (section 4) | passed |

Run B is the reference for this report.

- A single read-only connectivity check (`boards(ids:…) { id name }`) succeeded before the ingestion ran.
- Commands: `ingest --since 2026-02-01T00:00:00Z`, `ingest_verify`, `scripts/real_data_analysis.py … 1.4.0`, `profile_cli build … editor-label-6`.

## 2. Ingestion checks (run B)

| Check | Result |
|---|---|
| Pagination and cap | 43 windows, all read to the last page. The largest window held 5,641 logs against the 10,000 cap, so no window needed a split. |
| Window tiling | Both the `column_logs` and `all_logs` windows tile the coverage window exactly, with no gap and no overlap. |
| Duplicate events | None: 26,698 `update_column_value` and 1,509 `create_pulse` logs, with unique IDs. |
| SHA-256 integrity | All 131 raw files and `extract.json` match the manifest. |
| Logs outside the window | 0 |
| Snapshots | 1,295 items, each with a current-value snapshot. |
| Creation events | 1,290 of the 1,295 items have a `create_pulse`. The other 5 were moved in from other boards (section 4). |
| Complete history | 1,290 items: created on this board inside the window. |
| Evidence lineage | Will's profile cites 784 event IDs, and every one is present in the extract. His Requested ETA evidence is an activity-log event in 156 projects; the remaining project has no ETA. |

**Batch column changes.**
- The ingestion keeps only per-item `update_column_value` logs. The board also has 1,264 `batch_change_pulses_column_value` logs.
- Those logs cover 1,596 item changes to tracked columns. For 1,595 of them, Monday also wrote a per-item `update_column_value` log within 60 s.
- The remaining change is item `2914951697` on 2026-05-23 13:41:08: a batch set 13 items to `In Progress` (index 9). This item had already been `In Progress` since 05-19 16:16:48, so the change was a no-op. Monday wrote no per-item log, and nothing is lost.

## 3. Metrics compared with REAL-003 (contract 1.4.0)

| | REAL-003 reference extract (17:45:30Z) | Live run B |
|---|---:|---:|
| Items on the board | 1,291 | 1,295 |
| Completed first cycles | 861 | 861 |
| Completed cycles with a verified Editor | 170 | 170 |
| Speed-eligible | 147 | 147 |
| Deadlines classified, verified Editors | 142: 24 early / 0 on time / 118 late | 142: 24 / 0 / 118 |
| Date-only ETA / missing ETA / other | 9 / 1 / 18 | 9 / 1 / 18 |
| Contract 1.3.0 (D1, latest ETA) | 98 early / 44 late | 98 / 44 (run A) |
| Will: completed / speed-eligible | 157 / — | 157 / 134 |
| Will deadlines | 129: 20 early / 109 late | 129: 20 / 109 |
| Will monthly deadline rows (04–09) | section 6 | identical |
| Will results with ignored post-RFA ETA changes | 67 + 9 ETA changes | 76 |
| Section 3 spot-check (16 projects) | 16/16 | 16/16 (run A) |

**Will (editor-label-6), run B:**
- **Quality:** 26 Performance Issues occurrences on 24 of 157 projects: Late Delivery 20, Poor Communication 5, `3- Technical Issues` 1. There are 233 quarantined occurrences overall: 174 with an unresolved Editor and 59 with no completed cycle.
- **Revision context (context only):** 135 of 157 projects had client revisions: 314 client revision events and 99 internal ones.
- **Current workload, by current Monday status (descriptive):** Sent 126, Done 42, Revisions 1, Internal Revisions 1.
- **Speed:**
  - Class A (`4`): Will's median is 38.2 h over 37 projects. The team median is 42.4 h over 44 projects and 5 Editors, so the result is `faster_than_team_median`.
  - Ai + Class A (`16:4`): 36.8 h over 5 projects, `equal_to_team_median`.
  - `10:4` and `10:16:4`: `insufficient_sample`.
  - Every other cohort is `not_comparable`: either Will is the only Editor, or the cohort is not benchmark-eligible.
  - The Class A team includes 7 cycles by labels 15–18 (Sobhy, Ezz, Ali, Mohamed Mansour (Office)). These labels are mapped in `monday-editor-v1.1`.

**Exclusions and quarantines (unchanged from REAL-003):**
- **Completed-cycle exclusions:** `UNMAPPED_EDITOR` 518, `MISSING_EDITOR_EVENT` 162, `UNMAPPED_STATUS_WITHIN_CYCLE_WINDOW` 120, `EDITOR_CHANGED_WITHIN_CYCLE` 11, `MISSING_EDITOR` 10, `MISSING_VIDEO_TYPE_EVENT` 1.
- **Quarantined status logs:** `Uploading` 627, cleared 220, `Editing Now` 51, unresolved label 34, `Downloaded` 22, `Downloading` 22, `For Social Media` 22, `Ready For Review` 17, `Coloring` 6, `Captions` 2, `Not Started` 1.

**Differences and their causes:**

| Difference | Classification | Evidence |
|---|---|---|
| Items 1,291 → 1,295 | Legitimate new Monday activity | 4 items were created after the reference (19:18:21Z–19:23:23Z): `3248895716`, `3248936722`, `3248937694`, `3248891843`. |
| 35 logs after the reference in run A, 17 items touched; open cycles 306 (run A) → 307 (run B) | Legitimate new Monday activity | Status 18, Requested ETA 13, Editor 1, `create_pulse` 3. None of them changes a completed first cycle: every metric count is unchanged, and `scripts/compare_profiles.py` shows Will's 157 projects identical between runs A and B. |
| 6 items declared "complete history" in run A | **Ingestion defect**, fixed in section 4 | 5 items moved in from other boards; 1 created after `until`. |

## 4. Defect: complete-history claim for items without a creation event

**Symptom (run A):**
- `complete_history_item_ids` included 6 items whose history is not all in the ingestion:
  - `2874613517`, moved in from board "Moore Realestate" at 2026-04-28 00:30:21Z, 32 s after its creation;
  - `2874871775`, `2874871855`, `2874880210` and `2874925934`, moved in from "Explore One Media" at 04:54:34Z, about 46 s after their creation (`move_pulse_into_board`);
  - `3248891843`, created at 19:23:23Z, after `until` (19:21:50Z) but before the items read.
- None of these items has a `create_pulse` on this board inside the window.
- The rule declared history complete for any item created at or after `since`. It checked neither `until` nor whether a creation event had been read.
- `ingest_verify` applied the same rule, so it did not detect the problem.

**Impact:**
- Evidence lineage only. The flag sets `requested_eta_history_coverage.status`, and no metric value depends on it.
- Will's project `2874871855` was labelled `complete`. It is now `observed_in_ingested_evidence`.
- Its deadline result is unchanged.

**Fix:**
- History is complete only for an item created on this board with `since <= created_at < until` whose `create_pulse` was read.
- `ingest_verify` applies the same bound, reports `items_created_after_window`, and fails a run that claims more.
- Regression test: `tests/test_ingest.py::test_items_moved_in_or_created_after_the_window_are_not_complete`. It fails on the previous code.
- No contract, schema or business-rule change.

## 5. Remaining business and data blockers (unchanged)

- **Open decisions 1–5 in `docs/DECISIONS.md`:**
  - Editor identities for labels 4, 5, 7, 8, 9, 10 and 11: 518 cycles are quarantined.
  - Unclassified Video Type labels `Unbranded` and `Reels Boost Pack`.
  - Retired statuses: they exclude 120 completed cycles, 23 of them Will's.
  - Conceptual status aliases.
  - Active-workload statuses.
- **Historical Editor coverage:** there are no Editor Name logs before 2026-03-14, so 162 cycles are `MISSING_EDITOR_EVENT`.
- **Speed comparisons:** for Will, most cohorts contain only Will, so only Class A and Ai + Class A are comparable.
