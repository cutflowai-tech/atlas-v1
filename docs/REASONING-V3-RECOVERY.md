# Reasoning V3 — backup, restore, rollback and recovery (Phase 20-B, prepared, not executed)

These are procedures for the separately approved Reasoning V3 rollout ([`REASONING-V3-PRODUCTION-ROLLOUT.md`](REASONING-V3-PRODUCTION-ROLLOUT.md)). Every
command that touches a host is marked **DO NOT EXECUTE WITHOUT LIVE-ROLLOUT APPROVAL**.

What has been tested is stated precisely in each section: disposable test databases, synthetic data and offline fakes. **No production
backup, production restore, live provider call or live Honcho call has been performed.**

In the commands below, `REASONING_OPS` stands for this prefix, copied verbatim:

```text
# DO NOT EXECUTE WITHOUT LIVE-ROLLOUT APPROVAL
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --env-file /etc/waset-atlas/reasoning.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml -f /opt/waset-atlas/current/deploy/production/compose.reasoning.yaml --profile reasoning-operations run --rm --no-deps reasoning-ops
```

## 1. Truth hierarchy

- **PostgreSQL (`atlas_reasoning` schema) is canonical.** It holds cases, results and every version, diffs, lifecycle transitions, ExecutiveBriefs and their history, notes, questions, answers, teachings, the audit tables (`llm_calls`, `memory_injections`, refused candidates) and `schema_migrations`.
  - Most history tables are append-only. Database triggers refuse `UPDATE`/`DELETE` on them.
- **Honcho is a copy.** Every memory record is rebuilt from canonical rows (`memory-sync`). Losing Honcho loses no canonical data.
- **Deterministic Atlas** keeps its own truth hierarchy in `/var/lib/waset-atlas` (`PRODUCTION-RUNBOOK.md` §3). Reasoning V3 never writes there.

## 2. Backup and restore

### 2.1 Pre-enable backup (design; future, approved)

