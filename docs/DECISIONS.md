# Atlas V1 decision log

Product decisions that drive runtime behavior. Each is encoded in a versioned executable
contract so historical results stay reproducible. A change to any of them is a new
contract version, never an edit of an approved one.

## Confirmed by Waset management (2026-09-28) — contract 1.2.0

| # | Decision | Runtime encoding |
|---|---|---|
| D1 | Deadline uses the **latest available Requested ETA**, even if it changed after Ready For Approval. `deadline_delta = ready_for_approval_at - latest_requested_eta`. The ETA change history is kept as evidence. | `deadline.requested_eta_selection = latest-available-requested-eta`; `cycles._resolve_latest_eta`; `metrics.deadline_result` (history in `evidence.source_values.requested_eta_history`). |
| D2 | Only the **first completed** `In Progress -> Ready For Approval` cycle feeds Speed / Work Duration. Later cycles are retained in evidence, never added or substituted. | `cycle_attributes.cycle_selection`; `CycleRecord.post_cycle_event_ids`, `later_ready_for_approval_event_ids`. |
| D3 | Work duration is **elapsed clock time**; nights, weekends, holidays and non-working hours are not excluded. | `cycle_attributes.duration`; `duration_seconds = first_ready_for_approval_at - first_in_progress_at`. |
| D4 | One project is not enough for an Editor-vs-team speed conclusion. A **minimum sample size** is required, but its value is not yet chosen. | `speed_benchmark.minimum_editor_sample_size = null`; results carry `comparison_status = minimum_sample_size_not_configured` and `conclusion = null` until it is set. |

## Carried from earlier approvals

- Video Type mapping `monday-video-type-v1.1` (contract 1.1.0): `Class A+` = label ID `8`. Cohorts are exact normalized full sets; `[8]` and `[5,8]` are different cohorts.
- Transition roles `monday-transition-role-v1.0` encode only transitions whose Monday labels exist verbatim: `In Progress -> Ready For Approval`, `Revisions -> Ready For Approval`, `Ready For Approval -> In Progress`, `* -> Revisions` (Editor); `Ready For Approval -> Sent` (Production Manager). Roles are context and audit only; the evaluated Editor always comes from the Editor Name field.
- Quality registry `monday-performance-issues-v1.0` records the live `Performance Issues` labels (column `dropdown_mm3tyk8g`) at equal weight, one occurrence per label per item.

## Engineering defaults awaiting confirmation

These defaults are deterministic, versioned, and visible in evidence. They were chosen only where the code needed a rule to run.

| Default | Why a rule is needed | Alternative |
|---|---|---|
| Editor of a cycle = Editor Name value in effect at Ready For Approval, from column-change events; an Editor change inside the cycle quarantines it. | Editor Name is sometimes edited after work starts. | Latest Editor Name value. |
| Video Type of a cycle = value in effect at Ready For Approval; a later change is flagged `VIDEO_TYPE_CHANGED_AFTER_READY_FOR_APPROVAL`. | Video Type is sometimes reclassified. | Latest Video Type value, which would match D1's approach. |
| Team benchmark population = every eligible first completed cycle in the cohort, including the subject Editor's. | A median needs a defined population. | Peers only, excluding the subject Editor. |
| Median of an even-sized sample = mean of the two middle values, floored to whole seconds. | The contract stores integer seconds. | — |

## Open decisions

1. **D4 value:** the minimum number of projects per Editor per cohort before a faster/slower conclusion.
2. **Date-only Requested ETA:** Monday allows an ETA without a time. Atlas currently produces no deadline result rather than guess a time.
3. **Unverified transition names:** "Ready to Edit" and "Approved / Delivered" are not Monday status labels. Do they correspond to `Create File` and `Ready To Send` / `Done`? Until confirmed, those transitions stay `unresolved` (context only; no metric depends on them).
4. **Editor registry gap:** active Editor Name labels 4, 5, 7, 9, 10 and 11 are not in `monday-editor-v1.0`, so their work is quarantined as `UNMAPPED_EDITOR`.
5. **Positive quality signals:** is the `For Bonus` dropdown (`dropdown_mm3tyvvc`) an approved source of positive quality signals? It is not used until confirmed.
