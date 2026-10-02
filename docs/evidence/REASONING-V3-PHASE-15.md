# Reasoning V3 Phase 15: validation and safety guardrails — review record

Policy and boundaries: [`docs/REASONING-V3-GUARDRAILS.md`](../REASONING-V3-GUARDRAILS.md). Architecture: [`docs/REASONING-V3.md`](../REASONING-V3.md) §17.

## 1. Start

| Item | Value |
|---|---|
| Starting SHA (FINAL_INTEGRATION_GATE_SHA) | `e058fc4c097e553dae52a0772df042d1ccc29c77` (= `origin/integration` when work began) |
| Branch | `reasoning-v3/validation-guardrails` (isolated worktree) |
| `main` | `61d7a471d2bb3b0098ee2c0f0c2c47b50a24c35b`, untouched |
| Credentials | Neither OpenRouter nor Honcho credentials are configured (no `OPENROUTER_API_KEY[_FILE]`, no `HONCHO_API_KEY[_FILE]`, no `/run/secrets/*`) |

## 2. Requirement matrix (REV/15 and the Phase 15 assignment)

| # | Requirement | Implementation | Test (`tests/test_reasoning_guardrails.py` unless named) | Status |
|---|---|---|---|---|
| 15.1 | Validate case/result identity | `guardrails._identity`: case, result, version, snapshot, fingerprint (expected from the work item), previous version, `created_at`, lifecycle, supersession, `previous_result_*`, prompt version, request ID, model | `IdentityTests` (wrong case ID, result ID, fingerprint, snapshot, version, previous result, provenance, model) | PASS |
| 15.2 | Validate all evidence references exist | `_evidence`: every cited `ref_id` in the case | `EvidenceTests.test_fabricated_evidence_reference`, `test_reference_from_another_case` | PASS |
| 15.2a | Supporting / counter roles preserved | `WRONG_EVIDENCE_ROLE`, `COUNTER_EVIDENCE_MISSING` | `test_supporting_and_counter_evidence_roles_cannot_be_inverted` | PASS |
| 15.3 | Numeric grounding | `output_checks.number_supported` (written-form aware: exact whole numbers, percentages only with %/percent/points, durations only with a unit, date parts only in written dates, number words incl. hyphenated, ordinals/suffixes); one numeric system shared with the updater | `NumberTests`, `ReviewFindingTests` (number rows), `test_reasoning_analyst` number tests | PASS |
| 15.4 | Person / project references belong to the case | `_entities`: Editor IDs, item / project numbers, Unicode proper names; context names only when attributed | `EntityTests` (fabricated project, fabricated person, valid known person/entities, context names) | PASS |
| 15.5 | Reject unsupported metric names | `_metrics`: explicit Atlas vocabulary + blocked metric nouns + "<x> rate / percentage / ratio" allowlist | `MetricTests` | PASS |
| 15.6 | Causal language vs association | `_causality`: documented phrase policy, scoped hedge / negation, factual fields never causal | `CausalityTests`, `ReviewFindingTests` | PASS |
| 15.7 | No blame / personality / psychological / salary / termination / HR language | `_people`: HR lexicon (incl. health and private life), blame patterns with case names | `PeopleTests` (personality, motivation, termination, blame, valid observable statements), `ReviewFindingTests` | PASS |
| 15.8 | Confidence never above the contract | ceiling, contradicted ≠ strong, certainty / high-confidence wording | `ConfidenceTests` | PASS |
| 15.9 | Teachings stay attributed | `_attribution`: management sources, distinctive-word overlap, named source; never in factual fields | `AttributionTests` (teaching as fact, answer as fact, attributed accepted), `test_a_short_management_statement_cannot_become_a_fact` | PASS |
| 15.10 | Supporting deterministic evidence for every visible conclusion | `NO_SUPPORTING_EVIDENCE` for observation, interpretation, management significance, each supporting item, context-free explanations | `test_every_visible_conclusion_needs_supporting_evidence` | PASS |
| 15.11 | Deterministic validation before canonical merge (both paths) | `engine._complete`: new = assembled v1, update = merged next version; commit only after acceptance | `PipelineTests.test_valid_end_to_end_result_passes_and_commits`, `test_invalid_new_result_is_not_committed_and_nothing_follows`, `test_invalid_update_never_replaces_the_previous_version` | PASS |
| 15.12 | Optional second reviewer, never the sole validator | `reviewer.LLMReviewer` (off by default; high-impact only; after the deterministic gate; can only refuse; fails safe; audited) | `ReviewerPolicyTests`, `test_reviewer_off_by_default_and_never_overrides_the_validator`, `test_reviewer_rejection_and_failure_fail_safe` | PASS |
| 15.13 | Failed candidates never replace the last valid result | refusal → no commit, no lifecycle, no question, no memory | `test_invalid_update_never_replaces_the_previous_version`, `test_malicious_note_cannot_change_the_committed_result` | PASS |
| 15.14 | Persist failed candidates and errors | `reasoning_failed_candidates` (0300), `record_failed_candidate` | `test_invalid_new_result_is_not_committed_and_nothing_follows` (codes, validator, model, prompt, request, candidate) | PASS |
| A.14 | Prompt-injection resistance (notes, answers, teachings) | context outside the fingerprint; guardrails on the output; correction messages carry codes only | `PromptInjectionTests`, `test_malicious_note_cannot_change_the_committed_result`, `test_malicious_teaching_cannot_reach_the_canonical_result`, `test_correction_message_carries_codes_and_paths_only` | PASS |
| A.19 | Stable error taxonomy | `ValidationCode` (documented, test-pinned) | `test_codes_are_stable_and_documented` | PASS |
| A.21 | Bounded retry with explicit codes | `ATLAS_REASONING_VALIDATION_RETRIES` (0–2, default 1); non-retryable identity / model / reviewer codes | `test_a_refused_candidate_is_retried_once_with_its_codes_and_can_succeed`, `test_retries_are_bounded_and_unrelated_cases_continue`, `test_a_substituted_model_is_not_retried` | PASS |
| A.23 | Inside the real connected pipeline; no follow-ups after refusal | gate → context → fake model → guardrails → commit or refusal → questions / memory only after acceptance | `PipelineTests`, `tests/test_reasoning_integration.py` | PASS |
| A.18 | Migration only in 0300–0399 | `0300_failed_candidates.sql` (one table) | migration tests (complete set once) | PASS |
| A.25 | OpenRouter live gate | — | — | **BLOCKED: credential not configured** |
| A.26 | Honcho live gate | — | — | **BLOCKED: credential not configured** |

