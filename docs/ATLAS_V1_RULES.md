# Atlas V1 deterministic rules

These rules are the authoritative baseline until superseded by a later approved
contract version. **Rules 1–11 below are the production rules of the active contract 1.4.0.** Contract 1.5.0 exists in the
repository as an inactive candidate; where it differs, the section *Contract 1.5.0 (candidate, not active)* at the end states the
1.5 rule and its decision, and neither rule set silently overrides the other. The active executable configuration is
`config/monday-contract-v1.4.json` (contract version `1.4.0`), which keeps every
contract 1.3.0 rule except the deadline Requested ETA selection (D19: the ETA is
frozen at the first Ready For Approval). Before it,
`config/monday-contract-v1.3.json` (contract version `1.3.0`), which keeps every
contract 1.2.0 rule and adds the second round of approved decisions; before that,
`config/monday-contract-v1.2.json` (contract version `1.2.0`), which keeps every
v1.1 registry unchanged and adds the Waset management decisions of 2026-09-28
(see `docs/DECISIONS.md`). The previous approved executable configuration is
`config/monday-contract-v1.1.json` (contract version `1.1.0`): it preserves the
v1.0 status and Editor registries and adds the approved `monday-video-type-v1.1`
mapping (`Class A+` = label ID `8`). Runtime resolves Video Type from Monday label
IDs and stamps every resolution with its mapping version. Any label
absent from the active explicit registries is unresolved and must quarantine
records rather than infer mappings. `config/monday-contract-v1.0.json` (contract version `1.0.0`) remains
the historical baseline for reproducibility; under it label ID `8` is unresolved.

1. **Monday is authoritative.** Persist every raw Monday label plus board/item/column/event identifiers and source timestamps. Each normalized event carries `mapping_version`.
2. **Status mappings are explicit.** Use the phase mapping in the executable configuration; contract 1.2.0 adds index-bound aliases for verified renames and keeps entries into a mapped status whose previous label is unmapped (raw previous text retained, previous status unresolved). Unmapped, deprecated, and newly introduced labels are quarantined; no silent inference.
3. **Editor is the evaluated entity.** The item `Editor Name` field is authoritative. Activity-log `user_id` is audit metadata only. Use a versioned person/label-ID mapping, including historical and deactivated identities; unresolved identities are quarantined. Account `99154021` never infers an Editor.
4. **Work duration is exact.** Only the first transition into `In Progress` starts the cycle, and only the first qualifying transition into `Ready For Approval` ends it. Repeated `In Progress`/`Create File` and post-revision transitions stay in the original cycle. Only this first completed cycle feeds Speed / Work Duration; later `In Progress -> Ready For Approval` rounds are retained as evidence and are never added to or substituted for it. Duration is elapsed clock time (`first_ready_for_approval_at - first_in_progress_at`); nights, weekends, holidays, and non-working hours are not excluded.
5. **Anomalies and open cycles are retained safely.** Duplicate or reversed transitions are ignored for timing and flagged. Incomplete cycles are retained as open/right-censored records and excluded from completed-cycle duration aggregates.
6. **Comparable benchmarks only.** A completed cycle's cohort is the latest valid Video Type at or before its Ready For Approval (creation values count; later changes never alter it). A cohort is benchmark-eligible only when every label is a confirmed base type or modifier and at least one is a confirmed base type (contract 1.3.0: base Class A, Class B, Simple Short, Class A+, Premium Short; modifiers 2*, Ai). The minimum Editor sample is 5 projects; the team benchmark includes the subject Editor; the approved statistic is the median. Normalize multi-select Video Type values using the versioned registry (`monday-video-type-v1.2` in contract 1.2.0: every label ID in the live Monday column settings, verbatim; `v1.1` in contract 1.1.0), key cohorts by sorted canonical IDs, and compare only within the same resolved cohort. Blank, unknown, or new types are quarantined; there is no global fallback. The team benchmark is a descriptive historical median, not an SLA. A faster/slower conclusion requires the configured minimum Editor sample size (`speed_benchmark.minimum_editor_sample_size`); while it is unset or unmet, only raw values and sample sizes are reported.
7. **Deadline uses the Requested ETA in effect at the first Ready For Approval (contract 1.4.0, deadline-v1.2).** `deadline_delta = ready_for_approval_at - selected_requested_eta`, where the selected ETA is the latest valid Requested ETA observed at or before the cycle's first Ready For Approval. A later ETA change (for example the reset when a project enters Revisions) never changes the result and is kept as ignored evidence. The result is `early` when `delta < 0`, `on_time` only when `delta == 0`, and `late` when `delta > 0`; there is no tolerance. A missing ETA, a date-only ETA, or an ETA that only appears after Ready For Approval yields no result and is never replaced by another field, a later value or a guessed time. Every observed Requested ETA value is retained; history is called complete only when ingestion metadata proves it. Contracts 1.2.0 and 1.3.0 keep the earlier latest-ETA rule (deadline-v1.1) for reproducibility.
8. **Revisions are context.** Revision counts and notes can explain outcomes but cannot directly lower a quality score without an explicit deterministic business rule.
9. **Quality is label-derived.** Quality values come from approved Monday labels and a versioned label mapping.
10. **Evidence is mandatory.** Every metric stores source record IDs, event IDs, field values, formula/rule version, and calculation time.
11. **AI is not authoritative.** AI can summarize, investigate, recommend, or flag anomalies. It cannot invent facts or overwrite deterministic source-derived values.

