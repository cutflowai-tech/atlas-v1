# Atlas Reasoning V3: foundation (Phases 01–06)

Reasoning V3 adds management reasoning (GPT-5.6 Sol through OpenRouter) **after** the deterministic Atlas pipeline. This document
describes the foundation that later phases build on: the input boundary, the reasoning contracts, the canonical PostgreSQL state,
stable case identity, evidence fingerprints with the Change Gate, and the provider gateway. The phase specifications are in
[`REV/`](../REV); the interfaces later phases must use are listed in [§8](#8-stable-public-interfaces).

```
Monday ─► deterministic Atlas ─► metrics ─► Interpretation 1.5 ─► Intelligence V2
                                                                      │  (published site documents, read-only)
                                                                      ▼
                                                        reasoning_input_boundary  (Phase 01)
                                                                      ▼
                         ReasoningInput ─► case mapping + case_id (04) ─► evidence fingerprint + Change Gate (05)
                                                                      ▼
                                       work items (new / update / lifecycle), persisted in PostgreSQL (03)
                                                                      ▼
                                 [Phase 07+: analyst / update reasoning] ─► gateway ─► OpenRouter (06)
```

Rules that hold everywhere (`REV/01`–`REV/20`, global rules):

- The deterministic Atlas pipeline is the source of truth. Reasoning V3 never writes to, or recomputes, a Monday fact, metric,
  component state, Overall Status, Trend, Recent Change, benchmark or Intelligence V2 finding.
- LLM output is never the source of truth for metrics, events, attribution, sample sizes, deadlines or evidence identity. The LLM
  never decides case identity, the Change Gate, or lifecycle transitions.
- PostgreSQL is the canonical store for Reasoning V3 application state. Honcho (Phase 10) is contextual memory only.
- With Reasoning V3 disabled (the default), Atlas behaves exactly as before.

## 1. Package layout

All Reasoning V3 code lives in `src/atlas_reasoning/`, a separate package. No module of `atlas_commander`, `atlas_sync` or
`atlas_monday_probe` imports it, and inside it only `reasoning_input_boundary.py` imports upstream Atlas
(`tests/test_reasoning_boundary.py::ImportDirectionTests`).

| Module | Phase | Role |
|---|---|---|
| `settings` | 01, 03, 06 | Feature flag and environment configuration |
| `frozen` | 01 | Deep-immutable copies of JSON-like values |
| `reasoning_input_boundary` | 01 | The one approved input path from Atlas |
| `enums` | 02 | Strict enums shared by contracts, database and later phases |
| `contracts` | 02 | `ReasoningCase`, `ReasoningResult`, `ReasoningUpdate`: schemas, typed models, semantic validators |
| `store.db`, `store.migrate`, `store.repository`, `store.health` | 03 | PostgreSQL connection, migration bootstrap, data access, health |
| `__main__` | 03+ | Operator commands (`python -m atlas_reasoning ...`) |
| `case_identity` | 04 | Deterministic `case_id` from normalized identity dimensions |
| `case_mapping` | 04 | Intelligence V2 findings → case candidates (topic rules, member keys) |
| `case_builder` | 05 | Case candidate → base `ReasoningCase` document |
| `fingerprint` | 05 | Canonical evidence and `evidence_fingerprint` |
| `delta` | 05 | Material delta between two evidence states |
| `change_gate` | 05 | Change Gate service, persisted decisions, `case_for_work` |
| `provider` | 06 | Provider-neutral request/response types, `Transport` protocol, error taxonomy, redaction |
| `gateway` | 06 | Retries, backoff, rate limits, concurrency, structured-output validation, call records, isolation |
| `openrouter_client` | 06 | OpenRouter transport (the only module that knows OpenRouter) |
| `fake_provider` | 06 | Scripted offline transport for tests |
| `structured` | 06 | Structured-output descriptions from the reasoning-v1 schemas |
| `store.calls` | 06 | Persists call metadata to `llm_calls` |
| `analyst`, `prompts/analyst-v1.md` | 07 | New-case reasoning: bounded canonical case input, versioned prompt, analyst output schema, result assembly |
| `output_checks` | 07 | Deterministic checks of model text against its case (no invented numbers) |
| `engine` | 07–09 | Work-item processing: claim, gateway call, validated persistence, failure isolation |
| `updater`, `prompts/update-v1.md` | 08 | Update reasoning: update input, required changes, patch output schema, ReasoningUpdate construction and validation |
| `patch` | 08 | Deterministic patch merge and version diffs |

## 2. Phase 01: the reasoning input boundary

### 2.1 What upstream Atlas produces

| Stage | Output | Where |
|---|---|---|
| Cycle reconstruction | `CycleReconstruction` (cycles, item snapshots, ingestion metadata) | `atlas_commander.pipeline` |
| Metrics + Interpretation 1.5 | Editor Profile documents (`editor-profile-v1.5`): speed, deadline, quality, component states, Overall Status, Trend, Recent Change, each with an evidence block | `atlas_commander.profile`, `intelligence`, `interpretation_policy` → `profiles/<editor_id>.json` |
| Publication identity | `publication.json`: `snapshot_id`, `release_id`, contract version | `atlas_commander.publication` |
| Intelligence V2 | `intelligence-v2.json` (`approved_only`): findings with typed statements, Monday evidence records, confidence, limitations | `atlas_commander.investigation` |
| Evidence serialization | Every evidence record names Monday item, cycle, event IDs, source timestamps and the values used | `investigation.models.Evidence`, profile evidence blocks |

### 2.2 The boundary

`atlas_reasoning.reasoning_input_boundary.build_reasoning_input(intelligence=..., publication=..., profiles=...)` is the single
input path. `load_reasoning_input(site_dir)` only reads those three documents from a built site and calls it. It:

- accepts only a schema-valid, consistency-valid, **publishable** (`approved_only`) Intelligence V2 document — review output never
  reaches Reasoning V3;
- requires the publication identity and checks that the V2 document, `publication.json` and every profile come from the same
  contract and Monday snapshot;
- refuses contracts without `editor_intelligence` (1.0–1.4) with `ReasoningInputUnavailable`;
- returns a `ReasoningInput`: frozen dataclasses whose mappings are read-only views of private deep copies. Mutating the payload
  raises; mutating the upstream documents after the build does not change it; building it never changes them.

| Payload part | Content |
|---|---|
| `contract` (`UpstreamContract`) | executable contract version, Intelligence V2 version and document version, V2 mode, publication view version, `boundary_version` (`reasoning-input-v1`) |
| `snapshot` (`SnapshotMetadata`) | `source_snapshot_id` (= `publication.json` `snapshot_id`), `release_id`, `generated_at`, `retrieved_at`, source run ID, board ID, windows |
| `findings` (`UpstreamFinding`) | each published finding: type, category, direction, scope, evidence level, upstream confidence and factors, rank, sample size, affected sets, parameters, limitations; statements split into `source_facts`, `derived_values`, `upstream_interpretations`; supporting / contradicting / context evidence blocks with their Monday records |
| `editors` (`EditorState`) | per Editor: Overall Status, component states, Recent Change values (read from the profile, never recomputed) |
| `video_types` | Video Type keys and labels |

Every field carries its kind in `dataclasses.field(metadata={"kind": ...})` (`field_kinds(cls)`): `source_fact`,
`deterministic_derived_value`, `upstream_interpretation`, `evidence_reference`, `contract_metadata`, `snapshot_metadata`. A
statement's `params` take the kind its level implies (`fact` → source fact; `metric`/`pattern`/`association` → derived value;
`interpretation`/`hypothesis` → upstream interpretation).

