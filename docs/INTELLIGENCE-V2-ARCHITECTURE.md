# Atlas Intelligence v2 — the Investigation Layer

**Branch:** `feat/atlas-intelligence-v2` (from `main` at `d9918d1`) · **Status:** architecture and recommendation, implemented as an
additive, non-scoring layer · **Date:** 2026-09-29

## 0. Summary

Atlas today answers "what are this Editor's numbers?" Each Editor Profile is correct, traceable and deliberately
conservative, but it is **descriptive**. Management still has to decide by hand:

- whether a high late rate is the Editor's doing;
- whether a pattern is one person or the whole team;
- where time is actually lost between a project's creation and its approval.

This document proposes an **investigation layer** that sits beside the contract-1.5 interpretation layer and answers a
different question:

> *What does the operating data tell management that it would not see by reading Monday, and how sure can we be?*

Its output is a ranked list of **findings**. Every finding is structured the same way:

```
Evidence  →  Pattern  →  Interpretation  →  Management significance  →  Suggested investigation
(records)    (fact or     (labelled as        (why it matters,             (what to look at next;
              statistical   interpretation or    which decision it affects)   never a verdict on a person)
              relationship) hypothesis)
```

The layer:

- is deterministic, versioned and recomputable from Monday event IDs;
- is **never an input** to Overall Status, component states, Trend or any score;
- may answer "not enough evidence", and records every analysis it could not complete, with the reason.

It is a separate document contract (`investigation-v0.1`). It does not change any existing contract, profile schema or
golden output.

## 1. What the existing Monday capture actually contains

Verified against the code (`pipeline.py`, `cycles.py`, `monday_source.py`) and production run
`20260929T130736Z-e6d03314e704` (2026-02-01 → 2026-09-29, 1,305 items, 26,866 update events, 1,300 items with proven complete
history). All real-data figures below are aggregates computed read-only from that run with the unmodified contract 1.5.0
reconstruction. No output was written to the repository.

| Captured | Derivable relationships |
|---|---|
| Every accepted `Status` transition (14 live statuses, from/to, timestamp, event ID) | Full per-item status timeline. It is not limited to the first cycle: post-cycle events are retained. It gives stage dwell times, loop counts (Sent → Revisions → Ready For Approval …) and review waits. |
| `Editor Name` changes with the logged name | When the attributed Editor was **assigned** (the start of the unbroken run of the value in effect at Ready For Approval), and hand-overs (`EDITOR_CHANGED_WITHIN_CYCLE`). |
| `Video Type` changes | The exact cohort at Ready For Approval; mix per Editor and per period. |
| `Requested ETA` history (activity log, creation value, snapshot) | The ETA in effect at first Ready For Approval (D19). The **time budget** the ETA left when work started (`ETA − In Progress`), when the ETA was set relative to the work, and whether it moved during the work. |
| Performance Issues and For Bonus labels, per label | Label occurrences per project and their agreement with the computed deadline facts. |
| Item snapshot (current Status, Editor, ETA, Video Type) at `retrieved_at` | Open work now: what is In Progress or Ready For Approval, for how long, and against which ETA. |
| Transition-role rules (`monday-transition-role-v1.0`) | The role for a few exact transitions only; the shared `Waset Co` account never identifies a person. |

## 2. What cannot safely be derived (and Atlas must say so)

