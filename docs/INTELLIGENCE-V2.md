# Atlas Intelligence V2: the investigation layer

**Branch:** `feat/atlas-intelligence-v2` (from `ui-ux` at `eccaa8c`). **Status:** implemented and tested; every new business
threshold is **unapproved** (`rule_not_approved`, pending decision D53).

Companion documents:

- [`INTELLIGENCE-V2-CURRENT-STATE.md`](INTELLIGENCE-V2-CURRENT-STATE.md): the audit;
- [`INTELLIGENCE-V2-DATA-CAPABILITIES.md`](INTELLIGENCE-V2-DATA-CAPABILITIES.md): the data map;
- [`INTELLIGENCE-V2-VALIDATION.md`](INTELLIGENCE-V2-VALIDATION.md): production validation;
- [`DECISIONS.md`](DECISIONS.md) → D53: the decisions this layer needs.

Atlas used to stop at `data → metrics → dashboard`. Intelligence V2 adds the step a manager did by hand:

```
Monday data → normalized evidence → deterministic metrics → baselines → patterns → contradictions → context
            → prioritized findings → investigation → management intelligence
```

It is a deterministic, auditable investigation engine. There is no model, no opaque score and no AI-authored fact. Every
sentence it produces can be rebuilt from a structured field, and every field can be rebuilt from Monday event IDs.

## 1. Architecture

```
CycleReconstruction ──► investigation.facts ─────► ProjectFact per completed first cycle, ItemTimeline per item, OpenWork (snapshot)
(existing pipeline)       │                       (reuses cycles, metrics.deadline_result, Quality occurrences; redefines nothing)
editor-profile 1.5 ───────┤
(existing, read-only)     ▼
                     investigation.baselines ──► team / Video Type / Editor self-history / Cairo windows and months
                          ▼
                     detectors (23, investigation.catalog) ──► Finding objects + examined-without-finding records
                          ▼
                     confidence ─► prioritization (rank, severity, duplicate clusters, sections) ─► graph (edges, chains)
                          ▼
                     narrative (deterministic templates) ─► executive brief
                          ▼
                     engine.build_intelligence ──► intelligence-v2 document (contracts/intelligence-v2.schema.json)
                          ▼                                  │
             html.render_intelligence_html (review page)     └─► optional site artifact (feature-gated, site.py)
```

**Package.** `src/atlas_commander/investigation/`:

| Module | Role |
|---|---|
| `policy` | Parameters, D25 approval state, modes |
| `models` | Finding, Statement, Evidence, invariants |
| `facts` | Fact rows, timelines, open work |
| `stats` | Medians, quantiles, exact fractions |
| `baselines` | Team, Video Type, Editor and time baselines |
| `confidence` | Evidence strength |
| detector modules | `concentration`, `bottlenecks`, `changes`, `workload`, `patterns`, `person_system`, `contradictions`, `risks`, `editor`, `data_quality` |
| `catalog` | The detector registry |
| `prioritization` | Rank, severity, clusters, sections |
| `graph` | Relationship edges and chains |
| `narrative` | Wording and executive brief |
| `ai_guard` | Guard for an optional AI rewrite |
| `engine` | Builds the document |
| `site` | Feature gate and publication checks |
| `html` | Review page |
| `__main__` | CLI |

**Boundaries:**

- V2 is **never an input** to a metric, a component state, Overall Status, Trend, a profile, the dashboard document or any
  existing contract.
- It reads the reconstruction and the finished profiles, and writes only its own document.
- `tests/test_investigation_engine.py` proves that profiles are byte-identical before and after an intelligence build.
- Contracts up to 1.4.0 are refused: V2 needs the `editor_intelligence` capability.

## 2. Domain model (Tasks 4-5)

A **Finding** carries:

- **Identity:** `finding_id` (the type plus a hash of scope, key and window, so it is stable across runs), `finding_type`,
  `detector_version`.
- **Classification:** `category` (one management section), `direction` (adverse / favourable / mixed / neutral), `scope`
  (team / editor / video_type / stage / project / data).
- **Statements.** Structured and typed by evidence level:
  - `fact`: read from Monday;
  - `metric`: an approved calculation;
  - `pattern`: "X of Y" with the comparison named;
  - `association`: two measures move together in this sample;
  - `interpretation`: what it may mean, labelled as such;
  - `hypothesis`: a possible explanation to check.

  An interpretation or hypothesis without an observed statement is invalid (`finding_errors`).
