# Atlas UI redesign (contract 1.5 presentation)

Branch `ui-ux`. A from-scratch presentation layer for contract 1.5.0, built to the product brief in
[`HANDOFF-V2.md`](HANDOFF-V2.md) (§12 information architecture, §13 profile order, §22–§24 UX principles, items 1–40).

## Why the old UI looked the way it did

- It grew contract by contract. Contract 1.4 had no approved judgements, so the home page led with a large "Management insights
  are being calibrated" block and many empty "not evaluated yet" slots. Contract 1.5 then stacked the interpretation layer
  (`interpretation_html.py`) on top of the 1.4 sections, so the profile showed Speed, Deadlines and Quality twice, in two visual
  languages (the warm dashboard and the unstyled report).
- Everything had to stay auditable, so raw codes (`deadline_not_classifiable_missing_eta`), mapping versions and rule IDs sat in
  the primary reading path.
- Profile content lived behind six tabs, so the first viewport could not answer "what is this Editor's state and why".

## What changed

| Area | Before | Now |
|---|---|---|
| Navigation | Editor team · Data & System, greeting, calibrating hero | Editors · Data & rules, data freshness chip, language switch |
| Editors overview | Long cards with a headline metric chosen by display order | Status pill, 3 component states with one fact each, top positive and issue label, sample; alphabetical; search (`/`) and a status filter with counts (no ranking) |
| Team context | Four stacked sections on the home page | One secondary, tabbed card: timeline, labels by class, current work, monthly history |
| Editor Profile | Header, 4 metric buttons, 6 tabs, interpretation block duplicated with the 1.4 panels | One page in §13 order with a sticky section bar: status + why + key figures (first viewport), Recent Change, signals, Quality, Speed, Deadlines, Revisions, Current work, History, Data & evidence |
| Evidence | Mixed: drawers for some metrics, tables for others | Every component and signal has an evidence link; component drawers list the rule, its approval, period and projects; the complete report is one click away |
| Report | Separate unstyled page | Same sections and design as the app, static (no script), printable, with every evidence record and event ID inline |
| Visual | Warm cream, dark hero, lime accent | Same brand accent; calm status scale; dashed grey for "not classifiable"; revisions always neutral; light + dark; RTL via logical properties |

## Guardrails kept

- Contracts 1.3 and 1.4 render exactly as before (`fixtures/golden` byte-for-byte). The new UI is selected only for contracts
  with `editor_intelligence` (1.5.0+), so a rollback to 1.4.0 also rolls back the presentation.
- The UI computes nothing. The only view-model change copies the engine's `client_revision_rate` into the 1.5 dashboard document.
- English and Arabic render one view model; tests check identical numbers, Monday values, IDs and classification attributes.
- Pages make no network request (no web fonts, no CDN).

## Local preview

```bash
make demo-showcase          # contract 1.5, six synthetic Editors covering every status
```

## Tests

`tests/test_ui_v15.py` (`make ui-v15`, in CI): navigation scope, profile section order, alphabetical cards with engine statuses,
filter counts, neutral revisions, sample sizes on every speed row, no unapproved ratings, no English UI on Arabic pages, EN/AR
parity, catalogue coverage, static report with every evidence record, no network requests.

## Open recommendations

1. **Arabic review.** 72 new `ui.*` strings are marked `Needs Arabic Review` in the catalogue.
2. **Approve Strength / Attention rules.** The profile groups supported facts as "Positive signals" and "Worth reviewing" and
   says they are not ratings. HANDOFF-V2 #9, #10, #22, #23 need approved thresholds before these become Strengths, Attention
   Areas, Recognition and Needs Attention Now.
3. **Approve Quality N/P and Trend materiality (still open in D52).** Every Editor currently shows Quality "Not classifiable" and
   Recent Change without a Trend. Until then the overview carries a grey Quality row on every card.
4. **Page weight.** The dashboard embeds every Editor's full report for the audit drawer (≈1.6 MB for six Editors). Loading the
   report by URL (`profiles/<id>.html`) in the iframe instead would cut this substantially as the team grows.
5. **Period control.** HANDOFF-V2 #24 allows controlled period changes; the engine computes one window today. A second window
   would need the engine to produce it, not the UI.
