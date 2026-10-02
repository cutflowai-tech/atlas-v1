# Reasoning V3 engine (Phases 07–09): review record

Branch `reasoning-v3/engine`, built on exactly `3c73823428b7a1960546d61a5e61fb23a21991aa` (the merged foundation on `integration`).
Architecture: [`docs/REASONING-V3.md`](../REASONING-V3.md) §10–13. Phase 17 is not part of this branch.

## 1. Requirement matrix

PASS = implemented and covered by the named test (`A` = `tests/test_reasoning_analyst.py`, `U` = `test_reasoning_update.py`,
`L` = `test_reasoning_lifecycle.py`). There is no FAIL.

| Phase | Requirement | Implementation | Test | Status |
|---|---|---|---|---|
| 07 | 1 Versioned analyst prompt | `prompts/analyst-v1.md`, `ANALYST_PROMPT_VERSION` | A `test_prompt_is_versioned_and_pinned` (SHA-256 pin) | PASS |
| 07 | 2 Only bounded evidence, findings, context, provenance | `analyst_input` / `case_evidence_input`, `MAX_INPUT_CHARS`, `CaseTooLarge` | A `test_request_carries_prompt_and_case_provenance`, `test_volatile_values_never_reach_the_prompt`, `test_oversized_case_is_refused_not_truncated` | PASS |
| 07 | 3 No invented numbers, people, projects, events, metrics | prompt rules; `output_checks` (`UNSUPPORTED_NUMBER`); `result_case_errors` (`UNKNOWN_EVIDENCE_REF`) | A `test_invented_numbers_are_refused_and_case_numbers_accepted`, `test_number_tokens_inside_identifiers_and_dates_are_not_numbers`, `test_evidence_references_are_preserved_exactly` | PASS (numbers and evidence enforced; names: prompt only, see §3) |
| 07 | 4 Observation / interpretation / alternative / limitation / hypothesis separated | output fields; `requires_context` | A `test_valid_output_becomes_a_version_one_result_with_python_owned_identity` | PASS |
| 07 | 5 Explicit counter-evidence | `COUNTER_EVIDENCE_MISSING` | A `test_counter_evidence_and_confidence_ceiling_are_enforced` | PASS |
| 07 | 6 Management questions | `questions_for_management` | A (valid output) | PASS |
| 07 | 7 No HR / personality / salary / termination / blame | prompt rule 7 | A `test_prompt_is_versioned_and_pinned` (rule present) | PASS (prompt-level; deterministic content guardrails are Phase 15) |
| 07 | 8 Strict structured ReasoningResult output | `analyst_output_schema` (strict, `provider_schema`), full contract validation | A `test_missing_and_malformed_fields_fail`, `test_schema_sent_to_the_provider_is_strict_mode_compatible` | PASS |
| 07 | 9 Deterministic serialization | canonical ordering, compact sorted JSON, no volatile IDs | A `test_equivalent_cases_serialize_identically` | PASS |
| 07 | 10 Prompt version and model metadata stored | `prompt_version`, `model_metadata`; `llm_calls` | A `test_every_new_case_gets_one_evidence_linked_result` | PASS |
| 07 | 11 Explicit summary, no hidden chain-of-thought | no field for it; unknown fields refused | A `test_hidden_reasoning_fields_are_refused` | PASS |
| 07 | Owner: immutable case ID, Python-owned identity | Python sets IDs | A `test_the_model_cannot_set_or_change_the_case_or_result_identity` | PASS |
| 07 | Owner: malformed output; provider failure isolation; pinned model | engine | A `test_malformed_and_invalid_output_fails_the_item_and_stores_nothing`, `test_provider_failure_is_isolated_to_its_case`, `test_a_substituted_model_is_refused` | PASS |
| 08 | 1 Separate versioned update prompt | `prompts/update-v1.md` | U `test_update_prompt_is_separate_versioned_and_complete` | PASS |
| 08 | 2 Input: previous result, delta, current evidence, both fingerprints | `update_input` | U `test_update_prompt_is_separate_versioned_and_complete` | PASS |
| 08 | 3 ReasoningUpdate output | `build_update`, `ReasoningUpdate.from_dict` | U `test_identity_and_history_fields_are_protected` | PASS |
| 08 | 4 Changed fields, preserved fields, rationale | update output schema; `FIELD_ACCOUNTING` | U `test_field_accounting_and_values_must_agree` | PASS |
| 08 | 5 Merge in Python | `patch.merge` | U `test_untouched_fields_keep_their_exact_wording` | PASS |
| 08 | 6 Immutable fields protected | merge + `IMMUTABLE_FIELD` + store `version_change_errors` | U `test_the_model_cannot_patch_immutable_or_unknown_paths`, `test_merge_refuses_a_stale_or_foreign_update` | PASS |
| 08 | 7 New version per accepted patch | `append_version_with_diff` | U `test_changed_evidence_patches_the_same_result_as_a_new_version` | PASS |
| 08 | 8 No-op preserves the result and records a review | `no_change_review` | U `test_no_change_review_preserves_every_field_byte_for_byte`, `test_no_change_review_keeps_the_card_and_records_the_review` | PASS |
| 08 | 9 Exact previous wording for untouched fields | copy, never re-serialize | U `test_untouched_fields_keep_their_exact_wording` | PASS |
| 08 | 10 Before/after diffs persisted | `reasoning_result_diffs` (0100) | U `test_changed_evidence_patches_the_same_result_as_a_new_version` | PASS |
| 08 | Tests: invalid path, rollback, version increment, field isolation | — | U `test_the_model_cannot_patch_immutable_or_unknown_paths`, `test_failed_patch_rolls_back_completely`, `test_a_concurrent_writer_wins_and_the_stale_patch_is_dropped`, `test_a_listed_change_must_really_change_the_field` | PASS |
| 08 | Owner: stability (same → nothing, changed → patch, new topic → new result, no duplicates) | gate + engine | U `test_same_evidence_changed_evidence_and_a_new_topic` | PASS |
| 09 | 1 Six states | `LifecycleStatus` (foundation) | L `test_every_pair_outside_the_table_is_refused` | PASS |
| 09 | 2 Explicit transition table | `lifecycle.TRANSITIONS` = DB CHECK (0101) | L `test_every_pair_outside_the_table_is_refused`, `test_database_check_is_the_same_table`, `test_the_database_refuses_transitions_outside_the_table` | PASS |
| 09 | 3 new → active | sweep `observed_again` | L `test_new_becomes_active_on_the_next_run` | PASS |
| 09 | 4 updated → active | `patch_accepted`, `update_settled` | L `test_updated_card_settles_back_to_active` | PASS |
| 09 | 5 Disappeared → cooling, not deleted | `not_in_snapshot` | L `test_disappeared_case_cools_persists_and_resolves` | PASS |
| 09 | 6 Resolution only after configured persistence | `cooling_runs_to_resolve` | L `test_disappeared_case_cools_persists_and_resolves`, `test_disappearance_cools_then_resolves_after_the_configured_runs`, `test_sweeping_after_skipped_runs_is_still_idempotent` | PASS |
| 09 | 7 Immediate resolution only for approved direct facts | `direct_fact_case_types` (none by default) | L `test_direct_facts_resolve_at_once_only_when_approved`, `test_direct_fact_case_resolves_immediately_when_approved` | PASS |
| 09 | 8 Superseded references its replacement | `supersede`, `superseded_by`, CHECKs | L `test_supersede_names_the_replacement` | PASS |
| 09 | 9 Transition reason and run ID persisted | `reasoning_lifecycle_transitions` | L `test_new_becomes_active_on_the_next_run`, `test_disappeared_case_cools_persists_and_resolves` | PASS |
| 09 | 10 LLM has no lifecycle authority | no lifecycle in either output schema | L `test_the_model_has_no_lifecycle_authority` | PASS |
| 09 | Reappearance reactivates the same case | `reappeared`, `reappeared_after_resolution` | L `test_reappearance_reactivates_the_same_card_without_reasoning`, `test_resolved_case_that_returns_reopens_its_card`, `test_resolved_case_that_returns_with_new_evidence_is_patched_not_regenerated` | PASS |
| 09 | Debug output; cooling config | CLI `lifecycle`; `policy_from_env` | L `test_lifecycle_debug_command`, `test_policy_configuration` | PASS |