### 2.3 Feature flag

`ATLAS_REASONING_V3` (`on`/`off`, default **off**; any other value is a configuration error). Phase 01 adds no hook into the
site build, sync or publication: with the flag off **or on**, those paths are byte-identical to the build made before any
Reasoning V3 code existed (`fixtures/golden/site-v1.5-showcase-sha256.json`, made at `001f6af`; contracts 1.3 and 1.4 keep their own
golden bytes). Commands that run reasoning (`python -m atlas_reasoning gate`, provider calls) refuse to start with the flag off;
infrastructure commands (`migrate`, `db-health`, `provider-health --dry-run`) work with it off so the database can be prepared
before writes are enabled.

### 2.4 Regression protection

`tests/test_reasoning_boundary.py`:

- the contract 1.5 showcase site is byte-identical to the pre-Reasoning-V3 golden with the flag unset, off and on; 1.3 and 1.4 sites
  keep their golden bytes with the flag on;
- the Intelligence V2 document is identical before and after importing and using the boundary (separate interpreters);
- the payload is deeply immutable, never aliases upstream documents, and building it leaves profiles (component states, Overall
  Status, Trend, Recent Change) and Intelligence V2 unchanged;
- nothing upstream imports `atlas_reasoning`; only the boundary module imports upstream Atlas;
- review output, missing or invalid V2 documents, and documents from different snapshots or contracts are refused.

## 3. Phase 02: reasoning contracts (`reasoning-v1`)

Schemas: `contracts/reasoning-case-v1.schema.json`, `reasoning-result-v1.schema.json`, `reasoning-update-v1.schema.json`, sharing
`reasoning-common-v1.schema.json` (JSON Schema 2020-12). Models and validators: `atlas_reasoning.contracts`. Enums:
`atlas_reasoning.enums`. Examples: `fixtures/reasoning/valid/*.json` and `fixtures/reasoning/invalid/*.json` (listed with their
expected error code in `fixtures/reasoning/manifest.json`, regenerated by `python3 tests/reasoning_factory.py --write`).

Every object, at every nesting level, rejects unknown fields (`additionalProperties: false`). The only open objects are the
deterministic upstream values a case carries verbatim (`params`, `values`) and the before/after values of a material delta.
Errors are `"<CODE>: <detail>"` (`ContractViolation.codes`): `UNKNOWN_FIELD`, `INVALID_ENUM`, `MISSING_EVIDENCE`,
`SCHEMA_INVALID`, and the semantic codes below.

### 3.1 ReasoningCase

One management issue with the deterministic evidence that currently supports or contradicts it. Built by Python from the
boundary payload (Phases 04–05), never by an LLM.

| Field | Meaning |
|---|---|
| `case_id`, `identity_version`, `identity_key`, `subject_type`, `subject_id`, `topic_key`, `identity_dimensions`, `case_type` | Stable identity (§5); `case_id` = `rc1_` + 32 hex |
| `scope` | Current breadth: affected Editors, Video Types, project count, windows (not identity) |
| `source_snapshot_id`, `upstream_contract_version`, `upstream` | Which snapshot and upstream versions the case was built from |
| `orientation` | Adverse or favourable, whichever side has more findings, then the stronger best upstream confidence; `mixed` on a tie or with only mixed findings, `neutral` otherwise. Never depends on V2 ranks or finding IDs |
| `supporting_findings`, `contradicting_findings` | `FindingRef`s: V2 `finding_id` (this snapshot), stable `member_key`, type, direction, category, evidence level, upstream confidence, sample size, rank. Contradicting = opposite direction to the orientation |
| `current_evidence.statements` | Every V2 statement of the contributing findings, typed (`source_fact` / `deterministic_derived_value` / `upstream_interpretation`) |
| `current_evidence.references` | One `EvidenceReference` per Monday record: stable `ref_id` (`ev1_` + 24 hex), member, role, evidence code, item, cycle, Editor, Video Type, event IDs, source timestamps, values |
| `previous_result_id`, `previous_result_version` | The canonical result this case continues (both or neither) |
| `evidence_fingerprint` | `ef1_` + SHA-256 of the canonical evidence (§6) |
| `material_delta` | What changed since the previous fingerprint (§6), or null for a new case |
| `manager_context`, `memory_context` | Attributed management context and memory (Phases 10–14 fill them; empty / `not_requested` until then) |
| `created_at` | When the case object was built |

