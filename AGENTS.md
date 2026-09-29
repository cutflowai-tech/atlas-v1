# Atlas agent instructions

The Commander reads `SPEC.md`, `ARCHITECTURE.md`, `CONTRACTS.md`, `TASK_GRAPH.md`, and `docs/ATLAS_V1_RULES.md` before planning work. Builders receive only the atomic task packet, this file, named affected contracts, and the minimum referenced architecture/rule sections needed for that task.

## Execution invariant

Parallelize implementation; serialize integration. Each candidate works in its own worktree and branch. Builders do not coordinate toward a shared solution before producing independent evidence. The arbiter selects or composes a winner. The integrator alone moves accepted changes through `integration`, CI/E2E, and then `main`.

## Definition of done

Every change must include tests, evidence for metric outputs, deterministic behavior, and a note for any contract/schema impact. Never claim completion from a prose review alone. Run the task-specific target during development and `make test` before integration handoff.

## Product invariants

- Monday is the source of truth.
- The Editor is the evaluated entity.
- Work duration is `In Progress` to `Ready For Approval`.
- Deadline delta is `first Ready For Approval − Requested ETA in effect then`: negative is early, zero is on time, positive is late, with no tolerance; missing ETA is not guessed.
- Benchmarks compare only within the same Video Type.
- Waset Co actor attribution is deterministic.
- Revisions are context only, never an automatic quality penalty.
- Quality comes from Monday labels.
- Every metric exposes supporting evidence.
- AI may explain or flag; AI is never the source of truth.
