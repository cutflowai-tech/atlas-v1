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

## R8. Duplicate findings: how §6 row 4 is read (T2.10)

- **"Same metric"** is the finding type, its measure (`late_rate`, `median_execution`, …) and its Video Type (`cohort_key`), for a
  finding about exactly one Editor. A change against the Editor's own history and a change against the comparison window are the
  same metric over the same current window, so they are duplicates (Anas's two "late rate improved" findings, 39 and 29 projects).
- **"Overlapping windows"** means the findings' `time_window` date ranges intersect (end exclusive); a finding without a dated window
  covers the whole snapshot and overlaps every window.
- **Which one is kept:** the larger sample, as the spec says; equal samples keep the lower finding ID, so rebuilds choose the same one.
  This can differ from Intelligence V2's own clusters (`cluster.primary`, a different rule: same direction and affected-project
  Jaccard ≥ 0.8). On production run `20260929T210734Z-4cb4bfa25596` Martin's cluster primary is his 39-project comparison finding,
  while the verdict layer keeps his 48-project history finding. Intelligence V2 is not changed; the redesigned pages take their
  overview findings from `verdicts.json` and still show every finding under More details.
- **Order of rules:** duplicates are removed before "mirrors the team" (row 3) is judged, so only a kept finding can give that reason.
  A finding hidden for both reasons is listed once, as `duplicate`.

## R9. Silent measurement and zero activity (T2.11)

- **Which measure can be silent:** Quality, the only dimension with an unapproved rule (Deadlines and Speed are approved, D52;
  Volume is a count). Its measure is the share of projects with a quality issue (`quality.facts.negative_rate`).
- **Two causes, one decision:** the spec's row 5 ("0% for every Editor") holds on the §9 fixture but **not on production data**
  (run `20260929T210734Z-4cb4bfa25596`: Mario 26.7%, Amir 6.7%). What silences Quality there is §7 row 5, "a rule not approved
  that silences a dimension": `rule_status` is `rule_not_approved` for every Editor. Either cause gives one `approve_rule`
  candidate (horizon `management`, owner `ceo`, target `rule:quality`) whose evidence names the cause(s). If a Quality rule is
  approved and still reads 0% for everyone, the title asks to *review* the rule instead. "Every Editor" needs at least two Editors
  with a value.
- **Not measured, never good:** while Quality is silent the verdict carries no Quality state and Quality takes no score weight. The
  positive-notes fact (share of projects with a positive client note) is still shown; it is a count, not a judgment.
- **Zero activity:** `completed == 0` and `active == 0` (Samra and Ahmed on real data; Michael has work in progress and overdue,
  so he is not asked "leave or assignment gap?"). The candidate is an `ask` decision of type `low_activity` listing those Editors;
  T2.14 widens it to every Low-activity Editor (§7 row 4), as the prototype's "Samra has no projects; Ahmed and Michael delivered
  nothing" decision does.
- **Decision IDs and priority:** `dec-` + the first 12 hex digits of SHA-256 of `type:subject` (subject: the rule's dimension, or
  the Editor IDs), stable across rebuilds of the same facts. Priority is the type's position in §7 (1–5), not a configured number.

## R10. Headlines and reasons (T2.12)

- **Keys, not sentences:** `verdict.headline.<tier>.<variant>` and `verdict.reason.<fact>`; parameters follow the schema's unit
  convention (`*_pct` percentages, counts, `labels`, hours). The catalogue templates are T4.1. The spec's "{himself}" becomes a
  gender-neutral "their own history" in both languages (no pronoun is inferred from a name).
