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
| `orientation` | Direction of the highest-ranked adverse/favourable finding (`mixed`/`neutral` when none) |
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