## 2. Independent review and fixes

An independent review of the three phase commits reported ten findings. All were fixed in a follow-up commit, each with a
regression test:

| # | Finding | Fix | Test |
|---|---|---|---|
| 1 | A "patch" that changed nothing passed validation, then failed the diff CHECK after a paid call | `UNCHANGED_PATCH_VALUE` (retried inside the gateway); status taken from the validated update | U `test_a_listed_change_must_really_change_the_field` |
| 2 | Items could stay `in_progress` forever (interrupted batch, killed worker) and block their case | unfinished claims are failed in `finally` (`work:INTERRUPTED`); `process_run` fails claims older than one hour (`work:STALE_CLAIM`) | U `test_claimed_items_are_never_left_in_progress`, `test_an_abandoned_claim_is_recovered` |
| 3 | Stale work could reopen a resolved card of a case that had disappeared again | reopen only when the case is present; otherwise the item is closed and the card stays resolved | L `test_stale_work_never_reopens_a_resolved_card_of_an_absent_case` |
| 4 | Sweeping an older run could move cards backwards | a run's observation applies only while it is the case's latest | L `test_an_older_run_never_moves_a_card_backwards` |
| 5 | After skipped runs, a second sweep could cool and then resolve in one run | never cool and resolve in the same run | L `test_sweeping_after_skipped_runs_is_still_idempotent`, `test_a_card_never_cools_and_resolves_in_the_same_run` |
| 6 | Direct-fact resolution was on by default (contradicting "normally cooling") | no case type approved by default; operators list them | L `test_direct_facts_resolve_at_once_only_when_approved`, `test_policy_configuration` |
| 7 | Number guard rejected case dates ("since 15 September") and missed range ends | date parts of case timestamps allowed; the number after a hyphen following a digit counts | A `test_number_tokens_inside_identifiers_and_dates_are_not_numbers` |
| 8 | Schemas sent in strict mode used keywords outside OpenAI's strict subset | `provider_schema` drops them and types every enum; full contract still validated locally | A `test_schema_sent_to_the_provider_is_strict_mode_compatible` |
| 9 | Output budget 6 000 tokens likely too small with reasoning tokens | 16 000 | — (configuration) |
| 10 | Lifecycle rows cited the LLM work item; minor robustness | only the gate's lifecycle item is cited | covered by L tests |