Semantic checks (`case_semantic_errors`): `PREVIOUS_RESULT_PAIRING`, `DELTA_FINGERPRINT_MISMATCH`, `DELTA_NOT_A_CHANGE`,
`DUPLICATE_FINDING`, `ORIENTATION_CONFLICT`, `UNKNOWN_MEMBER`, `STATEMENT_KIND_MISMATCH`, `DUPLICATE_REF`, `REF_ID_MISMATCH`,
`FINDING_WITHOUT_EVIDENCE`, and (registered by Phases 04–05 in `contracts.CASE_CHECKS`) `CASE_ID_MISMATCH` and
`FINGERPRINT_MISMATCH`: a case whose `case_id` or fingerprint does not follow from its own content is rejected.

### 3.2 ReasoningResult

Atlas's reasoning about one case, one version. `reasoning_summary` is an explicit summary written for management, never raw or
hidden chain-of-thought (there is no field for it, and unknown fields are rejected).

| Field | Rule |
|---|---|
| `result_id` | `rr1_` + 32 hex, created once (`new_result_id`), kept across versions; never patchable |
| `case_id`, `version` | The case it belongs to; version ≥ 1, incremented per accepted change (Phase 08) |
| `observation`, `interpretation`, `management_significance` | Claims: statement + **≥ 1** evidence reference |
| `supporting_evidence` (≥ 1), `counter_evidence` | Lists of claims, each with ≥ 1 evidence reference |
| `alternative_explanations` | Explanation, evidence references (may be empty), `requires_context` (true = a hypothesis needing business context) |
| `confidence` | `{level: weak/moderate/strong, rationale}`: the Intelligence V2 scale |
| `limitations`, `questions_for_management` (text, reason, `expected_context_type`), `suggested_investigations` | As named |
| `lifecycle_status`, `superseded_by` | Phase 09 lifecycle; `superseded` ⇔ `superseded_by` names the replacement |
| `source_snapshot_id`, `evidence_fingerprint`, `model_metadata` (provider, model, request IDs), `prompt_version`, `created_at`, `updated_at` | Provenance, set by Python |

Semantic checks: `SUPERSEDED_LINK`, `TIMESTAMP_ORDER`. Against its case (`result_case_errors`): `CASE_MISMATCH`,
`EVIDENCE_FINGERPRINT_MISMATCH`, `UNKNOWN_EVIDENCE_REF` (every cited reference exists in the case), `COUNTER_EVIDENCE_MISSING`
(a contradicted case needs counter-evidence), `CONFIDENCE_EXCEEDS_UPSTREAM` (never above the strongest supporting finding).

### 3.3 ReasoningUpdate

A patch to one result version, never a regenerated result. `changed_fields` (`[{field, value}]`) and `preserved_fields` together
list **every** patchable field exactly once; `change_rationale` explains the change; `base_version` and
`evidence_fingerprint_before/after` pin what was patched. `action` is `patch` (≥ 1 change) or `no_change` (none).

Patchable (`PATCHABLE_FIELDS`): title, observation, reasoning_summary, supporting_evidence, counter_evidence, interpretation,
alternative_explanations, confidence, limitations, management_significance, questions_for_management, suggested_investigations.
Everything else (`IMMUTABLE_RESULT_FIELDS`: contract_version, result_id, case_id, version, lifecycle_status, superseded_by,
source_snapshot_id, evidence_fingerprint, model_metadata, prompt_version, created_at, updated_at) is rejected with
`IMMUTABLE_FIELD`. Each changed value is validated against that field's result schema (`INVALID_FIELD_VALUE`), so a patched
claim still needs evidence. Other codes: `UNKNOWN_FIELD`, `DUPLICATE_CHANGE`, `FIELD_ACCOUNTING`, `ACTION_MISMATCH`; against the
result (`update_result_errors`): `IMMUTABLE_FIELD` (other case/result), `STALE_BASE_VERSION`, `EVIDENCE_FINGERPRINT_MISMATCH`; against
the case (`update_case_errors`): `CASE_MISMATCH`, `EVIDENCE_FINGERPRINT_MISMATCH`, `UNKNOWN_EVIDENCE_REF`.

### 3.4 Enums (`atlas_reasoning.enums`, mirrored in the schema and the database)

`SubjectType`, `CaseType`, `TopicKey`, `IdentityDimension`, `Direction`, `ConfidenceLevel`, `EvidenceLevel`, `StatementKind`,
`EvidenceRole`, `LifecycleStatus`, `GateAction`, `UpdateAction`, `NoteSource`, `QuestionState`, `ExpectedContextType`,
`MemoryStatus`, `TeachingScope`, `TeachingType`, `TeachingValidity`, `TeachingStatus`, `RunStatus`, `WorkKind`, `WorkStatus`,
`ResultChangeKind`, `LLMCallStatus`, `MemorySyncStatus`. Adding a value is a contract change.

### 3.5 Using the contracts

```python
from atlas_reasoning.contracts import ReasoningCase, ReasoningResult, ReasoningUpdate, ContractViolation, result_case_errors

case = ReasoningCase.from_dict(payload)        # schema + semantic validation, then typed, frozen objects
data = case.to_dict()                          # exact round trip
result = ReasoningResult.from_dict(llm_json)   # raises ContractViolation (with .codes) on any violation
problems = result_case_errors(result.to_dict(), case.to_dict())
```

## 4. Phase 03: canonical state in PostgreSQL

PostgreSQL is the canonical store of Reasoning V3 application state; Honcho (Phase 10) will only ever hold copies of context.
Every table lives in the PostgreSQL schema `atlas_reasoning`, so the database can be shared and a test database reset by dropping
one schema. Monday raw data is never copied here: evidence is referenced by Monday item, cycle and event IDs.

### 4.1 Setup

```bash
python3 -m pip install -r requirements-reasoning.txt          # psycopg 3 (also pulled in by requirements-dev.txt)
export ATLAS_REASONING_DATABASE_URL=postgresql://atlas@127.0.0.1:5432/atlas_reasoning   # or ..._URL_FILE=/run/secrets/<file>
PYTHONPATH=src python3 -m atlas_reasoning migrate             # idempotent; works with ATLAS_REASONING_V3 off
PYTHONPATH=src python3 -m atlas_reasoning db-health           # exit 0 only when reachable, fully migrated and untampered
```

