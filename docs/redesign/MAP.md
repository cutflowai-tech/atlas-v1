# Atlas redesign: repository map (Phase 0)

Written for the `atlas-redesign-handoff` package (T0.1, T0.2). The handoff was written without the code; this map is what the
code actually does, at `origin/main` `b036834` (2026-09-30). Paths are relative to the repository root. Where the handoff
assumed something else, the difference is logged in [`DECISIONS.md`](DECISIONS.md).

## Framework and build tool

- **No web framework and no JavaScript build.** Atlas is a Python 3.12 package (`src/atlas_commander`, `src/atlas_sync`,
  `src/atlas_monday_probe`) that renders **static, self-contained HTML** at build time. Each page carries one inline stylesheet and
  one small inline script; there is no bundler, no npm, no CDN and no network request from the page.
- Dependencies: [`requirements.txt`](../../requirements.txt) (runtime: `jsonschema`), [`requirements-dev.txt`](../../requirements-dev.txt)
  (ruff, mypy), [`pyproject.toml`](../../pyproject.toml) (ruff/mypy config).
- Task runner: [`Makefile`](../../Makefile). `make test` is the full gate (lint, typecheck, every unit/contract/UI suite).

## Routing

- One page per language: `en/dashboard.html` and `ar/dashboard.html`. Inside it, **hash routes** select a view:
  - `#/` Editors overview (`data-view="team"`),
  - `#/editor/<editor_id>` Editor Profile (`data-view="editor:<id>"`),
  - `#/system` Data & rules (`data-view="system"`).
- The router is the inline `SCRIPT` in [`src/atlas_commander/web/style.py`](../../src/atlas_commander/web/style.py) (`route()`,
  `hashchange`). Evidence drawers are filled from `<template id=…>` elements next to the claim (`openDrawer()`), not routed.
- Language switch: a link to the other language's page that keeps the current hash (`data-keep-hash`).
- Public URLs served by nginx ([`deploy/production/nginx.conf`](../../deploy/production/nginx.conf)): only `/`, `/en/…` and
  `/ar/…`. Everything else (including `dashboard.json`, `intelligence-v2.json`, `profiles/`) returns 404.

## Where the snapshot is generated

The handoff's "published snapshot" is, in Atlas, a **site build**: language-neutral JSON documents plus the HTML rendered from them.

| Step | Code |
|---|---|
| Read-only Monday ingest (activity logs + items) → `extract.json` | [`src/atlas_commander/ingest.py`](../../src/atlas_commander/ingest.py), [`src/atlas_commander/monday_source.py`](../../src/atlas_commander/monday_source.py) |
| Production cycle: ingest → verify → build → validate → atomic publish | [`src/atlas_sync/run.py`](../../src/atlas_sync/run.py) (`STAGES`, `run_sync`, `validate_site`), [`src/atlas_sync/publish.py`](../../src/atlas_sync/publish.py) (`validate_build`, publish, rollback) |
| Local / CLI build of the whole site | [`src/atlas_commander/profile_cli.py`](../../src/atlas_commander/profile_cli.py) (`build_all`: profiles → Intelligence V2 → dashboard) |
| File layout of a build | [`src/atlas_commander/site_layout.py`](../../src/atlas_commander/site_layout.py) |

A build (`out/<name>/` locally, `/var/lib/waset-atlas/…` in production) contains:

```
index.html                    root entry (currently → en/dashboard.html)
publication.json              release / snapshot identity (contract 1.5.0)
dashboard.json                CEO dashboard document (ceo-dashboard-v0.1): one summary per Editor, copied from the profiles
profiles/<editor_id>.json     Editor Profiles (editor-profile 1.5.0): every metric with its evidence
intelligence-v2.json          optional Intelligence V2 document (D53, approved_only)
en/dashboard.html, ar/…       the app (Editors, Profiles, Data & rules) in each language
en/profiles/<id>.html, ar/…   full printable profile report per Editor
```

## Where metrics, rules and findings are computed

