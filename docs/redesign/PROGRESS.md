# Atlas redesign: progress

Implementation of `atlas-redesign-handoff/03-TASKS.md` on branch `feat/atlas-redesign`, started from `origin/main`
`b036834784384c85c6f91bbf794280895e3f6683` (2026-09-30).

## Checklist

States: `pending`, `in_progress`, `verified`, `blocked`.

| Task | State | Task | State |
|---|---|---|---|
| T0.1 Repository map | verified | T2.13 Overdue list per editor | pending |
| T0.2 Run it locally | verified | T2.14 Decisions generator | pending |
| T0.3 Validate the handoff against the repo | verified | T2.15 Team verdict | pending |
| T0.4 Baseline tests | verified | T2.16 Wire into the real snapshot build | pending |
| T1.1 Reset scroll on route change | pending | T3.1 Tokens and fonts | pending |
| T1.2 Close drawers on route change | verified | T3.2 Avatar | pending |
| T1.3 Mobile tables become stacked records | pending | T3.3 LateBar | pending |
| T1.4 Bidi isolation helper | verified | T3.4 SpeedPill, TierChip, ConfidenceTag | pending |
| T1.5 Explain the 46 vs 55 findings count | verified | T3.5 PersonCard | pending |
| T2.1 Snapshot schema types | verified | T3.6 DecisionCard | pending |
| T2.2 Verdict config | verified | T3.7 TierSection | pending |
| T2.3 Test fixture | verified | T3.8 VerdictBand | pending |
| T2.4 Per-editor metric normalization | verified | T4.1 i18n strings for verdicts | pending |
| T2.5 Tier assignment | verified | T4.2 New Team overview page | pending |
| T2.6 Score and rank | pending | T4.3 Remove old first-layer content | pending |
| T2.7 Confidence | pending | T4.4 Editor profile drawer | pending |
| T2.8 Runway explains lateness | pending | T4.5 Profile "More details" | pending |
| T2.9 Change mirrors team | pending | T4.6 Global "More details" area | pending |
| T2.10 Duplicate findings | pending | T4.7 Plain data-health line | pending |
| T2.11 Silent measurement, zero activity | pending | T4.8 Rules page: proposals | pending |
| T2.12 Headlines and reasons | pending | T5.1 Photo source | pending |
| | | T5.2 Photo management | pending |
| | | T6.1 Responsive pass | pending |
| | | T6.2 Accessibility pass | pending |
| | | T6.3 Numbers verification | pending |
| | | T6.4 Release | pending |

Backlog B1–B8 is out of scope ("after release").

## Log

One line per task: ID, date, what changed, how it was verified.

