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
