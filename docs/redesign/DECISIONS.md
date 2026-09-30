# Atlas redesign: decisions and discrepancies

Where the `atlas-redesign-handoff` package and the repository disagree, the repository's facts win and the product intent is kept
(handoff README, rule 4). Each entry says what the handoff assumed, what the code does, and what the redesign does about it.
Management decisions for the redesign itself are recorded in [`docs/DECISIONS.md`](../DECISIONS.md) (D54); this file holds the
engineering detail behind them.

## R0. Governance: the redesign reverses earlier product rules

The handoff states that the owner rejects "Atlas never ranks Editors" and "Atlas prefers silence over an unsupported conclusion".
Several recorded rules said the opposite:

| Earlier rule | Where | What the redesign does |
|---|---|---|
| No leaderboard, no numbered rank, no best/worst | `docs/HANDOFF-V2.md` §24, §36 | Superseded **for the verdict layer only** by D54: tiers and ranks per `02-VERDICT-ENGINE-SPEC.md`. |
| No weighted composite or hidden score behind Overall Status | D37 | Unchanged. Overall Status (the D37 lookup) is still computed and shown under More details. The redesign's score is a **separate, visible, versioned** verdict-layer score (D54), never fed back into Overall Status. |
| Insufficient evidence is a data state, never a provisional status | D47 | Superseded for the verdict layer only: low data lowers confidence and never silences the verdict (handoff principle 4). The D47 profile states are unchanged under More details. |
| Rules apply only when approved (D25) | D25 | Kept: every verdict threshold and weight lives in `config/verdict-v1.json` with `decision_id` D54, and a test fails if config and decision disagree. |

## R1. There is no JS framework, router or snapshot API

- **Handoff assumed:** a client app with routes such as `/editors/:id`, UI components, and a snapshot the UI fetches.
- **Repo:** Python renders static HTML per language at build time; views are hash routes inside one page (`#/editor/<id>`);
  nginx serves only `/`, `/en/`, `/ar/` (see [`MAP.md`](MAP.md)).
