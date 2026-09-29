# Round 4 independent threshold candidate after identity attestation

**Candidate only — not an approval, contract change, production activation, or Monday write.**

This note is an independent replay of the copied, read-only production run
`20260929T130736Z-e6d03314e704`. It proposes values for owner review where the observed
distribution is strong enough to support a candidate. It leaves Trend open where the
current model and one adjacent-window comparison do not support a fair rule. Contract
1.5.0 remains unchanged and production remains pinned to its existing contract.

## Result in one page

- The run passes the production verifier: 132 manifest-declared raw/extract files checked,
  no failures. The immutable extract SHA-256 is
  `637b40ac13e503efc270608388f27a9643c8fe05c8123baa4e041c35666ff3a0`.
- The capture was made under contract 1.4.0. This analysis replays it through the current
  contract 1.5.0 candidate with an **in-memory only** exact-tuple identity overlay.
- The overlay increases all-history completed attribution from 170 to 681 (`+511`),
  current-window coverage from 36 to 136 (`+100`), and comparison-window coverage from
  25 to 129 (`+104`). Speed benchmark-eligible projects increase from 33 to 133 (`+100`)
  current and 24 to 128 (`+104`) comparison. It does not repair missing historical Editor
  events.
- A defensible **shadow-evaluation candidate** is:

  | Rule | Candidate value |
  |---|---|
  | Quality minimum | 10 eligible completed projects |
  | Quality Negative | negative occurrence rate `>= 20%` |
  | Quality Positive | otherwise, positive occurrence rate `>= 15%` |
  | Speed subject minimum | 5 projects in the exact eligible Video Type cohort |
  | Speed comparator minimum | 10 projects from at least 2 other Editors; the distinct-Editor floor needs config/runtime support |
  | Speed Faster / Similar / Slower | `< -30%` / `[-30%, +30%]` / `> +30%` versus leave-one-out peer median |
  | Deadline subject minimum | 10 deadline-classifiable projects |
  | Deadline comparator minimum | 30 other-Editor projects |
  | Deadline Positive / Neutral / Negative | late-rate difference `< -15 pp` / `[-15 pp, +15 pp]` / `> +15 pp` |
  | Overall Status | explicit symmetric lookup below; at least two classifiable components |
  | Trend | **leave open**; factual Recent Change only |

- These are proposed values, not facts. D25 still requires a versioned config entry and a
  matching decision-log approval before Atlas may classify production data.

## Inputs and deterministic method

Sources read were `AGENTS.md`, `docs/HANDOFF-V2.md` sections 12–21 and 26–29,
`docs/DECISIONS.md` D23–D50, `config/monday-contract-v1.5.json`, and the current cycle,
metric, quality, intelligence, and profile implementations.

The calculation used:

1. first completed cycles reconstructed from Monday evidence;
2. exact historical identity key `(source_label_id, logged_name)`;
3. first valid Ready For Approval as the common Africa/Cairo window anchor;
4. current window `2026-08-30` through `2026-09-28` inclusive and comparison window
   `2026-07-31` through `2026-08-29` inclusive;
5. exact eligible Video Type cohorts, with no pooling of type combinations;
6. leave-one-Editor-out medians for Speed and leave-one-Editor-out late rates for Deadline;
7. scored Quality label **occurrences** divided by eligible projects, exactly as D39 and
   the current implementation define it. Counts are not silently converted to distinct
   labelled projects;
8. client and internal revision events reported separately as non-scoring context.

Two clean executions of the aggregate replay produced byte-identical JSON with SHA-256
`8d162993741e3b237ba410ab0abb605017145cf4836a7bcf7d0967996bf0838b`.

The authoritative task input was applied only in memory:

| Historical tuple | Canonical Editor | Observations | First observed | Last observed |
|---|---|---:|---|---|
| `(4, Mario)` | Mario | 273 | 2026-03-14T00:44:34.286658Z | 2026-09-28T23:40:30.586199Z |
| `(5, Anas)` | Anas | 117 | 2026-05-18T21:18:49.066589Z | 2026-09-28T23:53:06.778508Z |
| `(7, Martin)` | Martin | 80 | 2026-05-12T16:18:07.005690Z | 2026-09-28T23:46:48.811226Z |
| `(8, Samra)` | Samra | 119 | 2026-03-14T06:03:43.139996Z | 2026-08-11T21:21:19.738906Z |
| `(9, Ibrahim)` | Ibrahim | 153 | 2026-05-03T14:10:25.391996Z | 2026-09-29T11:28:22.791445Z |
| `(10, Amir)` | Amir | 81 | 2026-04-22T16:43:52.478289Z | 2026-09-28T23:50:05.196143Z |
| `(11, Refaat)` | Refaat | 55 | 2026-06-29T01:31:10.174360Z | 2026-09-28T23:51:39.316328Z |
| `(5, Ahmed)` | Ahmed | 86 | 2026-03-14T05:58:12.013277Z | 2026-05-04T10:50:59.999145Z |
| `(7, Mans)` | Mansour / `editor-label-14` | 54 | 2026-03-14T06:03:36.639229Z | 2026-05-06T08:13:45.547424Z |
| `(9, Michael)` | Michael / `editor-label-13` | 44 | 2026-03-14T06:03:49.632351Z | 2026-05-02T20:03:48.180209Z |

The task's attestation is applied to each exact tuple over its observed historical range
shown above. The tuple and range together prevent reused label IDs from crossing names.
The current identity resolver keys on the exact tuple but does not enforce temporal bounds;
the production identity update therefore needs to preserve the attested range explicitly
and test that no observation outside it is silently admitted.

The three residual tuples remain quarantined and contribute to no calibration:
`(11, New)` (`invalid_identity_value`, 3 observations), `(2, Done)`
(`invalid_identity_value`, 2), and `(1, El Baz)`
(`unresolved_historical_identity`, 3).

## Coverage and exclusions

The reconstruction produced 1,283 cycles, 861 completed cycles, and 681 completed,
attributed cycles.

| Editor | Completed attributed cycles in captured history |
|---|---:|
| Will | 157 |
| Mario | 143 |
| Ibrahim | 103 |
| Samra | 60 |
| Amir | 59 |
| Martin | 46 |
| Refaat | 45 |
| Anas | 38 |
| Ahmed | 15 |
| Sobhy | 5 |
| Ezz | 4 |
| Ali | 2 |
| Michael | 2 |
| Mohamed Mansour (Office) | 2 |

The attested `Mans` tuple has observations but no completed attributable cycle in this
reconstruction. Samra, Ahmed, and Michael have historical completed cycles but none in
either evaluation window, so they correctly do not enter recent threshold distributions.

Across the whole captured history, cycle reasons were:

| Reason | Count |
|---|---:|
| Open cycle | 320 |
| Unmapped status within cycle window | 246 |
| Missing Editor event | 162 |
| Missing In Progress | 102 |
| Editor changed within cycle | 11 |
| Missing Editor value | 10 |
| Missing Video Type event | 1 |

Quality reconstructed 366 usable label occurrences; 61 occurrences were quarantined for
unresolved Editor and 88 because there was no completed cycle.

| Window | Included | Excluded in that window | Coverage | Deadline classifiable | Speed benchmark-eligible |
|---|---:|---:|---:|---:|---:|
| Current | 136 | 10 | 93.2% | 136 | 133 |
| Comparison | 129 | 14 | 90.2% | 129 | 128 |

Under the proposed sample floors (still shadow-only), component eligibility is:

| Candidate output | Current eligible Editors | Comparison eligible Editors | Paired current/comparison facts |
|---|---:|---:|---:|
| Quality component | 7 of 11 | 7 of 7 | 7 |
| Deadline component | 7 of 11 | 7 of 7 | 7 |
| Speed component | 7 of 11 | 7 of 7 | 7 with at least one shared exact cohort meeting both windows' floors |
| Overall Status (at least two components) | 7 of 11 | 7 of 7 | 7 |
| Approved Trend label | 0 | 0 | 0; seven Editors have paired factual inputs, but the Trend rule is unapproved |

Current exclusions contain 10 unresolved Editor histories, one of which also has an
unmapped status. Comparison exclusions contain 11 missing Editor histories and 3
Editor-changed-within-cycle records; 2 of those also have an empty Editor value. The Speed
loss is three current `Reels Boost Pack (22)` records and one comparison `Unbranded (26)`
record because those IDs are not approved base types or modifiers. Reason counts overlap
when one project has multiple reasons.

