# Atlas V1 Engineering Swarm

This repository is the executable control plane for Atlas V1. It uses isolated Git worktrees, independent builders, explicit validators, and a serialized integration lane.

The operating rule is **parallelize implementation, serialize integration**.

## Start here

```bash
make doctor
make test
./scripts/atlas classify --title "Add editor throughput metric" --business-rules
./scripts/atlas fanout ATLAS-001 --risk critical
./scripts/atlas ready
```

Read [docs/SWARM.md](docs/SWARM.md) for the end-to-end runbook and [docs/ATLAS_V1_RULES.md](docs/ATLAS_V1_RULES.md) for non-negotiable product rules.

## Branches

- `main`: releasable, CI-green state only.
- `integration`: the single merge lane for accepted work.
- `task/<id>/<slot>`: one isolated candidate implementation or validation branch.

Do not let builders share a worktree. Do not merge candidate branches directly to `main`.

