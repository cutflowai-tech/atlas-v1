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

## Confirmed by Waset management, 2026-09-28 (second round) — contract 1.3.0

| # | Decision | Runtime encoding |
|---|---|---|
| D14 | **Initial Video Type classification.**<br>Base types: Class A (4), Class B (5), Simple Short (6), Class A+ (8), Premium Short (27).<br>Modifiers: 2* (10), Ai (16).<br>All other labels are unclassified. | `video_type_cohorts.classification`. Exact combinations stay distinct cohorts; a cohort containing an unclassified label is not benchmark-eligible. |
| D15 | **Median** is the approved team speed benchmark. Benchmark and Editor sample sizes are always shown; a typical range may be shown descriptively. | `speed_benchmark.benchmark_statistic_status`.<br>Results carry `team_typical_range_seconds` (P25–P75, descriptive only), `editor_range_seconds` and `editor_vs_team_median_pct`. |
| D16 | Editors are verified **only with authoritative evidence**; project counts, display names and actors are not evidence. Label 6 is corrected to Will only if evidence confirms it. | `monday-editor-v1.1`: label 6 display name is `Will` (the only name the label has carried in every Monday observation).<br>Every entry is guarded by its recorded `label_names`, because Monday reused label IDs 5, 7, 9 and 11 for different people.<br>Labels 1, 4, 5, 7, 8, 9, 10 and 11 stay unmapped. |
| D17 | Projects without reliable historical Editor Name evidence stay excluded; the current value is never backfilled. | `editor_attribution.historical_coverage` (`MISSING_EDITOR_EVENT`). |
| D18 | Retired statuses (`Uploading`, `Editing Now`, `Ready For Review`, …) get no meaning without authoritative evidence. | They remain quarantined; affected cycles stay excluded (`UNMAPPED_STATUS_WITHIN_CYCLE_WINDOW`). |

D4–D10 are reconfirmed unchanged: minimum sample of 5, team includes the Editor, date-only ETA not classifiable, no tolerance, For Bonus context only, and Video Type at or before Ready For Approval. Revisions remain context only, and actor attribution stays deterministic.

## Confirmed by Waset management, 2026-09-28 (third round) — contract 1.4.0

| # | Decision | Runtime encoding |
|---|---|---|
| D19 | **The deadline Requested ETA is frozen at the first Ready For Approval.** The ETA used for a completed cycle is the latest valid Requested ETA observed at or before that cycle's first Ready For Approval. Later ETA changes, such as the reset when a project enters Revisions, never change that cycle's classification. **For contract 1.4.0 onward this replaces D1**; contracts 1.2.0 and 1.3.0 keep D1 unchanged for reproducibility. | `deadline.rule_version = deadline-v1.2`; `requested_eta_selection = latest-valid-requested-eta-at-or-before-first-ready-for-approval`; `deadline-metric-v1.2.schema.json`; `editor-profile-v1.4.schema.json`.<br>Logged changes and creation values are placed by their Monday timestamps. The current item value is used only when the item has no logged ETA and Monday's `changed_at` for it is at or before Ready For Approval. Cleared values are skipped and recorded.<br>Later changes are listed in `ignored_later_requested_eta_changes`. With no ETA at or before Ready For Approval the result is `not_classifiable_missing_eta` with reason `NO_REQUESTED_ETA_AT_OR_BEFORE_READY_FOR_APPROVAL`; a later ETA is never backfilled. D5 (no tolerance) and D6 (date-only not classifiable) are unchanged. Evidence: `docs/evidence/REAL-003-OPERATIONAL-VALIDATION.md` sections 5–6. |

## Confirmed by Waset management, 2026-09-29 (handoff v2 grilling, round 1) — pending contract 1.5.0

These decisions are confirmed but **not yet encoded**. Until contract 1.5.0 encodes them, runtime behavior follows contract 1.4.0. The approver is the Atlas business owner (see D25).

