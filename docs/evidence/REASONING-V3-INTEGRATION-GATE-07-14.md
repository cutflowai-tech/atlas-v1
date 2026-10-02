# Reasoning V3 integration gate: Phases 07–14

Independent review, merge, reconciliation, wiring and validation of the two parallel Reasoning V3 branches as one system. Not a
product phase; **Phase 15 has not started**. Architecture: [`docs/REASONING-V3.md`](../REASONING-V3.md) §14–16; memory layer:
[`docs/REASONING-V3-MEMORY.md`](../REASONING-V3-MEMORY.md).

## 1. Starting state (verified on GitHub before any merge)

| Item | Value |
|---|---|
| Common base (`integration`) | `3c73823428b7a1960546d61a5e61fb23a21991aa` |
| PR #34 `reasoning-v3/engine` (Phases 07–09) | open, head `0149d0c03d135d813fc1630a5a339b19239d12b2`, CI `verify` success, mergeable (clean) |
| PR #33 `reasoning-v3/memory-ui` (Phases 10–14) | open, head `a7ba543090ed0c0c31e568fc39ab89302949e0dc`, CI `verify` success, mergeable (clean) |
| `main` | `61d7a471d2bb3b0098ee2c0f0c2c47b50a24c35b`, untouched by Reasoning V3 |

## 2. Merge sequence

1. PR #34 merged (merge commit, tied to head `0149d0c`): `ENGINE_INTEGRATION_SHA = ed3d0af6bb301ab09071e0381eb52141afad2a53`; its tree equals
   the reviewed head.
2. `origin/integration` merged into `reasoning-v3/memory-ui` (merge commit `6f57932`, no history rewrite, no force-push). Overlaps:
   - `tests/test_reasoning_store.py` (textual conflict): migration tests now expect the complete migration set, each file exactly once,
     applied by one bootstrap;
   - `src/atlas_reasoning/__main__.py` (auto-merged, checked): `reason` and `lifecycle` (engine) and `memory-health` and `memory-sync`
     (memory) all present;
   - `docs/REASONING-V3.md` (auto-merged, checked): both subsystems described;
   - semantic: `store/health.py` now requires every table of both branches (`reasoning_result_diffs`, `reasoning_lifecycle_transitions`,
     `memory_injections`, `atlas_question_asks`, `engineering_review_flags`).
3. PR #33 review fixes committed on the branch (`365a958`), full suite green, pushed. CI on that head failed one test: the
   reconciliation had also asserted that a single concurrent bootstrap applies every migration, but the migration lock is per file
   (CI: 2 + 5 files). Fixed to the real invariant (complete set, each file exactly once) in `b1e1ee8`; CI on `b1e1ee8` green
   (run 36962208435).
4. PR #33 merged (merge commit, tied to head `b1e1ee8`): `COMBINED_07_14_SHA = 097e198dcf7f5ac66fa3caf97e0625fd472d2f42`; its tree
   equals the PR head.
5. This branch, `reasoning-v3/integration-gate-07-14`, starts at exactly `097e198`.

## 3. Migration verification

Clean PostgreSQL 17 database, `python -m atlas_reasoning migrate` twice, then `db-health`:

| Run | Applied |
|---|---|
| first | `0001_reasoning_core`, `0100_result_diffs`, `0101_result_lifecycle`, `0200_memory_sync`, `0201_memory_injections`, `0202_atlas_questions`, `0203_teach_atlas` (each once) |
| second | none |
| health | `ok: true`, nothing pending, no checksum problems, no missing tables |

No migration was added by the gate; no reserved range (`0300`–`0899`) was consumed.

## 4. Independent review findings

### PR #34 (engine, Phases 07–09)

