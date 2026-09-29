# Atlas V1 decision log

These product decisions drive runtime behavior. Each one is encoded in a versioned executable contract (`config/monday-contract-v*.json`), so historical results stay reproducible. Changing a decision requires a new contract version; an approved contract is never edited in place.

> **Implementation status, 2026-09-29:** D20–D50 are now encoded in the loadable contract 1.5.0 candidate and its deterministic runtime/profile/publication path. The `Pending contract 1.5.0` wording retained in the decision-round tables records the status when each decision was captured; it is no longer the implementation status. Production is deliberately still pinned to contract 1.4.0, all D44-blocked thresholds remain `null`/`rule_not_approved`, and the seven unattested identities remain unresolved. No deployment or production activation is authorized by this log update.

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

## Confirmed by Waset management, 2026-09-29 (handoff v2 grilling, round 2) — pending contract 1.5.0

Also not yet encoded; contract 1.4.0 behavior applies until contract 1.5.0. Refines D26.

| # | Decision | Runtime encoding |
|---|---|---|
| D28 | **For Bonus is a storage location, not a category. This replaces D10 from contract 1.5.0** (contracts 1.2.0–1.4.0 keep D10). Each label of the live `For Bonus` column (`dropdown_mm3tyvvc`) is classified on its own. **Positive:** `1- Exceptional Quality`, `Client Praise`, `On Time Delivery`, `Saved Rush Project` (D29). **Context:** `High Workload`, `Additional Revisions`. The Performance Issues column keeps its seven Negative labels. | Pending contract 1.5.0: per-label classes for both columns. |
| D29 | **`Saved Rush Project` is Positive.** It is management-recorded evidence of delivery under exceptional time pressure and may feed Strengths, Recognition and positive-signal counts and rates. It never adds a separate speed or deadline bonus: one delivery is not rewarded twice across components. | Pending contract 1.5.0. |
| D30 | **Scored vs visible quality.** The visible quality and evidence layer shows every supported Positive and Negative label, with Context labels shown separately. The scored Quality component excludes `On Time Delivery`, `Late Delivery` (D27) and every Context label. | Pending contract 1.5.0. |
| D31 | **Revision taxonomy: Client Revision and Internal Revision.** A transition into `Revisions` is a Client Revision; a transition into `Internal Revisions` is an Internal Revision. Both are context only: neither reduces Quality or Overall Status, counts as Editor fault, or triggers a negative signal by itself having happened. No cause beyond "client" or "internal" is inferred without explicit Monday evidence. Where revision detail is shown, client and internal projects and events are shown separately; a combined "total revision activity" may be added only alongside them. | Pending contract 1.5.0. |
| D32 | **Speed is first-pass work only (D2 reconfirmed).** Rework after a Client or Internal Revision never enters the Speed component. Where timestamps allow, client and internal rework durations may be shown as non-scoring context. | D2 unchanged; rework durations pending contract 1.5.0. |
| D33 | **Current Work.** *Active Work* is projects currently in `In Progress`, `Revisions` or `Internal Revisions`. *Awaiting Approval* is projects in `Ready For Approval`, counted separately because the next action belongs to production review. Not counted: `Waiting`, `Create File`, every Captions status, `TOPAZ`, `Ready To Send`, `Sent`, `Done`. Counts drill down by status. No `Under Pressure`, `High Load` or similar label comes from these counts without a separately approved capacity rule. Resolves open decision 5. | Pending contract 1.5.0. |
| D34 | **Handoff status names are concepts, not Monday strings.** See *Live status mapping* below. The aliases document the workflow only: historical events are never rewritten, missing transitions are never invented, and no metric depends on an alias. Editor performance logic uses the exact live statuses `In Progress`, `Ready For Approval`, `Revisions` and `Internal Revisions`. Resolves open decision 4. | Documentation only. |
| D35 | **A team comparison needs at least one other eligible Editor.** If the Video Type has no eligible Editor other than the one being viewed, Atlas shows "No valid team benchmark available" and never "faster", "slower" or "similar". This promotes the engineering default to a management decision. The minimum comparator sample for a strong conclusion belongs to the threshold round. Whether the viewed Editor is also removed from the benchmark (reversing D7) is **still open**. | Existing `no_other_editors_in_cohort` / `not_comparable` behavior. |

### Live status mapping

Monday board `5091110326`, `Status` column (`project_status`), verified 2026-09-29.