| Not derivable | Why | Consequence |
|---|---|---|
| **Effort or working hours** | Monday records status changes, not time worked. Durations are elapsed clock time (D3), including nights, weekends and parallel work. | Atlas can say "elapsed time was longer while the Editor had 2+ other open projects", never "the Editor worked N hours". |
| **Who set or changed an ETA, or who moved a card** | Most changes come from the shared `Waset Co` account (99154021). Only the exact transitions in the role table have a role. | Process findings name **stages and roles, never people** other than the evaluated Editor. Production Manager, reviewer and account-manager performance are out of scope (HANDOFF-V2 §27) and unmeasurable. |
| **Revision cause** | No reason field is captured. Only client vs internal is known (D31). | Revision patterns appear **only at Video Type or team level, as context**. No Editor-directed finding may use revisions (D31, HANDOFF §10/§18). |
| **Client identity, brief quality, footage volume, video length** | Not captured. | Video Type is the only complexity control. Every comparison says it is Video-Type-adjusted only. |
| **Why a project waited before assignment** | There is no queue or priority field. | The wait is a fact. Its cause is a hypothesis. |
| **Completeness of performance labels** | Management applies labels by hand. Run evidence: only **95 of 423** computed-late projects carry `Late Delivery`. | Label rates are **lower bounds**. Atlas reports label/fact disagreement as a data finding, not as Editor evidence. |
| **Causation** | This is observational data with no randomisation or experiment. | Every relationship is labelled `statistical_relationship`. Causal wording is prohibited in codes and templates, and interpretations are separate, labelled statements. |
| **Editor of open or unattributed work in the past** | Open cycles are not attributed (the Editor is resolved at Ready For Approval), and 180 of 861 completed cycles have no verified Editor. | Concurrency (workload) is a **lower bound**: it counts only attributed completed first cycles. Open work uses the current Editor Name snapshot, which is a current fact only. |
| **History before 2026-02-01; retired statuses** | Outside the ingestion window; 120 cycles are excluded under D18. | These appear in `coverage`; they are never imputed. |
| **Forecasts** | ML deadline prediction is out of scope (HANDOFF §27), and the history is only 8 months. | "Emerging risk" is limited to (a) facts about open work, e.g. already past its ETA, and (b) historical base rates for projects in the same observable position, labelled as hypotheses. |

## 3. What the real data shows (why this layer matters)

These are aggregates from the production run above, contract 1.5.0, all attributed completed first cycles. They are
**evidence that the analyses are worth building, not published findings**; the implemented engine recomputes them with its
own sample and confidence rules.

1. **Most lateness is associated with the ETA budget, not with slow work.**
   - Scope: 587 deadline-classifiable projects, 423 of them late (72%).
   - Among the 373 late projects with a valid same-Video-Type benchmark (other Editors, ≥10 projects), **329 (88%)**
     started with less time until the ETA than the other Editors' median work time for that type.
   - Projects with such a "tight" budget were late 74% of the time; projects with an adequate budget, 54%.
   - **143 of those 373 late projects (38%)** were finished at or faster than the peer median for their type.
   - This is the pattern D46 suspected ("this may reflect how Requested ETA is set"), now quantified per project.
2. **Where elapsed time goes.**
   - Per stage visit, medians: In Progress 24 h, Revisions 7 h, Create File 1.3 h, Ready For Approval (review wait)
     **0.7 h**, Internal Revisions 1.8 h.
   - Review is not the bottleneck. First-pass Editor work and client-revision loops dominate.
   - Time between `Sent` and the client's next action is the largest single elapsed block (median 6.5 h per visit,
     p75 28 h). It is outside Waset's control.
3. **Editors start as soon as they are assigned.**
   - Median assignment → In Progress: 0.16 h.
   - Median item creation → assignment: 3.2 h.
   - Time lost before work starts is lost **before the Editor's interval**, not inside it.
   - 10 projects were already past their ETA when In Progress began; all 10 are counted late against the Editor.
4. **Elapsed work time rises with concurrent load, within the same Video Type.**
   - Median duration by number of other open projects at start (0 / 1 / 2+):
     - Simple Short: 28.5 / 29.5 / 41.9 h
     - Class A: 29.8 / 34.6 / 49.9 h
     - Class B: 25.3 / 39.4 / 52.2 h
     - Premium Short: 29.4 / 41.9 / 60.7 h
   - This is an association in elapsed time and is consistent with parallel work. It is not proof of slower working.
