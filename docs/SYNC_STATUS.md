# Atlas sync status

`python -m atlas_sync status` evaluates the live dashboard entirely from persisted
attempt, build, raw-run and publication evidence. `--json` emits the same shared
structured snapshot. The command does not acquire the production-operation lock,
call Monday, repair evidence, or write files.

The `current` symlink is authoritative and is read before and after evaluation.
One unstable observation is retried; two unstable observations return `unknown`
with `concurrent_transition`, rather than combining evidence from two publications.
The live build is deeply verified using
the same artifact, provenance, bilingual-tree and production raw-evidence checks
used before publication. `CURRENT.json` and its exact publication-history record
must agree with the live source run, build hash, contract, board, publication ID,
time, link, target, and status. A mismatch is reported, never repaired.

`live_usable` independently says whether the pointer resolves to a fully verified
live build. System state is `failed` when no such build exists or when persisted
integrity/clock evidence fails. A valid live build stays usable when the system is
`degraded` or `failed`. One through `ATLAS_MAX_CONSECUTIVE_FAILURES - 1` trailing
failed attempts degrades the system; reaching the configured threshold fails it;
a successful attempt resets the count. Publication metadata mismatch degrades a
valid live build. `unknown` covers invalid configuration or concurrent transition.

Freshness uses the persisted Monday retrieval time of the raw run powering the
live build, never publish time. With configured interval `I` and stale threshold
`S`, age `<= I` is `fresh`, `I < age < S` is `delayed`, and age `>= S` is `stale`.
A negative age (retrieval in the future) is `unknown`; it is never clamped to zero.

Exit codes are deterministic: `0` means healthy and fresh; `1` means a usable
dashboard with a degraded system or delayed/stale data; `2` means failed/unknown
system state. Consumers must inspect `live_usable` separately. Status never uses
lock code 75.

The model also supports a read-only `build_time_snapshot(...)` from explicit
verified attempt/source/config fields and earlier immutable attempt records. It has the identical shape with
`snapshot_scope=build_time`; runtime CLI snapshots use `snapshot_scope=runtime`.
Because dashboard HTML is generated before the staged build is complete or
published, a build-time snapshot always reports system state `unknown` and
`live_usable=false`; it still reports the verified source retrieval, coverage,
freshness thresholds and in-progress attempt. The static page labels this scope
explicitly, while `atlas_sync status` remains authoritative for current runtime
and publication state.

When the last applied retention pass completed cleanly, `status --json` includes its aggregate
`storage_retention` counts, bytes, cutoff, and reasons. It never exposes cleanup paths or a failed,
partial report. Status remains read-only.