Take this backup before Stage 1 and before every migration or capability enablement (REV/20 #6).

1. **Quiesce writers.**
   - Stop scheduled reasoning, once it exists.
   - Wait for `reason` and `memory-sync` to finish.
   - Disable human-context writes for the duration, or take the backup in a maintenance window.

   The drill tool refuses a backup whose source changed while it was being dumped.
2. **Canonical Reasoning V3 PostgreSQL: schema and data.**
   - Command: `pg_dump --format=custom --schema=atlas_reasoning --no-owner --no-privileges`.
   - Run it from the approved backup host with a PostgreSQL client **at least as new as the server's major version**.
   - Connect through a `pg_service.conf`/`.pgpass` entry, so the URL and password are never on a command line.
   - Record a manifest beside the dump:
     - the artifact sha256;
     - the server and client versions;
     - the applied migrations (version, name, checksum);
     - per-table row counts and fingerprints;
     - the release record (§2.4).
   - `deploy/production/reasoning_ops/restore_drill.py` implements exactly this format. In this phase its `backup` mode accepts only disposable test databases. Using it against the production source is part of the live-rollout approval.
3. **Version compatibility.**
   - A dump restores into the same or a newer PostgreSQL major version.
   - Restored data is valid for code whose migrations include every applied migration in the manifest. `db-health` reports `problems` for an applied migration the code does not know or whose checksum changed, and the operator must not start reasoning on it.
   - Newer code applies its additional forward migrations with `migrate`.
4. **Encryption and access.**
   - Store the artifact in the approved encrypted backup store, encrypted at rest and access-controlled to the operators. Do not leave it only on the database host.
   - The dump contains manager notes, answers and teachings: treat it as confidential management data. Never attach it to tickets or chat.
5. **Deterministic Atlas data** is unchanged from `PRODUCTION-RUNBOOK.md` §10:
   - Stop the timer and back up `/var/lib/waset-atlas` with permissions, timestamps and symlinks.
   - Back up `/etc/waset-atlas` separately into the encrypted secret store.
   - The Reasoning V3 secret files under `/etc/waset-atlas/secrets` belong to that secret-store backup, never to the database artifact.
6. **Release and configuration metadata.**
   - Keep the release record (§2.4) and the non-secret `reasoning.env` with the backup.
   - `reasoning.env` contains only settings and secret *paths*.

### 2.2 Isolated restore drill (implemented and tested)

`deploy/production/reasoning_ops/restore_drill.py drill --source-url … --target-url …` runs the whole cycle on **two disposable test
databases**:
- **Backup:** dump plus manifest. Files are `0600` in a `0700` directory, and the password is never on a command line.
- **Restore:** into the second database, after the artifact's sha256 matched the manifest.
- **Verify:**
  - `database_health` is ok;
  - the restored `schema_migrations` equals the manifest and the code (migrations recognized);
  - `migrate` replay applies nothing;
  - every table's fingerprint is identical;
  - every trigger, function, constraint and index definition of the schema is identical (the append-only triggers rollback relies on);
  - the release record is still inspectable.

Both databases must pass the evaluation guard: the libpq-resolved name contains the word `test`, it is never
`ATLAS_REASONING_DATABASE_URL`, and source and target are distinct. The URLs must also state their host and port (libpq would otherwise
fill them from `PG*` variables), and inherited `PG*` variables are removed before any connection.

**Tested** in `tests/test_reasoning_ops_recovery.py`, on synthetic data from the showcase dataset:
- **The full drill** (`IsolatedRestoreDrillTests`):
  - The synthetic data covers results and versions, the ExecutiveBrief and its history, a note, an answer and a teaching, `llm_calls`, runs, unsynced memory copies and `schema_migrations`.
  - All verification checks are true, the output carries no URL, and the files have the expected modes.
- **Verification-only tests** (`RestoreDrillVerificationTests`): they detect a differing table and migration drift.
- **Guard tests:**
  - non-test or canonical targets;
  - a tampered artifact, refused before any tool runs;
  - release records carrying credentials;
  - no password on the command line.

The full drill needs `pg_dump`/`pg_restore` at least as new as the server. Where they are missing it is **skipped with that reason**, unless
`ATLAS_REASONING_REQUIRE_RESTORE_DRILL=1` is set, which turns that skip into a failure. **CI runs the full drill mandatorily:** it
installs the PostgreSQL 17 client from the official PGDG repository (matching the `postgres:17` service), and the Reasoning V3 step sets
`ATLAS_RESTORE_DRILL_PG_BIN=/usr/lib/postgresql/17/bin` and `ATLAS_REASONING_REQUIRE_RESTORE_DRILL=1`. A static test pins this wiring. **This is an isolated drill. It is not
evidence of a production backup or restore.**

Run it on the release workstation before each release (checklist item `isolated_restore_drill`), against two **disposable test
databases** with an explicit host and port — never a production or staging database:

```sh
PYTHONPATH=src:deploy/production python3 deploy/production/reasoning_ops/restore_drill.py drill \
  --source-url "postgresql://atlas@127.0.0.1:5432/atlas_reasoning_drill_src_test" \
  --target-url "postgresql://atlas@127.0.0.1:5432/atlas_reasoning_drill_dst_test" --release release.json
```

### 2.3 Database restore decision path

Restore is the **last** resort, because it discards every canonical write made after the backup.

1. **Prefer a capability rollback (§3).** A wrong card, an outage, cost, or a memory problem never needs a restore. Disabling keeps every row.
2. **Restore only when** canonical data is unrecoverably inconsistent. Examples: `db-health` reports `problems` after a failed storage event; integrity loss confirmed by the operators. Name the incident and the approver.
3. **Take a fresh backup of the current (damaged) state first**, for forensics. Never restore over the live database in place.
4. **Verify the artifact first, on a copy.** `restore_drill.py restore --backup DIR --target-url <disposable test database>` runs the §2.2
   checks. The drill tool only ever writes to test-named databases; it is never the production restore.
5. **Production restore (a separate, approved manual step).** Into a **new, non-test-named** database (for example
   `atlas_reasoning_restored_<date>`), so the Phase 19 guard keeps refusing it as an evaluation target. An approved operator runs
   `pg_restore --exit-on-error --no-owner --no-privileges` with a service/pgpass entry, then explicitly sets the owner to the dedicated
   Reasoning V3 role and re-applies its approved grants (ownership and grants are not in the artifact). Any role or grant change is
   **REQUIRES_FRESH_OPERATOR_SECURITY_APPROVAL**.
6. **Approved cutover:** point `reasoning_database_url` at the restored database, run `db-health` (and `migrate` when the code is newer),
   then re-enable stages one at a time. The old database is kept read-only until the incident is closed.
7. **Writes after the backup** are lost: reasoning results are recomputed by the next runs; human-context writes must be re-entered by managers. Communicate this before cutover.

### 2.4 Release association

A backup is associated with the release that produced it. Its manifest `release` record is a plain-identifier JSON (the tool refuses
URLs with credentials, keys and secrets): the release's Phase 20-A `release-metadata` identifiers (commit, model, prompt and contract
versions, latest migration) and the image digests and evaluation `report_sha256` of the release record.