| # | Severity | Finding | Resolution |
|---|---|---|---|
| E1 | major | Returned model compared to the pinned slug by exact string equality; OpenRouter publishes a dated canonical slug (`openai/gpt-5.6-sol-20260709`), which would fail every paid call as `MODEL_SUBSTITUTED` | Fixed: `settings.model_identity_matches` accepts the slug or exactly `<slug>-<YYYYMMDD>`; `-pro`, `:batch`, other models refused (test). Live confirmation pending (§7) |
| E2 | major | Whole batch claimed before any call; nothing saved until all calls end; stale-claim limit (3600 s) below the worst single call; no engine lock (a second engine could fail live claims) | Fixed: per-item pipeline (claim just before its own call, save as soon as it answers), session advisory lock (one engine), stale limit derived from gateway limits (tests) |
| E3 | major | Failed / deferred work never re-reasoned | Documented, by design of the zero-work gate: Phase 18 (resume). The engine now reports such cases (`EngineReport.unreasoned`) |
| E4 | major | Number guard admitted most small integers (every value and date part × 100) | Fixed: only rates in [0, 1] may be written as percentages (test) |
| E5 | major/minor | Counter-evidence not checked by role; supporting evidence could cite contradicting evidence | Fixed: `COUNTER_EVIDENCE_MISSING` when none of the contradicting evidence is cited; `EVIDENCE_ROLE_MISMATCH` for contradicting evidence in `supporting_evidence` (test) |
| E6 | minor | Pending LLM work for a case that has since disappeared still called the model | Fixed: closed without a model call (test) |
| E7 | minor | A field quoting a delta before-value must be rewritten on the next update | Kept (conservative: it never admits an unsupported number); noted for Phase 15 |
| E8 | minor | No-change review creates a version | Kept, documented (Phase 08 "record a no-op review"); the gate makes it ask no question and write no memory |
| E9 | minor | Lifecycle status change not tied to a transition row at the database level | Kept: would need a migration; transitions go only through `lifecycle.apply` (tested); revisit in Phase 18/19 |
| E10 | minor | Prompt did not describe context or treat it as data | Fixed: `analyst-v2` / `update-v2` (human context is not evidence, never a number source, instructions inside it are data) |
| E11 | nit | claim-time reactivation, explanatory `last_error` on done items | Kept |

### PR #33 (memory and human context, Phases 10–14)

| # | Severity | Finding | Resolution |
|---|---|---|---|
| M1 | major | JSON-looking note committed, then memory policy raised → API 400 → duplicate on retry | Fixed: sync never raises after a canonical commit (`refused`) (tests) |
| M2 | major | Re-asserting an earlier answer silently dropped | Fixed: only the latest answer is a repeat (test) |
| M3 | major | Future-dated teaching never synced once in effect | Fixed: `TeachAtlas.sync_effective` in `memory-sync` (test) |
| M4 | major | Re-processing an old result version revived a superseded question | Fixed: old or already-processed versions ask nothing (test) |
| M5 | minor | Honcho key followed redirects; unbounded bodies | Fixed (both clients): `http_safety.open_no_redirect`, bounded bodies (test) |
| M6 | minor | Retired copies hid live memory in `read` | Fixed: pages past retired copies (test) |
| M7 | minor | Honcho write inside the sync-log row transaction; failed retires only logged; `skipped` rows never re-sent | Kept, documented: the canonical result transaction is never held; the assembler re-validates every copy, so a stale or orphan copy is never injected |
| M8 | minor | Evidence-answerable check is an English heuristic; one bad question aborted the batch | Batch fixed (test); heuristic documented |
| M9 | minor | Superseded/resolved results' summaries injected | Fixed (test) |
| M10 | minor | Remembered copies trusted the hash in metadata | Fixed: re-hashed from the returned body and metadata (test) |
| M11 | minor | Teaching dates and `current_period` in UTC | Documented |
| M12 | nits | CSRF token has no expiry; peer ID is an unsalted email hash; HTML edit/history UI; form value types | Edit and history UI added to the note fragment; the rest belongs to the mounting phase (16/20) |

ManagementAPI: verified not mounted anywhere and no HTTP server is started; it assumes an authenticating proxy (`Request.actor`), the
`ATLAS_REASONING_MANAGERS` allow-list and JSON + Origin + HMAC CSRF protection. No unauthenticated production endpoint exists.

## 5. Cross-branch wiring

