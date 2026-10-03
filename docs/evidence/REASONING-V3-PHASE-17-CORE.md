# Reasoning V3 Phase 17 core: executive intelligence synthesis (backend only) — review record

Design and interfaces: [`docs/REASONING-V3-EXECUTIVE.md`](../REASONING-V3-EXECUTIVE.md). Specification: [`REV/17`](../../REV/17-build-the-executive-intelligence-synthesis-layer.md).

**Completion state of this pass: `PHASE17_CORE_COMPLETE` (not `PHASE17_COMPLETE`).** The ExecutiveBrief UI / home integration is deferred
until after Phase 16 (§5).

## 1. Start

| Item | Value |
|---|---|
| Base SHA (POST_PHASE15_INTEGRATION_SHA) | `fd4b140742e99132c0624713875f42ad4a4d124c` (= `origin/integration` when work began; verified) |
| Branch / worktree | `reasoning-v3/phase17-executive-core`, `.worktrees/reasoning-v3-phase17-executive-core` (exclusive) |
| Parallel work | Phase 16 (dashboard) on its own branch; no shared file touched (§4) |
| Migration range | `0500–0599`; used `0500_executive_briefs.sql` only |
| `main` | untouched |

## 2. Requirement matrix

| # | Requirement | Implementation | Tests (`tests/test_reasoning_executive.py` = U, `tests/test_reasoning_executive_store.py` = DB) | Status |
|---|---|---|---|---|
| 1 | ExecutiveBrief schema | `contracts/executive-brief-v1.schema.json` (separate; `reasoning-result-v1` unchanged) | U `ContractTests` | PASS |
| 2 | Typed model / contracts | `executive_contracts.ExecutiveBrief` (`Contract` subclass), semantic checks | U `ContractTests` (round trip, unknown fields, raw reasoning field, missing result IDs, semantic rules, empty brief, separate contract) | PASS |
| 3 | Canonical result selection (active/new/updated/resolved only) | `ExecutiveTransaction.canonical_results` (current versions; resolved within lookback; snapshot read) + `executive_input` re-checks | U `InputTests.test_only_canonical_eligible_results_are_admitted`; DB `test_input_is_exactly_the_canonical_eligible_results_and_never_a_failed_candidate`, `test_cooling_is_excluded_and_resolved_appears_only_within_the_lookback`, `test_the_input_is_read_from_one_snapshot` | PASS |
| 4 | Synthesis input builder (bounded, deterministic, no internal noise) | `executive.executive_input` | U `test_input_carries_no_raw_source`, `test_order_and_serialization_are_deterministic`, `test_equivalent_question_order_and_editor_order_do_not_change_the_fingerprint`, `test_the_input_is_bounded`, `test_golden_fingerprint_of_the_standard_input` | PASS |
| 5 | Versioned prompt, pinned | `prompts/executive-v1.md`, SHA-256 pinned | U `PromptTests` | PASS |
| 6 | Structured provider call through the existing gateway | `executive_request` → `ReasoningGateway.call` (pinned model, retries, strict output, no redirect, redaction unchanged) | U `test_the_request_goes_through_the_gateway_contract`; DB `test_first_brief_is_persisted_with_its_inputs_and_references` (`llm_calls` row) | PASS |
| 7 | Deterministic validator | `executive_validator.validate_brief` | U `ReferenceTests`, `LifecycleTests`, `GroundingTests`, `IdentityTests`, `ReviewFindingTests` | PASS |
| 8 | Result-reference grounding (statement → canonical result IDs only) | validator + FKs `executive_statement_refs → executive_brief_inputs → reasoning_result_versions` | U `ReferenceTests`; DB `test_the_database_enforces_grounding_and_append_only_history` | PASS |
| 9 | Persistence / version history by run | `store/executive.py`, `0500_executive_briefs.sql` | DB `test_first_brief_…`, `test_material_reasoning_change_makes_new_synthesis_work_and_keeps_history` | PASS |
| 10 | Unchanged / preserve policy (zero model calls) | `executive.decide`, `ei1_` input fingerprint (no versions, timestamps, prose) | U `PolicyTests`, `test_a_no_change_review_version_does_not_change_the_fingerprint`; DB `test_identical_input_makes_zero_model_calls_and_preserves_the_brief`, `test_no_eligible_result_gives_a_deterministic_empty_brief_without_a_model` | PASS |
| 11 | Provider-failure preservation | `ExecutiveSynthesizer._failed`; optimistic concurrency | DB `test_provider_failure_…`, `test_invalid_structured_output_…`, `test_validator_rejection_…`, `test_a_substituted_model_…`, `test_a_concurrent_writer_wins_…`, `test_version_conflicts_at_the_store`, `test_a_store_failure_on_commit_…`, `test_a_candidate_the_database_cannot_store_…` | PASS |
| 12 | Migration: clean apply, repeat = 0, health, constraints | `0500_executive_briefs.sql`, `store.health.REQUIRED_TABLES` (additive) | DB `test_migration_is_clean_repeatable_and_healthy`; existing `test_reasoning_store.MigrationTests` | PASS |
| 13 | UI-inert; no raw-source / memory / HTTP dependency | import scan | U `IsolationTests` | PASS |
| — | Card linking | — | `DEFERRED_TO_PHASE17_UI_AFTER_PHASE16` (§5) | DEFERRED |

