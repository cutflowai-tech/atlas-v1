# Atlas V1 Engineering Swarm

This repository is the executable control plane and contract baseline for Atlas V1, an internal Editor Performance Intelligence System built from Monday.com evidence. It uses isolated Git worktrees, independent builders, explicit validators, and a serialized integration lane.

The operating rule is **parallelize implementation, serialize integration**.

## Start here

```bash
python3 -m pip install -r requirements-dev.txt
make doctor
make test
./scripts/atlas classify --title "Add editor throughput metric" --business-rules
./scripts/atlas ready
```

Read [SPEC.md](SPEC.md), [ARCHITECTURE.md](ARCHITECTURE.md), [CONTRACTS.md](CONTRACTS.md), and [TASK_GRAPH.md](TASK_GRAPH.md) before execution. The operational runbook is [docs/SWARM.md](docs/SWARM.md), and [docs/ATLAS_V1_RULES.md](docs/ATLAS_V1_RULES.md) contains non-negotiable product rules.

## Run the dashboard locally (synthetic data)

```bash
make demo
```

This builds every Editor Profile and the bilingual CEO Dashboard from synthetic, Monday-shaped data with the same builders production uses, then serves `out/demo` at <http://127.0.0.1:8000> (`/en/` and `/ar/`; `make demo DEMO_PORT=8765` if 8000 is taken). It needs no Monday token and makes no network request. `python3 -m atlas_commander.demo build --out <dir>` only writes the files. The production path (read-only sync, staged build, atomic publish, status) is `python3 -m atlas_sync`; see `docs/PRODUCTION-RUNBOOK.md`.

## Launch the first real Atlas vertical slice

From this repository, dispatch exactly one mission to the existing Commander:

```bash
multica issue create \
  --title "Atlas V1: first real Editor vertical slice" \
  --assignee "Atlas Commander" \
  --priority high \
  --description "Use the repository authoritative docs and tasks/dag.json. Confirm ARCH-001 and ARCH-002 remain green, then run DATA-001 against real Monday data for one known Editor. In parallel dispatch every READY fixture task. Prioritize normalization -> deterministic actor attribution -> work-cycle reconstruction -> real metric validation -> evidence API -> Editor Profile E2E. Preserve Monday evidence, use integration only, and do not promote to main until the complete required CI gate passes."
```

The Commander must classify and dispatch from `tasks/dag.json`; do not manually fan out the whole vertical slice as one coding task.

## Branches

- `main`: protected releasable state; promotion only by pull request from `integration` with required CI.
- `integration`: the single merge lane for accepted work.
- `task/<id>/<slot>`: one isolated candidate implementation or validation branch.

Do not let builders share a worktree. Do not merge candidate branches directly to `main`.

## Read-only Monday ingestion

```bash
MONDAY_API_TOKEN=<read-only token> PYTHONPATH=src python3 -m atlas_commander.ingest \
  --since 2026-02-01T00:00:00Z --raw-dir ~/.atlas/raw/monday/<run-id>
```

The command:
- issues only GraphQL queries; the client rejects mutations before any request is sent;
- writes every raw response once, read-only, outside git;
- produces `extract.json` (the pipeline input) and `manifest.json` (window, per-window page counts, SHA-256 of every raw file, and which items have provably complete history).

Without `MONDAY_API_TOKEN` it stops with `MISSING_ACCESS` and writes nothing.

Before using a run, verify it offline (it rechecks every SHA-256, window completeness below the API cap, window tiling, duplicate log IDs, item snapshots and history-completeness claims):

```bash
PYTHONPATH=src python3 -m atlas_commander.ingest_verify ~/.atlas/raw/monday/<run-id>
```

`scripts/compare_profiles.py <reference.json> <new.json>` lists per-project differences between two Editor Profiles. The full live-validation procedure is in `docs/evidence/REAL-003-OPERATIONAL-VALIDATION.md`.

## Editor Profile (V1)

Build an evidence-backed profile for one verified Editor from a read-only Monday extract:

```bash
PYTHONPATH=src python3 -m atlas_commander.profile_cli list <extract.json>
PYTHONPATH=src python3 -m atlas_commander.profile_cli build <extract.json> editor-label-6 out/ \
  --monday-item-url "https://<account>.monday.com/boards/<board>/pulses/{item_id}"
```

The output is `out/<editor_id>.json` (contract `editor-profile-v1.4` under the active contract 1.4.0; `--contract 1.3.0` reproduces `editor-profile-v1.3`) and a static `out/<editor_id>.html`.

- The page only formats values computed by the deterministic engine.
- There is no composite score. Revisions are shown as context only.
- Every project row lists its Monday event IDs.
- Editors that cannot be verified have no profile.

## CEO Dashboard (V1 shell)

Build every Editor Profile and the management dashboard from one extract:

```bash
PYTHONPATH=src python3 -m atlas_commander.profile_cli dashboard <extract.json> out/ \
  --monday-item-url "https://<account>.monday.com/boards/<board>/pulses/{item_id}"
```

This writes three things:
- `out/profiles/<editor_id>.json|.html`: the same `build_editor_profile` output as `build`, for every Editor with attributed projects;
- `out/dashboard.json`: the dashboard document (`ceo-dashboard-v0.1`);
- `out/dashboard.html`: a self-contained page with three areas:
  - **Editor team:** management focus, Editor cards, Team Pulse timeline, context cards, performance history.
  - **Editor profile** for each Editor: header, four metric cards, pill sections, performance timeline, evidence drawers.
  - **Data & System:** snapshot, rules, identities, data-quality notes, attribution coverage.

  Each full Editor Profile report is kept, unchanged, as the audit view.

The dashboard is organised in three layers:
- **Metric engine** (`cycles`, `metrics`, `quality`, `pipeline`): unchanged.
- **Summary layer** (`dashboard.py`, `dashboard_html.py`): reads only Editor Profile documents. Every figure names the profile field it comes from.
- **Management rules** (`management.py`): holds the not-yet-approved rules, such as overall status, score, needs-attention, trend, workload capacity and recommendations. Each is shown as "Rule not approved yet" and never gets a value until a rule is approved in a new contract version.
- **Contract 1.5.0 interpretation layer (inactive candidate):** with `--contract 1.5.0` the profiles and pages add the D23–D51 layer (Overall Status lookup, component states and reasons, Recent Change, Cairo windows, evidence drill-down) from `interpretation_policy.py`, `intelligence.py` and `interpretation_html.py`. Production stays on 1.4.0; see `docs/CONTRACT-1.5-ACTIVATION.md` before any activation.

Write the output outside git, like the raw extract: it contains real Monday data.