| Handoff concept | Live Monday status(es) | Used by metrics? |
|---|---|---|
| Ready to Edit | `Create File` and the pre-In Progress workflow (`Waiting`) | No |
| In Progress | `In Progress` | Yes (work start) |
| Ready For Approval | `Ready For Approval` | Yes (work end, deadline) |
| Revisions (client revision) | `Revisions` | Context only |
| (not in handoff) internal revision | `Internal Revisions` | Context only |
| Approved / Sent / Delivered | `Ready To Send`, `Sent`, `Done` | No |
| (not in handoff) captions workflow | `Captions In Progress`, `Captions Revisions`, `Waiting For Captions`, `Captions Done` | No |
| (not in handoff) | `TOPAZ` | No |

## Confirmed by Waset management, 2026-09-29 (handoff v2 grilling, round 3) — pending contract 1.5.0

Not yet encoded. Threshold values (N, P, bands, minimum samples, material change) are deliberately absent: under D25 they are set only after distributions from a real production ingest run have been measured and reviewed.

| # | Decision | Runtime encoding |
|---|---|---|
| D36 | **Leave-one-out team benchmark. Contract 1.5.0 supersedes D7** (contracts 1.2.0–1.4.0 keep D7). For Editor E and Video Type V, the benchmark sample is the valid first-pass projects in V from every *other* eligible Editor; E's own projects are excluded. The handoff's "whole editor team" means the eligible comparison population excluding the subject. D35 still applies: with no contributing other Editor, or below the comparator minimum set in round 4, Atlas shows "No valid team benchmark available". | Pending contract 1.5.0. |
| D37 | **Overall Status = component states + explicit lookup table.** Quality, Speed and Deadline each produce `Positive`, `Neutral`, `Negative` or `Not classifiable`. A versioned, reviewable lookup table in config maps the combination to `Strong`, `Good`, `Mixed`, `Below Expectations` or `Not enough evidence to classify`. No weighted composite, no hidden numeric score, no arithmetic behind the lookup. "Why this status?" is derived directly from the component states and their supporting metrics. | Pending contract 1.5.0; the table's contents are a round-4 decision. |
| D38 | **Speed component = project-weighted majority over Video Types.** Each eligible Video Type gets `Faster`, `Similar`, `Slower` or `Not classifiable` (bands set in round 4). Each classifiable verdict is weighted by the Editor's valid project count in that type. Majority (> 50%) Faster → Positive; majority Slower → Negative; majority Similar or no majority → Neutral; no classifiable type → Not classifiable. Percentage differences are never averaged across Video Types. Example: Faster 10, Similar 6, Slower 5 of 21 → no majority → Neutral. | Pending contract 1.5.0. |
| D39 | **Quality component = two rates per eligible completed project in the window.** Negative Quality Rate = scored Negative label occurrences (excluding `Late Delivery`) ÷ eligible completed projects. Positive Quality Rate = scored Positive label occurrences (`1- Exceptional Quality`, `Client Praise`, `Saved Rush Project`; excluding `On Time Delivery`) ÷ the same denominator. Context labels enter neither. Rule: Negative Rate ≥ N → Negative; else Positive Rate ≥ P → Positive; else Neutral. Below the minimum project sample → Not classifiable. Counts are always shown beside rates. | Pending contract 1.5.0; N, P and the minimum sample are round-4 values. |
| D40 | **Deadline component = Late %** = late ÷ deadline-classifiable projects, classified by the approved deadline rule (D5, D19). Early and on time both count as "not late"; being very early earns no extra credit. Early %, on-time %, late %, median Deadline Delta and median early/late margin may be shown, but only Late % drives the component. | Pending contract 1.5.0; cut-offs and minimum sample are round-4 values. |
| D41 | **Overall Status needs at least two classifiable scored components out of three**, at least one of them Quality or Deadline (with three components, every valid pair satisfies this). Otherwise the status is `Not enough evidence to classify` and every available component fact is still shown. A status is never fabricated to avoid an empty state. | Pending contract 1.5.0. |
| D42 | **One window anchor for everything.** A project belongs to the window containing its first valid Ready For Approval in `Africa/Cairo` time (D24). The same cohort feeds Quality, Speed, Deadline, Overall Status, Recent Change and Trend. A label added later never moves the project to a later window; the label's own timestamp is kept and shown in Evidence (metric cohort date ≠ evidence event date). | Pending contract 1.5.0. |
| D43 | **Ingest must capture the For Bonus column** (`dropdown_mm3tyvvc`) with each label's individual identity, never flattened into a boolean or a single category. Positive Signal logic is not implemented until this lands. | Raw capture already exists: production run `20260929T130736Z-e6d03314e704` lists `dropdown_mm3tyvvc` in `tracked_columns`. Pending contract 1.5.0: per-label parsing and classification in the pipeline. |