5. **Revision activity is a property of the Video Type more than of any Editor.**
   - Client revisions touch 92–95% of Simple Short, Class B and Premium Short projects, against 49% of Class A.
   - This is context only (D31); it shows that type-level process drives the revision load.
6. **Labels and facts disagree.**
   - 5 projects carry `Late Delivery` although the Editor's first Ready For Approval was early: the lateness arose
     **after** the Editor's interval.
   - 7 projects carry `On Time Delivery` although computed late.
7. **Team behaviour moves by month.**
   - Late rate by Cairo month: 67%, 85%, 83%, 72%, 73%, 60% (Apr → Sep).
   - Median elapsed work time: 31.6 → 44.2 → 34.4 h (Apr → Aug → Sep).
   - An Editor's month is therefore always compared with the team's same-period movement before it is called a
     personal change.

The published Deadline component compares an Editor's **raw** late rate with the other Editors'. Findings 1, 3 and 5
show that a raw comparison can reflect the Editor's Video Type mix and the budgets they were given. The investigation
layer exists to surface exactly that kind of counter-evidence.

## 4. Which current metrics stay

All of them, unchanged. The contract 1.0–1.5 metric engine, component states, Overall Status lookup, Recent Change,
evidence blocks, coverage and golden outputs are untouched. The investigation layer only **reads** `CycleReconstruction`,
the deadline results and the quality occurrences. It adds no field to any existing document, and nothing it computes
flows back into them.

## 5. Higher-order analyses added

Each analysis has a stable code, a version, explicit sample rules and a declared **attribution scope**:

- `system_process`: a stage, role or Video Type, never a person;
- `editor`: the evaluated Editor only;
- `data`: a data-quality statement.

| # | Analysis (code) | Question | Scope | Claim types |
|---|---|---|---|---|
| A1 | `workflow_time_map` | Where does elapsed time go, stage by stage, before and after the first Ready For Approval? | system_process | observed_fact |
| A2 | `deadline_budget_feasibility` | Is lateness associated with ETAs that allow less time than typical same-type work? | system_process | fact, statistical_relationship, interpretation, hypothesis |
| A3 | `late_despite_typical_speed` | For an Editor with many late projects, how many were late although the work itself was at or below the typical time? | editor (counter-evidence) | fact, interpretation |
| A4 | `late_rate_mix_adjusted` | Does the Editor's raw late-rate gap remain once their Video Type mix is accounted for (indirect standardisation)? | editor | fact, statistical_relationship, interpretation |
| A5 | `pattern_breadth` | Is a problem concentrated in one Video Type and repeated across most Editors in it, or confined to one Editor? | system_process / editor | fact, statistical_relationship, interpretation |
| A6 | `workload_association` | Within the same Video Type, is elapsed work time associated with the number of the Editor's other open projects? | system_process (+ editor context) | statistical_relationship, hypothesis |
| A7 | `editor_baseline_shift` | Did the Editor's late rate or same-type work time change against **their own** history, and did the rest of the team shift the same way? | editor | fact, statistical_relationship, interpretation |
| A8 | `team_shift` | Did team-wide late rate, ETA budget, work time or revision load change in the current window against earlier history? | system_process | fact, statistical_relationship |
| A9 | `responsibility_interval` | For each late project, did the lateness begin before the Editor's interval (ETA already passed, ETA pulled in during work, assignment after most of the window had elapsed)? Is a `Late Delivery` label attached to a project the Editor submitted on time, i.e. did lateness begin after the interval? | editor (counter-evidence) + data | observed_fact |
| A10 | `open_work_risk` | Which open projects are already past their ETA, or have less time left than typical same-type work? How long have submitted projects waited for review? | system_process / editor (current facts) | observed_fact, hypothesis (with historical base rate) |
| A11 | `label_fact_agreement` | How far do performance labels agree with computed facts? | data | observed_fact |

Explicitly **not** added:

- any Editor ranking or composite;
- revision-based Editor findings;
- any statement about Production Managers, reviewers or other people;
- AI-generated text;
- forecasts beyond base rates.

## 6. The finding model

```jsonc
{
  "finding_id": "sha256-prefix of (analysis, subject, window, parameters)",  // stable across runs on the same data
  "analysis": "late_rate_mix_adjusted", "analysis_version": "investigation-v0.1",
  "subject": {"scope": "editor", "editor_id": "editor-label-6", "cohort_key": null, "stage": null},
  "window": {"timezone": "Africa/Cairo", "start_date": "...", "end_date_exclusive": "..."},
  "category": "counter_evidence | system_pattern | emerging_risk | person_specific_candidate | context | data_quality",
  "attribution": "system_process | person_specific_candidate | mixed | undetermined | data",
  "statements": [                                   // evidence → pattern → interpretation, each typed
    {"kind": "observed_fact",            "code": "...", "params": {...}},
    {"kind": "statistical_relationship", "code": "...", "params": {...}},
    {"kind": "interpretation",           "code": "...", "params": {...}},
    {"kind": "hypothesis",               "code": "...", "params": {...}}
  ],
  "significance": {"code": "...", "params": {...}},
  "suggested_investigation": [{"code": "...", "params": {...}}],
  "confidence": {"level": "low | moderate | high", "basis": {...}, "rules": ["..."]},
  "importance": {"rank": 1, "tier": "...", "basis": {...}},
  "evidence": {"source": "monday", "monday_board_id": "...", "column_ids": [...], "calculation": "...",
               "sample": {...}, "records": [{"monday_item_id", "cycle_id", "event_ids", "source_timestamps", "values"}],
               "exclusions": [...], "parameters": {...}, "rule_versions": {...}, "calculated_at": "..."},
  "caveats": ["elapsed_clock_time", "video_type_is_only_complexity_control", ...]
}
```

- Statements are **codes plus parameters**, the same pattern as `interpretation_view`. The English and Arabic
  renderers format them; nothing is pre-rendered prose. AI may later rephrase them but may not add to them.
- `investigation.not_enough_evidence[]` lists every analysis/subject pair that ran but could not conclude, with the
  missing sample. Silence therefore always has a stated reason.
- `investigation.coverage` states what was out of reach: unattributed and excluded projects, open cycles without an
  Editor, and the label-completeness indicator.

## 7. Evidence and confidence

### Evidence

Every finding carries a `scope.block`-shaped evidence block (the same shape as contract 1.5):

- Monday board and columns;
- the calculation;
- the sample;
- **one record per contributing project** (item ID, cycle ID, Monday event IDs, timestamps, the values used);
- exclusions with reasons;
- the parameters and rule versions used.

A schema-level consistency check (`investigation_consistency_errors`) requires the number of records to match the
declared sample, the same guarantee `evidence_consistency_errors` gives profiles.

### Confidence

Confidence is a deterministic function of sample size, interval separation and replication. The parameters live in
`config/investigation-v0.1.json` and are printed in every finding.

| Level | Rule |
|---|---|
| (no finding) | Below the analysis minimums. Recorded in `not_enough_evidence` with what is missing. |
| `low` | Minimums met and the effect exceeds the materiality floor, but the 95% intervals overlap. Emitted **only for team/system scope**, flagged `tentative`. Never emitted about an individual Editor (HANDOFF §23: small samples must not look authoritative). |
| `moderate` | Minimums met, materiality exceeded, and the 95% intervals are separated: Wilson score intervals for rates; distribution-free order-statistic intervals for medians; Byar's interval excludes 1 for observed/expected ratios. |
| `high` | `moderate`, **and** replicated: the pattern holds in both the current and comparison windows, or in at least two Video Type strata, or in ≥ two thirds of the Editors with enough sample. |

Minimums (engineering defaults, reviewable):

