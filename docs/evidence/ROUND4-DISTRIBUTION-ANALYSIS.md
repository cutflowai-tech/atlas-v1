# Round 4 Editor-intelligence distribution analysis (2026-09-29)

## Decision summary

The identity prerequisite in D44 is satisfied for this analysis by the management attestations supplied with the task. Applying those attestations only in memory raises attributable completed cycles from **170/861 (19.7%)** to **681/861 (79.1%)**. The common all-time metric cohort contains **617** projects, compared with the previous 147 fully speed-eligible projects. The current and comparison windows contain 136 and 129 eligible projects respectively.

This report proposes the following values for management review; none is written to the contract or treated as approved:

| Rule | Proposed value | Evidence status |
|---|---|---|
| Speed subject minimum | 5 projects in the exact Video Type | Candidate; nine current Editor/Video-Type pairs remain classifiable |
| Speed comparator minimum | 10 other-editor projects in the exact Video Type | Candidate; leave-one-out only |
| Speed bands | Faster below -25%; Similar -25% through +25%; Slower above +25% | Candidate; 255/278 (91.7%) one-project perturbations retain their verdict and 7/9 pairs are fully stable |
| Deadline subject minimum | 10 deadline-classifiable projects | Candidate; seven current Editors remain classifiable |
| Deadline comparator minimum | 60 other-editor deadline-classifiable projects | Candidate; all seven current comparisons exceed it |
| Deadline bands | Positive below -15 percentage points; Neutral -15 through +15; Negative above +15 | Candidate; all 952 one-project perturbations retain their state |
| Overall lookup | Explicit semantic table described in section 8; at least two components | Candidate policy table, not fitted arithmetic |
| Quality N/P/minimum | **Open** | Only two current Editors have any scored positive occurrence and only two have any scored negative occurrence; no independent outcome identifies acceptable rates |
| Trend minimum/material change | **Open** | One adjacent window pair is insufficient, and the current single threshold field mixes rate proportions with speed seconds |

Under D25, every candidate above remains `rule_not_approved` until a versioned contract entry and matching decision-log approval exist. This analysis did not modify `config/monday-contract-v1.5.json`, activate 1.5, deploy, or write to Monday.

## 1. Sources and reproducibility

Only primary repository sources and the copied production run were used:

- production run: `/Users/ahri/Atlas_Waset/prod-raw/20260929T130736Z-e6d03314e704`
- run ID: `20260929T130736Z-e6d03314e704`
- retrieved: `2026-09-29T13:10:36Z`
- manifest SHA-256: `74eae68dca4aface5dd15a6bc4a9c2a265bd0ca79be875ae6a5ec55c0421ea55`
- contract: `config/monday-contract-v1.5.json`
- contract SHA-256 at analysis time: `115f55e9171f45ec5bcb3ca63fd9bff2868e29bc0a76f5cfd8a2bc78058a7205`
- governing sources: `docs/DECISIONS.md` D23-D47, the Editor-intelligence sections of `docs/HANDOFF-V2.md`, the contract, and the production implementations in `intelligence.py` and `profile.py`
- comparison sources: `CONTRACT-1.5-IDENTITY.md`, `IDENTITY-ATTESTATION-REQUEST.md`, `BENCHMARK-STATISTIC-ANALYSIS.md`, and the REAL validation reports

The verifier passed: 132 raw/extract files checked, 43 read windows, no split/capped window, 26,866 update events, 1,305 items, and 1,300 items with proven complete history. Five moved-in items lack a `create_pulse`; the runtime retains that limitation rather than inferring history.

Reproduce the complete aggregate JSON:

```sh
PYTHONPATH=src python3 scripts/round4_distribution_analysis.py \
  --run-dir /Users/ahri/Atlas_Waset/prod-raw/20260929T130736Z-e6d03314e704
```

Two independent executions produced the same output SHA-256:

```text
e6b91666c11ccd3f5b0e65a9a8160e9db8b299ade95bf5612aac392eff1c141e
```