Local development needs any PostgreSQL 14+ (`brew install postgresql@17`, or `docker run -e POSTGRES_PASSWORD=... -p 5432:5432
postgres:17`). Tests use a separate, disposable database: `ATLAS_REASONING_TEST_DATABASE_URL` (its name must contain `test`;
each test drops and re-creates the `atlas_reasoning` schema). Without it the database tests are skipped locally; CI runs a
`postgres:17` service and sets `ATLAS_REASONING_REQUIRE_DB_TESTS=1`, which turns a missing database into a failure. The
production sync image does not include psycopg until Reasoning V3 is rolled out (Phase 20); `psycopg` is imported only when a
database is opened.

### 4.2 Migrations

`src/atlas_reasoning/store/migrations/NNNN_<name>.sql`, applied in order, each in its own transaction under an advisory lock
(concurrent bootstraps apply each file once). `schema_migrations` records each file's SHA-256; a changed applied file is refused —
change the schema with a new file. **Number ranges** so parallel branches never collide: `0001–0099` foundation (this work),
`0100–0199` Chat 2 (Phases 07–09, 15, 17–18), `0200–0299` Chat 3 (Phases 10–14, 16).

### 4.3 Tables (`0001_reasoning_core.sql`)

| Table | Key | Purpose and main constraints |
|---|---|---|
| `reasoning_runs` | `run_id` (`run_…`) | One run over one `source_snapshot_id`, with upstream contract, V2, boundary, identity and fingerprint versions; status `started → gated → complete/partial/degraded/failed`; per-action counts |
| `reasoning_cases` | `case_id` (`rc1_…`), `identity_key` UNIQUE | Stable identity (`case_type`, `subject_type`, `subject_id`, `topic_key`, optional `video_type`/`workflow_stage`/`detector_family`/`signal`) — immutable by trigger; observation state: `last_evidence_fingerprint` (deferred FK to its evidence), `presence`, `absent_since_run_id`, `consecutive_absent_runs` |
| `reasoning_case_evidence` | (`case_id`, `evidence_fingerprint`) | Each distinct evidence state once: canonical evidence + the `ReasoningCase` document; append-only |
| `reasoning_case_observations` | (`run_id`, `case_id`) | The Change Gate decision and reason for every known case in every run; CHECKs tie action to fingerprints (unchanged ⇒ same fingerprint and no work; updated ⇒ different fingerprints and a delta; disappeared ⇒ no fingerprint); append-only |
| `reasoning_work_items` | `work_item_id` (`wi_…`) | Gate output for later phases: `new_result` / `update_result` (LLM) or `lifecycle`; partial UNIQUE: one open LLM item and one open lifecycle item per case; superseding links (deferred FK) |
| `reasoning_results` | `result_id` (`rr1_…`) | Result identity, `current_version` (deferred FK to the version row), lifecycle, supersession link; partial UNIQUE: one open result per case; `result_id`/`case_id`/`created_at` immutable |
| `reasoning_result_versions` | (`result_id`, `version`) | Full `ReasoningResult` document per version, the `ReasoningUpdate` that produced it, change kind (`created`/`patched`/`no_change_review`/`lifecycle`), provenance; CHECKs tie the JSON to the columns; append-only |
| `reasoning_evidence_links` | (`result_id`, `version`, `ref_id`) | Every evidence reference a version cites, resolvable to Monday item, cycle and event IDs and to the case evidence state; append-only |
| `manager_notes`, `manager_note_revisions` | `note_id` | Phase 12: attributed `manager_interpretation` notes; composite FK keeps a note's case equal to its result's case |
| `atlas_questions`, `atlas_answers` | `question_id`, `answer_id` | Phase 13: partial UNIQUE one open question per (case, dedup key); answers are `manager_answer`, append-only, with conflict links |
| `teachings`, `teaching_revisions` | `teaching_id` | Phase 14: scope, type, validity, status as CHECKed enums; company scope ⇔ no scope ID; date ranges ordered |
| `llm_calls` | `call_id`, `request_id` UNIQUE | Phase 06: provider-call metadata only (never prompts, responses or credentials); append-only |
| `memory_sync_log` | `sync_id` | Phase 10: one row per (source, session, operation, content hash); canonical rows are written first |

Every status column is a CHECK constraint whose values equal `atlas_reasoning.enums` (`tests/test_reasoning_store.py`).

### 4.4 Data access (`atlas_reasoning.store.repository`)

```python
store = ReasoningStore(Database(settings.database_url()))
with store.transaction() as tx:          # one transaction: everything in the block commits together or not at all
    run_id = tx.create_run(...)
    tx.insert_case(...); tx.put_case_evidence(...); tx.record_observation(...); tx.create_work_item(...)
    tx.create_result(result)             # result + version 1 + evidence links, validated against its case
    tx.append_result_version(new_version, expected_version=n, change_kind=..., update=...)   # VersionConflict on a race
store.get_result(result_id, version=None); store.result_history(result_id); store.case_debug(case_id)
```

The store validates every result version against reasoning-v1 and against its case's stored evidence state, and checks what a new
version may change: identity and `created_at` never; a patch exactly its listed fields (to exactly their values,
`PATCH_NOT_APPLIED` / `UNPATCHED_FIELD_CHANGED`); a no-change review and a lifecycle version no patchable field. Errors:
`NotFound`, `VersionConflict`, `ResultConflict`, `CaseIdentityCollision`, `EvidenceCollision`, `ContractViolation`.

Debug: `python -m atlas_reasoning case <case_id> | result <result_id> | run <run_id>`.

## 5. Phase 04: stable case identity

`case_id` answers *what management issue is this about?* — never *what does the data look like now?*. It is computed by Python
(`atlas_reasoning.case_identity`), never by an LLM, from:

| Dimension | Source | Example |
|---|---|---|
| `subject_type` | the finding's scope kind (`editor`, `team`, `video_type`, `workflow_stage` (V2 `stage`), `project`, `data_source` (V2 `data`)) | `editor` |
| `subject_id` | the scope's Editor ID, Video Type key, stage, Monday item ID, `team`, or `monday` for data warnings | `editor-label-12` |
| `topic_key` | the topic rule of the finding type (`case_mapping.TOPIC_RULES`) | `deadline` |
| optional `video_type`, `workflow_stage`, `detector_family`, `signal` | only where the rule makes it part of the topic: `signal` for open-work risk signals and for each data warning code | `signal=past_eta` |