- 10 projects per compared group for rates, which aligns with the D52 Quality/Trend floors;
- 5 per side for medians;
- 10 in an Editor's own baseline;
- at least 3 Editors with ≥ 5 projects each for any breadth claim.

Materiality floors:

- 10 percentage points for rates;
- ±25% for medians, which mirrors the approved D52 speed band;
- observed/expected ≥ 1.25 or ≤ 0.8.

Statistical intervals are **screening tools, not proof**. Every finding says so (`caveat: observational_association`).

### Person-specific vs system/process attribution

| Attribution | Rule |
|---|---|
| `system_process` | The pattern appears in ≥ two thirds of the Editors with enough sample in the slice; or it is accounted for by factors the Editor does not control (Video Type mix, ETA budget at start, time before assignment); or the team shifted the same way over the same period. |
| `person_specific_candidate` | After Video Type adjustment, the Editor still differs from peers in the same slice at `moderate` confidence or better, and peers in that slice do not show the pattern. Always phrased as a **candidate** with a suggested conversation, never as a verdict. |
| `mixed` | Both hold. For example, the whole team is late on a Video Type, but this Editor is later still after adjustment. |
| `undetermined` | There is not enough evidence to separate the two. |

## 8. Ranking findings by management importance

Atlas ranks **findings, not people**. The ordering is lexicographic, and each finding carries its `importance.basis`:

1. **Tier.** Tiers are ordered by the cost to management of not knowing:
   1. `counter_evidence`: a published headline (a component state, a raw rate or a label) would lead to the wrong
      conclusion about a person. Fairness risk comes first.
   2. `system_pattern`: a process or structural cause affecting many projects.
   3. `emerging_risk`: open work that is already past its ETA or structurally at risk.
   4. `person_specific_candidate`.
   5. `context`.
   6. `data_quality`.
2. **Confidence**: high > moderate > low (tentative).
3. **Breadth**: projects affected, descending.
4. **Magnitude**: the effect size, for example percentage points or hours, descending.
5. **Tie-break**: `finding_id`, for determinism.

There is no weighted sum, so a reader can see from `basis` exactly why one finding precedes another. Current-state
emerging risks are also listed separately as `attention_now`, because they are time-sensitive.

## 9. Backend and domain changes

New modules (flat, following the existing layout):

- `investigation_stats.py` holds the pure, dependency-free statistics:
  - Wilson interval;
  - exact order-statistic median interval;
  - Byar's interval for observed/expected ratios;
  - Spearman rank correlation.
- `investigation_facts.py` builds one **project fact row** per completed attributed cycle:
  - creation (first observation), Editor assignment, In Progress, first Ready For Approval;
  - the selected ETA and when it was observed, and the ETA in effect at In Progress;
  - the budget, the leave-one-out typical time for the exact Video Type, concurrency at start;
  - stage dwell (pre- and post-first-Ready-For-Approval), revision counts (context), labels;
  - every event ID used.

  It also builds **open-work rows** from item snapshots, and it reuses the existing cycle, deadline, identity and
  quality code only.
- `investigation.py` holds the analyses A1–A11, the finding builder, confidence, attribution, ranking and the document
  builder `build_investigation(result, contract, generated_at, parameters)`.
- `investigation_html.py` is a standalone English page for review. It is not linked from the published dashboard (§12).
- `config/investigation-v0.1.json` holds the analysis parameters, with `approval_state: "engineering_default_pending_review"`.
- `contracts/investigation-v0.1.schema.json` is the document contract. It forbids score and rank-of-person fields, and it
  requires evidence records and typed statements.
- `capabilities.py` gains `investigation`, enabled for contracts ≥ 1.5.0 (the layer needs Cairo windows, leave-one-out
  and the label taxonomy).
- The CLI gains `profile_cli investigate <extract> <out> [--as-of]`. It writes `investigation.json` and `investigation.html`
  and requires the 1.5 contract.