## Confirmed by Waset management, 2026-09-29 (handoff v2 grilling, round 4a) — pending contract 1.5.0

Context: distributions measured on production run `20260929T130736Z-e6d03314e704`. Only 170 of 861 completed first cycles were attributable to a mapped Editor; the seven unmapped labels carried 309 projects in the last 90 days against 91 for mapped Editors.

| # | Decision | Runtime encoding |
|---|---|---|
| D44 | **Identities before thresholds.** No threshold (Overall Status lookup, Trend, Speed bands, Quality N/P, Deadline bands, minimum samples) is calibrated or approved until the seven unmapped Editor labels (Ibrahim, Refaat, Martin, Anas, Amir, Mario, Samra) are resolved. Mappings are **date-aware**: `source label id, effective_from, effective_to, editor_id, editor name, evidence or attestation source`. Where Monday reused a label ID, a current display name never applies to earlier activity. A management or Production Manager attestation is acceptable authoritative evidence (refines D16) when Monday data cannot resolve reuse. Order: approve mappings → update the identity mapping → record the decision → re-run production distributions → only then propose round-4 values. Thresholds calibrated before this are never approved for production. | Pending a new editor mapping version and contract 1.5.0. |
| D45 | **Deadline facts stay absolute; the Deadline component is relative.** The factual layer (D5, D19: delta, early, on time, late, no tolerance) is unchanged, and no tolerance is added to improve the numbers. The Deadline Component State compares the Editor's late rate with the late rate of the **other** eligible Editors' deadline-classifiable projects in the same window (leave-one-out, as D36). Bands and minimum samples are round-4 values. With an insufficient comparator the component is `Not classifiable`; there is never a silent fallback to an absolute threshold. The UI shows both, e.g. "Deadline: better than team comparison · Absolute late rate: 56.5%", without implying that the absolute rate is good. Refines D40. | Pending contract 1.5.0. |
| D46 | **Team-wide lateness is a process question, not a scoring input.** In production data the team was 61–96% late in every 30-day window (90 days: 71 of 90 late, median 15.2 h), while only 11 of the 71 carried `Late Delivery`. This may reflect how Requested ETA is set or used. Atlas never compensates by changing facts; investigating ETA-setting is a management matter outside editor scoring unless a later decision changes the deadline definition. | Documentation only. |
| D47 | **Insufficient evidence is a data state, not a performance state.** Editors below minimum samples keep their Overview card, Editor Profile, every available fact, data coverage and evidence. Status and components show `Not enough evidence to classify` / `Not classifiable` with the reason (e.g. "5 completed projects · 3 deadline-classifiable · no valid Speed benchmark yet"). Never hidden, never given a provisional status, never defaulted to Neutral, never penalized for missing history. | Pending contract 1.5.0. |

## Confirmed by Waset management, 2026-09-29 (handoff v2 grilling, round 4b) — pending a new editor mapping version

Round-4 threshold calibration stays blocked (D44) until the attestations in [`docs/evidence/IDENTITY-ATTESTATION-REQUEST.md`](evidence/IDENTITY-ATTESTATION-REQUEST.md) are answered. Calibrating on the currently mapped Editors alone is not an acceptable substitute.