- T0.1, 2026-09-30: `docs/redesign/MAP.md` maps framework, routing, build, metrics/findings, schemas, UI, i18n, styling, tests, deploy. Verified: a script resolved all 68 relative links to existing paths.
- T0.2, 2026-09-30: local dev loop documented in MAP.md (build from the real extract under contract 1.5.0, serve `out/`, test targets). Verified: site built from production run `20260929T210734Z-4cb4bfa25596` in 30 s and rendered locally; screenshot `screenshots/T0.2-editors-local-en.png`.
- T0.3, 2026-09-30: `docs/redesign/DECISIONS.md` marks every §1 input "exists at …" or "missing, plan: …" (plus team inputs, project name, source link, photo), and records the governance and routing discrepancies. Verified against `out/real` (dashboard, profiles, intelligence-v2 documents).
- T0.4, 2026-09-30: baseline `make test` on `b036834`: exit 0, 751 tests, 0 failures, 3 skipped (Docker runtime tests without `ATLAS_RUN_DOCKER`), ruff and mypy clean; no pre-existing failures. Added `tests/test_redesign_smoke.py` (the showcase snapshot builds through `profile_cli.build_all`, has Editors, and every required file exists in both languages) and the `make redesign` target, part of `make test` and CI. Verified: `make redesign` 2 tests OK, `make unit` OK.
- T1.2, 2026-09-30: a route change (link, nav or Back) closes the evidence drawer, empties it and its title, and keeps focus off the hidden trigger; Escape and the close button still return focus to the claim. No route owns an evidence drawer yet (the profile drawer arrives in T4.4). Verified by 3 browser tests in `tests/test_redesign_routing.py` (EN and AR); on the previous script the drawer closed but still held the old evidence (test failed: 4 nodes, title "Class B").
- T1.4, 2026-09-30: one isolation helper in `i18n.Loc`: `loc.isolating()` (turned on by the contract 1.5 app and report only, so the 1.3/1.4 golden pages stay byte for byte) wraps Latin runs of Arabic catalogue text in `<bdi dir="ltr">` (`isolate_latin`), `loc.when()` puts dates in `<time datetime>` (isolated by CSS, locale direction because Arabic dates use Arabic month names), and `web/intel.marked_html` does the same for the Intelligence narrative (findings, confidence, limitations). IDs/numbers/percentages were already isolated (`ltr`, `tech`, `num`). Also: IDs wrap only when longer than a line; Data & rules rule rows align on mobile. Verified: `tests/test_redesign_bidi.py` + `tests/bidi_check.py` find 0 unisolated IDs, dates, timestamps, percentages or Latin runs in the Arabic app and every Arabic profile report (19,317 on `main` for the real build); English catalogue text unchanged. Screenshots: `screenshots/T1.4-arabic-overview-1280.png` (IDs such as 3109734616 and the timestamp intact and in order), `T1.4-arabic-overview-390.png`, `T1.4-arabic-profile-390.png`, `T1.4-arabic-data-rules-390.png`. Test updates: `test_ui_intelligence` reads card text without isolation tags (the Arabic label "ما لاحظه Atlas" now isolates "Atlas").
- T1.5, 2026-09-30: cause found and written in DECISIONS.md R4 (55 = 5 Top + 46 listed + 4 grouped duplicates). Both scopes are labelled from one function (`web.intel.finding_scope`): overview list "46 more published findings" with a reconciling note, Data & rules "Published findings (all, including grouped duplicates)" plus "On the Editors page: 5 top findings + 46 more · 4 duplicates grouped". EN and AR strings added (Needs Arabic Review), review table regenerated. Verified: `tests/test_redesign_counts.py` (the three scopes partition every published finding; both pages state the same numbers in both languages); screenshots `screenshots/T1.5-overview-list-scope.png`, `T1.5-data-rules-scope.png` on the real build.
- T2.1, 2026-09-30: `contracts/verdict-v1.schema.json` defines `Msg`, `EditorVerdict`, `TeamVerdict`, `Decision` (snake_case, R5); new package `atlas_commander.verdict` builds `verdicts.json` (document 1.0.0, empty arrays, team null) inside `profile_cli.build_dashboard_files`, i.e. in both the CLI and the production cycle; it is an optional artifact with its own checker (`optional_artifacts.py`, used by `atlas_sync.run.validate_site` and `atlas_sync.publish.validate_build`). Verified: `tests/test_redesign_verdict_document.py` (schema-valid in the showcase snapshot, same snapshot/contract, rejected when malformed or from another snapshot); the real build's `verdicts.json` validates; `make sync-run publish contract-v15-release intelligence-v2 redesign` OK (one assertion in `test_investigation_engine` updated: there are now two optional artifacts).
- T2.2, 2026-09-30: `config/verdict-v1.json` holds every threshold and weight of spec §3–§5 and §8 (plus the decision cap, display tones and rounding), each with a one-line `meaning` and `decision_id` D54; the two materiality values shared with Intelligence V2 are read from `config/intelligence-v2.json` (D53). Loader `verdict/config.py` refuses unapproved, unexplained or non-numeric values; the publication gate `include_in_site_build` turns `verdicts.json` off without breaking the build. D54 recorded in `docs/DECISIONS.md` (owner handoff defaults; supersedes HANDOFF-V2 §24/§36 and D47 for the verdict layer only; D37 unchanged). Verified: `tests/test_redesign_verdict_config.py` (config ↔ D54 table agree value by value; refusals; an AST scan finds no numeric literal but 0, 1, 100 in `atlas_commander/verdict/` outside the config) and the gate-off build test.
- T2.3, 2026-09-30: `fixtures/verdict/september-2026.json` (written by `tests/make_verdict_fixture.py`, loaded by `tests/verdict_fixture.py`) reproduces spec §9: the six spec Editors with their numbers, plus six unremarkable Editors so the team totals match (late 76/129 = 59% now, 97/129 = 75% before; 3 overdue open projects of Michael, Refaat, Mario; 328 of 424 late with short runway, 73% of 448 vs 55% of 91; Anas's two overlapping late-rate findings; Refaat's +26.3% own-history speed change). `tests/test_redesign_verdict_fixture.py` asserts the team totals and schema validity (pass) and the spec tiers (expected failure until T2.5; it fails with "no verdict for Will" because the engine writes no Editor verdicts yet).
- T2.4, 2026-09-30: `verdict/inputs.py` normalizes one snapshot (`dashboard.json` + published `intelligence-v2.json`) into per-Editor inputs and team inputs, and maps them into `EditorVerdict.metrics` (completed, active, lifetime, late count/rate, team late rate, primary-Video-Type speed delta with its label and whether it is D52-classified, own-history speed change, quality). Team rates are sums of the Editors' own counts. Verified: `tests/test_redesign_verdict_fixture.py::MetricsTests` — late counts, rates and speed deltas match §9 exactly for all six spec Editors (e.g. Refaat 12/14 = 85.7%, +43% vs peers, +26% vs himself; team 59%). On the real build the team late rate (79/135 = 58.52%) equals Intelligence V2's own team figure.
- T2.5, 2026-09-30: `verdict/tiers.py` `assign_tier(metrics, overdue, config, standing)` implements spec §3 in order (low activity → weakest → watch → best → steady) with every threshold from the config; `score()` (§4 formula, needed by the Best rule) and ranking are in place; the engine now writes one verdict per Editor (confidence and sentences are provisional until T2.7/T2.12). Readings of the spec recorded in DECISIONS.md R6. Verified: fixture tiers Will best, Anas steady, Refaat weakest, Sobhy watch, Mohamed Mansour low_activity, Samra low_activity (`tests/test_redesign_verdict_fixture.py::test_spec_tiers`, no longer an expected failure); `tests/test_redesign_verdict_tiers.py` checks each rule at, below and above its threshold; the document stays schema-valid.