- **Evidence levels.** `evidence_level` is the observed basis: the highest of fact, metric, pattern and association.
  `statement_levels` lists every layer present.
- **Next steps.** `significance`, `suggested_investigations` and the investigation question (in `text`).
- **Evidence:** `supporting_evidence`, `contradicting_evidence` and `context_evidence` blocks (§3).
- **Grading:** `confidence` (§4), `importance` and `severity` (§5).
- **Scale:** `sample_size`, `affected_projects`, `affected_editors`, `affected_video_types` (all derived from the evidence
  records).
- **Governance and links:**
  - `parameters`: every parameter used, with its value and approval status;
  - `parameter_status`;
  - `limitations` (codes, with wording in `narrative.LIMITATIONS`);
  - `related` (graph);
  - `cluster` (duplicates);
  - `text` (the rendered wording).

A detector that examined a subject but could not conclude writes an **examined-without-finding** record instead. The record
holds:

- the detector;
- the scope;
- the reasons: `rule_not_approved`, `insufficient_sample`, `insufficient_comparison_group`, `insufficient_recent_window`,
  `insufficient_outcome_events`, `insufficient_qualifying_editors`, `missing_data`, `incomplete_timestamp_coverage` or
  `no_effect_at_approved_threshold`;
- the facts it did compute;
- the parameters it needed.

Silence therefore always has a stated reason, and "not enough evidence" is a first-class output. **Zero findings is a valid
document.**

## 3. Evidence rules (Tasks 5, 56-57)

Every evidence block names:

- Monday as the source, with the board and column IDs;
- the **calculation** in words, including the exact comparison;
- the **sample** of every compared group;
- the **comparison** values (group against reference);
- the time window;
- exclusions;
- one **record per project**: Monday item ID, cycle ID, Editor, Video Type, every event ID used, the source timestamps, and the
  values used (duration, runway, deadline result, typical time, expected probability, band and so on).

The schema rejects a record without event IDs or timestamps. `consistency_errors` requires `sample_size` to equal the distinct
supporting records. A test checks that every event ID resolves to a Monday activity-log ID or an item snapshot.

## 4. Confidence (Task 6)

Confidence is a level: `low`, `moderate` or `strong` evidence. It is never a percentage. The factors are:

| Factor | Supports when | Limits when |
|---|---|---|
| sample size | every compared group has ≥ `confidence.sample_multiple` × its minimum | a group only just meets its minimum |
| replication | the effect repeats in independent slices (the other window, other Video Types, other Editors, both halves of history) | it appears in one slice only |
| contradicting evidence | none was found | contradicting evidence is attached |
| data completeness | ≥ `confidence.minimum_completeness` of eligible projects carry every needed field | fields are missing |
| independent examples | several Editors and projects contribute (shown as information) | — |

The levels:

- **strong** = sample well supported **and** replicated in ≥ 2 slices **and** no contradicting evidence **and** data complete;
- **moderate** = sample well supported **or** replicated at least once, unless contradicted without replication;
- **low** = passed the detector's gate only.

A factor whose parameter is unapproved is `not_assessed` and can never support `strong`. Every result lists its factors,
the rule and `why`.

## 5. Prioritization (Tasks 40-42, 50)

**Importance** is a lexicographic order, with no weighted sum:

1. tier:
   1. time-sensitive or fairness-critical: open-work risk, an adverse needs-attention change, a finding that contradicts a
      published headline;
   2. adverse system pattern;
   3. adverse Editor-specific pattern;
   4. hidden context and historical base rates;
   5. favourable;
   6. neutral description;
   7. data warning;
2. evidence level;
3. worsening;
4. affected projects;
5. affected Editors;
6. magnitude;
7. recency;
8. persistence;
9. `finding_id`.

`importance.basis` shows each key. Importance and confidence are separate: a tier-1 finding can have moderate evidence.

**Severity** (high / medium / low / info) is a display grouping derived from the tier. It is not a score.

**Duplicates.** Findings with the same direction, the same Video Types and affected projects overlapping by at least
`prioritization.duplicate_overlap` form a cluster. Members stay in `findings`; sections list the primary only.

**Sections:**

- Top Findings (limited by `prioritization.top_findings`; all are listed while it is unapproved);
- Needs Attention;
- Important Improvements;
- System Patterns;
- Editor-Specific Patterns;
- Hidden Context;
- Emerging Risk Signals;
- Data Warnings;
- Suggested Investigations;
- Not Enough Evidence (every detector × reason, with counts).