## Editor, Deadline, Quality, and revision distributions

`E/L/rate` means evaluated projects / late projects / absolute late rate. Peer facts are
leave-one-Editor-out. `Δ pp` is Editor late rate minus peer late rate. Revisions are
projects/events and remain context only.

### Current window

| Editor | Projects | Deadline E/L/rate | Peer n/editors/rate | Δ pp | Quality +count/rate | Quality −count/rate | Client rev p/e | Internal rev p/e |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Ali | 2 | 2/2/100.0% | 134/10/61.2% | +38.81 | 0/0.0% | 0/0.0% | 2/3 | 2/3 |
| Amir | 14 | 14/12/85.7% | 122/10/59.0% | +26.70 | 0/0.0% | 1/7.1% | 12/36 | 4/5 |
| Anas | 12 | 12/7/58.3% | 124/10/62.1% | -3.76 | 0/0.0% | 0/0.0% | 11/29 | 8/12 |
| Ezz | 4 | 4/2/50.0% | 132/10/62.1% | -12.12 | 0/0.0% | 0/0.0% | 3/7 | 4/8 |
| Ibrahim | 26 | 26/8/30.8% | 110/10/69.1% | -38.32 | 2/7.7% | 0/0.0% | 11/18 | 3/3 |
| Mario | 17 | 17/14/82.3% | 119/10/58.8% | +23.53 | 0/0.0% | 5/29.4% | 16/40 | 5/11 |
| Martin | 17 | 17/9/52.9% | 119/10/63.0% | -10.08 | 0/0.0% | 0/0.0% | 17/48 | 6/6 |
| Mohamed Mansour (Office) | 2 | 2/1/50.0% | 134/10/61.9% | -11.94 | 0/0.0% | 0/0.0% | 2/4 | 1/1 |
| Refaat | 14 | 14/12/85.7% | 122/10/59.0% | +26.70 | 0/0.0% | 0/0.0% | 11/28 | 4/5 |
| Sobhy | 5 | 5/4/80.0% | 131/10/61.1% | +18.93 | 0/0.0% | 0/0.0% | 4/11 | 3/5 |
| Will | 23 | 23/13/56.5% | 113/10/62.8% | -6.31 | 4/17.4% | 0/0.0% | 18/29 | 9/10 |

There are 85 visible Quality occurrences: 6 scored Positive, 6 scored Negative, and 73
deadline/context occurrences that stay visible but do not enter Quality. Scored labels are
Amir `Technical Issues=1`, Ibrahim `Client Praise=2`, Mario `Technical Issues=1` plus
`Poor Communication=4`, and Will `Client Praise=4`. Deadline labels (`On Time Delivery`,
`Late Delivery`) are excluded from Quality scoring. Revision context totals are 107 projects
/ 253 client events and 49 projects / 69 internal events.

### Comparison window

| Editor | Projects | Deadline E/L/rate | Peer n/editors/rate | Δ pp | Quality +count/rate | Quality −count/rate | Client rev p/e | Internal rev p/e |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Amir | 12 | 12/9/75.0% | 117/6/72.7% | +2.35 | 0/0.0% | 0/0.0% | 12/26 | 9/16 |
| Anas | 16 | 16/12/75.0% | 113/6/72.6% | +2.43 | 0/0.0% | 0/0.0% | 16/34 | 11/31 |
| Ibrahim | 24 | 24/7/29.2% | 105/6/82.9% | -53.69 | 5/20.8% | 0/0.0% | 8/11 | 3/7 |
| Mario | 17 | 17/17/100.0% | 112/6/68.8% | +31.25 | 0/0.0% | 7/41.2% | 16/38 | 4/5 |
| Martin | 20 | 20/13/65.0% | 109/6/74.3% | -9.31 | 0/0.0% | 0/0.0% | 19/44 | 15/30 |
| Refaat | 15 | 15/14/93.3% | 114/6/70.2% | +23.16 | 0/0.0% | 1/6.7% | 14/24 | 10/16 |
| Will | 25 | 25/22/88.0% | 104/6/69.2% | +18.77 | 4/16.0% | 2/8.0% | 22/45 | 9/14 |

