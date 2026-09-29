# Intelligence V2: current-state audit

**Branch:** `feat/atlas-intelligence-v2`, created from `ui-ux` at `eccaa8c` (the contract 1.5 UI redesign). `ui-ux`'s own base is
`main` at `d9918d1`. **Date:** 2026-09-29. **Scope:** Phase 1, Tasks 1 and 3 of the Intelligence V2 brief. This audit changes no
production logic.

Companion documents:

- [`INTELLIGENCE-V2-DATA-CAPABILITIES.md`](INTELLIGENCE-V2-DATA-CAPABILITIES.md): Task 2, what the Monday data can support;
- [`INTELLIGENCE-V2.md`](INTELLIGENCE-V2.md): the specification of what this branch builds.

An earlier session drafted an architecture for the same goal (`docs/INTELLIGENCE-V2-ARCHITECTURE.md`, commit `e0cdaa9`, on a
**local, unpushed** branch based on `main`). This branch builds on its analysis and its production aggregates, and adopts its main
architectural choice: a separate, non-scoring layer with its own document contract. It is re-based onto `ui-ux`, and it keeps
threshold governance stricter (see §7).

## 1. Product scope today

Atlas is an **Editor Performance Intelligence System**. Monday.com is the only source, and the Editor is the only evaluated entity
(`SPEC.md`, `AGENTS.md`). `docs/HANDOFF-V2.md` is the product authority (D20). Management decisions D1–D52 in
`docs/DECISIONS.md` refine it.

Out of scope, and therefore also out of scope for Intelligence V2:

- composite scores, rankings and leaderboards;
- revision penalties;
- AI-authored facts;
- payroll, disciplinary, surveillance and client-scoring features;
- forecasting (HANDOFF §27);
- KPIs for non-Editor roles.

## 2. Contract and version model

| Layer | Versions | Where |
|---|---|---|
| Executable Monday contract | 1.0.0 … 1.5.0; every version stays loadable for reproducibility | `config/monday-contract-v*.json`, `runtime.CONTRACT_PATHS` |
| Code default | `ACTIVE_CONTRACT_VERSION = "1.4.0"` | `src/atlas_commander/runtime.py` |
| Production allow-list | `("1.4.0", "1.5.0")`: the host opts in with `ATLAS_CONTRACT_VERSION` (D52) | `src/atlas_sync/config.py` |
| Capability gate | contract ≥ 1.5.0 enables `label_taxonomy`, `editor_intelligence` and `publication_identity` | `src/atlas_commander/capabilities.py` |
| Profile document | editor-profile 1.3.0 / 1.4.0 / 1.5.0 | `contracts/editor-profile-v1.*.schema.json` |
| Dashboard document | `ceo-dashboard-v0.1`, a view over profiles | `dashboard.py` |
| Presentation | 1.3/1.4: `dashboard_html.py`, `profile_html.py` (byte-for-byte golden); 1.5: `web/` (ui-ux redesign) | `fixtures/golden` |

Rules for changing any of this:

- An approved contract is never edited in place.
- A threshold is approved only when **both** a versioned config entry and a matching decision-log entry exist (D25).
- An unapproved value is `null` with state `rule_not_approved`, and the loader refuses a half-configured rule
  (`interpretation_policy.policy_errors`).

### Approved and unapproved rules (contract 1.5.0)

**Approved by D52:**

- **Speed:** minimum subject projects per Video Type = 5; minimum comparator projects = 10; minimum comparator Editors = 2;
  bands ±25%.
- **Deadline:** minimum subject projects = 10; minimum comparator projects = 60; bands ±15 percentage points.
- **Quality:** minimum project sample = 10.
- **Trend:** minimum sample = 10 in each window.
- **Overall Status:** the 64-key lookup table.

**Open (`rule_not_approved`):**

- Quality N and P;
- every Trend material-change threshold;
- the capacity or workload classification (D33, HANDOFF §21);
- Strengths, Attention Areas, Recognition and Needs Attention Now (HANDOFF §9, §10, §22, §23; UI-REDESIGN recommendation 2).

## 3. Architecture

```
Monday API ──► atlas_monday_probe / atlas_sync.run (read-only ingest, immutable raw run + extract.json)
                    │
                    ▼
pipeline.reconstruct_cycles
   ├─ monday_source.status_log_records / parse_column_changes / item_column_snapshots
   ├─ normalization.normalize_events ─────────► accepted NormalizedStatusEvents + quarantine (UNKNOWN_STATUS, STATUS_CLEARED …)
   ├─ attribution.attribute_transitions ──────► role per exact transition (shared Waset Co account never identifies a person)
   └─ cycles.build_item_cycle (per item) ─────► CycleRecord: first In Progress → first Ready For Approval, Editor and Video Type
                                                in effect at Ready For Approval, Requested ETA per D19, flags, exclusions
                    │
                    ▼
metrics (deadline_result, speed_benchmarks [1.4], median/quantile) · quality.quality_occurrences (label taxonomy)
                    │
                    ▼
intelligence (1.5): Cairo windows, evaluation cohort, component states, Overall Status lookup, Recent Change/Trend,
                    one evidence block per conclusion (EvidenceScope.block)
                    │
                    ▼
profile.build_editor_profile ──► editor-profile document (schema + evidence_consistency_errors)
                    │
                    ▼
dashboard.build_dashboard / interpretation_view ──► ceo-dashboard document (copied facts only)
                    │
                    ▼
web.render_app / web.render_report (1.5) · dashboard_html / profile_html (≤1.4) ──► en/, ar/ static site
                    │
                    ▼
atlas_sync: validate staged build (required_files exactly, publication identity) → publish → status / rollback
```

