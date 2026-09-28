# Atlas V1 decision log

These product decisions drive runtime behavior. Each one is encoded in a versioned executable contract (`config/monday-contract-v*.json`), so historical results stay reproducible. Changing a decision requires a new contract version; an approved contract is never edited in place.

## Confirmed by Waset management, 2026-09-28 (contract 1.2.0)

| # | Decision | Runtime encoding |
|---|---|---|
| D1 | Deadline uses the **latest available Requested ETA**, even if it changed after Ready For Approval: `delta = ready_for_approval_at − latest_requested_eta`. | `deadline.requested_eta_selection`.<br>`reconstruct_cycles(..., items_payload=...)` treats the current item value as the latest; if it disagrees with the last logged value, the cycle is flagged `REQUESTED_ETA_SNAPSHOT_DIFFERS_FROM_LOG`.<br>ETA values observed in the ingested evidence (item creation, logged changes, item snapshot) are in `evidence.source_values.requested_eta_history`, with `requested_eta_history_coverage`. |
| D2 | Only the **first completed** `In Progress → Ready For Approval` cycle feeds Speed / Work Duration. Later cycles are kept in evidence. | `cycle_attributes.cycle_selection`; `post_cycle_event_ids`; `later_ready_for_approval_event_ids`. |
| D3 | Duration is **elapsed clock time**. Nights, weekends, holidays and non-working hours are not removed. | `cycle_attributes.duration`. |
| D4 | **At least 5 completed projects** for the Editor in the same exact eligible cohort before any faster/slower conclusion. Below that, observed values and sample sizes are shown with conclusion `insufficient_sample`. | `speed_benchmark.minimum_editor_sample_size = 5`. |
| D5 | Deadline is **early** (`delta < 0`), **on_time** (`delta == 0`) or **late** (`delta > 0`). There is **no tolerance**. | `deadline-metric-v1.1.schema.json`; `metrics.classify_deadline`; `deadline_summary`. |
| D6 | A **date-only Requested ETA** is excluded from early/on-time/late and reported as `not_classifiable_insufficient_eta_precision`. No time is ever invented. | `deadline.date_only_requested_eta`; `metrics.deadline_not_evaluated`. |
| D7 | The **team benchmark includes the Editor being evaluated**: the whole eligible team in the same exact cohort, not leave-one-out. | `speed_benchmark.team_population`; `team_includes_subject_editor: true`. |
| D8 | A completed cycle's Video Type is the **latest valid Video Type at or before its Ready For Approval**. Later changes never alter that cohort. | `cycle_attributes.video_type`.<br>The item's creation value (`create_pulse`) counts as its first observation.<br>Cleared values are skipped; the chosen event, its source and the skipped events are kept as evidence. |
| D9 | Mario, Anas, Martin, Ibrahim, Amir and Refaat are **not** added to the Editor mapping just because their labels exist. Their work stays quarantined until each is verified as an Editor with a stable identity. | `monday-editor-v1.0` is unchanged (`UNMAPPED_EDITOR`). Evidence: `docs/evidence/REAL-001-STATUS.md`. |
| D10 | **For Bonus** is context only. It is neither a positive nor a negative quality signal in V1. | `quality_labels.for_bonus.affects_quality = false`. |
| D11 | Status semantics are **not guessed**. Only verified renames are mapped, and unknown states stay quarantined. | `monday-status-v1.1`: index-bound aliases (`Ready To Sent`/`ready to sent` → `Ready To Send`, `Creat File` → `Create File`).<br>Retired labels are quarantined; a retired label at or before a cycle's Ready For Approval excludes that cycle from metrics.<br>Transition roles cover verbatim labels only. |
| D12 | **Base types vs modifiers must be confirmed.** A label's existence in Monday does not make it a comparable cohort. Exact combinations stay distinct. | `video_type_cohorts.classification`: no label confirmed yet.<br>A cohort is benchmark-eligible only when every label is a confirmed base or modifier and at least one is a base; otherwise the result is `cohort_not_benchmark_eligible` / `not_comparable`. |
| D13 | The **benchmark statistic is not locked** until a mean-vs-median analysis has been reviewed. | Runtime keeps the median, marked provisional (`speed_benchmark.benchmark_statistic_status`).<br>Analysis and recommendation: `docs/evidence/BENCHMARK-STATISTIC-ANALYSIS.md`. |

## Verified from Monday evidence (no business judgement involved)

- **Video Type mapping `monday-video-type-v1.2`:**
  - It contains all 25 label IDs with their verbatim names from the live column settings, plus the former names of IDs 6, 7 and 17 (accepted only together with the same ID). It is a superset of v1.1 with unchanged IDs.
  - It only *resolves* labels. Whether a label is a comparable business Video Type is D12.
- **Status label renames:**
  - Aliases bind to Monday's status label index.
  - Indexes that Monday reused for a different label (8, 10, 12, 14) are not aliased.
- **Quality registry `monday-performance-issues-v1.0`:** the seven live Performance Issues labels, resolved by ID. Former names of IDs 3, 4, 5 and 7 (without the numeric prefix) are accepted only together with the same ID. The rule is 1 occurrence = 1 point, with no severity weights.
- **Creation values:** `create_pulse.column_values_json` records the value an item was created with, with a real Monday timestamp.

## Engineering defaults (still open; not management decisions)

These defaults are deterministic, versioned and visible in evidence. They exist only because the code needs a rule to run, and they can change only through a new contract version.

| Default | Why a rule is needed | Alternative |
|---|---|---|
| Editor of a cycle = Editor Name value in effect at Ready For Approval, from column events or the creation value. A change inside the cycle quarantines it. | Editor Name is sometimes edited after work starts. | Latest Editor Name value. |
| A quality occurrence is attributed to the Editor of the item's first completed cycle; if that Editor is unresolved, the occurrence is quarantined. The current Monday value is authoritative (a removed label does not count). | A label sits on a project, not on a person. | Editor in effect when the label was added. |
| Median of an even-sized sample = mean of the two middle values, floored to whole seconds. | The contract stores integer seconds. | — |

## Open decisions (evidence in `docs/evidence/REAL-001-STATUS.md`)

1. **Base vs modifier Video Types (D12):** which label IDs are confirmed base types and which are modifiers? Until any base type is confirmed, no speed benchmark is produced.
2. **Editor identities (D9):** labels 4 Mario, 9 Ibrahim, 8 Samra (deactivated), 10 Amir, 5 Anas, 7 Martin and 11 Refaat account for 518 of 861 completed cycles.
3. **Editor registry corrections:** the approved `monday-editor-v1.0` names label 6 "Synthetic Editor" (the live label is "Will"). Labels 12 Ahmed, 13 Michael and 14 Mansour have no Editor cycles and appear in the Reviewer column.
4. **Items worked before the Editor Name column existed (before 2026-03-14):** they have no Editor Name event, and 162 completed cycles are excluded as `MISSING_EDITOR_EVENT`.
5. **Retired statuses:** what did `Uploading` (627 logs, Feb–Jul), `Editing Now`, `Coloring`, `Downloaded`, `Downloading`, `For Social Media`, `Ready For Review`, `Captions` and `Not Started` mean? They exclude 120 completed cycles.
6. **Conceptual status aliases:** "Ready to Edit" is a Monday group, not a status. Is `Create File` the "Ready to Edit" status, and is `Ready To Send` (and/or `Done`) "Approved / Delivered"? Those transitions stay `unresolved`.
7. **Benchmark statistic (D13):** the analysis recommends the median.