- **Variant = the strongest fact:** Weakest leads with "scheduling does not explain it" when that §6 rule holds (adding "slower than
  peers" and "than their own history" when each is true), otherwise the §3 rule that placed the Editor; Watch leads with overdue
  work, then lateness, then speed, and a Weakest limited to Watch by the runway rule says so; Best says "highest load, faster" only
  when both hold (on the §9 fixture Ibrahim, 24 projects, has the highest load, so Will's headline is `best.faster`); Steady leads
  with "mirrors the team", then "scheduling explains it".
- **Reasons** are the tier's facts in order of strength (the deciding fact first), then general facts (not ranked, work in progress);
  an Editor with a single fact gets its project count as the second bullet. "Same as peers" uses the display band
  (`display.speed_same_band_pct`), so the sentence and the SpeedPill agree.

## R11. Decisions (T2.14)

- **Priority** is the position of the decision's type in spec §7 (1 overdue, 2 Weakest, 3 scheduling, 4 ask, 5 rule). Within a
  priority the order is deterministic: Weakest plans lowest rank first. The overview shows the first `decisions.overview_max` (5);
  `decision_candidates` keeps all of them for More details.
- **Consequence on real data (flag for the owner):** production run `20260929T210734Z-4cb4bfa25596` has three Weakest Editors, so
  the five overview slots go to today (5 overdue projects), three Weakest plans and the scheduling review; the Low-activity question
  and the Quality-rule approval are only under More details. This follows the spec as written. A per-type limit (e.g. one Weakest
  slot listing all) would be a product decision; nothing changes without one.
- **Owners:** overdue work: the Editors holding it, most overdue first; Weakest: the Editor plus `editors_manager`; scheduling:
  `scheduling_owner`; ask: every Low-activity Editor by name; rule: `ceo`.
- **Confidence:** direct facts (overdue items, zero projects, an unapproved rule) are High; a Weakest plan is as confident as the
  verdict; the scheduling review takes the Intelligence V2 finding's level (strong/moderate/weak → high/medium/low).
- **Subjects for the stable ID:** the overdue item IDs, the Editor ID, `team`, the sorted Low-activity Editor IDs, the rule's
  dimension. The same facts give the same ID on every rebuild; a changed subject (a new overdue project) is a new decision.

## R12. Team verdict (T2.15)

- **Team late rate** (current and previous) is the sum of every profiled Editor's late projects over their deadline-classifiable
  projects in each window (T0.3). The previous window uses each Editor's own published comparison sample, so on real data it is
  72.9% (94 of 129) where the audit screenshot said "75%".
- **State on real data:** production run `20260929T210734Z-4cb4bfa25596` is `critical` because 5 open projects are past Requested
  ETA and `team.critical_overdue` is 5 (spec §8: "overdue ≥ 5"); its late rate (58.5%) alone would be `needs_intervention`. This is
  the spec's rule applied as written; it changes with the overdue count on every build.
- **Trend:** the late-rate move is compared in percentage points rounded to the document's precision, so a move of exactly 5 points
  is `flat`. Without a previous window the trend is `flat` and confidence drops one level.
- **Conclusion:** "which share dominates" uses the same threshold as the scheduling decision (`decisions.scheduling_runway_share`):
  at or above it the lateness is mostly scheduling, otherwise mostly the editing. The decision and the chain can never disagree.
- **KPI tones** follow the target design (`after/01`, `after/04`): the late rate is warn at or above the intervention rate and bad
  at or above the critical rate; any overdue project is bad (it is the `today` horizon), none is good; the short-runway share is
  neutral (it explains, it does not judge). Aligned in T3.8.
- **KPI values** are numerals without units (`"58.9"`, `"3"`); the page formats them per locale (digits, `%`, bidi isolation, T1.4),
  so no preformatted Latin text reaches the Arabic page.

## R13. Tokens and fonts without a web font (T3.1) — owner decision needed on font delivery

- **Conflict:** the handoff's fonts (Readex Pro, IBM Plex Sans Arabic, IBM Plex Mono) are loaded by the prototype from Google Fonts.
  The Atlas pages are "static and self-contained: no web font, no CDN, no network request" (`web/style.py`), enforced by
  `tests/test_ui_v15.py::test_pages_make_no_network_request`; nginx serves only `/`, `/en/`, `/ar/`.
- **Default used now (README rule 8):** each redesign font stack names the handoff font first and falls back to the existing system
  stacks (`--v-display`: Readex Pro → the locale's `--font`; `--v-body`: IBM Plex Sans Arabic → IBM Plex Sans → `--font`;
  `--v-num`: IBM Plex Mono → `--mono`). A viewer with the fonts installed sees them; everyone else sees today's fonts. No font is
  downloaded, embedded or requested.
- **To decide (owner):** either (a) embed subset WOFF2 files inline as `data:` URIs (no network request; roughly +100–250 KB per
  page and locale, OFL-licensed fonts), or (b) serve them from the locale trees (`/en/fonts/`, `/ar/fonts/`; one same-origin request,
  which changes the self-contained rule and the nginx paths), or (c) keep system fonts. Nothing else in the redesign depends on it:
  every component uses the stacks, so the switch is one CSS change.
- **Token names:** the handoff's names (`--bg`, `--surface`, `--line`, `--good`, …) already exist in the design system with other
  values. The redesign's tokens are prefixed `--v-` so the current pages stay pixel-identical until a redesigned view uses them;
  tier (`--v-tier-<tier>`) and decision-horizon (`--v-horizon-<horizon>`) aliases follow the prototype (ask = idle).

## R14. Person cards: one link, one name (T3.5)

- **"The whole card is one button":** the card is one `<a href="#/editor/<id>">`, a single interactive target like a button, because
  the profile drawer is bound to that URL (T4.4, R1): Enter, click, middle-click and deep links all work, and Back closes it.
- **Name (+ Latin name):** Atlas has one name per Editor, the Monday "Editor Name" value (mostly Latin), shown as recorded and isolated
  in Arabic. The prototype's Arabic transliterations (e.g. "ويل" for Will) were hand-written and have no source in the data, so the
  card shows the Monday name only; adding transliterations would need a maintained mapping (not in scope).

## R15. Verdict sentences in two languages (T4.1)

- **One key, one template per language:** the catalogue holds every engine key (`verdict.*`) with English and MSA Arabic templates;
  `atlas_commander.verdict.messages` lists every key and its parameters, and `web.verdict_ui.message()` renders a `Msg` by the unit
  each parameter name carries (whole percentages, hours, isolated Monday names and IDs, the locale's list comma, dimension names).
- **Counts that change the words** (`count`: overdue projects) use the catalogue's plural forms (Arabic zero/one/two/few/many/other).
  Other counts are phrased so no noun has to agree with them ("12 of 14", "in progress now: 2").
- **No inferred gender:** the spec's "slower … than {himself}" is "than their own earlier work"; in Arabic the templates use
  impersonal phrasings ("التأخير في …", "أبطأ من الزملاء", "الأداء السابق") instead of masculine forms where Arabic allows it.
- **Direction words, not arrows:** changes read "from 69% to 54%" / "من … إلى …", which never reorders in Arabic.
- The Arabic strings carry the review status "Needs Arabic Review" like every redesign string.

## R16. The Team overview arrives before the old first layer leaves (T4.2 → T4.3)

- T4.2 puts the judgment-first overview (band, tiers, decisions rail) at the top of the Editors view; T4.3 then moves the old first
  layer (alphabetical cards, "Atlas never ranks", findings list, Team Pulse) to More details. Between the two commits the old content
  sits below the new one; its heading becomes an `h2` so each view keeps one `h1` (the verdict headline).
- Order inside a tier is the engine's rank (lowest number first), then unranked Editors by name. The Weakest tier therefore lists
  rank 6, 7, 8 in that order, like every other tier.
- `test_ui_v15::test_cards_show_the_engine_status_in_alphabetical_order` keeps checking that the pre-redesign cards never rank; its
  "no Best / Rank" words check now reads the page without the verdict overview, which ranks by design (D54, R0).
- Without `verdicts.json` (publication gate off, or contracts 1.3/1.4) the Editors page is exactly the pre-redesign page.

## R17. Profile drawer routes (T4.4)

- `#/editor/<id>` (the repo's equivalent of the handoff's `/editors/:id`, R1) opens the Editor's verdict drawer over the Team overview
  whenever the page has verdicts; every existing link to an Editor (cards, decision faces, Team Pulse lanes, findings) therefore opens
  the drawer. The full pre-redesign profile (all sections and evidence) moves to `#/profile/<id>`, linked from the drawer's More details,
  so nothing that was reachable becomes unreachable. Without verdicts `#/editor/<id>` is the full profile, as before.
- The drawer sits on the inline-start side (right in Arabic, as in `after/02`), under the evidence drawer (so evidence opened from the
  profile stacks on top), is a modal dialog (`aria-modal`, the header and main content `inert` while it is open, Tab kept inside), and
  closes with Esc, its close button, the backdrop or any route change. Closing goes back in history when it was opened in the app, so
  the overview keeps its scroll position and focus returns to the card or face that opened it.
- The prototype's "Add/change photo" is not in the drawer: photos are managed as files by an admin (T5.2); the browser-only upload is
  not shipped.

## R18. Profile More details (T4.5)

- **Tracing numbers:** each profile metric value is a button to the evidence behind it (one click): the deadline component drawer
  (late rate), the speed component drawer, a new "projects completed this month" list (exactly the Editor's projects whose first Ready
  For Approval falls in the window, so its length is the count shown), and the quality component drawer; each overdue alert opens the
  Intelligence V2 open-work finding (or its Monday link when a template is configured). Numbers in the reasons are the same values, or come
  from a finding listed under More details (two clicks). The team rate (59%) is explained in the methodology as a sum of the Editors'
  own counts; it is not an evidence record of its own.
- **This Editor's findings** are Intelligence V2's per-Editor list (the same list, in the same order, as the full profile's Intelligence
  section) without the duplicates of R8. Group findings that Intelligence V2 attaches to several Editors appear for each of them, as they do
  in the full profile.
- **No UUID on the drawer:** Monday event UUIDs stay in the existing evidence drawers (traceability) and raw identifiers (Editor, finding
  and decision IDs, verdict and configuration versions) are under the nested Technical details.

## R19. One More details page (T4.6)

- The global More details area is the existing Data & rules view (`#/system`), relabelled "More details" in the top bar when the
  page has verdicts: it already held the rules and the data health, so the findings, the pre-redesign Editors list and Team Pulse join
  it instead of a second page. An index at the top jumps to Findings, Editors, Team Pulse, Rules and Data health.
- The moved parts keep their element IDs, so every existing link, tab, filter, search shortcut and drawer keeps working; the list of
  old sections and their new places is [`T4.6-reachability.md`](T4.6-reachability.md).
- Findings are deduplicated twice over: Intelligence V2 still groups its cluster duplicates under their primary finding, and a duplicate
  of the verdict layer (R8) is shown as "Same measure, smaller sample" under the finding kept, not as a row of its own. The published
  count and its reconciliation note (T1.5, R4) are unchanged.

## R20. The plain data-health line (T4.7)

- **Source:** the build's Task 7 status snapshot (`atlas_sync.status.build_time_snapshot`), already on the page for Data & rules:
  `freshness_state`, `system_state` and the Monday retrieval time. The line words it and computes nothing.
- **Three states:** "safe" only when the snapshot says `fresh`; "unavailable" when there is no Monday data or the snapshot reports a
  failed system; otherwise "delayed (last refresh …)". A freshness the snapshot could not confirm (`unknown`, or a local build without a
  snapshot) therefore reads "delayed": the first layer never claims more than the snapshot proves. A build-time snapshot's
  `system_state` is always `unknown` (the build cannot observe the runtime), so it is not used for "safe".
- **Technical fields** (publication and attempt IDs, freshness seconds, attempts, dashboard document version, contract) are under More
  details › Data health › Technical details; the first layer shows none of them, including the blank publication ID the audit saw.