| # | Decision | Runtime encoding |
|---|---|---|
| D20 | **`docs/HANDOFF-V2.md` is the product authority.** It overrides earlier wording in `SPEC.md`, `AGENTS.md`, `ARCHITECTURE.md`, `CONTRACTS.md` and `docs/ATLAS_V1_RULES.md` wherever they conflict. Decisions in this log refine the handoff where it leaves a rule open. | Documentation only. `SPEC.md` now states this and matches D5, D19 and transition-based actor attribution. |
| D21 | **Overall Status labels are `Strong`, `Good`, `Mixed` and `Below Expectations`.** `Under Pressure` is removed and, if a capacity rule is approved later, becomes a separate workload label, never a status. `Needs Attention` is not a status label. Scored inputs are only the Quality component (excluding lateness labels, see D27), the Speed component and the Deadline component. Revisions, current workload and Context labels are never scored. | Pending contract 1.5.0. Until thresholds are approved (D25) the status slot stays `rule_not_approved`. |
| D22 | **Two distinct pairs of findings.** A **Strength** or an **Attention Area** is a finding inside the current evaluation window. **Recognition** or **Needs Attention Now** is a flag raised by change between the current window and the comparison window. One Editor can have an Attention Area and a Needs Attention Now flag for the same metric. | Pending contract 1.5.0. |
| D23 | **Recent Change and Trend are separate.** Recent Change is the factual per-component difference between the current window (last 30 completed days) and the comparison window (the 30 completed days before it). Trend (`Improving`, `Stable`, `Declining`) is the deterministic interpretation of that difference and needs an approved minimum sample and material-change threshold; otherwise the fact is shown without a label. | Pending contract 1.5.0. |
| D24 | **Business days follow `Africa/Cairo`, not UTC.** Day boundaries, the 30-completed-day windows and monthly history use Cairo local time. A work cycle belongs to the window or month containing its Ready For Approval timestamp converted to Cairo time. "Last 30 completed days" excludes the current Cairo calendar day. **This is a deliberate metric-definition migration:** all historical and monthly aggregates are recomputed in Cairo time, and UTC and Cairo results are never mixed. Numbers that move near month boundaries compared with the UTC contracts are expected, not a bug; do not "fix" them back to UTC. | Pending contract 1.5.0. Contracts up to 1.4.0 keep UTC for reproducibility. |
| D25 | **Threshold approval.** The Atlas business owner approves business thresholds unless another named Waset manager is designated. A threshold is approved only when **both** a versioned configuration entry and a matching entry in this log exist. Until then Atlas shows the factual component result and "Not enough approved logic to classify", never an invented classification. | Process rule; applies to every contract from 1.5.0. |
| D26 | **Three quality label classes: Positive, Negative, Context.** Negative is the seven labels of `monday-performance-issues-v1.0`. For Bonus stays Context (D10). Handoff examples (Exceptional Quality, Client Praise, On Time Delivery as Positive; Additional Revisions, High Workload as Context) join a class **only after they are verified in live Monday data**; they are never added to a contract just because the handoff names them. Context labels are shown but never scored and never count as Strengths. | Pending live schema verification and contract 1.5.0. |
| D27 | **Lateness is scored once.** The computed Deadline component is the authoritative measure of early, on-time and late. The `Late Delivery` and `On Time Delivery` labels stay visible in the label breakdown and evidence, but are excluded from the Quality component that feeds Overall Status. | Pending contract 1.5.0. |

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
| A faster/slower conclusion also needs at least one other eligible Editor in the cohort; if the team is only the subject Editor, the result is `no_other_editors_in_cohort` / `not_comparable`, with all data shown. | On real data most cohorts contain only Will, so the "team median" would be his own median. | Conclude against the Editor's own median. |
| Editor Profile workload and monthly figures are descriptive only (editor-profile 1.3.0): current items grouped by current Monday status; monthly speed medians only per exact benchmark-eligible cohort, with sample sizes; monthly deadline counts and rates. No score, capacity or pressure rating, and no improving/declining conclusion. | Management asked for current state and monthly context without judgement. | — |
| Median of an even-sized sample = mean of the two middle values, floored to whole seconds. | The contract stores integer seconds. | — |

## Open decisions

1. **Editor identities:** Mario (4), Ibrahim (9), Samra (8), Amir (10), Anas (5), Martin (7) and Refaat (11) cannot be verified from Monday. See `docs/evidence/REAL-002-VALIDATION.md` for the identity evidence and the label-reuse history.
2. **Unclassified Video Type labels** that appear in real cohorts: `Unbranded` (26) and `Reels Boost Pack` (22). Other unclassified labels do not yet appear in eligible cycles.
3. **Retired statuses:** what did `Uploading`, `Editing Now`, `Ready For Review`, `Coloring`, `Downloaded`, `Downloading`, `For Social Media`, `Captions` and `Not Started` mean? The answer needs authoritative evidence, such as a documented workflow or a management attestation. They exclude 120 completed cycles.
4. **Conceptual status aliases:** is `Create File` the "Ready to Edit" status, and is `Ready To Send` / `Done` "Approved / Delivered"? These are context only; no metric depends on them.
5. **Active workload statuses:** which current statuses count as an Editor's active work. Until this is decided, the profile lists current items by status without totals or judgement.
6. **Resolved by D19 (contract 1.4.0).** Requested ETA reset at Revisions (formerly blocked the deadline section). Evidence is in `docs/evidence/REAL-003-OPERATIONAL-VALIDATION.md` section 5.
   - When a project enters `Revisions`, the shared account sets Requested ETA to the change time + 24 h. This affected 82 of 142 classified projects.
   - D1 (latest ETA, even after RFA) therefore shows 98 early / 44 late, against 24 early / 118 late using the ETA in effect at Ready For Approval.
   - 16 of the 17 `Late Delivery`-labelled projects show as early under D1.
   - Options:
     - keep D1;
     - use the latest ETA set at or before Ready For Approval (deadline-v1.2, a new contract version);
     - keep D1 but ignore only the changes made when a project enters Revisions.
   - Recommendation: the latest ETA set at or before Ready For Approval. It still honours ETA changes made before the Editor submits, and it cannot be moved by later client revisions.