| Layer | Code | Output |
|---|---|---|
| Cycles (In Progress → Ready For Approval), attribution, Video Type | [`cycles.py`](../../src/atlas_commander/cycles.py), [`pipeline.py`](../../src/atlas_commander/pipeline.py), [`identity.py`](../../src/atlas_commander/identity.py), [`attribution.py`](../../src/atlas_commander/attribution.py), [`video_type.py`](../../src/atlas_commander/video_type.py) | `CycleReconstruction` |
| Speed, deadline, quality metrics | [`metrics.py`](../../src/atlas_commander/metrics.py), [`quality.py`](../../src/atlas_commander/quality.py) | per-cycle facts |
| Contract 1.5 interpretation: windows, components, Overall Status lookup (D23–D47, D52) | [`intelligence.py`](../../src/atlas_commander/intelligence.py), [`interpretation_policy.py`](../../src/atlas_commander/interpretation_policy.py) | inside each profile |
| Editor Profile document | [`profile.py`](../../src/atlas_commander/profile.py) (`build_editor_profile`) | `profiles/<id>.json` |
| Dashboard view model (copies from profiles, computes nothing new) | [`dashboard.py`](../../src/atlas_commander/dashboard.py) (`build_dashboard`, `interpretation_view`) | `dashboard.json` |
| Intelligence V2 findings: facts, baselines, 20+ detectors, confidence, prioritization, EN/AR narrative | [`src/atlas_commander/investigation/`](../../src/atlas_commander/investigation/) (`engine.build_intelligence`, `site.py` gate) | `intelligence-v2.json` |
| Rules and thresholds (approved decisions only, D25) | contract [`config/monday-contract-v1.5.json`](../../config/monday-contract-v1.5.json), [`config/intelligence-v2.json`](../../config/intelligence-v2.json); decisions in [`docs/DECISIONS.md`](../DECISIONS.md) | — |
| Pending management rules (Quality N/P, Trend, Needs attention, …) | [`src/atlas_commander/management.py`](../../src/atlas_commander/management.py) | empty slots |

## Snapshot schema

| Document | Schema / version |
|---|---|
| Editor Profile | [`contracts/editor-profile-v1.5.schema.json`](../../contracts/editor-profile-v1.5.schema.json) |
| Intelligence V2 | [`contracts/intelligence-v2.schema.json`](../../contracts/intelligence-v2.schema.json) (`document_version` 2.0.0) |
| Dashboard | no JSON Schema; `DASHBOARD_VERSION = "ceo-dashboard-v0.1"` in [`dashboard.py`](../../src/atlas_commander/dashboard.py), structure covered by [`tests/test_dashboard.py`](../../tests/test_dashboard.py) |
| Publication identity | [`src/atlas_commander/publication.py`](../../src/atlas_commander/publication.py), checks in `site_layout.publication_problems` |
| Monday contract | [`contracts/monday-contract-v1.5.schema.json`](../../contracts/monday-contract-v1.5.schema.json) |

Optional artifacts are declared in `site_layout.optional_files()` and validated by `atlas_sync.run.validate_site` and
`atlas_sync.publish.validate_build`, so builds with and without them publish and roll back.

## UI component folders

Server-side Python functions that return HTML strings (no component framework):

| File | Contents |
|---|---|
| [`src/atlas_commander/web/app.py`](../../src/atlas_commander/web/app.py) | the contract 1.5 app: `overview`, `editor_card`, `team_context` (Team Pulse timeline, labels, current work, history), `editor_profile` and its sections, `data_rules`, `render_app`, `page` |
| [`src/atlas_commander/web/kit.py`](../../src/atlas_commander/web/kit.py) | primitives: `avatar`, chips, `template` (drawer content), `dl`, `table`, `meter`, project evidence drawers |
| [`src/atlas_commander/web/intel.py`](../../src/atlas_commander/web/intel.py) | Intelligence V2 section, finding cards, evidence drawers, rules card |
| [`src/atlas_commander/web/report.py`](../../src/atlas_commander/web/report.py) | standalone profile report |
| [`src/atlas_commander/web/style.py`](../../src/atlas_commander/web/style.py) | `CSS` (tokens, light/dark) and `SCRIPT` (router, drawers, tabs, filters) |
| [`src/atlas_commander/dashboard_html.py`](../../src/atlas_commander/dashboard_html.py) | entry `render_dashboard_html` (contract 1.5 → `web.render_app`; 1.3/1.4 pages kept byte for byte) |
| [`src/atlas_commander/interpretation_html.py`](../../src/atlas_commander/interpretation_html.py), [`profile_html.py`](../../src/atlas_commander/profile_html.py) | status/reason text helpers, profile report page |

## i18n

- One catalogue: [`src/atlas_commander/locales/catalog.json`](../../src/atlas_commander/locales/catalog.json)
  (`atlas-i18n-v1`, locales `en`, `ar`; each entry has `en`, `ar`, `context`, `status`, CLDR plural forms where counted).
- Accessor: [`src/atlas_commander/i18n.py`](../../src/atlas_commander/i18n.py) `Loc` — `t()` (escaped HTML), `count()`,
  `num()`/`pct()`/`hours()` (numbers in `<data value>` / `<bdi dir="ltr">`), `src()` (Monday values in `<bdi>`), `tech()` (IDs in
  `<code dir="ltr">`). A missing key or locale raises `TranslationError`: there is no English fallback.