The script fails closed if verification fails, an attested tuple is absent, its observed first/last day changes, or a contract mapping conflicts with an attestation. If an integrated contract already contains the exact mapping, the script uses that entry rather than adding a duplicate; the temporary overlay exists only for the pre-integration contract used here.

## 2. Identity and coverage

The exact `(source_label_id, logged_name)` key is retained. The observed raw-event project count below is not the earlier completed-cycle count: it includes every item on which the tuple appeared, including open, invalid, or later-excluded items.

| Observed tuple | Canonical Editor | First raw observation (UTC) | Last raw observation (UTC) | Items observed |
|---|---|---|---|---:|
| `(4, Mario)` | Mario | 2026-03-14 00:44:34 | 2026-09-28 23:40:30 | 188 |
| `(5, Anas)` | Anas | 2026-05-18 21:18:49 | 2026-09-28 23:53:06 | 77 |
| `(7, Martin)` | Martin | 2026-05-12 16:18:07 | 2026-09-28 23:46:48 | 62 |
| `(8, Samra)` | Samra | 2026-03-14 06:03:43 | 2026-08-11 21:21:19 | 98 |
| `(9, Ibrahim)` | Ibrahim | 2026-05-03 14:10:25 | 2026-09-29 11:28:22 | 134 |
| `(10, Amir)` | Amir | 2026-04-22 16:43:52 | 2026-09-28 23:50:05 | 81 |
| `(11, Refaat)` | Refaat | 2026-06-29 01:31:10 | 2026-09-28 23:51:39 | 54 |
| `(5, Ahmed)` | Ahmed (`editor-label-12`) | 2026-03-14 05:58:12 | 2026-05-04 10:50:59 | 47 |
| `(7, Mans)` | Mansour (`editor-label-14`) | 2026-03-14 06:03:36 | 2026-05-06 08:13:45 | 36 |
| `(9, Michael)` | Michael (`editor-label-13`) | 2026-03-14 06:03:49 | 2026-05-02 20:03:48 | 28 |

The quarantines remain unchanged: `(11, New)` one item and `(2, Done)` one item are invalid workflow residue; `(1, El Baz)` spans two items and remains an unresolved historical identity.

| Coverage measure | Previous analysis | Recomputed | Change |
|---|---:|---:|---:|
| Completed first cycles | 861 | 861 | 0 |
| Identity-attributed completed cycles | 170 | 681 | +511 |
| Speed-eligible completed cycles | 147 | 617 | +470 |
| Timing-valid cycles ignoring identity | 740 | unchanged source reference | — |

The remaining completed-cycle exclusions are: 162 `MISSING_EDITOR_EVENT`, 120 `UNMAPPED_STATUS_WITHIN_CYCLE_WINDOW`, 11 `EDITOR_CHANGED_WITHIN_CYCLE`, 10 `MISSING_EDITOR`, and one `MISSING_VIDEO_TYPE_EVENT`. Counts overlap. Quality reconstruction also quarantines 61 occurrences for unresolved Editor attribution and 88 for no completed cycle.

## 3. Cairo windows and population

The current Cairo day is excluded. A project is assigned once, by its first Ready For Approval converted to Cairo time; later quality-label events do not move it.

| Window | Cairo dates, end exclusive | Eligible projects | Editors |
|---|---|---:|---:|
| Current | 2026-08-30 → 2026-09-29 | 136 | 11 |
| Comparison | 2026-07-31 → 2026-08-30 | 129 | 7 |

Current projects by Editor: Ibrahim 26, Will 23, Mario 17, Martin 17, Amir 14, Refaat 14, Anas 12, Sobhy 5, Ezz 4, Ali 2, and Mohamed Mansour (Office) 2. Comparison projects: Will 25, Ibrahim 24, Martin 20, Mario 17, Anas 16, Refaat 15, and Amir 12.