There are 89 visible Quality occurrences: 9 scored Positive, 10 scored Negative, and 70
deadline/context occurrences. Scored labels are Ibrahim `Client Praise=5`, Mario
`Poor Communication=7`, Refaat `Poor Communication=1`, and Will `Client Praise=4` plus
`Poor Communication=2`. Revision context totals are 107 projects / 222 client events and
61 projects / 119 internal events.

The zero scored-label rate for several Editors means “no scored occurrence in this
snapshot-backed evidence”, not “proven perfect quality”. This distinction is material to
fairness and should be visible with the count and denominator.

## Exact Video Type and comparator distributions

Eligible cohort legend: `4` Class A, `5` Class B, `6` Simple Short, `8` Class A+,
`27` Premium Short; modifiers are `10` 2* and `16` Ai. Combinations remain exact.
Negative difference is faster than the peer median. Every row below is factual even when
it is below the proposed classification minimum.

### Current window

| Editor | Exact type | Subject n / median h | Peer n / editors / median h | Difference |
|---|---|---:|---:|---:|
| Ali | `16:4` | 1 / 28.18 | 6 / 3 / 41.53 | -32.2% |
| Ali | `4` | 1 / 66.04 | 35 / 6 / 34.42 | +91.9% |
| Amir | `27` | 10 / 37.92 | 32 / 5 / 32.98 | +15.0% |
| Amir | `5` | 3 / 39.63 | 13 / 3 / 32.68 | +21.3% |
| Amir | `6` | 1 / 37.69 | 23 / 3 / 41.61 | -9.4% |
| Anas | `27` | 4 / 36.66 | 38 / 5 / 36.22 | +1.2% |
| Anas | `6` | 8 / 43.71 | 16 / 3 / 37.24 | +17.4% |
| Ezz | `4` | 3 / 48.10 | 33 / 6 / 33.00 | +45.8% |
| Ibrahim | `10:16:4` | 1 / 28.29 | 1 / 1 / 29.06 | -2.6% |
| Ibrahim | `10:16:8` | 1 / 40.88 | 0 / 0 / — | not comparable |
| Ibrahim | `16:4` | 3 / 32.89 | 4 / 3 / 42.56 | -22.7% |
| Ibrahim | `4` | 20 / 31.44 | 16 / 6 / 47.83 | -34.3% |
| Ibrahim | `5` | 1 / 17.44 | 15 / 3 / 36.43 | -52.1% |
| Mario | `27` | 10 / 53.20 | 32 / 5 / 29.77 | +78.7% |
| Mario | `4` | 1 / 47.56 | 35 / 6 / 34.42 | +38.2% |
| Mario | `5` | 6 / 30.59 | 10 / 3 / 38.03 | -19.6% |
| Martin | `27` | 13 / 25.84 | 29 / 5 / 39.43 | -34.5% |
| Martin | `6` | 4 / 29.07 | 20 / 3 / 42.29 | -31.3% |
| Mohamed Mansour (Office) | `10:16:4` | 1 / 29.06 | 1 / 1 / 28.29 | +2.7% |
| Mohamed Mansour (Office) | `4` | 1 / 52.26 | 35 / 6 / 34.42 | +51.8% |
| Refaat | `27` | 3 / 38.67 | 39 / 5 / 34.89 | +10.8% |
| Refaat | `6` | 11 / 41.61 | 13 / 3 / 37.69 | +10.4% |
| Sobhy | `10:4` | 1 / 53.68 | 0 / 0 / — | not comparable |
| Sobhy | `16:4` | 1 / 56.94 | 6 / 3 / 30.53 | +86.5% |
| Sobhy | `4` | 2 / 56.88 | 34 / 6 / 33.71 | +68.7% |
| Will | `16:4` | 2 / 39.69 | 5 / 3 / 32.89 | +20.7% |
| Will | `16:5` | 1 / 48.54 | 0 / 0 / — | not comparable |
| Will | `27` | 2 / 50.64 | 40 / 5 / 32.98 | +53.6% |
| Will | `4` | 8 / 29.97 | 28 / 6 / 42.48 | -29.4% |
| Will | `5` | 6 / 37.51 | 10 / 3 / 35.92 | +4.4% |
| Will | `8` | 3 / 24.72 | 0 / 0 / — | not comparable |