## 6. Investigation graph, questions and narrative (Tasks 43-49, 51)

**Edges** come only from explicit rules over structured fields, and only between findings that **share Monday projects**:

- `context_for`: an allowed pair of a system finding and an Editor finding;
- `explains_breadth`: an allowed pair of system findings about the same Video Type;
- `supports` and `contradicts`: the same Editor and outcome family;
- `qualifies`: a mixed conflict set against an adverse finding.

**Chains** follow the highest-ranked neighbour on one subject. On production data a typical chain reads: *Will's late-rate
headline needs context* → *late projects often start with too little runway* → *short runway shared across Editors in Premium
Short* → *repeated delay combination in Premium Short* → *workload moves with outcomes*.

**Wording.** Every sentence comes from `narrative.T[code](params)`. There is no free text and no fallback template: a missing
template is an error. The uncertainty standards (Task 49) are published in the document's `language_rules`:

- associations say "is associated with … in this sample";
- interpretations say "This suggests …";
- hypotheses say "may warrant checking";
- insufficient evidence says "There is not enough comparable history to classify this pattern."

**AI (Task 48)** is optional and absent. `ai_guard.accept_rewrite` rejects any rewrite that introduces a number the finding
does not contain, uses causal, blame, personality or HR language, sounds over-certain on weaker evidence, or names people
outside the finding. The deterministic text is kept.

The **executive brief** (Task 51) answers, for each top finding: what happened, is it unusual, where, what evidence, why it
matters, and what to inspect next.

## 7. Detector catalog (Task 74)

Generated from `investigation.catalog`; `tests/test_investigation_model.py` requires every entry to be complete and every
required signal to be classed reliable or usable in the data capability map.