Across the all-time common cohort there are 617 projects: Mario 139, Will 134, Ibrahim 89, Samra 59, Martin 46, Refaat 45, Amir 40, Anas 38, Ahmed 12, Sobhy 5, Ezz 4, Michael 2, Ali 2, and Mohamed Mansour (Office) 2. The attested early Mansour observations yield no project surviving all common exclusions; the identity mapping is still retained as factual history.

## 4. Quality distribution

Quality uses the eligible completed-project denominator. It parses each supported label separately. `Late Delivery`, `On Time Delivery`, and every Context label stay visible but are excluded from scored Quality; revisions do not enter either rate.

Current visible labels:

| Taxonomy | Label | Occurrences | Scored Quality |
|---|---|---:|:---:|
| Negative | Late Delivery | 20 | no |
| Negative | Poor Communication | 4 | yes |
| Negative | 3- Technical Issues | 2 | yes |
| Positive | On Time Delivery | 48 | no |
| Positive | Client Praise | 6 | yes |
| Context | Additional Revisions | 5 | no |

Comparison visible labels are 28 Late Delivery, 10 Poor Communication, 40 On Time Delivery, 9 Client Praise, and 2 Additional Revisions. Thus the scored current totals are six positive and six negative occurrences; the comparison totals are nine positive and ten negative occurrences.

| Current Editor | Projects | Scored positive | Positive rate | Scored negative | Negative rate |
|---|---:|---:|---:|---:|---:|
| Amir | 14 | 0 | 0.0% | 1 | 7.1% |
| Refaat | 14 | 0 | 0.0% | 0 | 0.0% |
| Sobhy | 5 | 0 | 0.0% | 0 | 0.0% |
| Ezz | 4 | 0 | 0.0% | 0 | 0.0% |
| Ali | 2 | 0 | 0.0% | 0 | 0.0% |
| Mohamed Mansour (Office) | 2 | 0 | 0.0% | 0 | 0.0% |
| Mario | 17 | 0 | 0.0% | 5 | 29.4% |
| Anas | 12 | 0 | 0.0% | 0 | 0.0% |
| Will | 23 | 4 | 17.4% | 0 | 0.0% |
| Martin | 17 | 0 | 0.0% | 0 | 0.0% |
| Ibrahim | 26 | 2 | 7.7% | 0 | 0.0% |

Across Editors, current positive-rate min/Q1/median/Q3/max is 0/0/0/0/17.4%; negative rate is 0/0/0/0/29.4%. Only two Editors have a non-zero positive rate and only two have a non-zero negative rate. Zeroes dominate because scored labels are sparse, not because the data proves a universal Neutral boundary.

**Quality proposal: leave N, P, and minimum sample open.** The run measures frequency but contains no independent review outcome, client satisfaction outcome, or approved loss function that identifies an acceptable positive or negative rate. Any numeric threshold chosen from these four non-zero Editor/rate observations would mostly reproduce the current outliers and would not be evidence of a durable decision boundary.

## 5. Speed distribution and sensitivity

Speed uses first-pass duration only and exact Video Type. Each comparator excludes the subject Editor. Current Editor/Video-Type sample size has min/Q1/median/Q3/max **1/1/3/6/20**. Other-editor sample size is **0/5.5/16/32.5/40**. Across the 27 pairs with a comparator, relative difference is **-52.1% / -21.2% / +10.4% / +42.0% / +91.9%**.

All-time eligible projects by exact Video Type are: type 6: 165; type 4: 156; type 5: 113; type 27: 96; type 8: 24; type 16:4: 14; type 10:4: 13; type 10:16:4: 12; types 16:5 and 16:8: 4 each; type 10:5: 2; type 10:8: 2; and types 10:16:8 and 10:4:5: 1 each. This confirms why exact-type comparison needs a sample floor.

At the proposed 5-subject/10-comparator floor, the current evidence is:

| Editor | Type | Editor n / median h | Other Editors n / median h | Difference | Candidate verdict |
|---|---|---|---|---:|---|
| Amir | 27 | 10 / 37.92 | 32 / 32.98 | +15.0% | Similar |
| Refaat | 6 | 11 / 41.61 | 13 / 37.69 | +10.4% | Similar |
| Mario | 27 | 10 / 53.20 | 32 / 29.77 | +78.7% | Slower |
| Mario | 5 | 6 / 30.59 | 10 / 38.03 | -19.6% | Similar |
| Anas | 6 | 8 / 43.71 | 16 / 37.24 | +17.4% | Similar |
| Will | 4 | 8 / 29.97 | 28 / 42.48 | -29.4% | Faster |
| Will | 5 | 6 / 37.51 | 10 / 35.92 | +4.4% | Similar |
| Martin | 27 | 13 / 25.84 | 29 / 39.43 | -34.5% | Faster |
| Ibrahim | 4 | 20 / 31.44 | 16 / 47.83 | -34.3% | Faster |

Deterministic sensitivity removes each subject or comparator project once, recomputes both medians and the verdict, and treats falling below a floor as a disagreement:

| Symmetric Similar band | Pairs | Fully stable pairs | Agreement over 278 perturbations |
|---:|---:|---:|---:|
| ±10% | 9 | 5 | 80.6% |
| ±15% | 9 | 5 | 80.9% |
| ±20% | 9 | 5 | 83.8% |
| **±25%** | **9** | **7** | **91.7%** |
| ±30% | 9 | 6 | 85.3% |

**Speed proposal:** subject minimum 5, comparator minimum 10, Faster below -25%, Similar from -25% through +25%, Slower above +25%. It is the strongest observed one-project perturbation result in the tested grid while retaining nine pairs. This is a calibration candidate, not proof that 25% is intrinsically good or bad.

Applying D38 project-weighting to those candidate per-type verdicts would make Amir Neutral, Refaat Neutral, Mario Negative, Anas Neutral, Will Positive, Martin Positive, and Ibrahim Positive. Editors without a classifiable type remain Not classifiable.

## 6. Deadline distribution and sensitivity

Deadline remains absolute at the factual layer. In the all-time common cohort, 587 projects are classifiable: 164 early, 0 exactly on time, and 423 late. Current is 52/0/84 of 136; comparison is 35/0/94 of 129. The component comparison below is the subject late rate minus all other eligible Editors' late rate in the same window.

| Current Editor | n | Early / late | Absolute late rate | Other-editor n / late rate | Difference | Candidate state |
|---|---:|---:|---:|---:|---:|---|
| Amir | 14 | 2 / 12 | 85.7% | 122 / 59.0% | +26.7 pp | Negative |
| Refaat | 14 | 2 / 12 | 85.7% | 122 / 59.0% | +26.7 pp | Negative |
| Mario | 17 | 3 / 14 | 82.4% | 119 / 58.8% | +23.5 pp | Negative |
| Anas | 12 | 5 / 7 | 58.3% | 124 / 62.1% | -3.8 pp | Neutral |
| Will | 23 | 10 / 13 | 56.5% | 113 / 62.8% | -6.3 pp | Neutral |
| Martin | 17 | 8 / 9 | 52.9% | 119 / 63.0% | -10.1 pp | Neutral |
| Ibrahim | 26 | 18 / 8 | 30.8% | 110 / 69.1% | -38.3 pp | Positive |
| Sobhy | 5 | 1 / 4 | 80.0% | 131 / 61.1% | +18.9 pp | Not classifiable (n) |
| Ezz | 4 | 2 / 2 | 50.0% | 132 / 62.1% | -12.1 pp | Not classifiable (n) |
| Ali | 2 | 0 / 2 | 100.0% | 134 / 61.2% | +38.8 pp | Not classifiable (n) |
| Mohamed Mansour (Office) | 2 | 1 / 1 | 50.0% | 134 / 61.9% | -11.9 pp | Not classifiable (n) |

At subject minimum 10 and comparator minimum 60, the sensitivity grid gives 91.3% agreement for a ±10 pp band, 100% for ±15 pp, 100% for ±20 pp, and 99.7% for ±25 pp. The ±15 pp band is the narrowest tested band with complete leave-one-project-out stability across all seven eligible Editors.