### Comparison window

| Editor | Exact type | Subject n / median h | Peer n / editors / median h | Difference |
|---|---|---:|---:|---:|
| Amir | `27` | 10 / 51.08 | 29 / 5 / 49.46 | +3.3% |
| Amir | `6` | 2 / 18.60 | 28 / 3 / 36.09 | -48.5% |
| Anas | `27` | 7 / 50.18 | 32 / 5 / 48.72 | +3.0% |
| Anas | `6` | 9 / 36.16 | 21 / 3 / 33.95 | +6.5% |
| Ibrahim | `4` | 22 / 28.95 | 11 / 2 / 69.36 | -58.3% |
| Ibrahim | `5` | 1 / 25.63 | 21 / 2 / 59.54 | -57.0% |
| Ibrahim | `8` | 1 / 30.10 | 0 / 0 / — | not comparable |
| Mario | `27` | 4 / 98.44 | 35 / 5 / 48.70 | +102.1% |
| Mario | `4` | 3 / 120.53 | 30 / 2 / 31.37 | +284.2% |
| Mario | `5` | 10 / 67.22 | 12 / 2 / 57.86 | +16.2% |
| Martin | `27` | 14 / 42.06 | 25 / 5 / 50.74 | -17.1% |
| Martin | `6` | 6 / 15.57 | 24 / 3 / 37.49 | -58.5% |
| Refaat | `27` | 2 / 47.92 | 37 / 5 / 49.46 | -3.1% |
| Refaat | `6` | 13 / 41.03 | 17 / 3 / 22.37 | +83.4% |
| Will | `10:16:4` | 1 / 57.94 | 0 / 0 / — | not comparable |
| Will | `16:4` | 1 / 36.79 | 0 / 0 / — | not comparable |
| Will | `16:5` | 1 / 38.63 | 0 / 0 / — | not comparable |
| Will | `27` | 2 / 28.68 | 37 / 5 / 50.18 | -42.8% |
| Will | `4` | 8 / 50.52 | 25 / 2 / 30.59 | +65.1% |
| Will | `5` | 11 / 59.10 | 11 / 2 / 66.79 | -11.5% |

The exact-cohort distribution is sparse: 9 current and 10 comparison Editor/type cells
meet the proposed `5 subject / 10 peer / 2 peer Editors` minima. Raising the project pair
to `5 / 20` leaves only 4 and 6 cells; lowering it to `3 / 10` admits 14 and 12. The
`5 / 10 / 2` candidate preserves the already-established five-project subject guard,
prevents a nominal “team” benchmark made from only one other person, and avoids a
near-empty Speed component. All 19 cells meeting the two project-count floors in this run
also have at least two peer Editors, so the added fairness guard does not change the
eligibility counts above. It does require an explicit config field and runtime enforcement:
the current runtime only checks for one other Editor and merely reports the distinct count.

At a conservative ±30% band, the non-neutral qualifying cells are current Ibrahim/Class A
Faster, Mario/Premium Short Slower, Martin/Premium Short Faster; and comparison
Ibrahim/Class A Faster, Martin/Simple Short Faster, Refaat/Simple Short Slower, and
Will/Class A Slower. Leave-one-project-out median ranges preserve all of those directions
except Mario/Premium Short can move just inside the neutral boundary (its resulting
difference range is about +29.6% to +131.6%). That boundary sensitivity must remain
visible during shadow evaluation.

## Recent Change facts, not Trend

All rate changes are current minus comparison in percentage points. Speed change is the
change in the exact cohort's percentage difference; it is not averaged across types.

| Editor | Δ projects | Deadline late Δ pp | Quality positive Δ pp | Quality negative Δ pp | Exact-type Speed change |
|---|---:|---:|---:|---:|---|
| Amir | +2 | +10.71 | 0.00 | +7.14 | `27` +11.7; `6` +39.1 |
| Anas | -4 | -16.67 | 0.00 | 0.00 | `27` -1.8; `6` +10.9 |
| Ibrahim | +2 | +1.60 | -13.14 | 0.00 | `4` +24.0; `5` +4.9 |
| Mario | 0 | -17.65 | 0.00 | -11.77 | `27` -23.4; `4` -246.0; `5` -35.8 (sign flip) |
| Martin | -3 | -12.06 | 0.00 | 0.00 | `27` -17.4; `6` +27.2 |
| Refaat | -1 | -7.62 | 0.00 | -6.67 | `27` +13.9 (sign flip); `6` -73.0 |
| Will | -2 | -31.48 | +1.39 | -8.00 | `27` +96.4, `4` -94.5, `5` +15.9 (all sign flips) |