- **Decision:** "components" are Python render functions in `src/atlas_commander/web/`; "the snapshot" is the site build's JSON
  documents. The verdict engine writes a new language-neutral document next to `intelligence-v2.json`, and the renderer reads it.
  The profile drawer is bound to the hash route `#/editor/<id>` (the repo's routing equivalent of `/editors/:id`).

## R2. "This month" is the current 30-day window, not a calendar month

- **Handoff:** "reporting month", "September 2026 · 31/8 – 29/9".
- **Repo:** the contract 1.5 window is the last 30 completed Cairo days before the build (`cairo-completed-days-v1.0`), compared
  with the 30 days before it (D24, D42).
- **Decision:** the verdict layer uses exactly those two windows; the UI labels them by their dates, never as a calendar month.

## T0.3 Inputs of `02-VERDICT-ENGINE-SPEC.md` §1 against the real data

Checked against the local build of production run `20260929T210734Z-4cb4bfa25596` (`out/real`, not committed).

| Spec input | Status | Where it is |
|---|---|---|
| `completed` | **exists** | `dashboard.json` → `editors[].interpretation.coverage.current_projects` (profile `coverage.editor_window.current_projects`): projects whose first Ready For Approval falls in the current window. |
| `active` | **exists** | `dashboard.json` → `editors[].current_workload.active_work_count` (D33: In Progress, Revisions, Internal Revisions). |
| `lateCount`, `lateRate` | **exists** | `editors[].interpretation.components.deadline.facts.late` / `.absolute_late_rate` over `.deadline_classifiable_projects` (deadline-v1.2, ETA frozen at first Ready For Approval). |
| team late rate (current and previous) | **missing as one number, derivable exactly**. Plan: the engine sums `profiles/<id>.json` → `trend.late_rate_by_window.{current,comparison}.{late, deadline_classifiable_projects}` over every profiled Editor. (`facts.comparator_late_rate` exists but is leave-one-out per Editor, D45, so it is not the team rate.) |
| `speedDeltaPct` per Video Type | **exists** | `editors[].interpretation.components.speed.video_types[].editor_vs_comparator_pct` (leave-one-out median, same Video Type, D36). The engine uses the Editor's primary Video Type: the first row with a classified verdict, otherwise the largest-sample row with a comparator; the same row the current overview card shows. |
| `ownSpeedDeltaPct` | **exists when material** | `intelligence-v2.json` → finding `change.editor`, statement `median_execution_changed` (`pct_change`, `against: history`, with `team_pct_change`). Absent when the change is below the D53 material difference. Plan: null otherwise ("no material change"). |
| `quality` | **exists, not approved** | `editors[].interpretation.components.quality` (state `not_classifiable`, reason `rule_not_approved`; Quality N/P open). Plan: `metrics.quality = null` → "Not measured yet", plus the silent-measurement rule (§6 row 5). |
| `overdueOpen[]` | **exists** | `intelligence-v2.json` → finding `risk.open_work`, statement `risk_past_eta` → `params.items[]` (`monday_item_id`, `editor_name`, `status`, `requested_eta`, `hours_past_eta`). |
| `shortRunwayShare` | **exists** | `intelligence-v2.json` → `editors[].fairness_context.runway` (`late`, `late_with_short_runway`) over the ingested history. Share = `late_with_short_runway / late`. |
| `lifetimeCompleted` | **exists** | `editors[].sample.completed_projects` (all ingested history). |
| team short-runway split, count | **exists** | `intelligence-v2.json` → finding `bottleneck.pre_editor_runway`, statement `late_projects_with_short_runway` (`short_runway_late_rate`, `adequate_runway_late_rate`, `short_runway`, `adequate_runway`, `short_runway_late`, `late`, `share_of_late_with_short_runway`). |
| project name (for `overdue[]`) | **missing** | The ingest never requests Monday item names (`monday_source.py`). Plan: show the Video Type and Monday item ID (numeric, never a UUID) as the human-readable reference; adding item names is a later ingest change (see R3). |
| source link (`sourceUrl`) | **missing in production** | The renderer accepts a Monday item URL template (`monday_item_url`), but production passes none. Plan: `sourceUrl` is filled when a template is configured and is null otherwise; the evidence drawer remains the trace to Monday events. |
| editor photo (`photoUrl`) | **missing** | Editors are values of the Monday "Editor Name" dropdown on a shared account, not Monday users, so there is no avatar to fetch (T5.1). Plan: `assets/editors/<editor-id>.jpg`, else the initial. |

## R3. Monday item names are not ingested

- **Handoff:** overdue rows show "the project name, status and source link".
- **Repo:** the extract has item IDs, column values and activity logs, but no item name.
- **Decision:** no ingest change in this redesign (the handoff forbids unrelated API changes). Overdue rows show status, Video Type
  and the item ID, isolated LTR, and open the existing project evidence drawer.

## R4. The 46 vs 55 findings count (ATLAS-DATA-002, T1.5)

- **Cause:** both numbers were right but unlabelled. Data & rules counted every published finding (55). The overview's list,
  "All published findings (46)", left out the 5 Top findings already shown above it and the 4 duplicates that Intelligence V2
  groups under their cluster's primary finding (`cluster.suppressed_in_sections`): 55 = 5 + 46 + 4 on the audited snapshot and on
  production run `20260929T210734Z-4cb4bfa25596`.
- **Decision:** keep both views and label the scopes. The list reads "46 more published findings" with a note that reconciles
  it with the total; Data & rules shows "Published findings (all, including grouped duplicates)" and the same split. The split
  comes from one function, `web.intel.finding_scope`, so the two pages cannot drift apart.

## R5. The verdicts are a new snapshot artifact, not a dashboard version bump (T2.1)

- **Handoff:** add `EditorVerdict`, `TeamVerdict`, `Decision` and `Msg` to "the snapshot schema" and bump its version.
- **Repo convention:** the dashboard document (`ceo-dashboard-v0.1`) copies profile facts and has no JSON Schema; the last new
  layer (Intelligence V2, D53) became its own optional, schema-validated artifact.
- **Decision:** `verdicts.json` (`document_version` 1.0.0, `verdict_version` `verdict-v1.x`) with
  [`contracts/verdict-v1.schema.json`](../../contracts/verdict-v1.schema.json). It is listed in `site_layout.optional_files`, so the
  staged-build validation and publication check it whenever it is present (`atlas_commander.optional_artifacts`) and a build without
  it still publishes and rolls back. Field names follow the repo's snake_case (`editor_id`, `ranked_of`, `confidence_reasons`, …)
  instead of the spec's camelCase. `Msg.params` may also hold a list of strings (a list of names), which the page joins with the
  locale's own comma.

## R6. Tier rules: how the spec's words are read (T2.5)

- **Speed for a verdict** is the primary Video Type comparison only when the approved Speed rule classifies it (D52 sample
  minimums). A one-project comparison (Mohamed Mansour, +3%) is shown but never judged.
- **"Worse than the team"** (the Best rule): late rate above the team rate, slower than peers (any positive difference), or fewer
  completed projects than the ranked Editors' median. Quality joins once a Quality rule is approved.
- **"Top 25% of ranked Editors"**: rank ≤ ranked count × 0.25 (8 ranked → ranks 1–2). With fewer than 4 ranked Editors nobody is
  Best, which follows the spec literally.
- **Team late rate** is every profiled Editor's late projects over their deadline-classifiable projects in the window (not the
  leave-one-out comparator of D45).
- **Score (§4)** is computed here because the Best rule needs it; T2.6 adds the ranking tests. The median for the volume
  dimension is the median completed count of the ranked Editors.

## R7. Confidence: the spec's rules, applied as written (T2.7)

- **Reasons that lower the level:** `few_projects`, `missing_dimension` (deadlines or speed), `mixed_evidence`, each one step.
  `missing_<dimension>` codes from the score are kept as detail and do not lower it twice.
- **`mixed_evidence`** means a published Intelligence V2 finding (`contradiction.bad_headline`) qualifies the Editor's late-rate
  headline with contradicting evidence while the verdict uses the deadline dimension (Will, Refaat on the fixture and on real data).
- **`timeline_only`** cannot occur in Atlas: the prototype used it for Editors whose numbers were missing from its screenshots, but
  every Atlas verdict rests on computed counts. The rule is implemented and tested, and no real verdict carries it.
- **Zero-project Editors** (Samra) get Low confidence under §5 (few projects and no key dimension), although the prototype showed
  "Strong" for Samra. The spec's rules win, as for Mohamed Mansour's tier; the verdict itself ("no projects this month") still shows.