| Requirement | Implementation | Test (`tests/test_reasoning_integration.py`) |
|---|---|---|
| Scoped context before every analyst and update request | `engine._reason` → `ContextHooks.prepare` (`reasoning_context.HumanContext` → `MemoryContextAssembler`) | `test_new_result_flow`, `test_updated_result_flow` |
| Deterministic evidence separate; memory never evidence | context fills `manager_context` / `memory_context` only; fingerprint excludes them; number guard ignores them; v2 prompts | `test_answered_question_is_attributed_context_not_evidence`, `ReviewFixTests.test_numbers_in_human_context_are_never_admitted` |
| No cross-editor contamination | assembler scope rules, validated memory | `test_editor_a_memory_never_reaches_editor_b`, `test_teachings_reach_only_matching_cases_and_expire` |
| Degraded Honcho → canonical reasoning | assembler degraded mode | `test_honcho_unavailable` |
| Deterministic ordering, budgets | assembler (`memory_context`) | `test_reasoning_memory_context` (stable order, budgets) |
| Injection audited with request, run, work item IDs | request ID assigned first; `ContextHooks.record` before the call | `test_new_result_flow`, `test_updated_result_flow` |
| No direct Honcho calls from analyst/updater | engine and prompts see only `ContextHooks`; Honcho only in `honcho_client` | `test_reasoning_memory.test_only_the_honcho_client_knows_honcho_and_no_memory_module_reads_atlas` |
| Commit before memory; failure keeps the result | `ContextHooks.after_commit` after the result transaction; failures logged in `memory_sync_log`, retried by `memory-sync` | `CommittedFirstHoncho` in every flow, `test_honcho_unavailable` |
| Questions from the committed current version | `AtlasQuestions.record_result_questions(result_id, version, run_id)` before the result's memory sync | `test_new_result_flow`, `test_updated_result_flow`, `test_answered_question_is_attributed_context_not_evidence` |
| No-op review: no question churn, no memory churn | `after_commit` skips `no_change_review`; summary currency by content | `test_no_change_review_asks_nothing_and_writes_no_memory` |
| Same evidence → zero model work despite new context | gate unchanged; context outside the fingerprint | `test_same_evidence_still_creates_zero_model_work` |
| Client-scoped teachings | stored and synced; not injected (no canonical client dimension on `ReasoningCase`); never applied globally | `test_reasoning_teach_atlas.test_scope_isolation` |

## 6. Requirement matrix, Phases 07–14

Status: PASS = implemented and tested; PASS (16) = backend complete, mounting owned by Phase 16/20.