The architecture boundaries hold in the code:

- **Raw data is immutable.** Every derived record keeps board, item, column and event IDs.
- **Presentation computes nothing.** `dashboard.py` states it and `test_ui_v15.py` checks it.
- **Version-dependent behaviour** goes only through `capabilities()`.
- **Production validation** (`atlas_sync/run.py:221`, `publish.py:230`) rejects any artifact not listed in
  `site_layout.required_files`, so a new published file needs an explicit layout rule.

## 4. Current metric engine (Task 3)

### 4.1 Dependency map

```
raw activity log ─► status_log_records ─► normalize_events ─► accepted events ─┐
                 └► parse_column_changes (Editor, Video Type, ETA, labels) ────┤
items payload  ──► item_column_snapshots (current values) ─────────────────────┤
                                                                               ▼
                                                        build_item_cycle ► CycleRecord
                                                                               │
      ┌──────────────────────┬─────────────────────┬──────────────────────────┼────────────────────────┐
      ▼                      ▼                     ▼                          ▼                        ▼
 speed_eligible        deadline_eligible     quality_occurrences      revision_context         current_workload
 cohort_benchmark_     deadline_result       (label class, scored)    (client / internal,      (item snapshots;
 eligibility           (delta, early/on      │                        context only)            Active Work D33)
 │                     time/late, D5/D19)    │                        │                        │
 ▼                     ▼                     ▼                        │                        │
 intelligence.speed_   late_rate_facts,      quality_rates,           │                        │
 benchmarks (LOO)      deadline_component    quality_component        │                        │
 speed_component       (LOO, ±15 pp)         (N/P unapproved)         │                        │
      └──────────────┬──────┴─────────────────────┘                   │                        │
                     ▼                                                │                        │
              overall_status (lookup) · recent_change (facts; Trend label unapproved)          │
                     ▼                                                ▼                        ▼
              profile (editor-profile 1.5) ─────────────────────────────────────────────────────┘
                     ▼
              dashboard.editor_summary / interpretation_view ─► web app
```

### 4.2 Calculations

| Metric | Definition (code) | Floors and evidence |
|---|---|---|
| **Editor work time** | `rfa_at − in_progress_at`: the first In Progress to the first Ready For Approval, elapsed clock time (D2, D3). `cycles.build_item_cycle` | Cycles with exclusions, and open or invalid cycles, are kept but excluded. |
| **Speed (1.5)** | Per exact Video Type: the Editor's median against the leave-one-out median of the other Editors; `pct = (e − c)/c × 100`, compared unrounded with the ±25% band; D38 project-weighted majority. `intelligence.speed_benchmarks`, `speed_component` | 5 / 10 / 2 (D52). `speed_record` evidence per project. |
| **Deadline fact** | `delta = first RFA − ETA in effect then` (D19); < 0 early, = 0 on time, > 0 late (D5); a date-only or missing ETA gives no result. `metrics.deadline_result` | Evidence: RFA event, ETA event, ETA history and coverage. |
| **Deadline component** | Editor late rate − other Editors' late rate, compared as exact `Fraction`s against the ±15 pp band. `intelligence.deadline_component` | 10 subject / 60 comparator (D52). |
| **Quality rates** | Scored Negative (or Positive) label occurrences ÷ eligible completed projects in the window (D39). `quality_rates` | Minimum 10 (approved); N/P unapproved → `rule_not_approved`. |
| **Overall Status** | Lookup of `quality\|speed\|deadline` states; ≥ 2 classifiable components, including Quality or Deadline (D41). | No arithmetic. |
| **Recent Change** | Current window value − comparison window value, per measurement; Speed per exact Video Type. `recent_change` | Trend label needs approved materiality (open). |
| **Monthly history** | Cairo-month medians per exact cohort; deadline counts per month. `profile._trend` | Descriptive only, with sample sizes. |
| **Revisions** | Transitions into `Revisions` / `Internal Revisions`, counted per project. | Context only (D31). |
| **Current workload** | Current snapshot status of items whose current Editor Name resolves to the Editor: Active Work = In Progress, Revisions, Internal Revisions; Awaiting Approval = Ready For Approval (D33). | No capacity classification (open). |

### 4.3 Windows

- **Current and comparison windows:** 30 + 30 completed Cairo days. Today (Cairo) is excluded. A project is anchored by its first
  Ready For Approval (D24, D42). `intelligence.completed_day_windows`, `window_assignment`.
- **All history:** every completed cycle in the ingested log window (2026-02-01 onward in production). It feeds monthly history
  and project rows only.
