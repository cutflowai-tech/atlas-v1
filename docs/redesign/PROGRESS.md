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
| T0.4 Baseline tests | pending | T2.16 Wire into the real snapshot build | pending |
| T1.1 Reset scroll on route change | pending | T3.1 Tokens and fonts | pending |
| T1.2 Close drawers on route change | pending | T3.2 Avatar | pending |
| T1.3 Mobile tables become stacked records | pending | T3.3 LateBar | pending |
| T1.4 Bidi isolation helper | pending | T3.4 SpeedPill, TierChip, ConfidenceTag | pending |
| T1.5 Explain the 46 vs 55 findings count | pending | T3.5 PersonCard | pending |
| T2.1 Snapshot schema types | pending | T3.6 DecisionCard | pending |
| T2.2 Verdict config | pending | T3.7 TierSection | pending |
| T2.3 Test fixture | pending | T3.8 VerdictBand | pending |
| T2.4 Per-editor metric normalization | pending | T4.1 i18n strings for verdicts | pending |
| T2.5 Tier assignment | pending | T4.2 New Team overview page | pending |
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