| # | Decision | Runtime encoding |
|---|---|---|
| D48 | **Historical identity key = `(source_label_id, logged_name)`**, not the label ID alone: `(9, "Michael")` and `(9, "Ibrahim")` are distinct identities. Monday preserves the name as logged at each change, so observed first/last dates are supporting evidence and validation bounds, not the primary disambiguation. A mapping record holds `source_label_id`, `logged_name`, `editor_id`, `canonical_editor_name`, `role`, `first_observed_at`, `last_observed_at`, `attestation_source`, `decision_id`. A new name appearing under a mapped label ID never inherits the mapping; it is unresolved until explicitly mapped. | Pending a new editor mapping version (extends the `label_names` guard in `monday-editor-v1.1`). |
| D49 | **Presence in Editor Name is not attestation.** `(4, "Mario")`, `(5, "Anas")`, `(7, "Martin")`, `(8, "Samra")`, `(9, "Ibrahim")`, `(10, "Amir")`, `(11, "Refaat")` stay unresolved, and `(5, "Ahmed")`, `(7, "Mans")`, `(9, "Michael")` are **not** merged into labels 12, 14 and 13, until management attests identity and Editor role for the observed range. Role is never inferred from a name, another Monday column (e.g. Reviewer), current role, label ID or project volume. The 2026-08-30 changes on labels 12–14 filled empty values and are not evidence of sameness. Unresolved projects stay visible in identity diagnostics and never enter calibration. | Existing `UNMAPPED_EDITOR` quarantine. |
| D50 | **Leftover labels are quarantined with a reason.** `(11, "New")` and `(2, "Done")` → `invalid_identity_value` (no Editor is ever created with those names). `(1, "El Baz")` → `unresolved_historical_identity` (possibly a real person; one project is not enough). Raw evidence is kept. None of the three enters Quality, Speed, Deadline, Trend or Overall Status calibration unless a later identity decision resolves them. | Pending a new editor mapping version. |

## Verified from Monday evidence (no business judgement involved)

- **Video Type mapping `monday-video-type-v1.2`:**
  - It contains all 25 label IDs with their verbatim names from the live column settings, plus the former names of IDs 6, 7 and 17 (accepted only together with the same ID). It is a superset of v1.1 with unchanged IDs.
  - It only *resolves* labels. Whether a label is a comparable business Video Type is D12.
- **Status label renames:**
  - Aliases bind to Monday's status label index.
  - Indexes that Monday reused for a different label (8, 10, 12, 14) are not aliased.
- **Quality registry `monday-performance-issues-v1.0`:** the seven live Performance Issues labels, resolved by ID. Former names of IDs 3, 4, 5 and 7 (without the numeric prefix) are accepted only together with the same ID. The rule is 1 occurrence = 1 point, with no severity weights.
- **For Bonus column (verified 2026-09-29):** `dropdown_mm3tyvvc` holds `1- Exceptional Quality` (1), `Saved Rush Project` (3), `Client Praise` (4), `On Time Delivery` (5), `High Workload` (6) and `Additional Revisions` (7), all active. Every Positive and Context label named in `docs/HANDOFF-V2.md` §9 exists here; none is in Performance Issues.
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

1. **Editor identities (blocks round-4 thresholds, D44/D49):** Mario (4), Ibrahim (9), Samra (8), Amir (10), Anas (5), Martin (7) and Refaat (11) cannot be verified from Monday; attestation requested in `docs/evidence/IDENTITY-ATTESTATION-REQUEST.md`. See `docs/evidence/REAL-002-VALIDATION.md` for the identity evidence and the label-reuse history.
2. **Unclassified Video Type labels** that appear in real cohorts: `Unbranded` (26) and `Reels Boost Pack` (22). Other unclassified labels do not yet appear in eligible cycles.
3. **Retired statuses:** what did `Uploading`, `Editing Now`, `Ready For Review`, `Coloring`, `Downloaded`, `Downloading`, `For Social Media`, `Captions` and `Not Started` mean? The answer needs authoritative evidence, such as a documented workflow or a management attestation. They exclude 120 completed cycles.
4. **Resolved by D34.** Conceptual status aliases: is `Create File` the "Ready to Edit" status, and is `Ready To Send` / `Done` "Approved / Delivered"? These are context only; no metric depends on them.
5. **Resolved by D33.** Active workload statuses: which current statuses count as an Editor's active work. Until this is decided, the profile lists current items by status without totals or judgement.
6. **Resolved by D19 (contract 1.4.0).** Requested ETA reset at Revisions (formerly blocked the deadline section). Evidence is in `docs/evidence/REAL-003-OPERATIONAL-VALIDATION.md` section 5.
   - When a project enters `Revisions`, the shared account sets Requested ETA to the change time + 24 h. This affected 82 of 142 classified projects.
   - D1 (latest ETA, even after RFA) therefore shows 98 early / 44 late, against 24 early / 118 late using the ETA in effect at Ready For Approval.
   - 16 of the 17 `Late Delivery`-labelled projects show as early under D1.
   - Options:
     - keep D1;
     - use the latest ETA set at or before Ready For Approval (deadline-v1.2, a new contract version);
     - keep D1 but ignore only the changes made when a project enters Revisions.
   - Recommendation: the latest ETA set at or before Ready For Approval. It still honours ETA changes made before the Editor submits, and it cannot be moved by later client revisions.