- **Partial month:** the dashboard flags the Cairo month that contains `retrieved_at` as `partial` (`dashboard._monthly`) and
  emits a `PARTIAL_MONTH` warning. Nothing else compares partial months.

### 4.4 Reusable, tested functions that Intelligence V2 reuses

The layer reuses these functions and does not duplicate them:

- `pipeline.reconstruct_cycles`, `reconstruct_quality`;
- `metrics.deadline_result`, `classify_deadline`, `median_seconds`, `quantile_seconds`, `speed_eligible`,
  `cohort_benchmark_eligibility`;
- `intelligence.completed_day_windows`, `window_assignment`, `cairo_date`, `EvidenceScope`, `speed_record`, `deadline_record`;
- `interpretation_policy.InterpretationPolicy` (approved floors and bands);
- `profile.build_editor_profile` (component states, Overall Status, Recent Change: V2 reads them from the profile rather than
  recomputing).

Duplication in the current code:

- The rule "benchmark-eligible cycle" is written four times: `profile._metric_coverage`, `profile._trend`, `profile._v15_intelligence`
  and `intelligence._benchmark_eligible`. All four are equivalent to `intelligence._benchmark_eligible`.
- `_current_editor` (profile) is the only resolver for the current snapshot Editor.

V2 calls these through a single adapter (`investigation/facts.py`) and does not refactor them. That keeps the 1.4 and 1.5
outputs byte-identical.

## 5. Current intelligence capabilities and limits

**What Atlas can do today:**

- per-Editor facts;
- per-Video-Type speed comparison;
- the Deadline comparison against the other Editors;
- the Overall Status lookup;
- window deltas;
- evidence drawers with Monday IDs.

**What Atlas cannot do today:**

| Question from the brief | Today |
|---|---|
| Where is time actually lost (before / during / after the Editor)? | Not computed. The cycle keeps only first-cycle event IDs; the full status timeline is in `CycleReconstruction.status_events` but unused. |
| Is lateness caused before editing (short ETA runway)? | Not computed. D46 records the suspicion (team 61–96% late) as a process question. |
| Is a pattern one Editor or systemic? | Not computed. No cross-Editor view per Video Type. |
| Has the Editor changed against **their own** history? | Only the 30-vs-30-day Recent Change; no longer self-baseline. |
| Does concurrent workload coincide with worse outcomes? | Not computed. Workload is the current snapshot only. |
| Is a bad headline misleading, or a good one hiding risk? | Not computed. Components are shown side by side with no conflict analysis. |
| Which findings matter first? What should management check next? | Nothing. Management slots stay `rule_not_approved` (`management.py`). |

**Deterministic today:** everything above. **Presentation-only today:** display ordering (`dashboard.py` sorts by sample for
display), the "Positive signals" and "Worth reviewing" groupings in the redesigned profile, i18n and formatting.

## 6. Where Intelligence V2 lives

- **Layer.** V2 is a new analysis layer **after** `profile.build_editor_profile` and **beside** the dashboard. It reads the
  `CycleReconstruction`, the quality occurrences and the finished editor-profile documents. It writes nothing back into them.
- **Package.** `src/atlas_commander/investigation/` holds small modules: models, policy, facts, baselines, stats and the detector
  families. It is a package so no single `intelligence.py` grows; the existing `intelligence.py` name is already taken by the 1.5
  interpretation layer.
- **Contract.** V2 has its own document contract, `contracts/intelligence-v2.schema.json`, versioned independently. It needs the
  `editor_intelligence` capability (contract ≥ 1.5.0), because it depends on Cairo windows, leave-one-out comparison and the label
  taxonomy.
- **Parameters.** `config/intelligence-v2.json`. Each value carries its approval state; §7 explains why.
- **Gate.** V2 is off by default. It is built by an explicit CLI command (`python -m atlas_commander.investigation`) or, when the
  config enables it, as one **optional** build artifact. No existing file, schema, golden hash or 1.4/1.5 output changes.

## 7. Governance constraint that shapes V2

D25 forbids classifying anything with a threshold that has no config entry **and** decision. The brief also forbids inventing
business thresholds. Almost every interesting V2 judgement needs such a value:

- "concentrated" and "material change";
- "high workload" and "short runway";
- "shared across Editors".

V2 therefore runs in two explicit modes:

- **`approved_only`** (the default; the only mode that can be published):
  - A parameter is used only when it is approved.
  - It is approved when it literally reuses a D52 value in the meaning D52 approved it for, or when a later decision approves it.
  - A detector whose parameter is not approved produces no finding. It records the facts it computed, with `rule_not_approved`.
- **`review`** (explicit CLI flag, never publishable):
  - Proposed values from config (`proposed_value`, never `value`) are used.
  - Every finding produced this way carries `parameter_status: proposed_not_approved`.
  - This exists so management can see what each proposal would surface before approving it (Task 64). It follows the same
    pattern as the Round 4 shadow proposals (`docs/evidence/ROUND4-DISTRIBUTION-ANALYSIS.md`).

The proposals and the decision they need are recorded as **D53 (proposed, not approved)** in `docs/DECISIONS.md`.
