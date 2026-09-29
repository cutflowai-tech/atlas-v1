# Intelligence V2: production validation

Tasks 64 and 20-22 of the D53 production instruction. Two validations are recorded here: **§1-§5** the D53 validation that
preceded publication (2026-09-30, approved parameters), and **Appendix A** the earlier review-mode validation (2026-09-29,
proposed parameters), kept as it was written.

Nothing was written to Monday, the repository's data or any published location during validation. Raw extracts were read from
read-only local copies. No credential appears here. Editor names are the attested display names already used in the repository;
Monday item IDs are shown so a reviewer can open them.

## 1. Data

Production run `20260929T210734Z-4cb4bfa25596`, the newest completed production extract at validation time (it was the live
publication's source run):

- board `5091110326`, contract 1.5.0, activity window 2026-02-01 to 2026-09-29T21:07:34Z;
- `retrieved_at` and `generated_at` 2026-09-29T21:10:18Z (Cairo current window 2026-08-31 to 2026-09-29).

## 2. What was run (D53 values)

| Mode | Findings | Detectors with findings | Confidence | Withheld as Weak | `rule_not_approved` |
|---|---|---|---|---|---|
| `review` (never published) | 79 | 23 | 2 Strong, 47 Moderate, 30 Weak | — | none |
| `approved_only` (published) | 55 | 21 | 2 Strong, 47 Moderate, 6 Weak (direct fact or data warning) | 24 | none |

- Examined without a finding (approved_only): insufficient sample 146, insufficient outcome events 122, no effect at the approved
  threshold 135, insufficient recent window 49, insufficient qualifying Editors 42, Weak evidence kept for review 24.
- Duplicate clusters: 4 in approved_only (7 in review); every member stays in the document.
- Categories published: 7 system patterns, 1 needs attention, 17 hidden context, 18 Editor-specific patterns, 5 improvements,
  1 emerging risk, 6 data warnings.
- No D53 detector is blocked by governance. Quality N/P and contract Trend materiality remain open (D52) and are not used by any
  Intelligence V2 detector.

## 3. The Top 5, recomputed independently

A separate script (`reconstruct_cycles`, `metrics.deadline_result`, `speed_eligible`, `cohort_benchmark_eligibility`,
`median_seconds` and the raw item snapshot; it asserts that no `atlas_commander.investigation` module is loaded) re-derived each
Top finding from the raw extract. All five match exactly, including the Monday item ID sets.

| # | Finding | Evidence | Confidence | Independent result |
|---|---|---|---|---|
| 1 | **Open work: 5 projects already past their Requested ETA** (emerging risk, direct fact) | 3109734616 (Revisions, 33.4 h past), 3202025538 (Revisions, 102.8 h), 3236578961 (Revisions, 2.0 h), 3243372495 (Revisions, 3.4 h), 3248895716 (In Progress, 0.2 h), read from the item snapshot's status and Requested ETA | Strong (direct observation) | identical items, statuses, Editors and hours |
| 2 | **Late projects often start with too little runway** (system pattern) | 329 of 423 late projects entered In Progress with less time before the Requested ETA than the other Editors' typical same-Video-Type execution; 73.8% of 446 short-runway projects late against 53.9% of 89 adequate; 48 late projects had adequate runway (contradicting block) | Strong | identical counts, rates and 329 item IDs |
| 3 | **Refaat: execution time in Simple Short worsened against own history** (needs attention) | 41.6 h over 11 projects (current window) against 33.0 h over 27 (history), +26.3%; the other Editors' change over the same periods is −4.1% (16 current / 114 history projects, 3 Editors, valid at the D52 comparator minimums), so the change is Editor-specific. It agrees with the approved D52 Speed verdict (Slower in Simple Short, 41.6 h against 29.1 h for 16 projects of 3 other Editors) | Moderate | identical medians, samples, peer change and 38 item IDs |
| 4 | **Will: the late-rate headline needs context** (hidden context, mixed evidence) | late 84.5% (109 of 129) against 67.8% for the others; the approved Speed rule over the whole history reads neutral (faster 0, similar 109, slower 5); 30 late projects were executed within the others' typical time | Moderate | identical |
| 5 | **Mario: the late-rate headline needs context** (hidden context, mixed evidence) | late 82.4% (103 of 125) against 68.5%; whole-history Speed neutral (faster 41, similar 66, slower 25); 40 late projects within typical time; on the same Video Type mix the others would be late 81% against 82% observed | Moderate | identical |

The Top 5 ranking follows the approved order: time-sensitive facts and findings that change an obvious interpretation first,
then evidence strength, worsening, affected projects and Editors, magnitude, recency and persistence. The past-ETA fact ranks
above historical-similarity signals (D53.9).

## 4. False-positive review of the strongest findings

| Kind | Finding | Checks |
|---|---|---|
| Process-level | Runway (Top 2) | numerator, denominator and item IDs recomputed; typical time is leave-one-out, same exact Video Type, D52 minimums; contradicting block shown; wording "associated with", scheduling as a question (D46) |
| Editor-specific | *Will: late rate differs from peers on the same work* (Moderate) | 93 of 113 late against 76.01 predicted by the same Video Type mix: 15.04 pp, just at the D53.6 material difference; under similar runway 17 pp (98 projects). Reported as a difference on comparable work, with "worth a specific, evidence-based conversation", no judgement |
| Contradiction | Will's headline (Top 4) | contradicting blocks: speed competitive (114 projects), late despite typical execution (30); stated as "The evidence is mixed" |
| Bottleneck | *Delay after on-time submission* | 72 of 163 projects submitted on or before the ETA were delivered after it; review wait 3.9 h, submission to delivery 9.6 h median; stage named, no person (shared account) |
| Risk | Past ETA (Top 1) | recomputed from the raw item snapshot |
| Concentration | *Scored Positive labels concentrate in Class A* | 33 of 58 positive labels (57%) on 185 of 686 projects (27%): ratio 2.1 ≥ 1.25 and difference 30 pp ≥ 10 pp; 58 ≥ 5 events |
| Shared pattern | *Premium Short: execution time improved across Editors* | 3 of 3 Editors with ≥ 5 projects in both periods moved the same way (D53.4: ≥ 3 affected, ≥ 2/3) |

## 5. Defects found in the D53 review and fixed before publication

| Found | Fix | Test |
|---|---|---|
| `evidence.breadth_share` stored as 0.6667 rejected exactly two thirds (2 of 3) | exact fraction `2/3` | `test_investigation_d53.SharedPatternBoundaryTests` |
| "Shared" did not require 3 *affected* Editors, and team / Video Type changes said "across Editors" with any number of Editors | D53.4 rule in `common.shared_across_editors`, used by the pattern and both change detectors | same, and `ChangeTests` |
| Historical-similarity signals fired when the similar group was 1-4 points above its Video Type (72% vs 71%) | requires the D53.6 material rate difference | `FairnessGuardTests` |
| Repeated-delay cells were compared with the pooled late rate of all Video Types | compared with the same Video Type (overall and in both halves) | `FairnessGuardTests` |
| Timing buckets were not adjusted for Video Type mix | indirect standardisation by Video Type | `FairnessGuardTests` |
| An Editor change was called Editor-specific even when the team's comparison group was below any sample floor | the team's change counts only at the same floors (rates) or the D52 comparator minimums (execution); otherwise "team comparison unavailable" | `FairnessGuardTests` |
| A direct fact (past ETA) was graded "Weak" | Strong with the single factor `direct_observation` | `FairnessGuardTests` |
| Titles did not name their subject (two identical "headline needs context" cards) | every title names the Editor, Video Type or project | `test_investigation_i18n` |
| The high-workload open-work signal used the Editor's median | the Editor's own 75th percentile (D53.8) | `WorkloadPercentileBoundaryTests` |
| Two detectors used parameters their catalog entry did not declare | declared; a test compares used and declared parameters | `test_every_parameter_a_finding_uses_is_declared_in_the_detector_catalog` |

Residual concerns for reviewers: the workload association is partly mechanical (a long project overlaps more work), which the
wording and limitations say; "typical execution" uses other Editors' whole history; the Arabic narrative is *Needs Arabic Review*.

## Appendix A. Review-mode validation before D53 (2026-09-29, run `20260929T130736Z-e6d03314e704`)

### A.1 What was run

| Mode | Findings | Analyses run | Build time |
|---|---|---|---|
| `approved_only` (publishable) | 11 | 47 | 2.4 s (plus profiles) |
| `review` (proposed parameters, not publishable) | 75 | 476 | 2.8 s (plus profiles) |

**`approved_only` findings** use only approved rules:

- 4 approved Speed verdicts:
  - Mario slower in Premium Short, 53.2 h over 10 projects against 29.8 h for 32 projects of 5 other Editors;
  - Martin faster in Premium Short;
  - Ibrahim faster in Class A;
  - Will faster in Class A;
- 2 open projects already past their Requested ETA (a fact);
- 6 data warnings:
  - 180 of 861 completed projects unattributed;
  - 94 attributed projects not deadline-classifiable: 3 missing ETA, 32 date-only, 59 excluded for a retired status inside the
    cycle;
  - 58 ETAs first recorded after work started;
  - 804 status visits containing retired or cleared statuses;
  - label/fact disagreement: 5 Late Delivery labels on on-time submissions, 7 On Time Delivery labels on late projects, 328
    late projects without a Late Delivery label;
  - 10 projects in non-benchmark-eligible Video Types.

Every other detector reports `rule_not_approved` in this mode, which is the correct D25 behaviour.

**Review mode** also shows what the D53 proposals would surface:

- 20 hidden-context findings;
- 24 Editor-specific patterns (strengths and weaknesses);
- 9 system patterns;
- 6 emerging-risk signals;
- 4 improvements;
- 2 needs-attention findings.

Evidence levels: 45 findings have moderate evidence and 30 have low. None reaches strong, because no finding meets every
strong-evidence condition. The runway finding, for example, has 525 of 587 projects with a comparable typical time, which is
below the 90% completeness proposal.

### A.2 Independent recomputation

Each figure below was recomputed by a separate script that uses **only** the existing pipeline primitives:

- `reconstruct_cycles`;
- `metrics.deadline_result`;
- `speed_eligible` and `cohort_benchmark_eligibility`;
- `median_seconds`;
- the raw Monday status events.

It does not import any Intelligence V2 code. The script re-derives each rule from its definition (D19 ETA, D36
leave-one-out, D52 minimums, Cairo windows) and compares both the values and the **exact set of Monday item IDs**.

| Finding | Independent | Engine | Project IDs |
|---|---|---|---|
| Late projects that started with short runway | 329 of 423 late; 444 short-runway (74.1% late) vs 81 adequate (54.3% late) | identical | identical (329) |
| Will: late-rate headline | 109 of 129 late (84.5%) vs 68.6% for the other Editors; 31 late projects executed within the others' typical time | identical | — |
| Ibrahim: mix-adjusted late rate | 87 covered projects, 32 late, 60.44 expected | identical | identical (87) |
| On-time submissions delivered after the ETA | 72 of 162 | identical | identical (72) |
| Simple Short execution time | 39.7 h (24 projects, current window) vs 31.6 h (141 projects, history) | identical | — |
| Mario: Negative labels | 43 of 64 are Late Delivery | identical | — |

### A.3 One record traced to raw Monday data

Evidence record from *Will: the late-rate headline needs context*, in the contradicting block
`late_despite_typical_execution`:

- **Project:** item `2818459200`, Video Type Simple Short, Editor `editor-label-6` (Will).
- **Values used:**
  - `duration_seconds` 88,205 (24.5 h);
  - `runway_seconds` 41,147 (11.4 h);
  - `typical_execution_seconds` 112,226 (31.2 h, the other Editors' median in Simple Short);
  - `deadline_result` late.
- **Raw activity log:**
  - `390e58ab…`: `project_status` to label index 9 (**In Progress**) at 2026-04-02T19:34:12Z.
  - `9ea66a74…`: `project_status` to label index 3 (**Ready For Approval**) at 2026-04-03T20:04:17Z. That makes 24.5 h, matching
    the value used.
  - `97155998…`: `create_pulse` at 2026-04-02T06:10:10Z. It carries the creation values (Video Type and Requested ETA).
  - `fcbd71b7…`: Editor Name set to `Will` (label 6) at 2026-04-02T22:23:07Z.

What this record shows: the project was executed faster than typical (24.5 h against 31.2 h) but still late, because it
entered In Progress with 11.4 h of runway. That is the pattern the finding reports. It does not show that Will has no part in
lateness, and the wording says so.

### A.4 Reviewed findings, with wording checks

For each finding below, the evidence was reconstructed and the sample and wording checked. It had to state counts, name
what it compares against, say *associated* rather than *caused*, label interpretation as interpretation and hypothesis as a
question, and contain no personality or HR language.

1. **Late projects often start with too little runway** (system pattern, moderate).

   "329 of 423 late projects (78%) entered In Progress with less time before the Requested ETA than the other Editors' typical
   execution time for that Video Type. Short runway is associated with lateness in this sample: 74% of 444 short-runway
   projects were late against 54% of 81 with adequate runway. 10 late projects had already passed their Requested ETA when In
   Progress began."

   Interpretation, labelled: "part of the lateness may begin before the Editor's work starts". Contradicting evidence is
   attached: 44 late projects that had adequate runway. This quantifies the process question recorded in D46.

2. **Will: the late-rate headline needs context** (hidden context, moderate). The headline is 84% against 69%. The checks that
   hold:
   - competitive whole-history speed (all 109 speed-measurable projects are *similar*);
   - 31 late projects executed within typical time;
   - on the same Video Type mix, the others would be late 68% against 82% observed.

   One check does **not** hold and is published as such: late projects are *not* more concentrated in short runway than his
   on-time ones.

   **Consistency check.** The separate `person.mix_adjusted_deadline` finding states that the mix explains only 10% of Will's
   gap, and that the remaining 14 points sit just below the 15-point material difference. The two findings agree. Neither
   claims that the mix explains his lateness.

3. **Will: improvement against his own baseline** (improvement, moderate). The late rate is 57% in the last 30 days against 91%
   in his earlier history. The other Editors moved from 70% to 63% over the same periods, so the change is more likely specific
   to him.

4. **Mario** has several findings:
   - approved Slower in Premium Short, current window;
   - his whole-history speed reading is neutral, which the questioned-headline finding cites;
   - the graph links the two with a `contradicts` edge, so a reader sees both windows;
   - his late rate is 82%, while the others would be late 82% on the same Video Type mix (a headline explained by mix);
   - 43 of 64 Negative signals are Late Delivery;
   - at higher concurrent workload (above his own median), execution is associated with longer elapsed time in 4 of 4 Video
     Types. The wording is association only.

5. **Ibrahim** has three findings:
   - late 37% against 69% predicted by the same Video Type mix, and the gap persists under similar runway (79 projects). This is
     a favourable Editor-specific pattern pointing to recognition;
   - approved Faster in Class A;
   - he receives Class A work with short runway more often than his other work. This is published as **upstream context, not
     an Editor weakness**.

6. **Refaat: slower in Simple Short against his own history** (+26.3%). The team moved +24.3% over the same periods, so the
   finding is **hidden context** ("mirrors the team"), not an Editor deterioration. It links to the Video Type finding
   *Simple Short execution time worsened across Editors*: 4 of 4 Editors moved the same way.

7. **Delay after on-time submission** (hidden context, moderate). 72 of 162 projects submitted for approval on or before the
   ETA were delivered after it. 5 of these carry a Late Delivery label although the Editor submitted on time.

8. **Workload moves with outcomes across the team** (association, moderate). Across 31 Editor × Video Type groups, projects that
   started at higher concurrency took longer (median difference 59.1%, 27 of 31 groups the same way). The wording is "not proof
   of cause (elapsed time includes parallel work)".

### A.5 Defects found in validation and fixed

| Found | Fix |
|---|---|
| The mix-adjusted "raw gap reflects work mix" wording appeared when the mix explained only 10% of the gap (Will) | The wording now requires the mix to explain more than half of the gap; otherwise the finding says the adjusted gap fell just below material |
| Short runway confined to one Editor was reported as an adverse Editor-specific pattern | Runway is upstream: it is now hidden context with neutral wording |
| Open projects resembling historical groups that were late *less* often than their Video Type were flagged | Similarity is now a signal only when the similar group was late more often than the Video Type |
| An Editor's change that mirrored the team's change (Refaat, +26% against +24%) was an Editor deterioration | Difference-in-differences: an Editor change is Editor-specific only when it differs from the team's by the material amount |
| The relationship graph linked unrelated findings (185 context edges); chains hopped between Editors | Edges need an explicit type-pair rule **and** shared Monday projects; chains stay on one subject |
| Almost every finding reported evidence level "hypothesis" | `evidence_level` is the observed basis; `statement_levels` lists the layers |

### A.6 Residual concerns (before D53)

- **The workload association is partly mechanical.** A long project is more likely to overlap others; the wording and the
  limitations say so. Do not approve `workload.band_rule` without reading that caveat.
- **The whole-history "typical execution"** uses other Editors' work before and after each project. It is descriptive, not a
  time-aligned benchmark, and it is disclosed as a limitation.
- **Several proposals mirror D52 values** (15 points, 25%) chosen for a different purpose. D53 must decide them explicitly;
  mirroring is not approval.
