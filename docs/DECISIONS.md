# Atlas V1 decision log

Product decisions that drive runtime behavior. Each is encoded in a versioned executable
contract so historical results stay reproducible. A change to any of them is a new
contract version, never an edit of an approved one.

## Confirmed by Waset management (2026-09-28) — contract 1.2.0

| # | Decision | Runtime encoding |
|---|---|---|
| D1 | Deadline uses the **latest available Requested ETA**, even if it changed after Ready For Approval. `deadline_delta = ready_for_approval_at - latest_requested_eta`. Every Requested ETA value observed in the ingested evidence is kept. | `deadline.requested_eta_selection = latest-available-requested-eta`. `reconstruct_cycles(..., items_payload=...)` passes the current Monday item value to the cycle builder as the latest value, and flags any disagreement with the last logged value (`REQUESTED_ETA_SNAPSHOT_DIFFERS_FROM_LOG`). Observed values are in `evidence.source_values.requested_eta_history`. `requested_eta_history_coverage.status` is `observed_in_ingested_evidence` unless ingestion metadata lists the item in `complete_history_item_ids`. |
| D2 | Only the **first completed** `In Progress -> Ready For Approval` cycle feeds Speed / Work Duration. Later cycles are retained in evidence, never added or substituted. | `cycle_attributes.cycle_selection`; `CycleRecord.post_cycle_event_ids`, `later_ready_for_approval_event_ids`. |
| D3 | Work duration is **elapsed clock time**; nights, weekends, holidays and non-working hours are not excluded. | `cycle_attributes.duration`; `duration_seconds = first_ready_for_approval_at - first_in_progress_at`. |
| D1a | Deadline is classified **early** (`delta < 0`), **on_time** (`delta == 0`), or **late** (`delta > 0`). There is no tolerance. | `deadline-metric-v1.1.schema.json` (contract 1.1.0); `metrics.classify_deadline`; `deadline_summary` reports early, on-time and late counts and rates. The 1.0.0 deadline schema is unchanged. |
| D4 | One project is not enough for an Editor-vs-team speed conclusion. A **minimum sample size** is required, but its value is not yet chosen. | `speed_benchmark.minimum_editor_sample_size = null`; results carry `comparison_status = minimum_sample_size_not_configured` and `conclusion = null` until it is set. |

## Carried from earlier approvals

- Video Type mapping `monday-video-type-v1.1` (contract 1.1.0): `Class A+` = label ID `8`. Cohorts are exact normalized full sets; `[8]` and `[5,8]` are different cohorts.
- Video Type mapping `monday-video-type-v1.2` (contract 1.2.0) records all 25 label IDs and verbatim names from the live Monday column settings, including deactivated labels that historical items still carry. It is a superset of v1.1 with unchanged IDs. Nothing is merged: `[10,4]` (`2*` + `Class A`) is a different cohort from `[4]`. Evidence: `docs/evidence/VIDEO-TYPE-AUDIT.md`.
- Transition roles `monday-transition-role-v1.0` encode only transitions whose Monday labels exist verbatim: `In Progress -> Ready For Approval`, `Revisions -> Ready For Approval`, `Ready For Approval -> In Progress`, `* -> Revisions` (Editor); `Ready For Approval -> Sent` (Production Manager). Roles are context and audit only; the evaluated Editor always comes from the Editor Name field.
- Quality registry `monday-performance-issues-v1.0` records the live `Performance Issues` labels (column `dropdown_mm3tyk8g`) at equal weight, one occurrence per label per item.

## Engineering defaults (open; not management decisions)

These are deterministic, versioned, and visible in evidence. They exist only because the code needs a rule to run. They remain open for management and may change only through a new contract version.

| Default | Why a rule is needed | Alternative |
|---|---|---|
| Editor of a cycle = Editor Name value in effect at Ready For Approval, from column-change events; an Editor change inside the cycle quarantines it. | Editor Name is sometimes edited after work starts. | Latest Editor Name value. |
| Video Type of a cycle = value in effect at Ready For Approval; a later change is flagged `VIDEO_TYPE_CHANGED_AFTER_READY_FOR_APPROVAL`. | Video Type is sometimes reclassified. | Let post-RFA changes apply (the latest Video Type value). |
| Team benchmark population = every eligible first completed cycle in the cohort, including the subject Editor's. | A median needs a defined population. | Peers only, excluding the subject Editor. |
| Median of an even-sized sample = mean of the two middle values, floored to whole seconds. | The contract stores integer seconds. | — |

## Open decisions

None of these is answered in code; each stays configurable or quarantined.

1. **Minimum Editor sample size (D4 value):** `speed_benchmark.minimum_editor_sample_size = null`. Until a value is set, results show raw values and sample sizes with no faster/slower conclusion.
2. **Date-only Requested ETA:** Monday allows an ETA with no time. Atlas produces no deadline result (`REQUESTED_ETA_DATE_ONLY`) rather than guess a time.
3. **Team benchmark population:** the subject Editor is included in the team median (default above), versus peers only.
4. **Video Type selection:** should changes made after Ready For Approval affect the cycle's cohort? The default above says no, and flags them.
5. **Unresolved Editor Name labels:** active labels 4, 5, 7, 9, 10 and 11 are not in `monday-editor-v1.0`, so their cycles are quarantined as `UNMAPPED_EDITOR`.
6. **For Bonus:** is the `For Bonus` dropdown (`dropdown_mm3tyvvc`) a source of positive quality signals? It is not used.
7. **Live status semantic aliases:** "Ready to Edit" and "Approved / Delivered" are not Monday status labels. The candidates are `Create File` and `Ready To Send` / `Done`. Those transitions stay `unresolved` (context only; no metric depends on them).
8. **On-time tolerance:** none. Exact zero is `on_time` until management defines a tolerance.
9. **Video Type modifiers:** labels such as `2*`, `3*`, `4*`, `Unbranded`, `Ai`, `Premium Capions` combine with base types. Atlas keeps every combination as its own exact cohort. Any grouping would be a management decision and a new mapping version.