**Deadline proposal:** subject minimum 10, comparator minimum 60, Positive below -15 pp, Neutral from -15 through +15 pp, Negative above +15 pp. The comparator floor also limits worst-case binary-rate standard error to about 6.5 percentage points; it is a proposed evidence floor, not an SLA or a claim that the absolute late rate is acceptable.

## 7. Recent Change, Trend, and revision context

Recent Change remains factual. For the seven Editors present in both windows, current-minus-comparison late-rate change is:

| Editor | Current n / late rate | Comparison n / late rate | Change |
|---|---|---|---:|
| Amir | 14 / 85.7% | 12 / 75.0% | +10.7 pp |
| Refaat | 14 / 85.7% | 15 / 93.3% | -7.6 pp |
| Mario | 17 / 82.4% | 17 / 100.0% | -17.7 pp |
| Anas | 12 / 58.3% | 16 / 75.0% | -16.7 pp |
| Will | 23 / 56.5% | 25 / 88.0% | -31.5 pp |
| Martin | 17 / 52.9% | 20 / 65.0% | -12.1 pp |
| Ibrahim | 26 / 30.8% | 24 / 29.2% | +1.6 pp |

Across those Editors, deadline change min/Q1/median/Q3/max is -31.5/-17.2/-12.1/-3.0/+10.7 pp. Quality positive-rate change is dominated by zeroes (median 0; range -13.1 to +1.4 pp), as is negative-rate change (median 0; range -11.8 to +7.1 pp). Eighteen Editor/Video-Type pairs occur in both windows; their median-duration change ranges from -72.97 to +21.96 hours, with median -8.72 hours. The full per-pair rows are emitted by the script.

**Trend proposal: leave open.** This run supplies only one adjacent pair of 30-day windows, so there is no repeated evidence of durable change. In addition, the current contract exposes one `material_change_threshold` but the runtime applies it both to rate proportions and to speed seconds. Those units cannot share a defensible scalar. A later contract should use measurement-specific thresholds and calibration over multiple window pairs.

Revisions are context only. Across current Editors, client-revision project-rate min/Q1/median/Q3/max is 42.3/78.4/85.7/97.1/100%; internal-revision rate is 11.5/29.0/39.1/63.3/100%. High prevalence makes revisions important explanatory context, but it supplies no causal evidence about Editor quality and has **no scoring effect**.

## 8. Overall lookup proposal

Overall Status cannot be estimated from Monday history because it is a product-policy mapping, not a measured outcome. It can still be proposed transparently without inventing a numeric score:

1. Fewer than two classifiable components → `Not enough evidence to classify`.
2. Two or more Negative components → `Below Expectations`.
3. Exactly one Negative component → `Mixed`.
4. No Negative and two or more Positive components → `Strong`.
5. No Negative and fewer than two Positive components → `Good`.

The script expands this rule to all 54 Quality/Speed/Deadline combinations with at least two classifiable components. This makes the lookup complete and reviewable while preserving D37 and D41. It deliberately makes one visible Negative sufficient for `Mixed`, two Negative sufficient for `Below Expectations`, and two Positive necessary for `Strong`.

As a non-production what-if using only the proposed Speed and Deadline rules (Quality remains Not classifiable), the seven two-component Editors would be: Amir Mixed, Refaat Mixed, Mario Below Expectations, Anas Good, Will Good, Martin Good, and Ibrahim Strong. This is a policy illustration, not an approved rating.

## 9. What remains open

- Quality N/P/minimum sample: underidentified by sparse scored labels and no external outcome.
- Trend minimum/material threshold: underidentified by one comparison pair and currently not expressible safely across mixed units.
- Strength, attention, recognition, workload, and capacity thresholds: outside this analysis and still unapproved.
- Every proposed Speed, Deadline, and Overall value: requires D25 approval and versioned configuration before the runtime may classify.

No threshold value in this report is a factual property of an Editor. The underlying facts, evidence references, exclusions, rule versions, and `rule_not_approved` behavior remain the authoritative current output.