Ali, Ezz, Mohamed Mansour (Office), and Sobhy have no eligible comparison-window sample,
so no change is computed.

Trend should remain unapproved for two independent reasons:

1. This is one frozen run with only one adjacent comparison. Leave-one-project-out ranges
   already cross a plausible 15 pp Deadline materiality boundary for Anas, Mario, and
   Martin; only Will's -31.48 pp change stays beyond -20 pp across that sensitivity check.
2. The current config/runtime exposes one global `material_change_threshold`, but D23 and
   HANDOFF-V2 require metric-specific materiality. Deadline and Quality rates are rate
   differences, Speed facts are exact-type percentage differences, their favorable
   directions differ, and D38 provides no single scalar Speed change to feed that global
   field. A single number would be unit-confused and unfair.

Continue showing these factual changes, with samples, until the rule can express
metric-specific thresholds and Speed Trend aggregation and can be checked on more than
one frozen evaluation date.

## Why the proposed component values are reasonable candidates

### Quality

At minimum 10 projects, 7 current and all 7 comparison Editors are classifiable; a minimum
of 5 would add only one current Editor, while 8 classifies the same seven as 10. The 20%
negative candidate isolates Mario in both windows (29.4%, 41.2%) and stays above his
leave-one-project-out lower bounds (25.0%, 37.5%). The 15% positive candidate identifies
Will in both windows (17.4%, 16.0%) and Ibrahim only in comparison (20.8%); Will is close
enough to the boundary that shadow monitoring is required. Negative takes precedence, as
D39 specifies.

This is the least reliable proposed component because scored labels are sparse and label
application completeness is not proven. Do not interpret zero as a positive signal, and
do not approve the candidate unless the business owner confirms that the Monday label
workflow is applied consistently.

### Deadline

All 265 eligible projects are Deadline-classifiable, and proposed 10-project subject /
30-project peer minima classify 7 Editors in each window. Every qualifying current peer
sample contains 10 other Editors and every qualifying comparison peer sample contains 6,
so the observed result is not a disguised one-Editor comparator. The ±15 percentage-point
band separates the large observed gaps from the central group:

- current: Positive Ibrahim; Negative Amir, Mario, Refaat; Neutral Anas, Martin, Will;
- comparison: Positive Ibrahim; Negative Mario, Refaat, Will; Neutral Amir, Anas, Martin.

The absolute late rates remain visible and authoritative facts; the component is relative
and must not describe 56.5% late as intrinsically good merely because peers were later.

### Speed

The ±30% band is intentionally wider than the dense cluster near zero and avoids making
cells at +15% to +21% or -20% look decisive. A five-project subject median can still be
sensitive, so the exact subject count, peer project count, and peer Editor count must
remain adjacent to any verdict. A minimum of two peer Editors is warranted: otherwise one
person's work is relabelled as a “team” comparator, creating a concentration fairness
problem even when project count is 10. Exact cohorts and leave-one-out peers are
non-negotiable.

## Proposed Overall Status lookup

This is a semantic proposal rather than a fitted score. It is symmetric across Quality,
Speed, and Deadline, uses no weights, and should be expanded into explicit versioned keys
in configuration if approved. `P`, `0`, `N`, and `X` mean Positive, Neutral, Negative, and
Not classifiable.

For three classifiable components, the table is:

| Component-state multiset | Status |
|---|---|
| `P P P` | Strong |
| `P P 0` | Strong |
| `P P N` | Mixed |
| `P 0 0` | Good |
| `P 0 N` | Mixed |
| `P N N` | Below Expectations |
| `0 0 0` | Good |
| `0 0 N` | Mixed |
| `0 N N` | Below Expectations |
| `N N N` | Below Expectations |