## 3. Decisions and known limits

- **Model output shape.** The model writes only the result's patchable content (analyst) or a patch description (update); Python
  owns every identifier, version, fingerprint, provenance field and lifecycle status, and validates the assembled `ReasoningResult`
  / `ReasoningUpdate` against reasoning-v1.
- **No-op review.** Recorded as a `no_change_review` version whose content is byte-identical and whose provenance moves to the
  reviewed evidence (otherwise the foundation's `unreasoned_cases` would report the case and later deltas would restart from stale
  evidence). The previous version is never touched.
- **new → active** happens on the next run in which the case is present, so `new` (and `updated`) are visible for one run.
- **Resolved cases** that reappear reopen their own card; the gate's `new_result` item for them becomes a patch, never a second card.
  Supersession retires a result for good; if the superseded case is still observed later, it gets a new result (one open card per
  case remains guaranteed by the database).
- **Not enforced deterministically here** (prompt-level; Phase 15 guardrails): people's and projects' names, numbers written as
  words, HR/personality wording. The number guard treats any case value × 100 as a percentage.
- **Live provider not exercised.** CI uses offline fakes only. The first live call (rollout) should confirm the strict schema is
  accepted and that OpenRouter reports the model slug unchanged (`MODEL_SUBSTITUTED` otherwise).
- **Resume of failed items** (`unreasoned_cases`) is Phase 18.

## 4. Foundation changes

- `store/repository.py`: additive methods only (`append_version_with_diff`, `record_result_diff`, `result_diffs`,
  `record_lifecycle_transition`, `lifecycle_transitions`, `latest_result`, `version_run_id`, `stale_in_progress_work`, and their
  `ReasoningStore` readers). No existing signature or behaviour changed.
- `__main__.py`: new commands `reason` and `lifecycle`.
- `tests/test_reasoning_store.py`: two assertions assumed exactly one migration file; they now compare with
  `available_migrations()` (needed by any branch that adds a migration).

## 5. Results

| Check | Result |
|---|---|
| `make test` (PostgreSQL 17 test database, `ATLAS_REASONING_REQUIRE_DB_TESTS=1`) | **1134 tests, 0 failures, 3 skipped** (the Docker runtime tests, as in the foundation baseline) |
| of which Reasoning V3 (`make reasoning`) | 209 tests (146 foundation + 63 new), 0 failures, 0 skipped |
| `ruff check src tests` / `mypy src` | clean / clean (130 files) |
| Golden sites 1.3, 1.4, 1.5 (flag unset / off / on) | byte-identical (`test_reasoning_boundary.py`) |
| Live provider calls in tests | none (offline fakes only) |