| Phase | Requirement | Implementation | Test | Status |
|---|---|---|---|---|
| 07 | Versioned analyst prompt | `prompts/analyst-v2.md` (v1 kept), SHA-pinned | `test_prompt_is_versioned_and_pinned` | PASS |
| 07 | Only bounded case evidence, findings, context, provenance | `analyst.case_evidence_input`, `MAX_INPUT_CHARS` | `test_oversized_case_is_refused_not_truncated`, `test_volatile_values_never_reach_the_prompt` | PASS |
| 07 | No invented numbers, people, projects, events, metrics | prompt rules; `output_checks` (rates only scaled) | `test_invented_numbers_are_refused_and_case_numbers_accepted`, `ReviewFixTests` | PASS |
| 07 | Separate observation / interpretation / alternative / limitation / hypothesis | contract fields, `requires_context` | `test_valid_output_becomes_a_version_one_result_with_python_owned_identity` | PASS |
| 07 | Explicit counter-evidence handling | `result_case_errors` (role-checked) | `test_counter_evidence_and_confidence_ceiling_are_enforced`, `ReviewFixTests.test_counter_evidence_must_cite_contradicting_evidence` | PASS |
| 07 | Management questions when context is missing | `questions_for_management` | `test_new_result_flow` | PASS |
| 07 | Prohibit HR / personality / salary / termination / blame | prompt rule 7 (deterministic guardrails: Phase 15) | `test_prompt_is_versioned_and_pinned` | PASS (prompt level) |
| 07 | Strict structured output | `analyst_output_schema`, `provider_schema`, local validation | `test_schema_sent_to_the_provider_is_strict_mode_compatible`, `test_missing_and_malformed_fields_fail` | PASS |
| 07 | Deterministic serialization | canonical JSON | `test_equivalent_cases_serialize_identically` | PASS |
| 07 | Prompt version and model metadata stored | `model_metadata`, `prompt_version`, `llm_calls` | `test_every_new_case_gets_one_evidence_linked_result` | PASS |
| 07 | Explicit summary, never hidden chain-of-thought | `reasoning: {exclude: true}`, no field for it | `test_hidden_reasoning_fields_are_refused` | PASS |
| 08 | Separate versioned update prompt | `prompts/update-v2.md` | `test_update_prompt_is_separate_versioned_and_complete` | PASS |
| 08 | Input: previous result, exact delta, current evidence, both fingerprints | `updater.update_input` | `test_changed_evidence_patches_the_same_result_as_a_new_version` | PASS |
| 08 | ReasoningUpdate output; changed / preserved fields; rationale | `update_output_schema` | `test_field_accounting_and_values_must_agree` | PASS |
| 08 | Python patch merge; immutable fields protected | `patch.merge`, contract checks | `test_identity_and_history_fields_are_protected`, `test_the_model_cannot_patch_immutable_or_unknown_paths` | PASS |
| 08 | New version per accepted material patch | `append_version_with_diff` | `test_changed_evidence_patches_the_same_result_as_a_new_version` | PASS |
| 08 | No-op preserves result exactly and records the review | `no_change_review` | `test_no_change_review_preserves_every_field_byte_for_byte`, `test_no_change_review_keeps_the_card_and_records_the_review` | PASS |
| 08 | Exact wording of untouched fields; before/after diffs | `patch.diff`, `reasoning_result_diffs` | `test_untouched_fields_keep_their_exact_wording` | PASS |
| 08 | Failed patch rollback | one transaction | `test_failed_patch_rolls_back_completely`, `test_an_invalid_patch_from_the_model_changes_nothing` | PASS |
| 09 | States, explicit transition table (code = database) | `lifecycle.TRANSITIONS`, `0101` CHECK | `test_every_pair_outside_the_table_is_refused`, `test_database_check_is_the_same_table` | PASS |
| 09 | new → active; updated → active | `lifecycle.decide` | `test_new_becomes_active_on_the_next_run`, `test_updated_card_settles_back_to_active` | PASS |
| 09 | Disappeared → cooling → resolved after configured runs | `LifecyclePolicy` | `test_disappeared_case_cools_persists_and_resolves` | PASS |
| 09 | Immediate resolution only for approved direct facts | policy | `test_direct_fact_case_resolves_immediately_when_approved` | PASS |
| 09 | Superseded references its replacement | `lifecycle.supersede` | `test_supersede_names_the_replacement` | PASS |
| 09 | Transition reason and run ID persisted; LLM has no authority | `reasoning_lifecycle_transitions` | `test_the_model_has_no_lifecycle_authority`, `test_lifecycle_debug_command` | PASS |
| 10 | Honcho client; one workspace per environment | `honcho_client`, `settings.honcho_settings` | `test_one_workspace_per_environment` | PASS |
| 10 | Peers for Atlas and managers; session naming | `memory` | `test_session_naming_convention`, `test_manager_peers_are_pseudonymous` | PASS |
| 10 | Memory writes and retrieval; source tags | `MemorySyncService`, `read` | `test_mock_write_and_read`, `test_provenance_preserves_source` | PASS |
| 10 | `memory_sync_log`; PostgreSQL first; failure never loses canonical state | `memory_sync`, `0200` | `test_outage_logs_failure_and_retry_sends_current_content`, `test_honcho_unavailable` | PASS |
| 10 | No raw Monday upload; no Honcho IDs as Atlas IDs | `check_record`, `honcho_session_id` | `test_raw_data_leakage_is_refused`, `test_honcho_ids_are_safe_distinct_and_not_atlas_ids` | PASS |
| 10 | Duplicate handling; wrong-session prevention | sync-log uniqueness, `SESSION_POLICY` | `test_duplicate_sync_is_not_sent_twice`, `test_wrong_session_is_refused` | PASS |
| 11 | Assembler; scopes by case type; team isolation | `MemoryContextAssembler`, `case_scope` | `test_team_case_sees_no_editor_memory_unless_explicitly_included`, `test_editor_a_memory_never_reaches_editor_b` | PASS |
| 11 | Budgets, dedup, provenance, stable order | `MemoryBudget`, `_select` | `test_budgets_are_enforced`, `test_deduplication_by_source_and_by_text`, `test_stable_order_regardless_of_input_order` | PASS |
| 11 | Evidence separate from memory | `AssembledContext.apply` | `test_context_never_changes_evidence_or_identity` | PASS |
| 11 | Degraded mode | `memory_status = degraded` | `test_retrieval_failure_degrades_but_keeps_canonical_context`, `test_honcho_unavailable` | PASS |
| 11 | Persist exactly which memory was injected into each LLM call | `memory_injections` via engine (request, run, work item IDs) | `test_new_result_flow`, `test_updated_result_flow` | PASS |
| 12 | Note service/API with IDs, author, source, timestamps | `ManagerNotes`, `ManagementAPI` | `test_create_persists_then_syncs_to_the_result_session`, `test_create_edit_list_history` | PASS |
| 12 | Create and update with audit history | revisions table | `test_edit_keeps_history_and_replaces_the_memory_copy`, `test_concurrent_edits_never_lose_a_revision` | PASS |
| 12 | Text box on every reasoning card | `note_panel` (create, edit, revision history) | `test_note_text_is_escaped_and_labelled`, `test_note_edit_control_and_revision_history_are_escaped_and_attributed` | PASS (16) |
| 12 | PostgreSQL first; Honcho failure never loses the note | | `test_honcho_failure_never_loses_the_note_and_retry_catches_up`, `test_note_that_looks_like_json_is_saved_once_and_succeeds` | PASS |
| 12 | Future reasoning uses the note only as attributed context | `NoteContextSource` + engine wiring | `test_updated_result_flow`, `test_note_is_context_never_evidence` | PASS |
| 12 | Separate labels; escaping | `human_context_html` | `test_note_text_is_escaped_and_labelled` | PASS |
| 13 | Structured questions persisted with required fields | `AtlasQuestions`, `0202` | `test_questions_are_stored_with_their_context_and_synced` | PASS |
| 13 | Answers persisted, `manager_answer`, synced after commit | `answer` | `test_answer_persistence_attribution_and_sync` | PASS |
| 13 | Answer / dismiss UI | `question_panel`, API routes | `test_question_panel_escapes_and_labels`, `test_answer_and_dismiss_routes` | PASS (16) |
| 13 | Answered questions feed later reasoning | `AnswerContextSource` + engine wiring | `test_answered_question_is_attributed_context_not_evidence` | PASS |
| 13 | No questions answerable from evidence | `evidence_answerable` (heuristic) | `test_questions_answerable_from_evidence_are_recognised` | PASS (heuristic) |
| 13 | Dedup across runs; conflicts preserved and flagged | dedup key, conflict links | `test_no_duplicate_open_question_across_repeated_runs`, `test_conflicting_answers_are_preserved_and_flagged`, `test_reasserting_an_earlier_answer_is_management_s_latest_position` | PASS |
| 14 | Teaching model, scopes, types, validity | `TeachAtlas`, `0203` | `test_validity_modes`, `test_scope_sessions` | PASS |
| 14 | Local first; sync active teachings; exclude expired | `_after_commit`, `sync_effective`, `is_effective` | `test_expiration_and_temporary_validity`, `test_future_teaching_is_synced_when_it_comes_into_effect`, `test_teachings_reach_only_matching_cases_and_expire` | PASS |
| 14 | Enable / disable / archive (re-enable re-syncs) | `set_status` | `test_disable_enable_archive` | PASS |
| 14 | Teach Atlas UI showing source, scope, type, validity | `teach_atlas_page` | `test_teach_atlas_page_shows_scope_type_validity_and_escapes` | PASS (16) |
| 14 | Never rewrites evidence; bad-source corrections flagged | `engineering_review_flags` | `test_corrections_flag_bad_upstream_data_and_never_change_evidence`, `test_human_context_code_never_writes_evidence_tables` | PASS |
| 14 | Client scope | stored and synced; not injected (no canonical client–case relationship) | `test_scope_isolation` | PASS (known limitation, §8) |