- Intelligence V2 narrative has its own EN/AR tables: [`investigation/narrative.py`](../../src/atlas_commander/investigation/narrative.py),
  [`investigation/narrative_ar.py`](../../src/atlas_commander/investigation/narrative_ar.py) (Unicode isolates → `<bdi>` in
  `web/intel.marked_html`).
- Arabic review table (generated): [`docs/i18n/ARABIC-TRANSLATION-REVIEW.md`](../i18n/ARABIC-TRANSLATION-REVIEW.md), via
  `python3 -m atlas_commander.i18n review`.

## Styling

- Plain CSS in `web/style.py`: custom properties on `:root`, a `prefers-color-scheme: dark` block, logical properties
  (`inset-inline-*`, `margin-inline-*`) so LTR and RTL share one stylesheet. System font stacks only (no web font is loaded).
- Direction is structural: `<html lang="ar" dir="rtl">` (`site_layout.document_opening`).

## Tests

- `unittest`, run per suite through `make` targets; `make test` runs all of them plus ruff and mypy
  (CI: [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml), on pull requests and pushes to `main`/`integration`).
- UI suites: [`tests/test_ui_v15.py`](../../tests/test_ui_v15.py), [`tests/test_ui_intelligence.py`](../../tests/test_ui_intelligence.py) (`make ui-v15`).
- i18n: [`tests/test_i18n.py`](../../tests/test_i18n.py), [`tests/test_investigation_i18n.py`](../../tests/test_investigation_i18n.py).
- Dashboard / profile: [`tests/test_dashboard.py`](../../tests/test_dashboard.py), [`tests/test_profile.py`](../../tests/test_profile.py), [`tests/test_contract_v15_release.py`](../../tests/test_contract_v15_release.py).
- Build / publish: [`tests/test_sync_run.py`](../../tests/test_sync_run.py), [`tests/test_publish.py`](../../tests/test_publish.py).
- Synthetic data: [`src/atlas_commander/demo.py`](../../src/atlas_commander/demo.py) (`showcase_extract()`, contract 1.5 team),
  [`tests/investigation_factory.py`](../../tests/investigation_factory.py), [`fixtures/`](../../fixtures/).

## Deploy

- Production host `atlas.wasetco.com`: two images built from [`deploy/production/Dockerfile.app`](../../deploy/production/Dockerfile.app)
  and [`Dockerfile.nginx`](../../deploy/production/Dockerfile.nginx), run by [`compose.yaml`](../../deploy/production/compose.yaml);
  an hourly systemd timer ([`waset-atlas.timer`](../../deploy/production/waset-atlas.timer)) runs one sync cycle (ingest → build →
  validate → atomic publish).
- Procedure: [`docs/PRODUCTION-RUNBOOK.md`](../PRODUCTION-RUNBOOK.md) §4 (deploy), §6 (rollback), §9 (upgrade), §10b (Intelligence V2
  gate). The record of the last deployment is [`docs/evidence/INTELLIGENCE-V2-DEPLOYMENT.md`](../evidence/INTELLIGENCE-V2-DEPLOYMENT.md).
- Production builds with `ATLAS_CONTRACT_VERSION=1.5.0` (the code default, `runtime.ACTIVE_CONTRACT_VERSION`, is still 1.4.0).

## Local dev loop (T0.2)

```sh
# 1. Build a site from a real read-only extract (≈30 s). The contract must be named: the default is 1.4.0.
PYTHONPATH=src python3 -m atlas_commander.profile_cli --contract 1.5.0 dashboard <extract.json> out/real --generated-at <extract retrieved_at>

# 2. Or build the synthetic contract 1.5 showcase (no real data needed) and serve it.
make demo-showcase            # builds out/showcase and serves it on $(DEMO_PORT)

# 3. Review the verdicts of a build (T2.16): exits 1 unless verdicts.json is publishable and covers every Editor.
PYTHONPATH=src python3 -m atlas_commander.verdict.review out/real

# 4. Serve any build and open the app.
python3 -m http.server 8766 --directory out --bind 127.0.0.1
open http://127.0.0.1:8766/real/en/dashboard.html     # Arabic: /real/ar/dashboard.html

# 5. Tests.
make test                     # full gate
make redesign                 # the redesign's own suites (test_redesign*.py)
make ui-v15 i18n dashboard    # the suites the redesign touches most
```

Real extracts are never committed (`/out/` is ignored). The extract used in this redesign is the production run
`20260929T210734Z-4cb4bfa25596`, kept outside the repository. Screenshot of the local Editors page from that build:
[`screenshots/T0.2-editors-local-en.png`](screenshots/T0.2-editors-local-en.png). Screenshots in this folder are taken with headless
Chrome (`--headless=new --window-size=W,H --screenshot=…`; `--blink-settings=preferredColorScheme=0|1` selects dark or light).