Required test list of the assignment (§19), all present: input (canonical only, failed candidate excluded, unsupported lifecycle excluded,
deterministic ordering, stable serialization); contract (valid, unknown field, raw reasoning field, missing result IDs); references
(missing, not supplied, multiple valid, raw detector); lifecycle (resolved as resolved, active/new/updated preserved, resolved never a
current concern by wording); grounding (invented metric, invented number, supported claim); stability (identical input → zero calls,
ordering → same fingerprint, material change → new work, preserve keeps wording/version); failure (provider, invalid structured output,
validator rejection); persistence (first, later, history, conflict).

## 3. Independent review

An independent reviewer (separate agent, adversarial probes against `validate_brief`) reviewed `fd4b140..93ab8b5`:

| # | Severity | Finding | Fix (commit `4613b68`) | Regression test |
|---|---|---|---|---|
| 1 | High | Lifecycle wording bypasses: open results called "stopped / ended / closed / fixed"; mixed resolved+open citations disabled both checks; resolved results described as "needs attention / keeps recurring / getting worse" | One resolution vocabulary both ways; broader current/pressing wording; no state statement mixing resolved and open results | `ReviewFindingTests.test_open_results_…`, `test_resolved_results_are_never_…`, `test_resolved_and_open_results_are_not_mixed_…` |
| 2 | High | Number grounding weaker than Phase 15: counts ↔ percentages, counts as durations, date parts as counts, free 100, multipliers/ordinal words, loose derived count | Per-form grounding (`output_checks.written_numbers`, additive): plain / percent / date / minute–year / difference; multipliers and ordinals; no free 100; derived counts only next to result / Editor nouns | `test_numbers_keep_their_written_form`, `test_date_parts_and_durations_stay_dates_and_durations` |
| 3 | Medium | Loose / Unicode-hyphen Editor IDs and display names not caught | Hyphen normalization, `label N` reading, boundary-aware lookup, capitalized-name check against the cited results' words | `test_editors_written_loosely_or_by_name_are_grounded` |
| 4 | Medium | A NUL in a statement passed the validator, then broke the commit and the failed-run audit | `INVALID_TEXT`; `_commit` records any store error (`store:<error>`); the audit retries without an unstorable candidate; NUL scrubbed in stored candidates | U `test_confidence_and_control_characters`; DB `test_a_candidate_the_database_cannot_store_…`, `test_a_store_failure_on_commit_…` |
| 5 | Medium | Questions not tied to the cited results' open questions | Text must equal one of them (case / whitespace-insensitive) | `test_questions_are_the_cited_results_open_questions` |
| 6 | Medium | No section / orientation rule | `SECTION_MISMATCH` (improvements favourable or resolved; concerns never favourable) | `test_sections_follow_orientation_and_lifecycle` |
| 7 | Medium-low | Input read with several READ COMMITTED queries | `ExecutiveStore.snapshot()` (REPEATABLE READ, READ ONLY) | DB `test_the_input_is_read_from_one_snapshot` |
| 8 | Low | "Atlas is confident" not caught; `"None"` orientation; only last request ID audited; prompt upgrade does not refresh; no DB tie of input lifecycle | Fixed the first three; the last two documented as deliberate / limitation (`REASONING-V3-EXECUTIVE.md` §10) | `test_confidence_and_control_characters` |

Checked and fine by the reviewer: no raw Monday / Intelligence V2 / evidence / Change Gate / Honcho / notes source; failed candidates never
selected; cooling and superseded excluded; resolved-lookback SQL; fingerprint free of volatile values; optimistic concurrency and the
first-brief race; refusals never replace the current brief; correction message carries codes and paths only; no Phase 16 file touched.

Re-verification of the fixes: see §6.

## 4. File ownership (no Phase 16 overlap)

