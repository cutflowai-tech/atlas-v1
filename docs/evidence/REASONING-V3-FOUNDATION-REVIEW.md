# Reasoning V3 foundation (Phases 01–06): review record

Branch `reasoning-v3/core`, built on `001f6af` (`chore/reconcile-current-atlas-config`: Phase 00 and the `REV/` plan, which are
not yet on `integration`; the pull request brings them along). Integration target: `integration` (`2fc950b` at the start).
Architecture and interfaces: [`docs/REASONING-V3.md`](../REASONING-V3.md).

## 1. Baseline (before any change, `001f6af`)

| Check | Result |
|---|---|
| `make test` | 925 tests, 0 failures, 3 skipped (Docker runtime tests without `ATLAS_RUN_DOCKER_TESTS=1`) |
| `ruff check src tests` / `mypy src` | clean / clean (100 files) |
| Contract 1.5 showcase site | every file's SHA-256 recorded in `fixtures/golden/site-v1.5-showcase-sha256.json` before any Reasoning V3 code |

## 2. Requirement matrix

Status: PASS = implemented and covered by the named test; N/A = not applicable. There is no FAIL.

| Phase | Requirement (REV/0x #) | Implementation | Test | Status |
|---|---|---|---|---|
| 01 | 1 Identify upstream outputs | `docs/REASONING-V3.md` §2.1 | — (documentation) | PASS |
| 01 | 2 Single boundary module | `reasoning_input_boundary` | `test_reasoning_boundary.ImportDirectionTests` | PASS |
| 01 | 3 Typed immutable payload | frozen dataclasses, `frozen.freeze` | `BoundaryPayloadTests.test_payload_is_deeply_immutable` | PASS |
| 01 | 4 Facts / derived / evidence marked | `field(metadata={"kind"})`, `field_kinds` | `test_every_field_is_classified` | PASS |
| 01 | 5 Feature flag default OFF | `settings.ATLAS_REASONING_V3` | `FeatureFlagTests` | PASS |
| 01 | 6 OFF ⇒ build unchanged | no build hook; golden | `GoldenSiteTests` (flag unset/off/on; 1.3/1.4 goldens) | PASS |
| 01 | 7 Cannot mutate profiles, states, Overall Status, Trend, Recent Change, V2 | deep copies, read-only views | `test_building_never_mutates_or_aliases_upstream_documents`, `IntelligenceUnchangedTests` | PASS |
| 01 | 8 Contract version + snapshot ID exposed | `UpstreamContract`, `SnapshotMetadata` | `test_payload_names_the_snapshot_and_contract_future_runs_need` | PASS |
| 01 | 9 Architecture documentation | `docs/REASONING-V3.md` §1–2, `ARCHITECTURE.md` 5c | — | PASS |
| 02 | 1 ReasoningCase fields | `reasoning-case-v1`, `ReasoningCase` | `RoundTripTests` | PASS |
| 02 | 2 ReasoningResult fields | `reasoning-result-v1`, `ReasoningResult` | `RoundTripTests` | PASS |
| 02 | 3 ReasoningUpdate patch (changed / preserved / rationale) | `reasoning-update-v1`, `ReasoningUpdate` | `test_update_invariants` | PASS |
| 02 | 4 `case_id` immutable | frozen models; not patchable; DB trigger | `ImmutableIdentityTests`, `test_identity_and_history_are_immutable` | PASS |
| 02 | 5 Visible conclusions reference evidence | claim `minItems: 1`; `result_case_errors` | `EvidenceRequirementTests` | PASS |
| 02 | 6 Strict enums | `enums` = schema = DB CHECKs | `test_schema_enums_equal_the_python_enums`, `test_status_constraints_mirror_the_enums` | PASS |
| 02 | 7 Unknown / invalid fields rejected | `additionalProperties: false` everywhere | `test_unknown_fields_fail_at_every_level` | PASS |
| 02 | 8 Cross-field semantic validation | `*_semantic_errors`, cross-object validators | `SemanticInvariantTests` | PASS |
| 02 | 9 Version `reasoning-v1` | `contract_version` const | `test_contract_version_is_reasoning_v1` | PASS |
| 03 | 1 PostgreSQL | `store.db` (psycopg 3, schema `atlas_reasoning`) | every `@requires_db` test (PostgreSQL 17) | PASS |
| 03 | 2 The eleven tables | `0001_reasoning_core.sql` | `test_every_required_table_exists_and_health_is_ok` | PASS |
| 03 | 3 Keys, FKs, uniqueness, indexes, version constraints | migration | `IntegrityTests` | PASS |
| 03 | 4 Identifiers and statuses relational | columns + CHECKs | `test_status_constraints_mirror_the_enums` | PASS |
| 03 | 5 JSON only for documents | contract documents, canonical evidence, deltas | review | PASS |
| 03 | 6 Repository; SQL not in rendering | `store.repository` | `test_sql_and_the_driver_stay_inside_the_store` | PASS |
| 03 | 7 Transactions for results and versions | `create_result`, `append_result_version` | `AtomicityTests`, `ConcurrencyTests` | PASS |
| 03 | 8 Health check + migration bootstrap | `store.health`, `store.migrate`, CLI | `MigrationTests`, `CommandTests` | PASS |
| 03 | 9 Local development configuration | URL / URL_FILE, test-DB guard | `SkipPolicyTests`, CI `ATLAS_REASONING_REQUIRE_DB_TESTS=1` | PASS |
| 03 | 10 No Monday raw data copied | references by ID only | review | PASS |
| 03 | Tests: migrations, integrity, uniqueness, rollback, restart, concurrency | — | `MigrationTests`, `IntegrityTests`, `AtomicityTests`, `RestartPersistenceTests`, `ConcurrencyTests` | PASS |
| 04 | 1–3 Deterministic builder from stable dimensions, optional dims per rule | `case_identity`, `case_mapping.TOPIC_RULES` | `IdentityConstructionTests` | PASS |
| 04 | 4 Volatile values excluded | identity has no value fields | `test_changed_evidence_values_keep_the_case_id`, `test_volatile_metadata_never_enters_identity`, `test_late_rate_20_31_45_percent_is_one_case` | PASS |
| 04 | 5 Normalization | `normalize_component` | `test_case_id_is_a_hash_of_the_normalized_identity_key` | PASS |
| 04 | 6 Collision handling | `assert_no_collisions`, DB keys | `test_collisions_are_detected_not_merged`, `test_case_identity_collisions_are_refused` | PASS |
| 04 | 7 Many findings → one case | `map_findings` | `test_findings_of_one_issue_share_a_case` | PASS |
| 04 | 8 When a new case is created | documented (§5) | `test_different_topic_and_different_editor_separate` | PASS |
| 04 | 9 Identity dimensions persisted | `reasoning_cases` columns | `IntegrityTests`, `case` debug command | PASS |
| 04 | Ordering, history replay, golden | — | `test_input_order_does_not_matter`, `test_historical_replay_keeps_identities`, `test_identity_golden` | PASS |
| 05 | 1–3 Canonical, sorted, prose/timestamps/IDs excluded | `fingerprint` | `FingerprintTests` | PASS |
| 05 | 4 Material delta lists | `delta.material_delta` | `DeltaTests` | PASS |
| 05 | 5 Gate actions | `change_gate.run_gate` | `ChangeGateTests` | PASS |
| 05 | 6 Unchanged ⇒ zero LLM work | no work item for `unchanged` (DB CHECK too) | `test_same_snapshot_twice_creates_zero_work_on_the_second_run` | PASS |
| 05 | 7 New ⇒ new-case work item | `new_result` | `test_first_run_creates_one_new_result_item_per_case`, `test_new_topic_creates_a_new_case` | PASS |
| 05 | 8 Updated ⇒ update work item with exact delta | `update_result` + delta | `test_update_work_carries_the_delta_from_the_open_results_evidence` | PASS |
| 05 | 9 Disappeared never deletes / resolves | `lifecycle` work item only | `test_disappeared_case_is_kept_and_tracked` | PASS |
| 05 | 10 Decision + reason persisted per case per run | `reasoning_case_observations` | `test_same_snapshot_twice…`, `test_disappeared_case_is_kept_and_tracked` | PASS |
| 06 | 1 `openrouter_client` | `atlas_reasoning/openrouter_client.py` | `OpenRouterTransportTests` | PASS |
| 06 | 2 Credentials from environment only | `settings.openrouter_settings` | `test_key_comes_from_environment_or_file_never_both` | PASS |
| 06 | 3 Model pinned | `PINNED_MODEL = "openai/gpt-5.6-sol"` | `test_model_is_pinned`, `test_request_body_pins_the_model…` | PASS |
| 06 | 4 Structured output matching reasoning schemas | `structured.contract_output` | `test_structured_output_matches_reasoning_v3_contracts` | PASS |
| 06 | 5 Timeout, bounded retries, backoff, rate limits | `gateway` | `test_timeout_is_retried…`, `test_retry_then_success`, `test_rate_limit_honours_retry_after…` | PASS |
| 06 | 6 Error taxonomy | `provider` | `test_http_and_provider_errors_map_to_the_taxonomy`, `test_network_failures` | PASS |
| 06 | 7 Request IDs, safe logs | `gateway` | `test_success…`, `test_secrets_never_reach_logs_errors_or_records` | PASS |
| 06 | 8 Concurrency limit | `BoundedSemaphore` | `test_concurrency_limit` | PASS |
| 06 | 9 Call metadata to `llm_calls` | `store.calls.StoreCallRecorder` | `CallRecordingTests` | PASS |
| 06 | 10 Fake provider | `fake_provider` | all gateway tests | PASS |
| 06 | 11 Provider-neutral domain | imports | `IsolationTests` | PASS |
| 06 | Health-check command | `provider-health` (`--dry-run`) | `HealthCommandTests` (local server, no live call) | PASS |

## 3. Decisions and deviations to know

- **Base branch.** `integration` (`2fc950b`) does not yet contain Phase 00 (`001f6af`) or the `REV/` plan (`aca201b`); this branch
  is built on them, so its pull request to `integration` carries both.
- **Database variable.** Phase 00 listed `DATABASE_URL` as planned; the implementation reads `ATLAS_REASONING_DATABASE_URL` (or
  `_FILE`), consistent with every other `ATLAS_*` variable and safe on a shared host.
- **No build hook.** Phase 01 adds no call from the site build, sync or publication into Reasoning V3; the flag gates the reasoning
  commands. Wiring reasoning into the production cycle is rollout work (Phase 20).
- **Production image.** `psycopg` is in `requirements-reasoning.txt` (pulled in by `requirements-dev.txt` for CI), not in
  `deploy/production/runtime-requirements.txt`; adding it is part of the rollout.
- **Extra tables** beyond the eleven named: `reasoning_case_evidence` (each evidence state once), `reasoning_case_observations`
  (gate decisions), `reasoning_work_items` (gate output), `manager_note_revisions` and `teaching_revisions` (audit history Phases 12
  and 14 require). They match the contracts and later phases and are documented in §4 of the architecture document.
- **Contract amendment during Phase 05.** Cases carry evidence-block summaries and finding limitations so the fingerprint can be
  recomputed from the case itself; work status gained `cancelled`. Both happened before anything was merged.
- **Reappearance.** A case that reappears with the same evidence is `unchanged` (reason `reappeared_same_evidence`) and creates no
  work; the lifecycle phase reads that reason code. Pending LLM work of a disappearing case is left to the lifecycle / reliability
  phases.
- **Python.** CI runs 3.12; local verification ran 3.13 with the same dependency ranges.
- **Absent cases** are recorded (`still_absent`) in every later run until a later phase retires them; retirement policy belongs to
  the lifecycle phase (09).

## 4. Independent review and fixes

An independent review of the whole diff reported nine findings. All were fixed and each has a regression test:

| # | Finding | Fix | Test |
|---|---|---|---|
| 1 | Work items reused the first document stored for a fingerprint (old snapshot ID and V2 finding IDs) | each LLM work item stores the case document of the run that created it; `case_for_work` uses it | `test_work_items_carry_the_document_of_their_own_run` |
| 2 | A failed/cancelled item left a case without a result while evidence stayed the same | the gate still creates no work for `unchanged` (REV/05); `StoreTransaction.unreasoned_cases()` lists such cases for the resume phase | `test_in_progress_work_is_never_superseded_and_unreasoned_cases_are_listed` |
| 3 | Malformed patch field lists crashed validation (`TypeError`) | type-guarded semantic checks; `SCHEMA_INVALID` | `MalformedPatchTests` |
| 4 | `password=` query parameters and `@` in passwords escaped URL redaction | URL parsed and every credential masked; driver messages scrubbed | `test_every_form_of_database_password_is_redacted` |
| 5 | `http://127.0.0.1.evil.example` passed the local-HTTP exception | parsed host must be exactly 127.0.0.1 / localhost / ::1 | `test_key_comes_from_environment_or_file_never_both` |
| 6 | A reappearing case kept its pending `disappeared` lifecycle item | cancelled when the case is present again | `test_reappearance_cancels_stale_lifecycle_work` |
| 7 | In-progress work could be superseded; status changes unguarded | only pending items are superseded (in-progress → deferred); `WORK_TRANSITIONS` | `test_status_transitions_are_guarded`, `test_in_progress_…` |
| 8 | Concurrent result creation surfaced a raw `UniqueViolation`; lifecycle versions accepted an update | case row locked, violation mapped to `ResultConflict`; lifecycle + update refused | `test_concurrent_creation_…`, `test_a_lifecycle_version_records_no_update` |
| 9 | `cohort_label` hashed; orientation followed V2 rank (finding-ID tie-break); `IncompleteRead` not retried; request-ID reuse | `cohort_label` volatile; orientation from counts and confidence only; `http.client.HTTPException` → network error (retryable); request-ID uniqueness documented | `test_orientation_and_fingerprint_ignore_v2_ranks_and_labels`, `test_network_failures` |

## 5. Results (final, after the fixes)

| Check | Result |
|---|---|
| `make test` (PostgreSQL 17 test database, `ATLAS_REASONING_REQUIRE_DB_TESTS=1`) | **1071 tests, 0 failures, 3 skipped** (the same Docker runtime tests as the baseline) |
| of which Reasoning V3 (`make reasoning`) | 146 tests, 0 failures, 0 skipped |
| `ruff check src tests` / `mypy src` | clean / clean (124 files) |
| Golden sites 1.3, 1.4, 1.5 (flag unset / off / on) | byte-identical |
| Live provider calls in tests | none |

Coverage is not measured in this repository (no coverage tool in `requirements-dev.txt`); every requirement above maps to a named
test instead.
