# Atlas Reasoning V3: the reasoning-first dashboard (Phase 16)

Phase 16 ([`REV/16`](../REV/16-build-the-reasoning-first-dashboard.md)) makes validated, canonical Reasoning V3 results the primary
management view, while every card stays auditable down to Monday evidence. It is presentation only: no upstream metric, reasoning,
identity, fingerprint, Change Gate, lifecycle or Phase 15 rule changes, and **no migration** (canonical state already holds everything
the dashboard shows). Foundation: [`REASONING-V3.md`](REASONING-V3.md); human context: [`REASONING-V3-MEMORY.md`](REASONING-V3-MEMORY.md);
guardrails: [`REASONING-V3-GUARDRAILS.md`](REASONING-V3-GUARDRAILS.md).

```
PostgreSQL (canonical)                                   Phase 16 (presentation, read-only except via ManagementAPI)
  reasoning_results.current_version ─┐
  reasoning_result_versions ─────────┤                    dashboard.DashboardService ──► view objects (to_dict) ──► reasoning_read_api (JSON)
  reasoning_evidence_links ──────────┤ store.dashboard_read                     │                                 └► dashboard_html (EN / AR pages)
  reasoning_case_evidence ───────────┤                                          └── Phase 12-14 services (notes, questions, teachings)
  reasoning_work_items, memory_injections, memory_sync_log, lifecycle transitions        ▲ writes only through management_api
                                                                                           │
                                         web_app (WSGI): /reasoning/<en|ar>/…, /api/reasoning/read/…, /api/reasoning/… (+ assets)
```

## 1. Where it is mounted, and what stays unchanged

Atlas publishes a static site; nothing in `atlas_commander`, `atlas_sync` or `atlas_monday_probe` imports Reasoning V3 (tested). Phase 16
therefore does **not** touch the static site, its build, its publication or its golden bytes. The dashboard is a separate stdlib WSGI
application, `atlas_reasoning.web_app`, for the authenticating proxy to route `/reasoning/` and `/api/reasoning/` to. The static Atlas
dashboard remains the deterministic diagnostics path (metrics, Editor Profiles, every Intelligence V2 finding) and every dashboard page
links to it.

- **Reasoning V3 off (default):** `create_app` raises `ReasoningDisabled`; no PostgreSQL, Honcho, OpenRouter or web service is needed by
  legacy Atlas. The static site is byte-identical (existing golden tests in `tests/test_reasoning_boundary.py`).
- **Production topology** (process manager, proxy routes, TLS, rollout) is Phase 20's. Phase 16 deploys nothing.
- **Local preview** (loopback only): `ATLAS_REASONING_V3=on … PYTHONPATH=src python -m atlas_reasoning.web_app --port 8765
  [--dev-actor you@example.com]`. `--dev-actor` exists only in this preview entry point (there is no proxy on a developer machine); it is
  not reachable through `create_app`.

## 2. Modules

| Module | Role |
|---|---|
| `dashboard_routes` | Stable addresses (§8); refuses non-canonical result IDs and locales |
| `store.dashboard_read` | Read-only SQL over canonical tables (never `reasoning_failed_candidates`) |
| `dashboard` | `DashboardService`: canonical state → view objects (`Home`, `CardSummary`, `ResultCard`, `EvidenceTrace`, `History`, `HumanContext`) |
| `reasoning_read_api` | `ReasoningReadAPI`: the same view objects as JSON, GET only |
| `dashboard_i18n` | English and Arabic interface wording (same keys and placeholders, tested) |
| `dashboard_html` | Server-rendered pages: home, card, evidence, history, Teach Atlas, errors |
| `dashboard_assets` | `dashboard.css` and `dashboard.js` (served as files, so the CSP allows no inline code) |
| `web_app` | WSGI mounting of pages, read API and `ManagementAPI`; `create_app`, `WebSettings`, preview `main` |

Changed existing files (all Chat A / Phase 12–14 surfaces):

| File | Change | Public interface | Integration impact |
|---|---|---|---|
| `human_context_html.py` | optional `locale="en"` on `note_panel`, `question_panel`, `teach_atlas_page`; wording from `dashboard_i18n` | additive keyword | English output byte-identical (SHA-256 pinned in tests) |
| `management_api.py` | `authorize_actor(settings, actor)` extracted from `ManagementAPI._authorize` (same rule) so reads and writes share one check; docstring now says Phase 16 mounts it | new function | none: behaviour identical, existing API tests pass |
| `docs/REASONING-V3-MEMORY.md` | §3.2: the API is now mounted by Phase 16 | — | documentation only |

