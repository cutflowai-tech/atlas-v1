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