New: `contracts/executive-brief-v1.schema.json`, `src/atlas_reasoning/executive.py`, `executive_contracts.py`, `executive_validator.py`,
`prompts/executive-v1.md`, `store/executive.py`, `store/migrations/0500_executive_briefs.sql`, `tests/reasoning_executive_support.py`,
`tests/test_reasoning_executive.py`, `tests/test_reasoning_executive_store.py`, `docs/REASONING-V3-EXECUTIVE.md`, this file.
Additive edits only: `store/health.py` (five table names), `guardrails.py` (`statement_safety_violations`, a public wrapper of the existing
Phase 15 rules; no rule changed), `output_checks.py` (`written_numbers`, a public view of the existing number forms; no rule changed).
Not touched: `atlas_commander/web/*`, `site_layout.py`, `profile_cli.py`, localization, `human_context_html.py`, `management_api.py`,
`__main__.py`, `settings.py`, `docs/REASONING-V3.md`, any route, CSS or JS.

## 5. Deferred to Phase 17 UI, after Phase 16

Executive home / overview, home-route change, statement → result-card links, drill-down into the Phase 16 evidence view, card anchors /
routes, executive UI, CSS / JS, navigation, EN / AR presentation, site / publication integration, Management API transport.
The card-linking acceptance test is **`DEFERRED_TO_PHASE17_UI_AFTER_PHASE16`**: it must be written against Phase 16's real published
result-card interface; no placeholder was invented. The brief persists canonical `result_id`s only (`executive_statement_refs`).

## 6. Verification

Independent review rounds: (1) `93ab8b5` → 6 reproduced findings (2 high), fixed in `4613b68`; (2) re-review of `4613b68` → remaining
lifecycle / ranking bypasses and false positives (valid sentences refused; prompt not stating the new rules), fixed in `6ea941f`;
(3) final check of `6ea941f` → no critical bypass; residual narrow bypasses and false positives, fixed in `f16cfc2`. All reviewer probes
(`scratchpad/review/probe1–7`) behave as expected at `f16cfc2`: every bypass refused, every expected-valid sentence accepted. Accepted
residuals (low): vague quantities ("most editors"), lowercase names, "Editor one" (`REASONING-V3-EXECUTIVE.md` §10).

Local verification at `f16cfc26add2745c97d16e4af5db508d2cf790c4` (PostgreSQL 17, `ATLAS_REASONING_REQUIRE_DB_TESTS=1`):

| Check | Result |
|---|---|
| `make test` (lint, typecheck, every suite incl. golden regressions, DB tests forced on) | PASS, 1 382 tests, exit 0; only the 3 Docker image tests skipped (need `ATLAS_RUN_DOCKER_TESTS=1`) |
| `make reasoning` (Reasoning V3 suite incl. Phase 15 guardrail regressions) | PASS, 457 tests (380 before this branch + 77 new) |
| Phase 17 core: `tests/test_reasoning_executive.py`, `tests/test_reasoning_executive_store.py` | PASS, 57 + 20 |
| Migration: clean apply, repeat = 0, `db-health` ok | PASS (`test_migration_is_clean_repeatable_and_healthy`, `test_reasoning_store.MigrationTests`) |
| ruff, mypy (152 source files) | PASS |
| Dashboard unchanged / UI-inert | PASS (`IsolationTests`; all dashboard, UI, i18n and redesign suites green) |
| Live provider gate | Not required: the request uses only strict-schema keywords and the pinned model path already verified live by Phase 15 (`maxItems` is not sent) |

Exact-head CI at `68d10d2`: Atlas CI run `37027352456`, `verify` SUCCESS (DB tests required; 457 reasoning tests).

## 7. Chat A cross-review of PR #38 (review `5394453752` on `68d10d2`)

