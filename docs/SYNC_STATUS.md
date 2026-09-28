# Atlas sync status

`python -m atlas_sync status` evaluates the live dashboard entirely from persisted
attempt, build, raw-run and publication evidence. `--json` emits the same shared
structured snapshot. The command does not acquire the production-operation lock,
call Monday, repair evidence, or write files.

The `current` symlink is authoritative. The live build is deeply verified using
the same artifact, provenance, bilingual-tree and production raw-evidence checks
used before publication. `CURRENT.json` disagreement is reported, never repaired.

System state is `failed` when no safely resolved and fully verified live build
exists; `degraded` when that build is usable but `CURRENT.json` disagrees or the
latest recorded sync failed; and `healthy` otherwise. `unknown` is used when the
evaluation configuration cannot be established.

Freshness uses the persisted Monday retrieval time of the raw run powering the
live build, never publish time. With configured interval `I` and stale threshold
`S`, age `<= I` is `fresh`, `I < age < S` is `delayed`, and age `>= S` is `stale`.

Exit codes are deterministic: `0` means healthy and fresh; `1` means a usable
dashboard with a degraded system or delayed/stale data; `2` means failed/unknown
system state and no trustworthy live publication. Status never uses lock code 75.
