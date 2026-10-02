# Reasoning V3 Phase 15: validation and safety guardrails — review record

Policy and boundaries: [`docs/REASONING-V3-GUARDRAILS.md`](../REASONING-V3-GUARDRAILS.md). Architecture: [`docs/REASONING-V3.md`](../REASONING-V3.md) §17.

## 1. Start

| Item | Value |
|---|---|
| Starting SHA (FINAL_INTEGRATION_GATE_SHA) | `e058fc4c097e553dae52a0772df042d1ccc29c77` (= `origin/integration` when work began) |
| Branch | `reasoning-v3/validation-guardrails` (isolated worktree) |
| `main` | `61d7a471d2bb3b0098ee2c0f0c2c47b50a24c35b`, untouched |
| Credentials | Absent at implementation time; supplied out of band by the operator for the live gates (§4), never committed |

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
| A.25 | OpenRouter live gate | production gateway, pinned model, strict schemas | live run (§4) | PASS |
| A.26 | Honcho live gate | `HonchoClient` / sync / assembler on `waset-atlas-test` | live synthetic smoke (§4) | PASS |

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

Credentials were supplied out of band by the operator; only the supported variable names (`OPENROUTER_API_KEY`, `HONCHO_API_KEY`;
the preferred convention is `OPENROUTER_API_KEY_FILE` / `HONCHO_API_KEY_FILE` under `/run/secrets/`) were loaded into each one-shot
process, never printed, logged or committed. Every run checked that no secret value appeared in its stdout or stderr. TLS
verification stayed on (system CA bundle, `SSL_CERT_FILE=/etc/ssl/cert.pem`, needed by this Mac's Python build; nothing was disabled).

### OpenRouter — PASS (2026-10-02, 11:39–11:42 UTC)

Configuration: `ATLAS_REASONING_MODEL=openai/gpt-5.6-sol`, `ATLAS_REASONING_ALLOW_MODEL_OVERRIDE=off`,
`ATLAS_REASONING_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1`; all calls through the production gateway (`ReasoningGateway` +
`OpenRouterTransport`).

| Check | Result |
|---|---|
| `python -m atlas_reasoning provider-health` (11:39:56 UTC) | PASS: `ok: true`, live call, 1 attempt, request `req_5fca39c9ac2947c9bcf64e39ad6737d9`, 42 input / 13 output tokens, 12 455 ms |
| Authentication, network | PASS (HTTP success on the first attempt) |
| Strict structured output — health schema | PASS: accepted; parsed output equals `{"ok": true}` |
| Strict structured output — production analyst schema (`atlas_analyst_result_v1`, synthetic test-fixture case) | PASS: accepted and parsed (requests `req_c50adf6a…`, `req_90dda61f…`, `req_1289dc67…`; ~3 954 input / ~1 700–2 000 output tokens) |
| Strict structured output — production update schema (`atlas_update_patch_v1`, synthetic case) | PASS: accepted and parsed (requests `req_4761dc98…`, `req_d02bd753…`; ~4 792 input / ~378 output tokens) |
| Requested model | `openai/gpt-5.6-sol` (pinned; override off) |
| **Returned model** | **`openai/gpt-5.6-sol`** — exactly the pinned slug on every call (`model_identity_matches`: true) |
| Redirects | none occurred; the client never follows one (a 3xx is a configuration error) |
| Secrets in output / errors / call records | none |
| Phase 15 guardrails on the live answers | update answers PASS; the first live analyst answer was refused (`UNKNOWN_ENTITY`) for a sentence starting "Two projects were excluded…": a false positive (a number word read as a name). Fixed narrowly (number words are quantities, never names; the number rule still grounds them), regression test added; the next live analyst answer PASSED |

### Honcho — PASS (2026-10-02, 11:42–11:44 UTC)

Configuration: `ATLAS_REASONING_MEMORY=on`, `ATLAS_REASONING_ENVIRONMENT=test`, `ATLAS_HONCHO_BASE_URL=https://api.honcho.dev` → workspace
**`waset-atlas-test`**. The production workspace was never used. Synthetic identities only (`compat-smoke-543df3c46d`,
`compat-smoke-543df3c46d-other`), synthetic result text, no staff, Monday, performance, management or client data. Run through the
existing abstractions: `HonchoClient`, `MemorySyncService` (PostgreSQL sync log first), `MemoryContextAssembler`.

| # | Check | Result |
|---|---|---|
| 1 | Authentication (`memory-health`, 11:42:51 UTC: `ok: true`, live call; and workspace get-or-create in the smoke test) | PASS |
| 2 | Workspace behavior: environment `test` → `waset-atlas-test` | PASS |
| 3 | Synthetic write: two result summaries to their result and Editor sessions, all four copies logged `synced` after the canonical rows | PASS |
| 4 | Scoped retrieval: the Editor session and the result session each return exactly the copy written there | PASS |
| 5 | Provenance: source type, session key, result version, case ID survive the round trip; the content hash re-computed from the returned body and metadata equals the stored one and the sync log's; the assembler accepted the live copy as canonical-current (validated, not trusted) | PASS |
| 6 | Missing session: a never-written session reads as empty memory (not an outage); a case with no memory gets `memory_status=available`, no items. Degraded mode: a rejected key (synthetic invalid key) raises `MemoryRejected` and the assembler degrades to canonical context (`degraded`, `memory_rejected`) | PASS |
| 7 | Isolation: Editor A's context and session contain nothing of Editor B (and vice versa); Editor B's session is not in Editor A's scope | PASS |
| 8 | Redirect restriction: against a local server answering 302, the client refused the redirect (`memory_rejected`) and the redirect target received no request and no key | PASS |
| 9 | Only `waset-atlas-test` was touched (every call path checked; no `production` in any path or workspace ID) | PASS |
| — | Cleanup: Honcho has no per-message delete; the synthetic copies were retired (`atlas_retired`) and verified excluded from live reads. They remain only in `waset-atlas-test` under the synthetic IDs above (and one earlier synthetic Atlas-question record from the coordinator's smoke, also retired) | done |

The Phase 15 merge gate's live items are therefore PASS.
