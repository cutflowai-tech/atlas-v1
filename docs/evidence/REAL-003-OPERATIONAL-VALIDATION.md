# REAL-003: operational validation (2026-09-28)

Covers `main` at `d51a9f7`: contract 1.3.0 and editor-profile 1.3.0. All Monday access in this report was read-only.

## 1. Live ingestion: `MISSING_ACCESS`

`MONDAY_API_TOKEN` is not set in the runtime, so `atlas_commander.ingest` stops with exit code 2 before writing anything. The live ingestion has **not** been run, and none of the numbers below come from it.

Once a read-only token is available as `MONDAY_API_TOKEN`, run:

```sh
RUN=~/.atlas/raw/monday/$(date -u +%Y%m%dT%H%M%SZ)
PYTHONPATH=src python3 -m atlas_commander.ingest --since 2026-02-01T00:00:00Z --raw-dir "$RUN"
PYTHONPATH=src python3 -m atlas_commander.ingest_verify "$RUN"
PYTHONPATH=src python3 scripts/real_data_analysis.py "$RUN/extract.json" 1.3.0 > "$RUN/analysis.json"
PYTHONPATH=src python3 -m atlas_commander.profile_cli build "$RUN/extract.json" editor-label-6 "$RUN/profile"
```

- `--until` defaults to the time of the run.
- `ingest_verify` must report `"passed": true` before the extract is used.
- Compare `analysis.json` → `validation` with section 4.
- Compare the Will profile with `scripts/compare_profiles.py <reference> "$RUN/profile/editor-label-6.json"` when a reference profile is available. Also re-check the projects in section 3.

## 2. Ingestion behaviour verified without the token

**Window boundaries (live, read-only probe).**
- Queried board `5091110326` for the whole of 2026-09-20, then for the two halves split at `11:55:36Z`, which is the whole second of the log created at 11:55:36.39.
- The log appeared only in the later half.
- The two halves together equalled the whole day, with no log in both halves and none missing.
- `from` is therefore inclusive and `to` exclusive. Windows split at any instant tile the range without gaps or overlaps.
- The ingestion also de-duplicates by activity-log ID. A test that simulates an API returning logs at the upper bound too shows a boundary log is still kept exactly once.

**Offline verifier (`python3 -m atlas_commander.ingest_verify <raw_dir>`).** It checks:
- every raw file and `extract.json` against the SHA-256 in `manifest.json`;
- that every read window finished below the 10,000-log cap, with capped windows split;
- that the finished windows of each kind tile the declared coverage window exactly;
- that there are no duplicate log IDs;
- that extract counts equal manifest counts;
- that every log lies inside the window;
- that every item has a current-value snapshot;
- `create_pulse` coverage of items created inside the window, which is reported, not assumed;
- that the complete-history item list is exactly the items created inside a fully read window.

Tests cover plain runs, split runs, a tampered raw file and a boundary log (`tests/test_ingest.py`).

## 3. Manual spot-check: 16 Will projects (reference extract)

**Data:** the read-only reference extract (retrieved 2026-09-28T17:45:30Z, SHA-256 `d38c848d4a9c4b16…`), not a live ingestion. Each value was read directly from the raw activity logs, then compared with Will's editor-profile 1.3.0 row (profile SHA-256 `2221867ae61e76b8…`).

**Sample:** chosen to cover:
- early and late deadlines;
- a date-only ETA and a missing ETA;
- Performance Issues labels and client revisions;
- a multi-label Video Type and an unclassified Video Type;
- retired-status exclusions.