Name backup directories `<UTC timestamp>-<integration SHA>`.

## 3. Rollback runbooks

Principles:
- Rollback **never** deletes or edits reasoning rows. History tables refuse it in the database.
- Deterministic Atlas is untouched by every rollback below. Its own rollback is `PRODUCTION-RUNBOOK.md` §6/§10b.
- After any rollback, run `db-health` and capture the reliability report for the incident.

| Situation | Rollback | What remains |
|---|---|---|
| **Reasoning execution disabled** | `ATLAS_REASONING_V3=off` (available now), or after Phase 20-A merges `ATLAS_REASONING_EXECUTION=off` (*planned* kill switch: `gate` and `reason` exit 2, stored results stay readable). With `ATLAS_REASONING_V3=off` (master: `gate` and `reason` exit 2 with `ReasoningDisabled`, the web app refuses to start). Neither stops `memory-sync`, `provider-health`, `memory-health`, `migrate` or `evaluate`: also set `ATLAS_REASONING_MEMORY=off` to stop all Honcho traffic | Every canonical row. **Tested:** canonical fingerprints identical after `gate` and `reason` are refused (`CapabilityRollbackTests`) |
| **Visible reasoning disabled** | `ATLAS_REASONING_AUDIENCE=none` (Phase 20-A, *planned*), and the approved removal of the proxy route. Before Phase 20-A nothing is visible (no route exists) | Reasoning may continue in shadow; deterministic pages unchanged |
| **Human-context interaction disabled** | `ATLAS_REASONING_HUMAN_CONTEXT=off` (Phase 20-A, *planned*) | Existing notes, answers and teachings remain canonical and keep informing reasoning |
| **Executive-primary disabled** | `ATLAS_REASONING_EXECUTIVE_HOME=off` (Phase 20-A, *planned*) | The ExecutiveBrief and its history remain; the cards lead the home |
| **Honcho disabled** | `ATLAS_REASONING_MEMORY=off` | Canonical context only. Notes are still written. Copies resume with `memory-sync` when re-enabled. **Tested:** `test_memory_off_uses_canonical_context_only` |
| **OpenRouter unavailable** | No configuration change needed: §5 | Prior results and the current brief. **Tested** (§5) |
| **Previous model** | `ATLAS_REASONING_MODEL=<previous slug>` **and** `ATLAS_REASONING_ALLOW_MODEL_OVERRIDE=on`, with a recorded reason. Identity checks then verify the *requested* model. Return to the pinned model by clearing both. Both pass through the overlay's allow-list (tested). Release eligibility evaluates the pinned model only, so an override is an incident measure, never a release | All rows. New versions record the model. **Tested:** the override is required (`test_model_rollback_needs_the_explicit_override`) |
| **Previous prompt** | Prompt versions are code constants (`analyst-v2`, `update-v2`, `reviewer-v1`, `executive-v1`). Roll back by redeploying the previous release | Results keep the prompt version they were made with |
| **Previous repository release** | Redeploy the previous reviewed release directory and image digests (`PRODUCTION-RUNBOOK.md` §9). Only allowed when the previous release knows every applied migration (§2.1 compatibility); otherwise roll back capabilities instead | All rows |
| **Database restore** | §2.3 decision path only | See §2.3 |

