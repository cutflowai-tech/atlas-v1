# Atlas agent instructions

Read `docs/ATLAS_V1_RULES.md` before changing product logic, schemas, metrics, or contracts.

## Execution invariant

Parallelize implementation; serialize integration. Each candidate works in its own worktree and branch. Builders do not coordinate toward a shared solution before producing independent evidence. The arbiter selects or composes a winner. The integrator alone moves accepted changes through `integration`, CI/E2E, and then `main`.

## Definition of done

Every change must include tests, evidence for metric outputs, deterministic behavior, and a note for any contract/schema impact. Never claim completion from a prose review alone. Run `make test` before handoff.

## Product invariants

- Monday is the source of truth.
- The Editor is the evaluated entity.
- Work duration is `In Progress` to `Ready For Approval`.
- Deadline and Requested ETA are distinct fields and concepts.
- Benchmarks compare only within the same Video Type.
- Waset Co actor attribution is deterministic.
- Revisions are context only, never an automatic quality penalty.
- Quality comes from Monday labels.
- Every metric exposes supporting evidence.
- AI may explain or flag; AI is never the source of truth.