## Contract 1.5.0 (candidate, not active)

`config/monday-contract-v1.5.json` encodes D20–D51 (`docs/DECISIONS.md`; `docs/HANDOFF-V2.md` is the product source). It is loadable
and fully tested but **not active**: `ACTIVE_CONTRACT_VERSION` and `PRODUCTION_CONTRACT_VERSIONS` stay `1.4.0`, and production sync
refuses 1.5.0. Activation is a separate, explicitly approved step (`docs/CONTRACT-1.5-ACTIVATION.md`). Under 1.5.0 these rules
replace the corresponding 1.4.0 rules above; every other rule above applies unchanged.

- **Rule 3 (Editor identity), D48–D51.** An Editor is resolved by the exact `(source_label_id, logged_name)` tuple, never by the
  label ID alone; a new name under a known label ID is unresolved. Each mapping declares `validity`: `ongoing` (a confirmed current
  Editor, valid from its first attested observation with no end date) or `historical` (a reused label tuple valid only between its
  first and last attested observation). `(11, "New")`, `(2, "Done")` and `(1, "El Baz")` stay quarantined with their reasons.
- **Rule 6 (benchmarks), D35–D36, D38.** The Speed benchmark is **leave-one-out**: the other eligible Editors' first-pass projects in
  the same exact Video Type, the viewed Editor excluded. With no other Editor the result is "No valid team benchmark available".
  Classification needs approved minimum Editor, comparator-project and comparator-Editor samples and approved bands; until then
  only facts and samples are shown.
- **Rule 9 (quality), D26–D30, D39.** Labels have three classes: Negative (Performance Issues), Positive and Context (For Bonus,
  parsed per label). Whether a label counts in the Quality component comes only from its `scored_quality` registry flag; `Late
  Delivery`, `On Time Delivery` and every Context label are visible but never scored (Deadline is authoritative for lateness).
- **Windows, D24 and D42.** Business days, the 30-completed-day current and comparison windows and monthly history use
  `Africa/Cairo`; the current Cairo day is excluded. A project belongs to the window of its first valid Ready For Approval.
  Contracts up to 1.4.0 keep UTC months.
- **Interpretation, D23, D25, D37, D41, D45, D47.** Quality, Speed and Deadline each have a component state (positive, neutral,
  negative, not classifiable) with a reason. Overall Status is an explicit lookup of those three states, with no weights or score;
  Revisions, Current Work and Context labels never affect it. The Deadline component compares the Editor's late rate with the
  other Editors' (leave-one-out) and the absolute facts stay visible beside it. Recent Change is a fact; Trend needs an approved
  per-measurement materiality threshold and direction. A rule classifies only when it is marked approved in the contract **and**
  names its decision (D25); until then results show "Not enough approved logic to classify", which is distinct from the data state
  "Not enough evidence to classify". D52 approves the Speed and Deadline values, the Overall lookup and the Quality and Trend sample
  floors; Quality N/P and Trend materiality stay unapproved, so Quality and Trend show facts only, and an Overall Status needs two
  classifiable components (in practice Speed and Deadline).
- **Rule 10 (evidence).** Every 1.5 conclusion carries an evidence block from which it can be recomputed: Monday board and columns,
  Cairo date range, sample, calculation, one record per contributing project (item, cycle, event IDs, timestamps, values used),
  exclusions and reasons, rule version and calculation time. `contracts/editor-profile-v1.5.schema.json` rejects empty event IDs or
  timestamps, a conclusion without its evidence, and any classification, verdict, Overall Status or Trend label under an unapproved
  rule; `profile.evidence_consistency_errors` (run at build, staged validation and publication) rejects evidence whose records do not
  match the published sample.

## Contract ownership

Changes under `contracts/` require a designated contract owner review plus compatibility tests. Builders may propose contract changes; the arbiter cannot waive contract review.