Pause processing (the first rollback step for any Reasoning V3 incident), validate, then check health. Always write the explicit value
`=off`; never delete or blank a switch to turn it off:

```sh
# DO NOT EXECUTE WITHOUT LIVE-ROLLOUT APPROVAL
sudoedit /etc/waset-atlas/reasoning.env        # set ATLAS_REASONING_V3=off (after Phase 20-A merges: ATLAS_REASONING_EXECUTION=off also works)
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --env-file /etc/waset-atlas/reasoning.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml -f /opt/waset-atlas/current/deploy/production/compose.reasoning.yaml --profile reasoning-operations run --rm --no-deps reasoning-ops rollout     # Phase 20-A command (planned): validates the new configuration
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --env-file /etc/waset-atlas/reasoning.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml -f /opt/waset-atlas/current/deploy/production/compose.reasoning.yaml --profile reasoning-operations run --rm --no-deps reasoning-ops db-health
```

## 4. Partial-run recovery (Phase 18 semantics; `REASONING-V3-ORCHESTRATION.md`)

`python -m atlas_reasoning reason <run_id>` runs one orchestration pass, then executive synthesis when the run is executive-ready.
`--resume` runs the bounded resume. Exit 0 only when the run is `complete`.

| Status | Meaning | Operator action |
|---|---|---|
| `complete` | Every LLM item done or legitimately closed; also a run with zero work (unchanged cases cost nothing) | None |
| `partial` (`work_deferred`) | The pass budget (`ATLAS_REASONING_RUN_CALL_BUDGET`) deferred work; deferred items stay `pending` and spend no attempt | `reason <run_id> --resume` once, in the next window; each resume is a new budget window |
| `partial` (`resumable_failures`) | Retryable failures (outage classes, `work:INTERRUPTED`, `work:STALE_CLAIM`, `provider:circuit_open`, `provider:budget_exhausted`) with attempts left | Fix or wait out the cause (§5), then `reason <run_id> --resume` once |
| `degraded` | All work attempted, but some failures are final (not retryable, out of attempts, superseded), a follow-up failed, or memory was degraded | Inspect the failures; a degraded run's failures are final and resume does not retry them. A finally failed case is reasoned again only when its evidence changes (the Change Gate creates no work for unchanged evidence); until then it is visible in `backlog.unreasoned_cases` |
| `failed` | Never gated, an orchestration error, or every attempt failed at the provider with no usable result | Fix the cause; then `reason <run_id> --resume` (resume advances `partial` and `failed` runs that still have eligible work, and is a no-op otherwise); if nothing is eligible, the next gated run starts fresh |