No change to:

- `cycles.py`, `metrics.py`, `intelligence.py`, `profile.py` or `dashboard.py` beyond read-only imports;
- the sync, publish or status paths;
- any schema other than the new one.

## 10. Tests

- **Statistics**: Wilson, median interval and Byar values against textbook values; edge cases n = 0, k = 0, k = n.
- **Facts**: assignment time from Editor Name events; budget and ETA-at-start; concurrency counting only overlaps at
  start; stage dwell summing to the timeline; input-order independence.
- **Each analysis**, on synthetic Monday-shaped extracts (full pipeline):
  - a pattern is detected at the specified confidence;
  - just below the minimums it moves to `not_enough_evidence`;
  - replication raises the level to `high`;
  - person and system attribution flip correctly when peers do or do not share the pattern.
- **Governance invariants**:
  - no Editor-scoped finding references revision metrics;
  - no `low` confidence finding about an Editor;
  - every finding has ≥ 1 evidence record with event IDs;
  - record counts match the sample;
  - statement kinds come from the four allowed ones;
  - interpretation and hypothesis statements never appear without a supporting fact or relationship in the same
    finding;
  - no causal verbs in template codes.
- **Isolation**:
  - building an investigation leaves `build_editor_profile` output byte-identical;
  - the full existing suite (including the golden site hashes) passes unchanged.
- **Schema**: the document validates; fields named score, rank or grade are rejected.
- **Determinism**: two builds over shuffled input produce identical JSON.

## 11. Contract and versioning impact

- **No existing contract changes.** Monday contracts 1.0–1.5, editor-profile 1.3–1.5, the dashboard document and the golden
  hashes are unchanged.
- **New independent contract `investigation-v0.1`** (document) plus `config/investigation-v0.1.json` (parameters). It is
  versioned on its own axis, because a finding is not a metric: changing a surfacing threshold must not require a new
  Monday contract. Each document names the Monday contract version it was computed under, and it refuses contracts
  without the `investigation` capability.
- **Governance.** The parameters are engineering defaults, not D25 business thresholds: they decide **whether a pattern is
  shown for investigation**, never how an Editor is classified. Still, because this surface is new, the recommendation
  is a management decision, **D53**, before any production publication. It should:
  1. accept the scope extension to process-level findings that name stages and roles only. HANDOFF-V2 §1 and §27 exclude
     company-wide intelligence and Operations/Production Manager KPIs. This layer produces no KPI for any non-Editor
     role, but management should confirm the boundary;
  2. review the parameters in `config/investigation-v0.1.json`;
  3. confirm that Editor-scoped counter-evidence may be shown next to the component states it qualifies.

  Until D53, the investigation is a CLI/review artifact, and production sync does not publish it.

## 12. Presentation

A separate UI/UX redesign is in progress on another branch. This branch therefore adds **no change to
`dashboard_html.py`, `profile_html.py` or the locale catalog**. `investigation_html.py` renders a plain standalone review
page from the language-neutral JSON. Integration guidance:

- the redesigned UI should consume `investigation.json` statements by code;
- Arabic strings belong in the catalog once the redesign fixes its view-model boundary.

## 13. Risks

- **Statistics can mislead with multiple comparisons.** Many slices × many Editors will produce some chance separations.
  Mitigations: materiality floors, replication for `high`, no `low` Editor findings, and a count of analyses run that is
  published with the findings.
- **Counter-evidence can be read as exoneration.** "Late despite typical speed" shows that the budget was tight; it does
  not show the Editor carries no responsibility. The templates say "points to" and "consistent with", never "caused by"
  or "not responsible".
- **Workload is under-counted** (attributed completed cycles only). This is stated in every workload finding.
- **The ETA budget uses the ETA in effect at the first Ready For Approval** (D19). A budget computed with a later-set ETA
  is flagged (`eta_set_after_work_started`) rather than silently treated as the original plan.
