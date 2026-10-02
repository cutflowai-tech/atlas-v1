# Atlas Reasoning V3 — Phase 17 executive intelligence core

Specification: [`REV/17`](../REV/17-build-the-executive-intelligence-synthesis-layer.md). Architecture of the rest of Reasoning V3:
[`REASONING-V3.md`](REASONING-V3.md); the Phase 15 guardrails this layer sits behind: [`REASONING-V3-GUARDRAILS.md`](REASONING-V3-GUARDRAILS.md).
Review record: [`evidence/REASONING-V3-PHASE-17-CORE.md`](evidence/REASONING-V3-PHASE-17-CORE.md).

**Status: Phase 17 complete with the executive UI (§11).** §1–§10 describe the presentation-independent core (contract, input, prompt,
provider call, validator, persistence, preserve policy), merged first as `PHASE17_CORE_COMPLETE`. §11 is the read-only executive overview
that completes `REV/17` #10 on top of Phase 16's reasoning-first dashboard.

```
Phase 15 guardrails ─► canonical ReasoningResults (PostgreSQL)                  (already validated; never refused candidates)
                                   │  current versions; new / active / updated, resolved within the lookback
                                   ▼
            executive_input (bounded, ordered, key-sorted)  ─►  input_fingerprint  ei1_…
                                   ▼
            preserve policy:  same fingerprint as the current brief ─► unchanged (no model call, brief untouched)
                              no eligible result               ─► deterministic empty brief (no model call)
                                   ▼
            gateway (pinned model, retries, strict structured output, no redirects, redaction)  — prompt executive-v1
                                   ▼
            executive_validator (deterministic): references, numbers, metrics, entities, lifecycle, questions, safety, identity
                                   ▼   refused ─► one corrective re-ask (codes only) ─► failed: previous brief stays current
            executive_brief_versions (+ inputs, statement → result references)  ── optimistic concurrency ──  executive_brief_runs
```

## 1. Modules

| Module | Role |
|---|---|
| `contracts/executive-brief-v1.schema.json`, `executive_contracts` | The separate, versioned `ExecutiveBrief` contract: schema, semantic checks, typed frozen model, the model's output shape |
| `executive` | Canonical input and fingerprint, preserve policy, request, brief assembly, `ExecutiveSynthesizer` |
| `executive_validator` | The deterministic executive validator (`validate_brief`, `ExecutiveCode`) |
| `prompts/executive-v1.md` | The versioned synthesis prompt (SHA-256 pinned in `tests/test_reasoning_executive.py`); it states every validator rule. Its text was finalized during this review, before any brief was produced with it; any later change needs `executive-v2` |
| `store/executive`, migration `0500_executive_briefs.sql` | Canonical persistence: briefs, versions by run, inputs, statement references, run audit |
| `guardrails.statement_safety_violations` | Additive public wrapper: Phase 15's causality, people and certainty rules on one free-text statement |

`reasoning-result-v1` is not changed. Nothing outside these modules imports them (`IsolationTests.test_executive_core_is_ui_inert`), and
they import no upstream Atlas package, no input boundary, case mapping, Change Gate, fingerprint, memory / Honcho module, management API,
HTML fragment or HTTP library (`IsolationTests.test_no_raw_source_memory_or_http_dependency`).

## 2. The ExecutiveBrief contract (`executive-brief-v1`)

| Field | Rule |
|---|---|
| `brief_id` | `eb1_` + 32 hex; one per scope (`company`), kept across versions |
| `version`, `run_id` | Version ≥ 1 per accepted synthesis; the reasoning run it was synthesized for |
| `input_version`, `input_fingerprint` | `executive-input-v1`; `ei1_` + SHA-256 of the canonical input |
| `input_results` | `[{result_id, result_version, lifecycle_status}]` — exactly the canonical result versions the synthesis saw |
| `omitted_result_count` | Eligible results left out by the input bound (never citable) |
| `sections` | `what_changed`, `top_concerns`, `important_improvements`, `system_patterns`, `editor_context` (+ `editor_id`), `unresolved_questions`, `uncertainty`, `inspect_next`; each ≤ 12 statements |
| statement | `statement_id` (`<section>-<n>`, Python), `text` (≤ 1200 chars), `result_ids` (1–20 unique `rr1_…`) |
| `generator` | `model` (provider, model, request IDs) or `deterministic_empty` (none) |
| `prompt_version`, `validator_version`, `created_at` | Provenance |

