# Swarm runbook

## Risk routing

| Risk | Independent builders | Validation | Integration |
|---|---:|---:|---|
| Simple | 1 | 1 reviewer | Integrator after tests |
| Normal | 2 | 1 test/reviewer | Arbiter, then integrator |
| Critical business logic | 3 across Codex/Claude families | 2 validators | Arbiter, integrator, CI/E2E |

Critical means a change affects deterministic business rules, attribution, metric formulas, source-of-truth behavior, schema compatibility, money, access control, or destructive migration.

## Lifecycle

1. Commander writes a task with acceptance tests, affected contracts, risk, dependencies, and evidence requirements.
2. `./scripts/atlas fanout TASK-ID --risk <level>` creates isolated branches and worktrees from `integration`.
3. Independent builders implement without sharing code or conclusions.
4. Reviewers/validators inspect candidate diffs and run tests. Critical tasks require validators from different model families where available.
5. Arbiter records the selected candidate and reasons in `.atlas/runs/TASK-ID/decision.json`.
6. Integrator merges only the accepted branch(es) into `integration`, resolves conflicts, and runs `make test` plus E2E.
7. Only a green `integration` is promoted to `main`.

## Runtime pool

- `Atlas Codex A`, `Atlas Codex M`, `Atlas Codex W`: builders, reviewers, validators, arbiter/integrator.
- `Atlas Claude A`: independent cross-family builder/validator.
- `Atlas Claude M`: configured but must pass `./scripts/runtime-health` before assignment.
- Hermes: audit/research/memory/documentation only; never a required coding dependency.

## Queue and DAG

Tasks live in `tasks/dag.json`. A task is READY only when its status is `todo`, every dependency is `done`, and no unresolved contract-owner gate exists. `./scripts/atlas ready` prints the current queue. Status transitions are `todo -> ready -> in_progress -> in_review -> done` (or `blocked`).

## Useful commands

```bash
./scripts/atlas doctor
./scripts/atlas classify --title "..." [--business-rules] [--schema] [--security]
./scripts/atlas fanout ATLAS-001 --risk normal
git worktree list
make test
```

