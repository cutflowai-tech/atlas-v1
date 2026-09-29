# Atlas scheduled run

Task 8 exposes one scheduler-friendly command; it does not install or run a scheduler:

```text
PYTHONPATH=src python3 -m atlas_sync scheduled-run [--json]
```

The intended cadence is once per hour. `ATLAS_SYNC_INTERVAL_SECONDS` (default `3600`)
remains the canonical expected interval. Task 9 may translate it into cron or a systemd
timer, but no OS scheduling configuration belongs to this task.

## One cycle

One non-blocking production-operation lock covers the whole cycle. Under that one lock,
Atlas runs one private already-locked sync attempt, retains its exact attempt ID, and—only
when that attempt completed successfully—passes that same ID to the private already-locked
publication path. It never enumerates staged builds to choose a target and never falls back
to an older build. Public `run-once`, `publish`, and `rollback` still acquire the same lock
when called directly.

Publication repeats all Task 5 validation. Any ingestion, verification, profile, dashboard,
English/Arabic, build, or pre-switch publication failure leaves `current` unchanged. The
symlink rename is the atomic boundary. If a durability, verification, history, or CURRENT
metadata failure occurs after the rename, the new pointer is reported truthfully as live,
the cycle fails with `publish_metadata_inconsistent`, and the publication-integrity state
is evaluated; Atlas does not attempt an unsafe automatic rollback.

After the run/publish outcome, Atlas evaluates the existing Task 7 runtime status and uses
that same snapshot to update operational alert state. No second health implementation and
no Monday request are used for this step.

After an exact attempt is published and status evaluation succeeds, the same locked cycle applies
bounded retention. The default `ATLAS_RETENTION_HOURS=96` boundary is inclusive: an object is
age-eligible at exactly 96 hours. Cleanup failure is reported in the cycle's `retention` result but
never changes or rolls back the successful publication. Failed sync, rejected/inconsistent publish,
failed status evaluation, and lock-contention cycles do not clean anything.

Retention deletes only strictly named Atlas-owned raw runs, terminal builds/attempt records,
publication-history records, and terminal scheduled-cycle groups. It preserves the live attempt,
every explicitly rollback-authorized published attempt, the default rollback target, all of their
source runs, within-window evidence, active/incomplete evidence, and anything corrupt, ambiguous,
unknown, symlinked, or outside its configured root. References are retained transitively. Duplicate
old publication records may be removed, but one successful authorization record remains for every
distinct attempt accepted by explicit rollback.
Age is derived from the UTC timestamp embedded in the immutable Atlas run, attempt, publication,
or cycle ID—not mutable filesystem timestamps.

Operators can inspect the identical decision engine without deleting anything:

```text
PYTHONPATH=src python3 -m atlas_sync retention --json
```

`--apply` performs cleanup under the shared production lock. The JSON report contains deterministic
per-kind object/byte totals, eligible/deleted totals, protection reasons, and safe failure categories.

## Persisted operational state

The already validated `ATLAS_LOCK_DIR` (normally `<ATLAS_DATA_DIR>/locks`) is also the safe
operational-state root. It is separate from raw evidence, builds, and published data:

- `scheduled-cycles/<cycle_id>.started.json`: durable start written before Monday access;
- `scheduled-cycles/<cycle_id>.outcome.json`: immutable core outcome written before alerts;
- `scheduled-cycles/<cycle_id>.json`: immutable finalized cycle result;
- `alerts/state.json`: atomically replaced alert lifecycle state.

These append-only phases form one crash-recoverable journal. A start without an outcome is
reconstructed as an interrupted failed cycle; an outcome without a final record remains the
authoritative restart fact. Atlas never resumes or publishes an orphaned staged build. Writing the
outcome before alert mutation prevents alert state from getting ahead of cycle history.

Cycle records contain version, monotonic sequence, IDs/times, exact run and publication
outcomes, previous/resulting live attempts, final Task 7 system/freshness state, safe failure
categories, scheduled-failure count, active alert types, and the retention report when cleanup ran. They contain no token, request
header, raw exception text, or raw exception type. The persisted records reconstruct counters
and incidents after a process or container restart.

Lock contention is a skipped cycle: no Monday request, attempt, build, publication, status
evaluation, alert update, or failure-count increment occurs. A safe immutable `locked` cycle
record is written and the command exits `75`.

## Alert rules and recovery

- `data_stale` is critical exactly when Task 7 reports `freshness_state=stale`; Task 7 owns
  the exact `age >= ATLAS_STALE_AFTER_SECONDS` boundary.
- `consecutive_scheduled_failures` is critical when trailing failed scheduled cycles reach
  `ATLAS_MAX_CONSECUTIVE_FAILURES`. Manual commands and locked/skipped triggers do not count.
  Below the threshold the count is recorded but no incident is opened.
- `publication_integrity` is critical immediately when Task 7 finds the live publication
  unusable because a pointer/build/raw/provenance check failed.
- `publication_metadata_inconsistent` is warning immediately when the actual pointer and
  CURRENT/history metadata materially disagree while the live build may remain usable.

An unchanged condition updates one active incident rather than opening duplicates. Resolution
marks that incident resolved. A later recurrence opens a new linked incident. No delivery
transport exists in Task 8.

A later fully successful scheduled run publishes only its new validated build, resets the
scheduled-failure streak, and resolves conditions that are no longer present. A failed cycle
does not delete, replace, or invalidate the last-good dashboard before the atomic switch.

## Exit codes

- `0`: exact attempt built and publication completed; alerts do not retroactively change it.
- `2`: configuration or lock configuration failure.
- `3`: sync/run failure.
- `4`: publication rejected or failed before the switch.
- `5`: pointer switched but publication durability/metadata is inconsistent.
- `6`: Task 7 status or alert-state evaluation/persistence failed.
- `7`: immutable scheduled-cycle record could not be written.
- `75`: production lock held; cycle skipped.