No edit to `__main__.py`, `settings.py`, `store/repository.py`, `store/health.py`, `tests/test_reasoning_store.py`, `docs/REASONING-V3.md`,
contracts, prompts, migrations or any `atlas_commander` file.

## 3. The card

A card is a result at its **current** version (`reasoning_results.current_version`). A Phase 15 refused candidate never becomes a version,
so it is never a card; the dashboard does not read `reasoning_failed_candidates` at all. Each card shows, from the canonical document:

| Part | Source |
|---|---|
| Title, Atlas reasoning summary, observation, supporting evidence, counter-evidence, interpretation, alternative explanations (with "needs business context" for `requires_context`), confidence (level + rationale), limitations, management significance, suggested investigations, questions asked in this version | the version's `ReasoningResult` document, verbatim (escaped) |
| Lifecycle | the version's stored `lifecycle_status` (Phase 09) |
| What changed | stored `ReasoningUpdate` of the last content version (changed fields, `change_rationale`), `delta.summary` of the stored material delta of its work item, or the lifecycle transition's reason code |
| Manager interpretation, Atlas questions, answers (conflicts flagged), dismissals | Phase 12–13 services (`ManagerNotes`, `AtlasQuestions`) |
| Provenance | result and case IDs, model, prompt version, source snapshot, evidence fingerprint, timestamps |

Three sources are visually and semantically separate on every card (`data-source-type`): **ATLAS REASONING** (model text, checked by the
guardrails, never a source of numbers), **MANAGEMENT CONTEXT** (attributed, never evidence) and **DETERMINISTIC EVIDENCE**. No hidden
reasoning exists to show (the contract has no field for it and the gateway requests `reasoning.exclude`).

**Lifecycle** is never colour-only: every badge carries a symbol (decorative, `aria-hidden`), the word and, on the card, a one-line
explanation. Home groups current cards (new, updated, active, cooling) apart from the record (resolved, superseded). A superseded card
links to its replacement (`superseded_by`); the replacement lists the cards it replaced. Resolved and superseded cards stay fully
inspectable. Any earlier version opens with `?version=n`, marked "historical".

## 4. Evidence drill-down

`DashboardService.evidence(result_id, version)` resolves, for the shown version:

1. the references the card cites (`repository.citations` of the document) against `reasoning_evidence_links` for that version **and**
   the stored case evidence state (`reasoning_case_evidence.case_document` at the version's `evidence_fingerprint`);
2. each reference to its case finding by `member_key`: the Intelligence V2 `finding_id` (of the snapshot that evidence state came from),
   type, direction, category, evidence level, upstream confidence, sample size, limitations;
3. the finding's deterministic statements (metric values exactly as stored) and evidence blocks (samples, comparisons, exclusions);
4. the Monday records: item ID (linked when `ATLAS_REASONING_MONDAY_ITEM_URL` is set), cycle, event IDs, source timestamps, Editor,
   Video Type, values used.

Every record of the case is shown, cited or not (nothing a detector produced disappears). A cited reference that does not resolve is
listed as needing engineering review (never expected; `EvidenceTrace.unresolved`). The case's `manager_context` / `memory_context` are
never part of the trace. Each record has the anchor `#ev-<ref_id>`, each card claim links to it, and the evidence page links the subject
to the deterministic dashboard (`/<locale>/dashboard.html#/editor/<id>` for an Editor). When the case has newer evidence than the card,
the trace says so.

## 5. Human interaction

The pages place the Phase 12–14 fragments on every card and on `/reasoning/<locale>/teach`; their forms post JSON to the mounted
`ManagementAPI` (create/edit notes with revision history, answer, conflicting answers, dismiss, Teach Atlas create/enable/disable/archive).
No business rule is reimplemented: `dashboard.js` only serializes the form, sends `X-Atlas-CSRF` and reloads on success; the server
enforces authentication, the manager allow-list, CSRF, Origin, JSON-only bodies, size limits, validation and audit identity. Stored text is
escaped on output and always labelled management context.

## 6. Degraded, empty and error states

| State | Canonical signal | Shown |
|---|---|---|
| No results yet | no `reasoning_results` | empty state + link to the deterministic dashboard |
| Newer evidence not yet reasoned | case `last_evidence_fingerprint` ≠ card's fingerprint (case present) | notice `evidence_changed`; the trace names the newer fingerprint |
| Update queued | latest LLM work item `pending` / `in_progress` | notice `update_pending` |
| Provider failure, previous card kept | latest LLM work item `failed`, `last_error` `provider:*` | notice `provider_failed`; card = last valid version |
| Phase 15 refusal, previous card kept | latest LLM work item `failed`, `last_error` `validation:*` | notice `validation_refused`; codes and candidate never shown |
| Other refresh failure | latest LLM work item `failed` otherwise | notice `refresh_failed` |
| Honcho degraded, PostgreSQL fine | latest `memory_injections.memory_status` `degraded`/`unavailable`; `memory_sync_log` pending/failed rows | notice `memory_degraded`; home banner with the backlog count; canonical notes still shown |
| Cooling / resolved | lifecycle | badge + explanation; resolved banner |
| Human-context service unavailable | service missing or failing | the card renders; the management panel says context is unavailable |
| API / read failure | database unreachable or failing | 503 page (plain language, no detail) with the deterministic dashboard link; JSON `READ_FAILED` |

Honcho is never contacted by the dashboard: it is not a source for anything shown.

## 7. English / Arabic

Both locales render the same view objects: same result IDs, versions, lifecycle, confidence, evidence references, findings, questions,
notes and management context (tested by comparing every `data-*` identifier of every page in both languages). Only the interface wording
differs (`dashboard_i18n`); model text, Monday values and management text are shown as stored with `dir="auto"`, never translated or
regenerated. Arabic pages are `dir="rtl"` with logical CSS properties; identifiers and timestamps are isolated left-to-right.

## 8. Phase 17 handoff interface (stable)

Phase 17 (ExecutiveBrief) must consume these and must not depend on page markup beyond them:

1. **Card address / anchor.** `dashboard_routes.card_path(locale, result_id)` → `/reasoning/<locale>/results/<result_id>#result-<result_id>`.
   On the home page every card is the element `id="result-<result_id>"` (`card_anchor(result_id)`), so `/reasoning/<locale>/#result-<id>`
   also lands on it.
2. **Open one ReasoningResult.** Page: `card_path(locale, result_id[, version=n])`. Data: `DashboardService.card(result_id[, version])`
   (`ResultCard`, raises `NotFound`) or `GET /api/reasoning/read/results/<result_id>[?version=n]`.
3. **Evidence drill-down.** `evidence_path(locale, result_id[, version=n])` (records anchored `#ev-<ref_id>`); data `DashboardService.evidence(...)` or
   `GET /api/reasoning/read/results/<result_id>/evidence`.
4. **History.** `history_path(locale, result_id)`; data `DashboardService.history(result_id)` or `GET …/results/<result_id>/history`.
5. **Executive statements with `result_ids`.** `dashboard_routes.result_links(locale, result_ids)` → `[{result_id, card, evidence, history}]`
   (order kept, duplicates removed, non-canonical IDs refused with `InvalidRoute`); existence against canonical state:
   `DashboardService.existing(result_ids)` or `GET /api/reasoning/read/links?locale=<l>&result_id=<id>[&result_id=…]` (404
   `UNKNOWN_RESULT` if any is unknown). Statements must link to cards this way, never by title or position.
6. **Home insertion point.** `dashboard_html.home_page(home, ctx, lead_html=...)` places trusted, server-rendered HTML above
   `<section id="reasoning-results">` (after the page title and any memory banner). Phase 16 never passes it; Phase 17 may own it for an
   executive overview. Phase 16 creates no executive home, navigation or brief.

## 9. Configuration

| Variable | Default | Meaning |
|---|---|---|
| `ATLAS_REASONING_V3` | `off` | `on` required to start the app |
| `ATLAS_REASONING_DATABASE_URL` / `_FILE` | — | canonical store (as everywhere in Reasoning V3) |
| `ATLAS_REASONING_MANAGERS` | — | allow-list for every page and API route |
| `ATLAS_REASONING_CSRF_SECRET` / `_FILE` | — | ≥ 32 bytes; CSRF tokens are HMAC(secret, actor) |
| `ATLAS_REASONING_ALLOWED_ORIGINS` | — | must include the dashboard's own origin (browsers send `Origin` on writes) |
| `ATLAS_REASONING_ACTOR_HEADER` | unset (`REMOTE_USER`) | a header the proxy sets **and strips from clients**; when set, `REMOTE_USER` is ignored |
| `ATLAS_REASONING_DIAGNOSTICS_URL` | `/{locale}/dashboard.html` | the deterministic dashboard; a site path or https URL |
| `ATLAS_REASONING_MONDAY_ITEM_URL` | unset | https URL template with `{item_id}` for Monday item links |
| `ATLAS_REASONING_MEMORY`, Honcho variables | `off` | only for the memory copy after a human-context write (server-side) |

## 10. Security

| Concern | Rule (tested) |
|---|---|
| Authentication | actor from the proxy only (`REMOTE_USER`, or the configured header); never body or query |
| Authorization | `management_api.authorize_actor` for every page, read and write route (401 / 403 pages and codes) |
| CSRF / Origin / JSON | unchanged `ManagementAPI` rules for every write; token bound to the actor; bodies read to at most `max_body_bytes + 1` |
| XSS | every stored, model and identifier value escaped; IDs in URLs must be canonical (`rr1_…`, `ev1_…`) or are percent-encoded; operator URLs validated (no `javascript:`, no protocol-relative, no quotes/spaces) |
| Headers | `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; …; frame-ancestors 'none'` (no inline code), `no-store`, `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` |
| Leakage | errors are plain pages / JSON codes; no exception text, database URL, key or work-item error string reaches a page; failed-candidate codes are not shown |
| Script | `dashboard.js` uses `textContent` only, no `innerHTML`/`eval`, reads no reasoning data, computes nothing |

## 11. Tests

`tests/test_reasoning_dashboard.py` (runs in `make reasoning`): routes and ID injection; catalog parity; byte-identical English fragments
and Arabic parity of fragments; script and stylesheet safety; settings validation; flag off; WSGI auth, headers, HEAD, 405/404, read
failure 503 without leaks (no database); escaping of every model field in both languages; lifecycle never colour-only; with PostgreSQL:
empty state, current-version-only cards with canonical fields, every card part, refused candidates absent with the previous card kept,
evidence resolution (case → finding → Monday), every evidence link on every page resolves, management context never in evidence, every
lifecycle with supersession links, history and old versions, notes (create, edit, history, conflict) and questions (answers, conflicts,
dismissal) and Teach Atlas through the mounted API, CSRF / Origin / content-type / auth / actor-bound token / unknown field / body size,
proxy-header mode, human context unavailable, memory degraded and backlog, pending and provider-failed updates; and through the real
connected pipeline (gate → engine → guardrails): every card traces to the published Intelligence V2 finding and its Monday item, cycle and
event IDs, a refused update and a provider failure keep the last valid card, EN/AR identical canonical identifiers on every page, and the
Phase 17 links route.

## 12. Independent review (before the Draft PR)

A separate review pass (no implementation context) checked calculation leakage, evidence trace, dynamic mounting, XSS, CSRF/auth,
language divergence, stale-result presentation, failed-candidate exposure, Honcho authority and Phase 17 scope. No critical or high
finding. Fixed, each with a regression test:

| Severity | Finding | Fix |
|---|---|---|
| medium | A historical version's evidence links opened the *current* version's drill-down | `evidence_path(..., version=)`; historical cards link to their own version; the evidence page uses same-page anchors |
| low | History and evidence pages did not repeat the stale-result notices | `History` carries notices; history and evidence pages render them |
| low | A cited reference outside every case finding counted as resolved but had no anchor | counted as unresolved |
| low | Actor values with a comma (joined duplicate headers) or control characters were accepted as identities | refused (401) |
| low | Preview server with `--dev-actor` was open to DNS rebinding | the preview wrapper accepts only loopback `Host` values |
| low | Management panels skipped a heading level; no notice that saving needs JavaScript | `heading=` on the fragments (English default unchanged); `<noscript>` notice |

Kept as known limitations (below): the card page composes four short read transactions; the home card's "Updated" time is the
version's `updated_at` (a lifecycle-only version moves it).

## 13. Known limitations

- Not deployed: production routing, TLS, process supervision and the proxy's header stripping are Phase 20's.
- Without JavaScript the pages are fully readable, but forms cannot submit (writes must be JSON with the CSRF header by design).
- Intelligence V2 finding IDs shown in the drill-down belong to the snapshot in which that evidence state was first stored; the static
  dashboard shows the latest snapshot. The deterministic link opens the subject (Editor) rather than a single finding, because the static
  site has no per-finding anchor (changing it would alter the deterministic site's golden bytes).
- Model text is shown in the language the model wrote it (English) on Arabic pages, by design: Arabic reasoning is never regenerated.
- The card page reads card, evidence, history and human context in separate short transactions; a version committed between them
  can make the embedded history name a newer current version than the card (reloading shows the new card).
- The home card's "Updated" time is the current version's `updated_at`, which a lifecycle-only version also moves; the card's
  "What changed" says which version last changed the content.
- The proxy must overwrite (not append to) the actor header in both `-` and `_` spellings and the app must listen only on the
  proxy-facing interface (Phase 20).
- "What changed" counts come from the stored material delta of the patch's work item; versions written by tools that do not record a
  work item show the stored rationale and fields only.