For exactly two classifiable components (the third is `X`):

| Two classifiable states | Status |
|---|---|
| `P P` | Strong |
| `P 0` | Good |
| `P N` | Mixed |
| `0 0` | Good |
| `0 N` | Mixed |
| `N N` | Below Expectations |

Fewer than two classifiable components maps to `Not enough evidence to classify`, before
lookup, per D41. Component order must not change the result; production config should
enumerate every ordered key rather than calculate a score at runtime.

Applying the full candidate only as a shadow calculation yields:

| Editor | Current Q/S/D | Current candidate status | Comparison Q/S/D | Comparison candidate status |
|---|---|---|---|---|
| Ali | X/X/X | Not enough evidence | — | — |
| Amir | 0/0/N | Mixed | 0/0/0 | Good |
| Anas | 0/0/0 | Good | 0/0/0 | Good |
| Ezz | X/X/X | Not enough evidence | — | — |
| Ibrahim | 0/P/P | Strong | P/P/P | Strong |
| Mario | N/N/N | Below Expectations | N/0/N | Below Expectations |
| Martin | 0/P/0 | Good | 0/0/0 | Good |
| Mohamed Mansour (Office) | X/X/X | Not enough evidence | — | — |
| Refaat | 0/0/N | Mixed | 0/N/N | Below Expectations |
| Sobhy | X/X/X | Not enough evidence | — | — |
| Will | P/0/0 | Good | P/0/N | Mixed |

This table is an interpretive stress test, not a publication result.

## Reliability, fairness, and semantic findings

1. **Identity improvement is real but does not imply complete history.** The overlay lifts
   recent coverage sharply, yet 10 current and 14 comparison projects remain excluded for
   missing/changed Editor history. Current snapshots are never substituted for historical
   Editor evidence.
2. **Quality counts are occurrences, not distinct projects.** The present data happen not
   to create an obvious rate above 100%, but the rule permits multiple scored labels on one
   project. UI wording and tests must not call the numerator “projects with a label”.
3. **Comparator Editor count matters.** Deadline qualifying comparators have 6–10 distinct
   other Editors in this run. Speed cells have only 2–6, and several factual cells have
   zero. Project count alone can hide concentration; always expose both counts.
4. **Exact types prevent an unfair pooled benchmark but create sparsity.** Only 6 current
   and 4 comparison exact types have at least two Editors at all; several modifier cohorts
   are non-comparable. Never collapse `16:4` into `4` to gain sample size.
5. **Type mix differs materially by Editor.** For example, current Ibrahim has 20 Class A
   projects while Mario and Martin are concentrated in Premium Short. D38's project-weighted
   majority is fairer than averaging cohort percentage differences, but it still means a
   high-volume type dominates the Editor's Speed component by design.
6. **Deadline is relative but not Video-Type-adjusted.** That is the settled D45 rule, not
   an error, but managers must see both the absolute late rate and peer comparison so
   differing work mix is not obscured.
7. **Revision volume is high and non-scoring.** Current client/internal event totals are
   253/69; comparison totals are 222/119. No threshold recommendation uses them.
8. **Temporal stability is not established.** Two non-overlapping windows show several
   Speed sign flips and large changes. A second frozen evaluation date is needed before
   calling these thresholds stable rather than merely plausible.
9. **The capture/replay contract distinction must be retained.** The immutable run says
   contract 1.4.0; this note is a deterministic 1.5.0 candidate replay, not evidence that
   production already ran contract 1.5.0.

## Recommendation to the approver

Advance the Quality, Speed, Deadline, and Overall lookup values above as a **shadow
candidate** for business-owner review. Do not activate them from this note. Before D25
approval, require:

1. confirmation that scored Quality labels are applied consistently enough that absence is
   meaningful;
2. the same report on at least one later frozen evaluation date, with boundary-flip counts;
3. explicit acceptance of the `5/10/2` Speed sample tradeoff, plus config/runtime support
   for `minimum_comparator_editor_count = 2`;
4. expansion of the symmetric Overall lookup to all ordered configuration keys; and
5. separate design/approval of metric-specific Trend rules. Until item 5 is complete,
   publish Recent Change facts only.

No production file, contract threshold, activation flag, Monday value, or publication was
changed by this analysis.
