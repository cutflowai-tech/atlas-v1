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

Only after publication, status evaluation, durable outcome evidence, and alert state all
succeed, the same lock holder applies bounded retention. The cleanup result is included in
the finalized cycle record. `ATLAS_RETENTION_SECONDS` defaults to `345600` (96 hours).
Retention failure is reported separately and never changes a successful publication into a
failed one. Failed or inconsistent cycles do no cleanup.

## Persisted operational state

The already validated `ATLAS_LOCK_DIR` (normally `<ATLAS_DATA_DIR>/locks`) is also the safe
operational-state root. It is separate from raw evidence, builds, and published data:

- `scheduled-cycles/<cycle_id>.started.json`: durable start written before Monday access;
- `scheduled-cycles/<cycle_id>.outcome.json`: immutable core outcome written before alerts;
- `scheduled-cycles/<cycle_id>.json`: immutable finalized cycle result;
- `alerts/state.json`: atomically replaced alert lifecycle state.
- `retention/latest.json`: atomically replaced safe aggregate/report from the last completed cleanup.

These append-only phases form one crash-recoverable journal. A start without an outcome is
reconstructed as an interrupted failed cycle; an outcome without a final record remains the
authoritative restart fact. Atlas never resumes or publishes an orphaned staged build. Writing the
outcome before alert mutation prevents alert state from getting ahead of cycle history.

Cycle records contain version, monotonic sequence, IDs/times, exact run and publication
outcomes, previous/resulting live attempts, final Task 7 system/freshness state, safe failure
categories, scheduled-failure count, and active alert types. They contain no token, request
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

## Bounded retention

`python -m atlas_sync retention --dry-run --json` takes the production lock and emits the
exact deterministic decisions without deleting or writing the latest report. The non-dry
command is available for controlled operator use; normal cleanup is the post-success step of
`scheduled-run`.

Retention considers only exact Atlas run IDs and publication/cycle filenames directly under
the configured roots. It never follows symlinks. Unknown objects, incomplete work, unsafe or
outside-root references, corrupt JSON, and ambiguous provenance are retained. The current
publication, the actual default rollback target selected by publication history, every
successful publication still inside the retention window, and all of their attempt/build/raw
provenance are retained transitively. The exact 96-hour boundary is retained; an object must
be strictly older than the cutoff to be eligible. Terminal failed attempts may expire, while
running/incomplete artifacts and orphaned cycle starts remain protected.

The JSON report includes per-object kind/name/action/reason/bytes plus deleted, retained, and
dry-run-would-delete counts and bytes. A clean report also contains aggregate retained storage
by evidence kind. Treat `blocked` or `partial` as a request for operator investigation; do not
delete around it manually.

## Exit codes

- `0`: exact attempt built and publication completed; alerts do not retroactively change it.
- `2`: configuration or lock configuration failure.
- `3`: sync/run failure.
- `4`: publication rejected or failed before the switch.
- `5`: pointer switched but publication durability/metadata is inconsistent.
- `6`: Task 7 status or alert-state evaluation/persistence failed.
- `7`: immutable scheduled-cycle record could not be written.
- `75`: production lock held; cycle skipped.
