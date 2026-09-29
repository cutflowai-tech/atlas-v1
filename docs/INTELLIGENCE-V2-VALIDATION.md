# Intelligence V2: production validation

Task 64 of the Intelligence V2 brief.

**Data.** Production run `20260929T130736Z-e6d03314e704`:

- 2026-02-01 to 2026-09-29;
- 1,305 items;
- 861 completed first cycles, 681 attributed;
- contract 1.5.0;
- `generated_at` equal to the snapshot time, `2026-09-29T13:10:36Z`.

The run was read from a read-only copy of the raw extract. Nothing was written to Monday, the repository or any published
location. No credential appears here. Editor names are the attested display names already used throughout the repository.
Monday item IDs are shown so a reviewer can open them.

## 1. What was run

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

## 2. Independent recomputation

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

## 3. One record traced to raw Monday data

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

## 4. Reviewed findings, with wording checks

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

## 5. Defects found in validation and fixed before this report

| Found | Fix |
|---|---|
| The mix-adjusted "raw gap reflects work mix" wording appeared when the mix explained only 10% of the gap (Will) | The wording now requires the mix to explain more than half of the gap; otherwise the finding says the adjusted gap fell just below material |
| Short runway confined to one Editor was reported as an adverse Editor-specific pattern | Runway is upstream: it is now hidden context with neutral wording |
| Open projects resembling historical groups that were late *less* often than their Video Type were flagged | Similarity is now a signal only when the similar group was late more often than the Video Type |
| An Editor's change that mirrored the team's change (Refaat, +26% against +24%) was an Editor deterioration | Difference-in-differences: an Editor change is Editor-specific only when it differs from the team's by the material amount |
| The relationship graph linked unrelated findings (185 context edges); chains hopped between Editors | Edges need an explicit type-pair rule **and** shared Monday projects; chains stay on one subject |
| Almost every finding reported evidence level "hypothesis" | `evidence_level` is the observed basis; `statement_levels` lists the layers |

## 6. Residual concerns for reviewers

- **The workload association is partly mechanical.** A long project is more likely to overlap others; the wording and the
  limitations say so. Do not approve `workload.band_rule` without reading that caveat.
- **The whole-history "typical execution"** uses other Editors' work before and after each project. It is descriptive, not a
  time-aligned benchmark, and it is disclosed as a limitation.
- **Several proposals mirror D52 values** (15 points, 25%) chosen for a different purpose. D53 must decide them explicitly;
  mirroring is not approval.