Excluded, always: rates, counts, sample sizes, dates and windows, confidence, rank, severity, wording, finding order, Intelligence
V2 `finding_id` (it hashes the analysis window and changes daily), evidence values, request IDs and LLM output.

**Construction.** Each component is normalized (NFC, whitespace collapsed and trimmed, lower case; empty is an error), percent-
encoded and joined into `identity_key` = `case-identity-v1|<subject_type>|<subject_id>|<topic_key>[|<dimension>=<value>…]` (fixed
dimension order; the encoding is injective). `case_id = "rc1_" + sha256(identity_key)[:32]`. Both, and every dimension, are stored
in `reasoning_cases` for debugging. A case whose `case_id` or `identity_key` does not follow from its own dimensions fails the
contract (`CASE_ID_MISMATCH`, registered in `contracts.CASE_CHECKS`).

**Collisions.** Within a run, two identity keys with one `case_id` stop the run (`CaseIdentityCollision`); the database refuses a
`case_id` or `identity_key` already held by another identity. Nothing is ever merged silently.

**Topic rules** (`TOPIC_RULES`, `case-mapping-v1`):

| Finding type(s) | Topic |
|---|---|
| `change.editor`, `change.team`, `change.video_type` | by `measure`: `late_rate` → deadline, `median_execution` → speed, `negative_label_rate` → quality |
| `person.mix_adjusted_deadline`, `contradiction.bad_headline`, `pattern.repeated_delay`, `pattern.time` | deadline |
| `concentration.negative` / `.positive` | by `outcome`: (not) late delivery → deadline; negative/positive label → quality |
| `pattern.shared_across_editors` | by `measure`: late delivery → deadline; short runway → runway |
| `editor.speed_pattern` | speed |
| `editor.label_pattern`, `pattern.repeated_quality` | quality |
| `workload.association`, `workload.overload_pattern` | workload |
| `bottleneck.pre_editor_runway` | runway (subject: stage `pre_editor`) |
| `bottleneck.post_editor` | post_editor_delay |
| `workflow.time_map` | workflow_time |
| `contradiction.metric_conflict` | component_conflict |
| `contradiction.hidden_risk` | hidden_signal |
| `risk.open_work` | open_work_risk + `signal` (case type `open_work_risk`) |
| `risk.historical_similarity` | open_work_risk, subject = the project (case type `project_risk`) |
| `data.<code>` | data_quality + `signal=<code>` (case type `data_quality`) |

`case_type` follows the subject (`editor_pattern`, `team_pattern`, `video_type_pattern`, `workflow_pattern`, `project_risk`,
`data_quality`) unless the rule names one. A finding of an unknown type, or with a parameter value its rule does not know, is
reported in `CaseMapping.unmapped` with the reason — never guessed. A test requires a rule for every registered detector.

**Many findings, one case.** All findings with the same identity form one case: in the showcase snapshot, Editor
`editor-label-12`'s deadline case holds two late-rate changes (against history and against the comparison window), the mix-adjusted
lateness, an on-time concentration and the contradiction that qualifies the late headline. Within a case each finding has a
**member key** (type, scope, categorical discriminators such as `measure`/`against`/`outcome`, supporting evidence kinds, first
statement code): stable while the finding reports the same thing, whatever its values or window.

**New case vs update.** A new case exists exactly when subject, topic or a rule-declared dimension differs. Different findings
within the topic, new evidence, new values, new confidence or a moved window update the existing case (Phase 05 decides whether
that is material). Changing the rules requires a new `IDENTITY_VERSION`; `fixtures/reasoning/case-identity-showcase.json` pins every
identity of the showcase snapshot so an accidental rule change fails CI.

**Replay.** Rebuilding the showcase snapshot with the analysis windows moved forward 1 and 7 days changes every Intelligence V2
`finding_id` (0 of 30 reused) while every issue still present keeps its `case_id` (15 of 17 cases persist with identical IDs; the
other two left the window).

## 6. Phase 05: evidence fingerprint, material delta and the Change Gate

### 6.1 Evidence fingerprint (`fingerprint`)

`canonical_evidence(case_document)` derives, from the `ReasoningCase` document alone, exactly what is hashed:

- **included**, per contributing finding (keyed by member key): type, direction, category, evidence level, upstream confidence level,
  sample size, limitation codes, every statement's parameters (the metric values), every evidence block's sample, comparison and
  exclusions, every evidence record (Monday item, cycle, Editor, Video Type, event IDs, source timestamps, values used); plus the
  case orientation;
- **excluded**: generated prose, V2 `finding_id` and rank, analysis-window dates, snapshot/release IDs, `created_at` and other
  operational timestamps (`retrieved_at`, `generated_at`, …), request IDs, display names (`editor_name`, `group_label`, `cohort_label`), previous
  LLM wording, manager and memory context;
- **normalized**: keys sorted; event IDs, timestamps, limitations and exclusions sorted; statements read in canonical order
  (evidence level, code); floats rounded to 6 decimals; compact key-sorted JSON.

`evidence_fingerprint = "ef1_" + sha256(canonical JSON)`. A case whose fingerprint does not match its own evidence fails the
contract (`FINGERPRINT_MISMATCH`), so any holder can verify it. Tested: same snapshot → same fingerprints; findings, statements,
records, event IDs and limitations shuffled → same; renamed Editors, moved windows, new snapshot ID, new finding IDs, new wording →
same.

### 6.2 Material delta (`delta.material_delta(before, after)`)

Computed from two canonical evidence documents; every difference appears in at least one list, so the delta is empty exactly when
the fingerprints are equal (property-tested):

| Field | Content |
|---|---|
| `added_findings`, `removed_findings` | member keys joining / leaving the case |
| `added_evidence`, `removed_evidence` | supporting/context records: `ref_id`, member, role, evidence code, Monday item, cycle |
| `changed_values` | every other changed leaf with `path`, `before`, `after` (statement parameters such as `statements/metric:late_rate_changed/current`, block samples/comparisons, record values, limitations, direction, sample size) |
| `changed_confidence` | upstream confidence level per finding, before/after |
| `added_contradictions`, `removed_contradictions` | contradicting evidence records (`kind: evidence`) and findings that started/stopped opposing the orientation (`kind: finding`) |
| `orientation_change` | before/after when the case orientation flipped |