## 3. Independent review of the diff

No bypass found: every model answer reaches the store only through `_persist_new` / `_persist_update` after `validate_candidate`
accepts the complete candidate; lifecycle versions only copy previous content; follow-ups run only for committed outcomes; the retry
loop terminates; correction messages carry codes and paths only; the migration and the reviewer behave as specified.

| # | Severity | Finding | Resolution |
|---|---|---|---|
| R1 | high | Short management statements (≤1 distinctive word) could be laundered into fact; generic verbs counted as attribution; no health terms | Fixed: thresholds 1/2/3 by item size; attribution must name management; health / private-life terms are HR judgements (tests) |
| R2 | high | One negation anywhere in a sentence disabled causal, blame, certainty (and HR-in-limitations) rules | Fixed: negation counts only when it governs the phrase (four words before, same clause) (tests) |
| R3 | high | HR / blame lexicon gaps (disengaged, commitment, team player, let go, removing from project, performer, underperform, struggling, "his fault") | Fixed (tests) |
| R4 | high | Causal misses (explains, driving, produced, made … late, hurt) and false refusals (team lead, results in the window, due to a client, leads to the interpretation); hedge anywhere in sentence | Fixed: phrase list extended, non-causal uses excluded, hedge must precede in the same clause (tests) |
| R5 | medium-high | Numbers too permissive: ±0.5 on every value, rate ×100 as counts, hyphenated words, "may" as a month, ordinals / suffixes, units ignored | Fixed: written-form aware grounding (tests) |
| R6 | medium | Metric rule a blocklist; "ratio", "<x> percentage" passed | Fixed: ratio blocked, rate / percentage / ratio allowlist; explicit Atlas vocabulary documented (tests) |
| R7 | medium | Name checks skipped Title Case titles, non-ASCII names, sentence-initial entities | Fixed: runs of unknown capitalized words in titles, Unicode names, sentence-initial entity nouns (tests) |
| R8 | medium | HR false positive on the case's own limitation ("elapsed clock time is not effort"), "character animation", "newly hired" | Fixed: negated HR terms allowed in confidence rationale too; "character" / hiring narrowed (tests) |
| R9 | medium | Certainty wording gaps (clear, evident, confirms, strong pattern) | Fixed (tests) |
| R10 | medium | Reviewer saw human context but its call was not audited | Fixed: `memory_injections` row (purpose `review`) before the call (pipeline test) |
| R11 | medium | Update can be refused forever on legacy text; patch violation paths named the code, not the field | Path fixed (test); legacy policy documented (an update must correct the field) |
| R12 | low | Identity expectations taken from the answer / case | Fixed: fingerprint from the work item, request ID from the request; new results must have no previous result |
| R13 | low | Reviewer errors outside provider/value errors not mapped to `REVIEWER_FAILED` | Fixed: any reviewer exception fails safe as `REVIEWER_FAILED` |
| R14 | low | A resolved card reactivated at claim time stays active after a refusal | Documented: the case's own deterministic state change, predates Phase 15 |
| nits | — | `candidate` / `candidate_omitted` CHECK; legacy public validators; regex compilation | CHECK added; `analyst_output_errors` / `update_output_errors` / `result_from_response` / `apply_response` kept for tests and documented as not the engine path |

Kept as opinions: prompts were not re-versioned for the new lexicons (the v2 prompts already state the same rules; refusal rates are
for Phase 19 to measure); "failed to deliver" is treated as blame.

## 4. Live compatibility gates

| Gate | Result |
|---|---|
| OpenRouter (`python -m atlas_reasoning provider-health`, pinned `openai/gpt-5.6-sol`) | **BLOCKED: credential not configured** (`OPENROUTER_API_KEY` / `OPENROUTER_API_KEY_FILE` absent; `/run/secrets/openrouter_api_key` absent) |
| Honcho (`memory-health`, synthetic `waset-atlas-test` smoke test) | **BLOCKED: credential not configured** (`HONCHO_API_KEY` / `HONCHO_API_KEY_FILE` absent; `/run/secrets/honcho_api_key` absent) |

Per the merge gate, the Phase 15 PR stays a draft and is not merged until both gates pass.