| # | Finding | Disposition | Change | Regression test |
|---|---|---|---|---|
| M1 (required) | Raw source identifiers inside statement **text** were accepted (V2 finding IDs, `ev1_`, `rc1_`, `ef1_`, `wi_`, `run_`, `req_`, `fc_`, uncited `rr1_`) | FIXED | `executive_validator._identifiers_in_text`: unanchored scan of every statement text, also truncated IDs (≥ 6 hex); `fc_` → `FAILED_CANDIDATE_REFERENCE`, everything else (any `rr1_` included) → `RAW_SOURCE_REFERENCE`; retryable; correction message says so | U `ChatAReviewTests.test_source_identifiers_in_statement_text_are_refused`, `test_identifier_like_words_are_not_ids`; DB `test_an_identifier_in_statement_text_is_refused_and_preserves_the_brief` (refused, previous brief current, nothing committed, audit recorded) |
| L1 | Ranking within the team ("the most late deliveries in the team", "of any other editor") accepted | FIXED | two ranking patterns in `_METRIC_TERMS` | U `test_rankings_within_the_team_are_unsupported_metrics` |
| L2 | Lifecycle settling (`new → active`, `updated → active`) triggers a synthesis | KEPT, documented as intended | none (docs §4): the input carries the lifecycle; a brief still calling a settled card "new" / "updated" would be stale | U `test_lifecycle_settling_is_material_by_design` (also `test_material_reasoning_changes_change_the_fingerprint`; DB `test_material_reasoning_change_…`) |
| L3 | `executive_brief_inputs.lifecycle_status` not tied in the database to the result version's lifecycle | FIXED | trigger `executive_brief_inputs_lifecycle` in `0500_executive_briefs.sql` (amended: the migration is unreleased, never applied outside disposable test databases) | DB `test_the_database_enforces_grounding_and_append_only_history` (mismatched lifecycle refused) |
| Info | Statement text may contain markup / URLs; any presentation must escape it | Noted for Phase 17 UI | none in core | — |

Own delta review: the identifier checks on `result_ids` now use `fullmatch` (a `$`-anchored pattern also accepts a trailing newline; such a
reference was already refused as not in the input, so this is hygiene) — `test_reference_ids_with_a_trailing_newline_are_refused`.
The prompt `executive-v1` is unchanged (it already forbids citing any identifier other than `result_ids`).

Exact-head CI of the fix head: recorded on the Draft PR.

## 8. Reconciliation with Phase 16 (POST_PHASE16_INTEGRATION_SHA)

| Item | Value |
|---|---|
| Pre-reconciliation Phase 17 head | `82504f8308d914d78e72f92198c26c0d717b11cc` |
| Merged | `origin/integration` = `3931b21554427316dbd09bcb04e58994ae57cc99` (merge of PR #37; its tree is identical to the reviewed Phase 16 head `a7d9cff`) |
| Reconciliation merge commit | `c10de79a7d293cdbe0416a76c1b16229382be98e`, parents `82504f8` + `3931b21`, `--no-ff`, no rebase / squash / force-push |
| Textual conflicts | **None**. The two changes share no file: `diff(3931b21, merge)` is byte-identical to the reviewed Phase 17 delta `diff(fd4b140, 82504f8)`, and `diff(82504f8, merge)` to the Phase 16 delta `diff(fd4b140, 3931b21)` — nothing reverted, nothing altered |
| Semantic compatibility fixes | None needed. Added guard tests only: `Phase16CompatibilityTests` (the brief's `result_id` pattern is Phase 16's `dashboard_routes.RESULT_ID`; every referenced ID passes `parse_result_id`; input versions are positive integers for `card_path(..., version=n)`; the brief stores no `/reasoning/`, `#result-`, `#ev-` or URL) and DB `test_persisted_references_resolve_to_phase16_canonical_cards` (every persisted statement reference and input row is a canonical result version Phase 16 can open) |
| Migrations (fresh schema, CLI) | Run 1 applied 9: `0001, 0100, 0101, 0200, 0201, 0202, 0203, 0300, 0500` (no `0400`); run 2 applied 0; `db-health` ok (no pending, problems or missing tables); recorded `0500` checksum = file SHA-256 `c26573c0…259f`; 5 executive tables present |

Compatibility review of the merged tree:

- **Identity.** Statements persist canonical `rr1_` result IDs only, and every input row carries its `result_version`. This is exactly what
  Phase 16's handoff (`docs/REASONING-V3-DASHBOARD.md` §8.5: `result_links`, `result_states`, `card_path(..., version=n)`) consumes. A
  later UI can map them without any change to brief persistence. No URL or anchor is derived or stored in the core.
- **Guardrails.** Phase 16 changed neither `guardrails.py` nor `output_checks.py`; Phase 17's additions there are unchanged and the Phase 15
  suite passes on the merged tree.
- **UI-inert.** Nothing in the merged `src/` (Phase 16 dashboard, routes, read API, web app, ManagementAPI included) imports the executive
  core (`IsolationTests.test_executive_core_is_ui_inert`); `home_page(lead_html=)` and the Phase 16 routes are untouched.
- **Reasoning V3 off.** The executive core adds no import-time requirement (psycopg is loaded only when a database is opened) and nothing
  runs it; the flag-off byte-identity tests and Phase 16's refusal to start with the flag off are unchanged.
- **Deferred.** Phase 17 UI remains unimplemented: `PHASE17_CORE_COMPLETE`, not `PHASE17_COMPLETE`.