### 6.3 Change Gate (`change_gate.run_gate(payload, store)`)

| Decision | Condition | Reason codes | Work item |
|---|---|---|---|
| `new` | case_id never observed | `first_observation` | `new_result` (LLM) |
| `unchanged` | same fingerprint as last observed | `same_evidence_fingerprint`, `reappeared_same_evidence` | **none** |
| `updated` | different fingerprint | `evidence_changed`, `reappeared_evidence_changed` | `update_result` with the delta from the open result's evidence (`fingerprint_before` = what the result says); `new_result` when there is no open result; none (and a pending item cancelled) when the evidence is back to the result's state |
| `disappeared` | known case absent from the snapshot | `not_in_snapshot` (first run absent), `still_absent` (with `absent_runs`) | `lifecycle` (no LLM) the first time; the result is never deleted or resolved by the gate |

- The whole gate runs in one transaction under an advisory lock (concurrent gates serialize), recording the run, new cases, each
  new evidence state once, one observation per known case (decision, reason code, detail, fingerprints, delta) and the work items.
- At most one open LLM work item per case: newer evidence supersedes a *pending* item, keeping the older base so the delta always
  starts from what the open result says. An item already `in_progress` is never superseded (the decision records it as deferred).
  Work-item status changes follow `WORK_TRANSITIONS` (`WorkTransitionError` otherwise).
- Each LLM work item stores the case document of the run that created it, so its snapshot ID and V2 finding IDs resolve in that
  run's Intelligence V2 document (evidence states are stored once per fingerprint, documents per work item).
- A case present again cancels its pending `lifecycle` item. Pending LLM work of a case that disappears is left to the lifecycle /
  reliability phases.
- `unchanged` never creates work, even when an earlier item failed or was cancelled. `StoreTransaction.unreasoned_cases()` lists
  present cases whose current evidence has neither an open result reasoned on it nor open LLM work: the resume phase (18) uses it.
- **Running the same snapshot twice creates no work item at all on the second run** (`test_same_snapshot_twice_creates_zero_work_on_the_second_run`).
- `case_for_work(tx, work_item)` returns the exact `ReasoningCase` for a work item: the evidence state it targets, with
  `previous_result_id/version` and the material delta (validated, fingerprint verified). Phases 07/08 use it as their input.

Commands: `python -m atlas_reasoning inspect <site_dir>` (cases, members, fingerprints; no database, flag not needed);
`python -m atlas_reasoning gate <site_dir>` (requires `ATLAS_REASONING_V3=on`); `python -m atlas_reasoning run <run_id>` (the
persisted decisions).

## 7. Phase 06: the provider gateway (GPT-5.6 Sol through OpenRouter)

Transport only: no prompt, no reasoning, no merge. Domain modules (contracts, identity, mapping, fingerprint, delta, Change Gate,
store) neither import the gateway nor mention OpenRouter (`tests/test_reasoning_gateway.py::IsolationTests`).

```python
from atlas_reasoning import settings
from atlas_reasoning.gateway import ReasoningGateway
from atlas_reasoning.openrouter_client import OpenRouterTransport
from atlas_reasoning.provider import CallContext, Message, ProviderRequest, ProviderError
from atlas_reasoning.store.calls import StoreCallRecorder
from atlas_reasoning.structured import contract_output

router = settings.openrouter_settings()
gateway = ReasoningGateway(OpenRouterTransport(router), settings.gateway_settings(), recorder=StoreCallRecorder(store),
                           secrets=(router.api_key,))
request = ProviderRequest(CallContext(purpose="analyst", run_id=..., case_id=..., work_item_id=..., prompt_version="analyst-v1",
                                      source_snapshot_id=..., evidence_fingerprint=...),
                          (Message("system", ...), Message("user", ...)), contract_output("reasoning-update-v1.schema.json"))
response = gateway.call(request)               # response.parsed is validated JSON, or a ProviderError subclass is raised
outcomes = gateway.call_many([request_a, request_b, request_c])   # one CallOutcome per request; failures are isolated
```