| Item | Work start (first In Progress) | Ready For Approval (first) | Video Type at RFA | Latest ETA → result | ETA in effect at RFA → result | Quality labels | Client revisions | Matches evidence |
|---|---|---|---|---|---|---|---:|:---:|
| 3226750738 | 09-16 12:55:00 | 09-17 08:16:13 | Ai + Class A (`16:4`; 2* removed before RFA) | 09-17 21:00 → early | same → early | — | 0 | yes |
| 3229253960 | 09-17 12:02:30 | 09-18 19:26:17 | Class A | 09-18 21:00 → early | same → early | — | 0 | yes |
| 2862511875 | 04-24 09:54:38 | 04-24 22:05:38 | Class B | 04-24 01:00 (creation value) → late | same → late | — | 2 | yes; Mario set and removed before Will |
| 2935538521 | 05-23 13:41:08 | 05-26 15:23:44 | Simple Short (logged under former name `Short`) | 05-24 13:00 → late | same → late | — | 0 | yes; Waiting inside the cycle counts as elapsed time |
| 3112446647 | 07-25 03:27:41 | 07-27 06:52:42 | Class A | 07-26 21:00 → late | same → late | — | 0 | yes; Internal Revisions are not client revisions |
| 3218569766 | 09-11 11:47:16 | 09-13 20:10:39 | Class A | **09-14 20:44:38 → early** | 09-13 09:00 → **late** | Late Delivery | 1 | yes (see section 5) |
| 3040779228 | 07-01 21:23:35 | 07-03 18:40:40 | Simple Short (`Short`) | **07-07 13:54:19 → early** | 07-02 21:00 → **late** | Late Delivery, Poor Communication | 1 | yes (see section 5) |
| 3162534522 | 08-14 19:23:56 | 08-17 20:00:12 | Class B | **08-22 14:23:57 → early** | 08-16 09:00 → **late** | Late Delivery | 3 | yes (see section 5) |
| 2856384141 | 04-21 10:57:24 | 04-24 06:22:32 | Class B | 04-22 21:00 → late | same → late | — | 4 | yes; first In Progress lasted 2 s before Create File (see note) |
| 3097988391 | 07-21 01:07:53 | 07-21 20:26:17 | Premium Short | 07-24 23:52:27 → early | 07-21 21:00 → early | — | 3 | yes |
| 3139361369 | 08-05 09:08:19 | 08-07 21:33:30 | Unbranded + Class A (`26:4`, not benchmark-eligible, not in monthly speed) | **08-08 22:06:51 → early** | 08-06 21:00 → **late** | — | 1 | yes |
| 2995254472 | 06-14 12:31:13 | 06-17 14:01:02 | Walkthrough Reel + Class B (`24:5`) | excluded: `Uploading` inside the window | — | — | 2 | yes; retired status quarantined |
| 3009253614 | 06-18 20:41:41 | 06-21 06:28:27 | Class A | excluded: `Uploading` inside the window | — | Late Delivery | 0 | yes |
| 2814764323 | 04-03 20:32:40 | 04-04 22:00:58 | Class A | date-only `2026-04-03` → not classifiable | — | — | 1 | yes; the Editor was toggled but was Will at RFA |
| 2924804207 | 05-28 15:55:23 | 05-30 06:45:10 | 2* + Ai + Class A (`10:16:4`) | 05-29 15:00 → late | same → late | — | 2 | yes |
| 2821483740 | 04-03 20:32:38 | 04-05 18:07:52 | Class A | no ETA ever set → missing | — | — | 2 | yes |

**Result:** 16 of 16 rows match the raw Monday evidence under the approved rules. The Editor was `Will` (label 6) at RFA on every row. No implementation defect was found.

**Note (no change made):** on 2856384141 and 2995254472 the first In Progress lasted seconds before a return to Create File. Work start follows the approved first-entry rule, which adds about 1.5 h and 13.5 h of elapsed time respectively.

## 4. Reference counts

Reproduced exactly from the reference extract on `main` `d51a9f7` (contract 1.3.0):

| | Count |
|---|---:|
| Total items | 1,291 |
| Completed first cycles | 861 |
| With a verified Editor | 170 |
| Speed-eligible | 147 |
| Deadlines classified | 142 (early 98, on time 0, late 44) |
| Date-only ETA | 9 |
| Missing ETA | 1 |

## 5. Finding: Requested ETA is reset when a project enters Revisions

**Evidence:**
- 84 of the 142 classified projects had their Requested ETA changed after Ready For Approval.
- In 82 of those 84 projects, every post-RFA change came within 10 s of the item entering `Revisions`.
- On those projects there are 170 post-RFA ETA changes. All were made by user `99154021` ("Waset Co Studio", the shared account).
- 157 of the 170 set the ETA to exactly the change time + 24 h, and 10 to + 12 h.
- No native Monday automation on the board writes the date column. Its active automations are status and column webhooks owned by the same account, which is consistent with an external integration resetting the ETA as a revision deadline. The integration itself has not been identified.

**Effect under the approved rule (D1: latest available Requested ETA, even if changed after RFA):**

| Verified Editors, 142 classified | Latest ETA (current rule) | ETA in effect at RFA |
|---|---:|---:|
| Early | 98 | 24 |
| Late | 44 | 118 |

- 74 projects are late against the ETA in effect at RFA but early against the latest ETA.
- 17 classified projects carry the Monday Performance Issues label `Late Delivery`. The current rule shows 16 of them as **early**.
- Will's monthly deadline figures:

| Month | Latest ETA early / late | ETA at RFA early / late | Projects with a post-RFA ETA change |
|---|---|---|---:|
| 2026-04 | 2 / 13 | 2 / 13 | 0 |
| 2026-05 | 3 / 9 | 2 / 10 | 1 |
| 2026-06 | 11 / 14 | 1 / 24 | 10 |
| 2026-07 | 26 / 5 | 2 / 29 | 26 |
| 2026-08 | 24 / 1 | 3 / 22 | 23 |
| 2026-09 | 21 / 0 | 10 / 11 | 16 |

The apparent late-to-early shift from April to September follows the start of the ETA resets, not a change in delivery.

**Status:**
- The implementation applies D1 exactly as approved, so this is not an implementation defect.
- D1 was approved before this evidence was available.
- Changing it needs a management decision and a new contract version; see `docs/DECISIONS.md`, open decision 6.
- Until then, the deadline section of the Editor Profile is not reliable for internal use.