Every object rejects unknown fields (so there is no place for hidden reasoning). Semantic checks: `STATEMENT_ID_MISMATCH`,
`DUPLICATE_INPUT_RESULT`, `REFERENCE_NOT_IN_INPUT` (a statement may reference only the brief's own `input_results`),
`EMPTY_BRIEF_MISMATCH`, `GENERATOR_MISMATCH`. The model writes only the sections (statements without IDs); Python adds everything else.

## 3. Input boundary

Selected by `ExecutiveTransaction.canonical_results(run_id)` from `reasoning_results` joined to their **current** version:

- lifecycle `new`, `active`, `updated`; or `resolved` by a lifecycle transition whose run is one of the `resolved_lookback_runs`
  (default 3) most recent runs up to `run_id` — so a resolution is reported for the run that resolved it and the next two;
- never `cooling` or `superseded`; never a refused Phase 15 candidate (it is not a result); nothing upstream.

`executive.executive_input` re-checks every row (eligible lifecycle; the document is the current version with the row's lifecycle;
no duplicate) and exposes per result only: `result_id`; `subject` (case type, subject type and ID, topic, identity dimensions,
orientation and affected Editors of the evidence state the version was reasoned on); `lifecycle_status`; `change` (the reason code of
the transition into the current status; for `updated` the fields of the latest accepted patch); `title`, `summary`, `observation`,
`interpretation`, `management_significance` (statements only — no evidence `ref_id`s); `confidence`; `limitations`; `open_questions`
(canonical Atlas questions still `open`); `suggested_investigations` (texts). No Monday item / event IDs, V2 finding IDs, evidence
references, snapshot IDs, model metadata, manager notes or memory.

Order: `new`, `updated`, `active`, `resolved`; then strong → weak confidence; then subject, topic, `result_id`. At most
`MAX_INPUT_RESULTS` (60) results; the rest are counted in `omitted_results`. Larger than `MAX_INPUT_CHARS` → `InputTooLarge`, never
truncated. Compact, key-sorted JSON: equivalent canonical state gives a byte-identical payload whatever order the database returns.

## 4. Fingerprint and preserve policy

`input_fingerprint = "ei1_" + sha256(canonical_json(payload))`. Result versions, timestamps, request IDs and generated prose never take
part: a `no_change_review` version (no visible change) does not change the fingerprint; a lifecycle change, a reworded card, a changed
confidence, an answered question, an added or removed result does.

`executive.decide(current, input)`:

| Condition | Decision | Model calls | Brief |
|---|---|---|---|
| current brief has the same fingerprint | `unchanged` | 0 | preserved exactly (no new version, no new wording); the run is recorded |
| no eligible result | `synthesized_empty` | 0 | new deterministic empty version |
| otherwise | `synthesized` (or `failed`) | ≥ 1 | new version only if the validator accepts |

Lifecycle settling (`new → active`, `updated → active`) is material by design: the input carries the lifecycle, and a brief that still
calls a settled result "new" or "updated" would be stale (Chat A review L2, disposition: intended).

A failed run leaves the current brief's fingerprint different from the input, so the next synthesis tries again; the Change Gate's
"same evidence → zero work" property carries through: same canonical reasoning → zero executive model work.

## 5. Provider

`ExecutiveSynthesizer` calls `gateway.ReasoningGateway.call` — no separate HTTP client — with purpose `executive`, prompt version
`executive-v1`, the run ID, strict structured output (`executive_contracts.model_output_schema`; the provider copy drops the keywords
outside the strict subset already proven live by the Phase 15 gate, i.e. `minLength`, `maxLength`, `uniqueItems`, `format`, `maxItems`;
the local validation enforces them), `max_output_tokens` 16 000, effort `medium`. Model identity, retries, backoff, concurrency,
no-redirect and secret redaction are the gateway's, unchanged; calls are recorded in `llm_calls` (`case_id` null). The gateway only
checks the answer's shape; grounding is the validator's. No new live gate: the request uses only already-proven schema keywords and the
already-proven pinned model path.

## 6. Validator (`executive_validator.validate_brief`)

Runs on the complete candidate (model sections + Python identity), separate from the prompt; an additional boundary after Phase 15,
which it does not change. Codes (`ExecutiveCode`, stable):

| Rule | Codes |
|---|---|
| Hidden reasoning | `RAW_REASONING_FIELD` (any reasoning-like key anywhere), `HIDDEN_REASONING_TEXT` |
| References | `MISSING_RESULT_REFERENCE`, `INVALID_REFERENCE`, `DUPLICATE_REFERENCE`; outside the input: `RESULT_NOT_IN_INPUT` (canonical, not supplied), `FAILED_CANDIDATE_REFERENCE` (a refused Phase 15 candidate's result or `fc_` ID), `RAW_SOURCE_REFERENCE` (V2 finding, `ev1_`, `rc1_`, `ef1_`, work item, run, request, question, Monday item number), `UNKNOWN_RESULT`. The same identifiers written **in statement text** (also truncated, ≥ 6 hex digits; any `rr1_` too) are refused: a statement names its sources only through `result_ids` |
| Numbers | `UNSUPPORTED_NUMBER`: every number (digits, number words, ordinals, multipliers such as "doubled" / "half" / "second") is written by one of the **cited** results' input texts **in the same written form** (`output_checks.written_numbers`): a count stays a count, a percentage a percentage, a date part a date, a duration a duration in the same unit (minutes … years), a difference ("by 5") a difference. 100 is not free. The only derived numbers: the count of cited results next to a result noun ("two results") and of cited Editors next to "Editor(s)" |
| Metrics | `UNSUPPORTED_METRIC`: score, index, rating, ranking, KPI, productivity, efficiency, percentile, grade, composite, utilization, ratio, throughput, velocity, turnaround, SLA, percentage, average, median, "<x> rate", and rankings / comparisons between subjects ("the slowest Editor", "the worst record", "of all editors", "the most late deliveries in the team", "of any other editor", "later than every other", "lags behind" …), unless the cited results use the term |
| Entities | `UNKNOWN_ENTITY`: an Editor ID (also written loosely — "editor label-7", "label 7" — or with Unicode hyphens) the cited results do not concern; a capitalized name the cited results do not use (mid-sentence, or possessive / followed by a person verb at the start); `EDITOR_MISMATCH` (`editor_context` citing a result not about its `editor_id`) |
| Lifecycle | `LIFECYCLE_CONTRADICTION`: a resolved result in `top_concerns`; only-resolved citations described as current / pressing / recurring / worsening, or not described as over; an open result described as over (one vocabulary both ways: resolved, stopped, ended, closed, fixed, gone, addressed, recovered, back on track, back to normal …); a resolved-only statement that turns against itself (a contrast followed by a present-state clause — "…, yet it is late again" — or "reopened", "is a risk", "again"); resolution words inside a "whether / if" clause are not claims; resolved and open results in one statement outside `system_patterns` / `uncertainty` (and there without state wording); `what_changed` citing no new / updated / resolved / reappeared result |
| Sections | `SECTION_MISMATCH`: `important_improvements` cites only favourable or resolved results; `top_concerns` never a favourable one |
| Questions | `QUESTION_AS_FACT` (an `unresolved_questions` statement that is not a question), `UNSUPPORTED_QUESTION` (not one of the cited results' open Atlas questions, compared case- and whitespace-insensitively) |
| Text | `INVALID_TEXT`: control characters (a NUL could not even be stored); `PROJECTION`: a forecast ("will continue", "next month", "may spread soon") no cited result makes (not in `inspect_next` or a "whether" clause, which say what to check) |
| Safety | `CAUSAL_OVERCLAIM`, `HR_JUDGMENT`, `UNSUPPORTED_BLAME`, `CONFIDENCE_EXCEEDED` (Phase 15 rules via `guardrails.statement_safety_violations`; plus high-confidence wording when no cited result is strong) |
| Identity | `IDENTITY_MISMATCH`, `PROVENANCE_MISMATCH`, `MODEL_SUBSTITUTED` (not retried), `CONTRACT_INVALID`, `DUPLICATE_STATEMENT` |

A refused answer is re-asked at most `ATLAS_REASONING_VALIDATION_RETRIES` times (default 1) with codes and paths only
(`correction_message`); then the run fails `validation:<codes>`.

## 7. Persistence (`0500_executive_briefs.sql`)

| Table | Key | Purpose |
|---|---|---|
| `executive_briefs` | `brief_id`, `scope` UNIQUE | Identity and `current_version` (deferred FK to its version); identity immutable; no delete |
| `executive_brief_versions` | (`brief_id`, `version`) | The full document per version, run, fingerprint, generator, model, prompt and validator versions; CHECKs tie JSON to columns; append-only |
| `executive_brief_inputs` | (`brief_id`, `version`, `result_id`) | Every canonical result version of the input (FK to `reasoning_result_versions`; a trigger requires its `lifecycle_status` to be that version's); append-only |
| `executive_statement_refs` | (`brief_id`, `version`, `statement_id`, `result_id`) | Statement → result references; FK to the version's **input** rows, so the database refuses a reference outside the input; append-only |
| `executive_brief_runs` | `synthesis_id` | One row per synthesis run: decision, policy version, fingerprint, the version current afterwards, model calls, failure, codes, violations, a refused candidate (debug only, ≤ 256 KiB), model, prompt, request IDs; append-only |

The input is read in one `REPEATABLE READ, READ ONLY` transaction (`ExecutiveStore.snapshot`), so result rows, lifecycle reasons,
patches and questions come from one committed state even while the engine runs.

`ExecutiveTransaction.append_brief(brief, expected_version=…)` re-validates the document, then inserts (first version; a second first
writer hits the `scope` UNIQUE) or moves `current_version` only `WHERE current_version = expected` — otherwise `VersionConflict` and the
whole transaction rolls back. A provider failure, invalid structured output, validator refusal, conflict or any other store error on commit
(`store:<error>`) never writes a version: the previous valid brief stays current, and the failure is recorded in `executive_brief_runs`
with every request ID of the run. If the refused candidate itself cannot be stored, the run is recorded without it
(`candidate_omitted`); NUL characters in a stored candidate are replaced by U+FFFD. Readers (`current_brief`, `brief_history`,
`get_brief`) read versions only; refused candidates are never returned as briefs. One synthesizer at a time: session advisory lock
`EXECUTIVE_LOCK_KEY` (a second one returns `skipped = executive_busy` and does nothing).

## 8. Interfaces

| Interface | Module |
|---|---|
| `ExecutiveBrief` (`from_dict`, `to_dict`, `referenced_result_ids`), `brief_errors`, `SECTIONS`, `ELIGIBLE_LIFECYCLE`, `model_output_schema` | `executive_contracts` |
| `ExecutiveSynthesizer.synthesize(run_id)` → `SynthesisOutcome`, `executive_input`, `CanonicalResult`, `InputPolicy`, `decide`, `Decision`, `EXECUTIVE_PROMPT_VERSION`, `EXECUTIVE_LOCK_KEY` | `executive` |
| `validate_brief`, `ExecutiveCode`, `ExpectedBrief`, `ReferenceIndex`, `VALIDATOR_VERSION` | `executive_validator` |
| `ExecutiveStore` (`transaction`, `current_brief`, `brief_history`, `synthesis_runs`), `ExecutiveTransaction` (`canonical_results`, `classify_references`, `append_brief`, `record_run`, `brief_inputs`, `statement_refs`, `get_brief`) | `store.executive` |

Typical wiring (no CLI or route is added in this pass; the core is callable internally):

```python
store = ReasoningStore(Database(settings.database_url()))
gateway = ReasoningGateway(OpenRouterTransport(router), settings.gateway_settings(), recorder=StoreCallRecorder(store), secrets=(router.api_key,))
report = ReasoningEngine(store, gateway, context=...).process_run(run_id)
outcome = ExecutiveSynthesizer(ExecutiveStore(store), gateway).synthesize(run_id)
```

## 9. Items deferred by the core, now delivered by the Phase 17 UI (§11)

| Item (REV/17 #10 and the Phase 17 assignment) | Status |
|---|---|
| Executive home / overview | DONE: the lead of `/reasoning/<locale>/` through Phase 16's `home_page(lead_html=)` |
| Executive statement → result-card links; drill-down into the Phase 16 evidence view | DONE: pinned to the synthesized result version |
| Card anchors / routes (owned by Phase 16) | Reused unchanged (`dashboard_routes`); the brief still persists result IDs only and no URL |
| EN / AR presentation, CSS | DONE (Phase 16 catalogs and stylesheet, additive) |
| Site / publication integration, Management API transport | Not part of the UI: the overview is served by the Reasoning V3 web app (Phase 16); the static site is unchanged; there is no executive write API |
| Card-linking acceptance test | DONE: `tests/test_reasoning_executive_ui.py` (`test_full_phase17_acceptance_brief_to_card_to_evidence`, `test_statement_links_are_the_deferred_card_links_made_real`) |

## 10. Known limitations

- Entity grounding uses only the cited results' own words: a display name the cited results never write is refused, but there is no
  roster of real names (that lives upstream, outside the boundary). A sentence-initial capitalized word is a name only when possessive
  or followed by a person verb.
- Residual phrase-level gaps found by the review and accepted as low: vague quantities ("most editors"), lowercase names, "Editor one".
- Direction words ("rose", "fell") are not checked against the numbers; differences must be written as the results write them.
- The fingerprint ignores prompt and validator versions on purpose (no regeneration for freshness): after a prompt upgrade the brief is
  rewritten at the next material input change.
- An input larger than `MAX_INPUT_CHARS` fails every run until it shrinks (no degraded brief).
- Lifecycle wording is checked with an English phrase policy (like Phase 15's); brief text is English.
- The resolved lookback counts runs, not time; with a long gap between runs a resolution stays visible for three runs.
- No production command runs the synthesizer yet; wiring it after `reason` (and resuming failed syntheses) belongs to the rollout /
  reliability phases.

## 11. The executive overview (Phase 17 UI, `REV/17` #10)

```
canonical ExecutiveBrief (PostgreSQL, current version)          read only: no synthesis, no model, no Honcho, no write
        │  ExecutiveTransaction.current_brief + executive_brief_runs (decision, failure class) + pinned titles
        ▼
executive_overview.ExecutiveOverviewService.overview()  ─►  Overview (sections, statements, cited results, provenance)
        │  cited result state now: Phase 16 DashboardService.result_states (current version, lifecycle, superseded_by)
        ▼
executive_html.overview_html  ─►  dashboard_html.home_page(..., lead_html=)  above <section id="reasoning-results">
```

| Module | Role |
|---|---|
| `store/executive_read` | Two bounded reads: the latest synthesis run of the scope (decision and failure *class* only) and the stored titles of the pinned result versions |
| `executive_overview` | `ExecutiveOverviewService` (state `brief` / `none` / `unavailable`), `Overview`, `StatementView`, `CitedResult` |
| `executive_html` | `overview_html` (the lead), `statement`, `cited_result` |
| `web_app` | `ReasoningWebApp(..., executive=ExecutiveOverviewService)`; `create_app` wires it; only the home page uses it |

- **Read only.** A GET renders the persisted current brief. The UI modules import only the core's read interfaces (`ExecutiveBrief`,
  `ExecutiveTransaction`, section constants) — never `ExecutiveSynthesizer`, the validator, the gateway, a provider or Honcho
  (`IsolationTests.test_only_the_read_only_executive_ui_uses_the_core`, `test_the_executive_ui_never_reaches_the_provider_memory_or_a_write`).
  Tests prove that home, card, evidence, history, Teach Atlas and read-API GETs make no provider or Honcho call and leave every table of
  the schema byte-identical. There is no executive write API.
- **Sections.** Every non-empty canonical section is rendered in contract order; an empty section is not rendered; a deterministic empty
  brief says it had no cards to summarize; no brief yet: "Executive brief not available yet." and the cards below as usual.
- **Links.** Each cited result links to the card **at the version the synthesis saw** (`card_path(locale, id, version=n)` from the
  brief's `input_results`) and to that version's evidence (`evidence_path(..., version=n)`); never to an Intelligence V2 finding or a Monday
  record (the lower audit chain is Phase 16's drill-down). A non-canonical ID never becomes a URL.
- **Moved on / resolved / replaced.** When the card has a newer version, the statement says so and links the current version; a resolved
  card is marked resolved; a superseded one links its replacement (`superseded_by`). The statement itself is shown exactly as stored.
- **Preserved and failed runs.** An `unchanged` run leaves the page identical. When the latest run failed while this brief stayed
  current, a notice says the last validated brief is shown — never the candidate, its codes or provider details. A run that only lost a
  version conflict is not counted (another writer produced the current brief). A stored brief that no longer satisfies its contract, or a
  database failure, makes the overview "unavailable" while the cards below still render. The overview reads in a `READ ONLY` transaction.
- **Resolved.** "Resolved since" only when the brief saw the card open; a card the brief already saw as resolved is just marked resolved.
- **Text.** Statements are model-written and untrusted: escaped, `dir="auto"`, shown as stored in both languages (only the interface wording
  is localized). Provenance: brief ID, version, run, generator, model, prompt and validator versions, creation time, input size.
- **No migration** and no change to any core module's behaviour.

Tests: `tests/test_reasoning_executive_ui.py`. Known limitations: the overview, the cards and the cited results' current states are read
in separate short transactions (a version committed in between shows on the next load); the isolation tests check direct imports (the
read-only store module transitively imports the synthesizer module, which is never constructed or called on a page).