| Concern | Behaviour |
|---|---|
| Configuration | Environment only (`settings`): `OPENROUTER_API_KEY` or `OPENROUTER_API_KEY_FILE`; `ATLAS_REASONING_MODEL` must equal the pinned `openai/gpt-5.6-sol` unless `ATLAS_REASONING_ALLOW_MODEL_OVERRIDE=on`; `ATLAS_REASONING_OPENROUTER_BASE_URL` (https; plain http only to 127.0.0.1/localhost/::1 for local test servers); bounded limits below. The key is excluded from every `repr` |
| Model | `settings.PINNED_MODEL = "openai/gpt-5.6-sol"` (OpenRouter slug verified 2026-10-01; supports structured outputs) |
| Structured output | `response_format: json_schema` (strict) with `provider.require_parameters: true`; the schema is the reasoning-v1 contract with `$ref`s inlined (`structured.contract_output`); the response is always re-validated locally against the real contract schema |
| Raw reasoning | requested with `reasoning.exclude: true`; never stored or returned |
| Timeouts | `ATLAS_REASONING_LLM_TIMEOUT_SECONDS` per attempt (default 120, 5–600) |
| Retries | `ATLAS_REASONING_LLM_MAX_RETRIES` after the first attempt (default 3, 0–6); only retryable errors |
| Backoff | `ATLAS_REASONING_LLM_BACKOFF_SECONDS` × 2^(retry−1) plus ≤ 25 % jitter, capped by `ATLAS_REASONING_LLM_MAX_BACKOFF_SECONDS` (default 2 s, 60 s) |
| Rate limits | HTTP 429 → `rate_limited`, retried after `max(backoff, Retry-After)` (capped) |
| Concurrency | `ATLAS_REASONING_LLM_CONCURRENCY` provider attempts in flight across all callers (default 4, 1–32); a slot is released while waiting to retry |
| Request IDs | `req_<32 hex>` per call unless the context names one (a caller-supplied ID must be unique per logical call: `llm_calls.request_id` is unique, and a duplicate's metadata is only logged); sent as `X-Request-Id`; recorded |
| Logs | logger `atlas_reasoning.gateway`: request ID, purpose, model, case ID, attempt, error class, status; never prompts, responses or credentials (redacted again before logging) |
| Call metadata | one `llm_calls` row per call: run, case, work item, request ID, provider, model, purpose, prompt version, snapshot, fingerprint, status, provider status, error class, attempts, retries, latency, input/output tokens, provider response ID. A recording failure is logged and never loses the result |
| Failure isolation | `call_many` returns one outcome per request; a provider error or even a transport bug (`internal_error`) in one case never affects another |

Error taxonomy (`provider.ProviderError.error_class`; retryable marked ✓): `timeout` ✓, `rate_limited` ✓, `provider_unavailable`
✓ (5xx, `finish_reason=error`), `network_error` ✓, `malformed_response` ✓, `invalid_structured_output` ✓, `authentication` (401),
`quota_exceeded` (402), `bad_request` (400/404/413/422), `content_filtered` (403, `finish_reason=content_filter`), `truncated`
(`finish_reason=length`), `configuration`, `internal_error`.

Health check: `python -m atlas_reasoning provider-health --dry-run` validates configuration without any network call;
`python -m atlas_reasoning provider-health [--record]` makes one minimal structured call to the pinned model (only when an operator
runs it). CI never makes a live call: tests use `fake_provider.FakeProvider`, an injected HTTP function, or a local HTTP server.

## 8. Stable public interfaces

Later phases build on these. They are covered by tests and documented here; change them only together with their tests and a
note in this section.

| Interface | Module | Use |
|---|---|---|
| `build_reasoning_input`, `load_reasoning_input`, `ReasoningInput` and its parts | `reasoning_input_boundary` | The only way to read Atlas |
| `ReasoningCase`, `ReasoningResult`, `ReasoningUpdate` (`from_dict`, `to_dict`, `validated`) | `contracts` | Construct and validate the three objects |
| `case_errors`, `result_errors`, `update_errors`, `result_case_errors`, `update_result_errors`, `update_case_errors`, `ContractViolation` | `contracts` | Validation with stable error codes |
| `PATCHABLE_FIELDS`, `IMMUTABLE_RESULT_FIELDS`, `new_result_id`, `evidence_ref_id` | `contracts` | Patch rules and identifiers |
| All enums | `enums` | Shared vocabulary (also the DB CHECKs) |
| `build_identity`, `CaseIdentity`, `IDENTITY_VERSION` | `case_identity` | Deterministic case identity |
| `map_cases`, `map_findings`, `CaseMapping`, `CaseCandidate`, `TOPIC_RULES` | `case_mapping` | Findings → cases |
| `canonical_evidence`, `evidence_fingerprint`, `FINGERPRINT_VERSION` | `fingerprint` | Evidence state |
| `material_delta`, `is_empty`, `summary` | `delta` | What changed |
| `run_gate`, `GateReport`, `prepare_cases`, `case_for_work` | `change_gate` | Gate and work-item input |
| `ReasoningStore`, `StoreTransaction` (runs, cases, evidence, observations, work items, results, versions, evidence links, LLM calls), exceptions | `store.repository` | Canonical state |
| `Database`, `apply_migrations`, `database_health` | `store.db`, `store.migrate`, `store.health` | Infrastructure |
| `ReasoningGateway`, `CallOutcome`, `CallRecord`, `MemoryRecorder` | `gateway` | Provider calls |
| `ProviderRequest`, `CallContext`, `Message`, `StructuredOutput`, `ProviderResponse`, `ProviderError` and subclasses, `Transport` | `provider` | Provider-neutral types |
| `contract_output`, `schema_output`, `inline_schema` | `structured` | Structured output |
| `FakeProvider`, `FakeReply`, `FakeError` | `fake_provider` | Offline tests |
| `StoreCallRecorder` | `store.calls` | Persist call metadata |
| `settings.reasoning_enabled`, `require_enabled`, `gateway_settings`, `openrouter_settings`, `database_url` | `settings` | Configuration |

**Do not depend on** (internal, may change): SQL text and table internals beyond the documented columns (use the repository);
`StoreTransaction._exec/_one/_all`; private helpers (`_finding`, `_param`, `_leaves`, …); the exact text of error messages (use
error codes and classes); the internal shape of `canonical_evidence` beyond "hashing it gives the fingerprint" (use
`material_delta`); `OpenRouterTransport.body`; the member-key string format (treat it as opaque, compare for equality);
`fixtures/reasoning/*` examples (regenerated from `tests/reasoning_factory.py`).

## 9. Ownership after the foundation

| Owner | Phases | Builds on | Adds (migrations in its range) |
|---|---|---|---|
| Chat 2 | 07–09, later 17 (and 15, 18 when assigned) | `change_gate.case_for_work`, work items (`new_result` / `update_result` / `lifecycle`), `StoreTransaction.create_result` / `append_result_version` (change kinds `created`, `patched`, `no_change_review`, `lifecycle`), `ReasoningGateway` + `contract_output`, observations' reason codes (`reappeared_same_evidence` for lifecycle) | prompts, analyst/update orchestration, patch merger, lifecycle policy; migrations `0100`–`0199` |
| Chat 3 | 10–14, 16 | `manager_notes`, `atlas_questions`, `atlas_answers`, `teachings`, `memory_sync_log` tables; `ReasoningCase.manager_context` / `memory_context`; `NoteSource`, `QuestionState`, `Teaching*` enums; read APIs of the store | Honcho client, memory assembler, notes/Q&A/Teach Atlas services and UI, reasoning-first dashboard; migrations `0200`–`0299` |

Rules for both: never write to upstream Atlas; read Atlas only through `reasoning_input_boundary`; never let an LLM set
`case_id`, a fingerprint, a gate decision or a lifecycle status; persist to PostgreSQL before any memory sync; keep
`ATLAS_REASONING_V3` off-by-default behaviour byte-identical (`tests/test_reasoning_boundary.py`).

## 10. Phase 07: the analyst reasoning engine (new cases)

One bounded `ReasoningCase` (a `new_result` work item, `change_gate.case_for_work`) becomes one `ReasoningResult` version 1.

| Concern | Behaviour |
|---|---|
| Prompt | `src/atlas_reasoning/prompts/analyst-v1.md`, `analyst.ANALYST_PROMPT_VERSION = "analyst-v1"`; a test pins its SHA-256, so the text cannot change without a new version. Rules: use only the case; no invented numbers, people, projects, events or metrics; cite `ref_id`s; keep observation / supporting / counter-evidence / interpretation / alternatives (hypotheses needing context: `requires_context`) / limitations apart; handle counter-evidence; confidence never above the upstream ceiling; ask management when context is missing; no HR, personality, health, salary, termination or unsupported blame judgements; `reasoning_summary` is an explicit summary, never hidden reasoning |
| Input | `analyst.analyst_input(case)`: identity (no `case_id`), scope, orientation, findings, typed statements, evidence blocks, citable references, manager and memory context, evidence provenance. Canonical order and compact key-sorted JSON; volatile values (V2 finding IDs and ranks, snapshot ID, case creation time, event IDs) are left out, so equivalent cases give byte-identical prompts. Larger than `MAX_INPUT_CHARS` (400 000, about 100k tokens; the largest showcase case is about 152 000) → `CaseTooLarge`, never truncated |
| Output | The model returns only the analyst fields (`PATCHABLE_FIELDS`), strict structured output (`analyst.analyst_output_schema()`, taken from `reasoning-result-v1`). Python adds `result_id`, `case_id`, version 1, lifecycle `new`, snapshot, fingerprint, `model_metadata` (provider, answering model, request ID), `prompt_version`, timestamps. Any other field (an ID, a lifecycle, `chain_of_thought`, …) is `UNKNOWN_FIELD` |
| Validation | Inside the gateway call (so failures are retried within its bounds and recorded): field set, `ReasoningResult.errors`, `result_case_errors` (only the case's references, counter-evidence when contradicted, confidence ceiling), `output_checks.unsupported_number_errors` (`UNSUPPORTED_NUMBER`: every number in visible text is a case value, optionally as a percentage, at the precision written). Re-validated before persisting |
| Model | The answering model must be the configured one (pinned `openai/gpt-5.6-sol`); anything else fails the item (`work:MODEL_SUBSTITUTED`) |
| Persistence | `engine.ReasoningEngine`: claim (`pending → in_progress`), one gateway call per item via `call_many`, then `create_result` + evidence links + `done` in one transaction. Any failure rolls back and marks only that item `failed` (`provider:<class>`, `contract:<codes>`, `work:<code>`, `store:<error>`) |

Command: `python -m atlas_reasoning reason <run_id>` (needs `ATLAS_REASONING_V3=on`, the OpenRouter key and the database) processes
every pending work item and prints the engine report. Tests: `tests/test_reasoning_analyst.py` (fake transport `tests/reasoning_fakes.py`).

## 11. Phase 08: update-only reasoning and the patch merge

An existing result is patched, never regenerated. An `update_result` work item — or a `new_result` item for a case that has an open
result by the time it is processed — becomes an update of the open result's **current** version.

| Step | Behaviour |
|---|---|
| Input (`updater.update_input`) | Previous result's patchable fields and version; `fingerprints` before (the result's) and after (the work item's); the exact `material_delta` between the two stored evidence states (equal to the gate's delta); the current case evidence and context (same canonical view as the analyst); `fields_requiring_change` (below). No case or result ID |
| Required changes (`updater.required_changes`, deterministic) | A field must change when it cites a `ref_id` no longer in the case (`cites_evidence_no_longer_in_the_case`), quotes a number the current evidence no longer carries (`uses_numbers_no_longer_in_the_case`), exceeds the new confidence ceiling, or the case gained counter-evidence the card ignores |
| Prompt | `prompts/update-v1.md`, `UPDATE_PROMPT_VERSION = "update-v1"`, separate from the analyst prompt, SHA-256 pinned. Change a field only when the evidence change makes it wrong, stale, unsupported or materially incomplete; never reword untouched fields; account for every field; explain the change |
| Output (`updater.update_output_schema`) | `action` (patch / no_change), `change_rationale`, `changed_fields`, `preserved_fields`, `patch` (every patchable field, null unless changed). Nothing else: an identity, version, fingerprint or lifecycle cannot be expressed |
| ReasoningUpdate | Python builds it (`build_update`): case, result, `base_version` and fingerprints are Python's; validated with `update_errors` (field accounting, `IMMUTABLE_FIELD`, `UNKNOWN_FIELD`, `ACTION_MISMATCH`, `INVALID_FIELD_VALUE`), `update_result_errors`, `update_case_errors`, plus `PATCH_VALUE_MISMATCH` (a value exactly for each changed field) and `REQUIRED_CHANGE_MISSING` |
| Merge (`patch.merge`, Python) | Changed fields replaced as whole fields; every other patchable field copied from the previous version (byte-identical wording); `contract_version`, `result_id`, `case_id`, `created_at`, `superseded_by` copied; version + 1, fingerprint, snapshot, model metadata, prompt version and `updated_at` set by Python; lifecycle chosen by the lifecycle policy (Phase 09), never by the model. The merged version is validated like a new result (contract, case, numbers) |
| No-op | `no_change` appends a `no_change_review` version: every patchable field identical, provenance advanced to the reviewed evidence (so later deltas start from it and the case is not reported as unreasoned); the previous version is never touched |
| Persistence | `StoreTransaction.append_version_with_diff`: the version (optimistic concurrency on the version read), its evidence links, the `ReasoningUpdate`, the before/after diff (`reasoning_result_diffs`, migration `0100_result_diffs.sql`) and the work item's `done` — one transaction. Any failure (invalid patch, `VersionConflict`, store error) rolls back everything; the item is `failed` and the result stays at its previous version |

Every check runs inside the gateway call, so an invalid patch is retried within the gateway's bounds; the merge is re-validated
before persisting. Tests: `tests/test_reasoning_update.py` (field isolation, immutable and unknown paths, accounting, required
changes, no-op byte preservation, version history and diffs, rollback, concurrent writer, and the stability property: same evidence
→ no reasoning, changed evidence → patch of the same result, new topic → new result, never two results for one case).