| Detector | Tasks | Purpose | Required data | Parameters | Minimum sample | Output | Confidence | Known limitations | Version |
|---|---|---|---|---|---|---|---|---|---|
| `concentration.negative` | 12 | Where late deliveries and scored Negative labels are disproportionately concentrated (by Video Type, Cairo month, and inside each Editor's own work by Video Type) | editor_identity, video_type, deadline_result, performance_labels | `evidence.minimum_group_projects`, `evidence.minimum_outcome_events`, `concentration.minimum_share_ratio`, `concentration.minimum_share_difference` | group >= evidence.minimum_group_projects; outcomes in group and population >= evidence.minimum_outcome_events | one finding per concentrated group with numerator, denominator, population share, ratio and the group's projects | groups vs minimums; replication = the outcome share also exceeds the population share in the current and comparison windows | Video Type is the only available control for complexity; length, footage and brief are not recorded; Labels are applied by hand, so label counts are a lower bound; The data shows what happened, not why | concentration-v1.0 |
| `concentration.positive` | 13 | Where not-late deliveries and scored Positive labels are disproportionately concentrated | editor_identity, video_type, deadline_result, performance_labels | `evidence.minimum_group_projects`, `evidence.minimum_outcome_events`, `concentration.minimum_share_ratio`, `concentration.minimum_share_difference` | group >= evidence.minimum_group_projects; outcomes in group and population >= evidence.minimum_outcome_events | one finding per concentrated group with numerator, denominator, population share, ratio and the group's projects | groups vs minimums; replication = the outcome share also exceeds the population share in the current and comparison windows | Video Type is the only available control for complexity; length, footage and brief are not recorded; Labels are applied by hand, so label counts are a lower bound | concentration-v1.0 |
| `workflow.time_map` | 14, 15 | Where elapsed project time is spent: pre-editor, editor execution (first In Progress -> first Ready For Approval), review wait, submission to delivery | status_history, editor_execution_interval, item_creation_time, post_editor_delivery | `evidence.minimum_group_projects` | every phase >= evidence.minimum_group_projects valid projects | one team finding with each phase's median and 75th percentile, invalid and censored visits counted | each phase vs its minimum; completeness = projects with a creation time | Durations are elapsed clock time, not effort: nights, weekends and parallel work are included (D3); Who held the project in this stage cannot be identified (shared Waset Co account) | bottlenecks-v1.0 |
| `bottleneck.pre_editor_runway` | 16 | Late projects that entered editor execution with less runway than typical same-Video-Type execution, and the association between short runway and lateness | requested_eta, execution_runway, video_type, deadline_result, editor_identity | `runway.short_rule`, `evidence.minimum_group_projects`, `evidence.minimum_outcome_events`, `evidence.material_rate_difference` | short and adequate runway groups >= evidence.minimum_group_projects; short-runway late >= evidence.minimum_outcome_events | one team finding: late projects with short runway, both groups' late rates, ETA already passed at start, contradicting late-with-adequate-runway projects | groups vs minimums; replication per exact Video Type and per window | This is an association in observational data, not proof of cause; Typical execution time uses the whole ingested history of other Editors in the same Video Type; Some Requested ETAs were first recorded after work started | bottlenecks-v1.0 |
| `bottleneck.post_editor` | 17 | Projects submitted for approval on or before the Requested ETA that were delivered after it (delay after the Editor's interval) | deadline_result, post_editor_delivery, performance_labels | `evidence.minimum_outcome_events`, `evidence.minimum_group_projects` | on-time submissions >= evidence.minimum_group_projects; delivered after ETA >= evidence.minimum_outcome_events | one team finding with the projects, review wait and submission-to-delivery medians, and Late Delivery labels on on-time submissions | groups vs minimums | Who held the project in this stage cannot be identified (shared Waset Co account); Labels are applied by hand, so label counts are a lower bound | bottlenecks-v1.0 |
| `change.editor` | 19, 52 | An Editor against their own history: late rate and scored Negative label rate (current vs comparison window and vs history), median execution per exact Video Type (current vs history); the rest of the team's change over the same periods is shown beside it | editor_identity, deadline_result, performance_labels, editor_execution_interval, video_type, concurrent_workload_history | `evidence.material_rate_difference`, `evidence.material_duration_pct`, `recent_change.minimum_sample`, `quality.minimum_projects`, `speed.minimum_editor_projects` | both periods >= recent_change.minimum_sample (rates, D52) / quality.minimum_projects (labels, D52) / speed.minimum_editor_projects per Video Type (D52) | one finding per material change (improving / deteriorating) with both periods' projects, the team's change and the Editor's workload | periods vs minimums; contradicting evidence when the team moved the same way; replication against the other baseline | The data shows what happened, not why; Durations are elapsed clock time, not effort: nights, weekends and parallel work are included (D3); Workload counts only attributed, completed first cycles, so it is a lower bound | changes-v1.0 |
| `change.team` | 20 | Team late rate and scored Negative label rate, current vs comparison window and vs history | deadline_result, performance_labels, editor_identity | `evidence.material_rate_difference`, `recent_change.minimum_sample`, `quality.minimum_projects` | both periods >= recent_change.minimum_sample / quality.minimum_projects | one finding per material team change, with how many Editors moved the same way | periods vs minimums; replication = Editors moving the same way | The data shows what happened, not why | changes-v1.0 |
| `change.video_type` | 21 | A Video Type's median execution time, current vs history, across Editors | editor_execution_interval, video_type | `evidence.material_duration_pct`, `evidence.minimum_group_projects` | both periods >= evidence.minimum_group_projects in the exact Video Type | one finding per material change with how many Editors moved the same way | periods vs minimums; replication = Editors moving the same way | Durations are elapsed clock time, not effort: nights, weekends and parallel work are included (D3); Video Type is the only available control for complexity; length, footage and brief are not recorded | changes-v1.0 |
| `workload.association` | 22, 23, 24, 25 | Team-wide association between concurrent workload (relative to each Editor's own median) and execution time (within Editor x exact Video Type), late rate and scored Negative label rate | concurrent_workload_history, editor_execution_interval, video_type, deadline_result, performance_labels | `workload.band_rule`, `evidence.minimum_group_projects`, `evidence.minimum_outcome_events`, `evidence.material_duration_pct`, `evidence.material_rate_difference` | both bands >= evidence.minimum_group_projects; rate outcomes >= evidence.minimum_outcome_events | one association finding per measurement with both bands, strata and agreement | bands vs minimums; replication = strata / Video Types agreeing | This is an association in observational data, not proof of cause; Workload counts only attributed, completed first cycles, so it is a lower bound | workload-v1.0 |
| `workload.overload_pattern` | 26 | Inside one Editor's work: repeated combination of higher concurrency (above their own median) and longer execution, a higher late rate or more Negative labels | concurrent_workload_history, editor_execution_interval, video_type, deadline_result, performance_labels | `workload.band_rule`, `evidence.minimum_group_projects`, `evidence.minimum_outcome_events`, `evidence.material_duration_pct`, `evidence.material_rate_difference` | both bands >= evidence.minimum_group_projects inside the Editor's work | one association finding per Editor and measurement | bands vs minimums; replication = strata / Video Types agreeing | This is an association in observational data, not proof of cause; Workload counts only attributed, completed first cycles, so it is a lower bound | workload-v1.0 |
| `pattern.shared_across_editors` | 18, 29, 32 | Whether elevated lateness (or short runway) in a Video Type appears across several Editors (process-wide) or in one Editor only, comparing each Editor with themselves inside vs outside the Video Type | editor_identity, video_type, deadline_result, execution_runway | `evidence.minimum_projects_per_editor_for_breadth`, `evidence.minimum_editors_for_breadth`, `evidence.breadth_share` | qualifying Editors (>= minimum projects inside and outside) >= evidence.minimum_editors_for_breadth | system pattern (shared) or editor-specific pattern (confined), with every qualifying Editor's two rates | qualifying Editors vs minimum; replication = each Editor agreeing with the conclusion | Video Type is the only available control for complexity; length, footage and brief are not recorded; The data shows what happened, not why | patterns-v1.0 |
| `pattern.repeated_delay` | 27 | Repeated combinations (Video Type x runway band, Video Type x workload band) with elevated lateness in both halves of the history | video_type, execution_runway, concurrent_workload_history, deadline_result | `runway.short_rule`, `workload.band_rule`, `evidence.minimum_group_projects`, `evidence.minimum_outcome_events`, `evidence.material_rate_difference`, `patterns.maximum_combinations` | cell >= evidence.minimum_group_projects and late >= evidence.minimum_outcome_events | one finding per repeated combination; cells tested published | cell vs minimums; replication = both halves of history | Several combinations were tested; some elevated cells can appear by chance, which is why repetition over time is required; This is an association in observational data, not proof of cause | patterns-v1.0 |
| `pattern.repeated_quality` | 28 | The same scored Negative label repeated in one Video Type across several Editors | performance_labels, video_type, editor_identity | `evidence.minimum_outcome_events`, `evidence.minimum_editors_for_breadth` | occurrences >= evidence.minimum_outcome_events across >= evidence.minimum_editors_for_breadth Editors | one finding per repeated label and Video Type | occurrences and Editors vs minimums | Labels are applied by hand, so label counts are a lower bound | patterns-v1.0 |
| `pattern.time` | 30 | Late rate by Cairo weekday of first In Progress and by period of the month, reported only when it repeats in >= 2 months | deadline_result, status_history | `evidence.minimum_group_projects`, `evidence.minimum_outcome_events`, `evidence.material_rate_difference` | bucket >= evidence.minimum_group_projects with >= evidence.minimum_outcome_events late | one finding per repeated timing bucket | bucket vs minimum; replication = months where the bucket is elevated | Several combinations were tested; some elevated cells can appear by chance, which is why repetition over time is required; This is an association in observational data, not proof of cause | patterns-v1.0 |
| `person.mix_adjusted_deadline` | 31, 33 | Whether an Editor's late rate differs from what the other Editors show on the same mix of Video Types (and under similar runway), or whether the raw gap is explained by the mix | editor_identity, video_type, deadline_result, execution_runway | `deadline.minimum_editor_projects`, `evidence.minimum_group_projects`, `evidence.material_rate_difference` | Editor projects covered by a comparable peer Video Type >= deadline.minimum_editor_projects (D52); peers per Video Type >= evidence.minimum_group_projects | editor-specific pattern (adverse or favourable) or hidden context (raw gap explained by mix), with every project's expected probability | Editor sample vs the approved minimum; replication = the excess survives the same-runway stratification | Video Type is the only available control for complexity; length, footage and brief are not recorded; The data shows what happened, not why | person-system-v1.0 |
| `contradiction.metric_conflict` | 37 | Approved component states that point in opposite directions (fast but late, slow but on time, better than team but mostly late) | editor_identity, deadline_result, editor_execution_interval | none (approved inputs only) | the published components' own approved minimums (D52) | one hidden-context finding per Editor with the conflicting components' evidence | component samples vs their approved minimums | The data shows what happened, not why | contradictions-v1.0 |
| `contradiction.bad_headline` | 34, 35 | A late rate above the other Editors' that deeper evidence qualifies: competitive execution speed, late projects clustered in short runway, late despite typical execution, peers as late on the same mix, ETA passed before work started | deadline_result, execution_runway, editor_execution_interval, video_type, editor_identity | `evidence.minimum_outcome_events`, `deadline.minimum_editor_projects` | Editor deadline-classifiable projects >= deadline.minimum_editor_projects (D52); each check's own minimum | one hidden-context finding per Editor with every check (holds / does not hold / not assessed) and contradicting evidence blocks | Editor sample vs minimum; replication = checks that hold | The data shows what happened, not why; Typical execution time uses the whole ingested history of other Editors in the same Video Type | contradictions-v1.0 |
| `contradiction.hidden_risk` | 36 | A favourable headline hiding another signal: Negative labels rising or present behind good speed, workload above the Editor's own history, late rate rising behind good speed | performance_labels, concurrent_workload_history, deadline_result | `evidence.material_rate_difference`, `evidence.minimum_outcome_events`, `recent_change.minimum_sample`, `quality.minimum_projects` | each check's window samples >= recent_change.minimum_sample / quality.minimum_projects (D52) | one hidden-context finding per Editor listing the checks that hold | current window vs minimum | Labels are applied by hand, so label counts are a lower bound; Workload counts only attributed, completed first cycles, so it is a lower bound | contradictions-v1.0 |
| `risk.open_work` | 38 | Deterministic risk signals on current open work: past ETA (fact), short remaining runway, execution beyond the typical percentile, Editor workload above their own median, review wait beyond the typical percentile | current_open_work, current_editor_of_open_work, requested_eta, video_type, status_history, concurrent_workload_history | `runway.short_rule`, `risk.elapsed_percentile`, `workload.band_rule` | no minimum for the past-ETA fact; typical times valid at the D52 comparator minimums | one emerging-risk finding per signal listing the projects | facts about the snapshot; not graded beyond the sample shown | Based on the current Monday snapshot only; Typical execution time uses the whole ingested history of other Editors in the same Video Type | risks-v1.0 |
| `risk.historical_similarity` | 39 | An In Progress project compared with historical same-Video-Type projects in the same runway band: their late share is a base rate, not a prediction | current_open_work, execution_runway, video_type, deadline_result | `runway.short_rule`, `evidence.minimum_group_projects` | similar historical projects >= evidence.minimum_group_projects | one emerging-risk finding per open project | similar group vs minimum | Based on the current Monday snapshot only; This is an association in observational data, not proof of cause | risks-v1.0 |
| `editor.speed_pattern` | 53, 54 | The approved per-Video-Type Speed verdicts (Faster / Slower, current window) as one strength and one weakness finding per Editor, with each comparator | editor_execution_interval, video_type, editor_identity | `speed.minimum_editor_projects`, `speed.minimum_comparator_projects`, `speed.minimum_comparator_editors`, `speed.faster_band_pct`, `speed.slower_band_pct` | the approved D52 Speed minimums (5 Editor / 10 comparator projects / 2 comparator Editors) | editor-specific pattern (favourable or adverse) listing each Video Type's comparison | per Video Type sample vs approved minimum; replication = several Video Types | Durations are elapsed clock time, not effort: nights, weekends and parallel work are included (D3); Video Type is the only available control for complexity; length, footage and brief are not recorded | editor-v1.0 |
| `editor.label_pattern` | 54, 53 | Where an Editor's Negative and Positive labels sit (top label and its share), e.g. negative evidence concentrated in Late Delivery rather than broad quality | performance_labels, editor_identity | `evidence.minimum_outcome_events` | label occurrences >= evidence.minimum_outcome_events | editor-specific pattern with the label distribution | occurrences vs minimum | Labels are applied by hand, so label counts are a lower bound | editor-v1.0 |
| `data.quality` | 59, 62 | Data warnings: unattributed projects, deadline-unclassifiable projects, ETAs set after work started, unknown-status spans, label/fact disagreement, non-benchmark-eligible Video Types | editor_identity, requested_eta, status_history, performance_labels, video_type | none (approved inputs only) | none: each warning is a count of affected projects | one data-warning finding per issue with the affected projects | not graded beyond the count shown | History starts at the ingest window (2026-02-01 in production) | data-quality-v1.0 |

**Fairness context** (Task 55) is not a finding. Each Editor block in the document carries `fairness_context`:

- sample;
- project mix against the team;
- workload median against the team;
- late projects with short runway;
- weak-comparator Video Types;
- ETAs observed after work started.

## 8. Configuration and governance (Tasks 7, 75)

`config/intelligence-v2.json` holds every parameter with its approval state.

**Reused approved values** are read from the contract and approved only while the contract approves them:

- Speed minimums and bands;
- Deadline minimums;
- the Recent Change sample floor;
- the Quality project floor.

**Every new threshold is `rule_not_approved`** with `value: null` and a documented `proposed_value`:

- sample floors for groups and outcomes;
- breadth: minimum Editors and the shared-pattern share;
- concentration: ratio and difference;
- materiality: rate and duration;
- the short-runway and workload-band definitions;
- the risk percentile;
- the search-space cap;
- the confidence method;
- the top-findings limit;
- the duplicate overlap.

The proposals and the decisions they need are recorded as **D53** in `DECISIONS.md`. `policy.config_errors` refuses:

- an approved value without a decision;
- a value while unapproved;
- a copied contract value;
- a publication mode other than `approved_only`.

**Modes:**

- `approved_only` (the default, and the only publishable mode) uses approved parameters only;
- `review` uses the proposals, marks every finding `proposed_not_approved` and the document `publishable: false`.

The review page carries a banner. The publication check refuses a review document.

**What each mode produces on production data (2026-09-29 run):**

- `approved_only`: 11 findings, namely the approved Speed strengths and weaknesses (4), the open-work past-ETA fact and 6 data
  warnings. Every other detector reports `rule_not_approved`.
- `review`: 75 findings. See [`INTELLIGENCE-V2-VALIDATION.md`](INTELLIGENCE-V2-VALIDATION.md).

## 9. Contract strategy, compatibility, gating and rollback (Tasks 65-68)

**Decision (Task 65): a separate, optional, independently versioned document contract.** `contracts/intelligence-v2.schema.json`
(`document_version` 2.0.0) is used, and the existing contracts are neither extended nor re-versioned. The reasons:

- A finding is not a metric. Tuning a surfacing threshold must not require a new Monday contract (D25 forbids editing an
  approved contract in place).
- Existing outputs stay byte-identical. Contracts 1.3/1.4 keep `fixtures/golden`; 1.5 profiles and the dashboard are
  unchanged. This is covered by the full suite and `test_building_intelligence_does_not_change_profiles`.
- It depends on the `editor_intelligence` capability (1.5.0+) and records the executable contract version it ran under.

The schema forbids unknown fields, requires evidence records with event IDs and timestamps, and contains no score, rating,
rank of people or HR field (tested).

**Backward compatibility (Task 66).**

- No existing document gains a field.
- Contracts ≤ 1.4.0 have no optional file (`site_layout.optional_files` → `[]`).
- A build without `intelligence-v2.json` is identical to today's.

**Feature gating (Task 67).** `config/intelligence-v2.json` → `publication.include_in_site_build` (default `false`). When it is
true, production sync and the local site build write `intelligence-v2.json`, built `approved_only` only. It is listed in
`build.json` like every artifact. It is validated whenever it is present:

- schema and consistency;
- `publishable`;
- the same Monday snapshot and contract.

The validation runs in `atlas_sync.run.validate_site` and `atlas_sync.publish`. Like `dashboard.json`, the file is not served
publicly; nginx serves only `/`, `/en` and `/ar`. Enabling it is a reviewed configuration change, the same path as contract
activation.

**Rollback (Task 68):**

1. Set `publication.include_in_site_build` back to `false` and deploy. The next cycle builds without the file.
2. Or roll the pointer back to any earlier publication with `atlas-runtime rollback` (`PRODUCTION-RUNBOOK.md`). Builds with and
   without the optional file both validate, publish and roll back, because the file is optional, never required.
3. To remove the code as well, deploy the previous release (production runbook §9). Nothing reads V2 output, so nothing else
   changes.

No step rewrites Git history or edits a published build.

## 10. UI integration (Tasks 69-72) and how the UI/UX branch should consume it

**Added here (minimal, validation only):**

- `python -m atlas_commander.investigation` (and `make intelligence-v2-review`) writes a static English review page.
  - It has an executive brief and one card per finding, in section order.
  - Each card shows severity, evidence label, basis and rank, a "proposed parameters" tag and a summary.
  - The drawers show why Atlas noticed it, the interpretation (labelled "not a fact"), contradicting evidence, the confidence
    explanation, limitations, what management may want to investigate, the full Monday evidence tables, related findings and
    the parameters used.
  - Further sections list clustered duplicates, Not Enough Evidence, Editors with fairness context, and parameters with their
    approval.
- The page has no script and makes no network request.
- No change was made to the redesigned `web/` app, `dashboard_html.py`, `profile_html.py` or the locale catalog.

**Guidance for the UI/UX branch:**

- Read `intelligence-v2.json` beside `dashboard.json`.
- Render from `statements[].code` plus `params`, never from `text`, which is English only. Add the catalog keys
  `iv2.<code>`, with Arabic, to `locales/catalog.json`. The narrative templates in `narrative.T` are the English reference.
- Map `sections` to the Overview:
  - Top Findings;
  - Needs Attention;
  - System Patterns;
  - Hidden Context.
- Put `editors[].finding_ids` and `fairness_context` on the Editor Profile, next to the components each finding qualifies.
- Evidence drawers reuse the existing drawer component: `supporting_evidence` / `contradicting_evidence` blocks have the same
  `records` shape (item, event IDs, timestamps, values) as the 1.5 evidence blocks.
- Always show `confidence.label` and `limitations` with a finding, and show `parameter_status` while it is not `approved`.
- Never show a finding whose `parameter_status` is not `approved` in the published app.
- Chains (`investigation_graph.chains`) fit an "Investigate" view: finding → why → evidence → contradicting evidence → what to
  check.

## 11. Final validation questions

The answers below are for the production data, in review mode.

| # | Question | Can Atlas answer it now? |
|---|---|---|
| 1 | What changed? | Yes: `change.editor`, `change.team`, `change.video_type` (both windows and history). |
| 2 | Is the change actually unusual? | Yes, against a stated baseline and material difference. The team's own change is subtracted (difference-in-differences). |
| 3 | Compared with what? | Always named: the previous 30 days, the Editor's own history, the other Editors (leave-one-out), or the same mix. |
| 4 | Where is the problem concentrated? | Yes: `concentration.*`, `pattern.repeated_delay`, Editor label patterns. |
| 5 | Is it specific to one Editor? | Yes: `person.mix_adjusted_deadline`, confined patterns, and the team-shift check on changes. |
| 6 | Does it appear across the team? | Yes: `pattern.shared_across_editors`, breadth counts on team and Video Type changes. |
| 7 | Is the headline metric misleading? | Yes: `contradiction.bad_headline` and "mix explains the raw gap". |
| 8 | Is there important contradictory evidence? | Yes: `contradicting_evidence` blocks, `contradicts` / `qualifies` edges, and `contradiction.metric_conflict`. |
| 9 | Is workload relevant? | As an association only: `workload.*` and `risk.open_work`. |
| 10 | Is Video Type relevant? | Yes. Every comparison is per exact Video Type or mix-adjusted, and there are Video Type findings. |
| 11 | Did the problem begin before editor execution? | Yes: `bottleneck.pre_editor_runway`, the ETA passed at start, and runway checks. |
| 12 | Did the delay happen after editor execution? | Yes: `bottleneck.post_editor`. |
| 13 | How many projects support the finding? | Always: `sample_size` and every group's sample. |
| 14 | How strong is the evidence? | `confidence.level`, factors, `why` and the rule. |
| 15 | What evidence contradicts it? | `contradicting_evidence`, each check marked "does not hold", and graph edges. |
| 16 | What should management inspect next? | `suggested_investigations`, the investigation question and the executive brief `next_step`. |
| 17 | Can a manager click through to the proving projects? | Yes. Every record carries the Monday item ID, with a URL template on the page, and every event ID. |
| 18 | Can Atlas clearly say "not enough evidence"? | Yes: `examined_without_finding` with reasons, and the Not Enough Evidence section. |
| 19 | Can Atlas distinguish an observation from a hypothesis? | Yes: typed statements, the `evidence_level` basis and `statement_levels`. |
| 20 | Can the conclusion be rebuilt without trusting an LLM? | Yes. No LLM is used; the calculation, samples and records are in the document and were independently recomputed. |

The honest limit is that in `approved_only` mode most of these answers are "rule not approved" until D53 is decided.

## 12. What Atlas still cannot safely determine

- Why a project was late or revised. There is no reason field, so Atlas offers hypotheses only.
- Effort or working hours. Durations are elapsed time.
- Who scheduled, reviewed or delayed a project in a stage. The shared account makes that impossible; Atlas names stages, not
  people.
- Complexity beyond Video Type: length, footage and brief quality are not recorded.
- Client behaviour. It is out of scope and not captured.
- Causation of any kind, including workload → speed.
- Future outcomes. Risk signals are facts and base rates, not predictions.
- Anything about the 180 unattributed completed projects at Editor level, or about history before the ingest window.