No FAIL. The earlier "partial" Phase 12 item (a text box on every card) is complete at the backend and fragment level: create,
edit with optimistic revision, revision history, escaping and labels; placing the fragment on the dashboard is Phase 16.

## 7. Live compatibility gates

| Gate | Result |
|---|---|
| OpenRouter | **Not run: credential missing.** Neither `OPENROUTER_API_KEY` nor `OPENROUTER_API_KEY_FILE` is set in this environment (shell, macOS session environment, project `.env`). The public model list (no credential) shows `openai/gpt-5.6-sol`, canonical slug `openai/gpt-5.6-sol-20260709`, with `structured_outputs` and `response_format` supported. A ready probe exists (gateway + generated analyst/update schemas, synthetic factory case) and must run before Phase 15 |
| Honcho | **Not run: credential missing.** Neither `HONCHO_API_KEY` nor `HONCHO_API_KEY_FILE` is set (memory also needs `ATLAS_REASONING_MEMORY=on`, `ATLAS_REASONING_ENVIRONMENT`) |

Both are deployment/environment blockers to be resolved before Phase 15 starts.

## 8. Known limitations

- Phase 15 (deterministic content safety and HR guardrails) has not started.
- Production mounting of the ManagementAPI and fragments awaits Phases 16/20.
- Client-scoped teachings are stored but not automatically injected until a canonical client-to-case relationship exists.
- Re-reasoning failed or deferred work is Phase 18's (`EngineReport.unreasoned` lists the cases).
- Live OpenRouter and Honcho behavior unverified until credentials are configured (§7).