Guarantees operators rely on. Never work around them:
- **Budget exhaustion** is deferral, not failure. Never raise the budget to "finish" a run without approval.
- **Circuit breaker.** After `ATLAS_REASONING_BREAKER_THRESHOLD` consecutive outage failures (each after the gateway's retries), calls
  are refused for the cooldown, then exactly one probe is sent. The breaker lives in one process: every `reasoning-ops` run is a new
  process with a closed breaker, so during an outage **do not start runs**; the outage bound per run is
  `threshold × (1 + ATLAS_REASONING_LLM_MAX_RETRIES)` provider requests (20 with the template's 5 and 3) before that run's breaker opens.
- **Duplicate protection:**
  - One engine at a time (an advisory lock): a second `reason` exits with `engine_busy`.
  - One open pass per run.
  - One open work item per case.
  - Retries are unique and bounded (`max_attempts` per case and evidence state).
  - Results, versions and questions are idempotent: a repeated resume with nothing eligible makes **no** call.
- **Interrupted processes.** A claim older than the longest possible call is recovered as `work:STALE_CLAIM` at the next pass. A pass left open is closed `interrupted`.
- **No shell retry loops.** Run one `--resume`, read the status and the reliability report, and decide.
- **Finding incomplete runs.** There is no separate command: `python -m atlas_reasoning.reliability_report --latest N` lists the latest
  runs with `run.status` and `orchestration.last_reasons`; resume the `partial` / `failed` ones once each.

```sh
# DO NOT EXECUTE WITHOUT LIVE-ROLLOUT APPROVAL — REASONING_OPS is the prefix from the top of this document
REASONING_OPS reason RUN_ID --resume
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --env-file /etc/waset-atlas/reasoning.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml -f /opt/waset-atlas/current/deploy/production/compose.reasoning.yaml --profile reasoning-operations run --rm --no-deps --entrypoint python reasoning-ops -m atlas_reasoning.reliability_report --run RUN_ID
```

## 5. OpenRouter outage

**Tested offline** (`ProviderOutageTests`). The outage is a fake transport that raises `ProviderUnavailable`; there is no network. The
scenario:
1. **A healthy baseline:** a complete run, a current ExecutiveBrief, and a note, an answer and a teaching.
2. **The outage.** The provider fails, and a material evidence change is gated and orchestrated.
   - The run is classified `partial` / `resumable_failures`. It is not `complete`, and it is listed by `incomplete_runs()`.
   - With the test's settings (threshold 1, one transport retry) the breaker opened after the first outage call: at most 2 provider
     requests (asserted `≤ 2`; 2 observed), then **no further requests**. There is no retry storm. With production settings the bound per
     process is `threshold × (1 + retries)` (§4).
   - Executive synthesis during the outage is refused `provider:circuit_open` with 0 calls, and the **current ExecutiveBrief is unchanged**.
   - Every earlier result version, diff and lifecycle transition is still present unchanged. No content version was written; the only new versions are Phase 09's model-free lifecycle settles. Brief tables are identical.
3. **Recovery.** The provider is back. After the breaker cooldown, **one** normal `resume`:
   - the run becomes `complete`;
   - the material change is reasoned (patched versions);
   - a new brief version is written, and the previous version stays in history;
   - a second resume makes **zero** provider requests.

Operator procedure:
1. Confirm with the reliability report: `provider_calls.total.failures_by_class` shows outage classes and `orchestration.last_reasons` shows `resumable_failures`.
2. Optionally check configuration without a network call: `python -m atlas_reasoning provider-health --dry-run`.
3. Deterministic Atlas keeps serving; reasoning cards and the brief keep showing the last valid state.
4. Do not raise retries, budgets or the breaker threshold during the outage, and do not start new `reason` runs: each run is a new
   process whose breaker starts closed (§4). Optionally pause with `ATLAS_REASONING_V3=off` (or, after Phase 20-A merges,
   `ATLAS_REASONING_EXECUTION=off`).
5. When the provider's own status shows recovery, run `reason <run_id> --resume` **once** per incomplete run (one at a time; a second
   concurrent run exits `engine_busy`).
6. A live provider check (`provider-health` without `--dry-run`) is DO NOT EXECUTE WITHOUT LIVE-ROLLOUT APPROVAL.

## 6. Honcho outage

**Tested offline** (`HonchoOutageTests`). The outage is `FakeHoncho.outage()`; there is no network.
- **Canonical writes still happen.** A manager note written during the outage is a canonical row, and its memory copy is left `pending`/`failed` in `memory_sync_log`.
- **Reasoning still commits results.** The run is `degraded` with reason `memory_degraded`.
- **The UI degrades safely.** The dashboard renders a result page from PostgreSQL (HTTP 200, no internals).
- **Recovery.** After `restore()`, the existing memory-sync retry re-sends every pending or failed copy; each ends `synced` (or `duplicate` when an earlier attempt had in fact arrived), leaving 0
  unsynced. Canonical result and human-context tables are byte-identical before and after.

Operator procedure:
1. Leave reasoning on, or set `ATLAS_REASONING_MEMORY=off` if the outage is long.
2. Do not delete or edit notes, answers or teachings.
3. When Honcho recovers, run `python -m atlas_reasoning memory-sync` once. `--limit` bounds a run; repeat it only after reading its output.
4. A live Honcho check (`memory-health` without `--dry-run`) is DO NOT EXECUTE WITHOUT LIVE-ROLLOUT APPROVAL. `python -m atlas_reasoning memory-health --dry-run` validates configuration only.

```sh
# DO NOT EXECUTE WITHOUT LIVE-ROLLOUT APPROVAL — REASONING_OPS is the prefix from the top of this document
REASONING_OPS memory-sync --limit 100
```
