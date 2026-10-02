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
