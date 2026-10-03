# Reasoning V3 — Phase 20-B evidence (operations readiness and recovery)

**Production-readiness repository work only. No live deployment or environment change was performed.** Specifically:
- no SSH and no connection to any server;
- no deploy and no image push or pull;
- no service, systemd, nginx, DNS, TLS or firewall change;
- no production database backup or restore;
- no live OpenRouter or Honcho call;
- no credential, secret, permission, access or security-policy change.

All verification used static checks, disposable local PostgreSQL test databases, synthetic data and offline fakes. Docker is not
installed on the verification machine, so the image build test is skipped under the established `ATLAS_RUN_DOCKER_TESTS` semantics.

**Base.** `74c015f59498484b7d04a7b35ee903361062d7df`, POST_PHASE19 (`PHASE19_CLOSURE=PASS`). There is no migration; range 0850–0899 is unused.

## 1. Deliverables

| REV/20 / prompt item | Deliverable |
|---|---|
| Rollout runbook, six stages, topology | [`REASONING-V3-PRODUCTION-ROLLOUT.md`](../REASONING-V3-PRODUCTION-ROLLOUT.md) |
| Backup and restore design, restore drill, rollback runbooks, partial-run recovery, provider and Honcho outages | [`REASONING-V3-RECOVERY.md`](../REASONING-V3-RECOVERY.md) |
| Monitoring checklist (Phase 18-C and Phase 19 fields only) | [`REASONING-V3-MONITORING.md`](../REASONING-V3-MONITORING.md) |
| Release verification checklist (never authorizes deployment) | [`REASONING-V3-RELEASE-CHECKLIST.md`](../REASONING-V3-RELEASE-CHECKLIST.md), `deploy/production/reasoning_ops/release_checklist.py` |
| Safe configuration and topology artifacts | `deploy/production/{Dockerfile.reasoning, Dockerfile.reasoning.dockerignore, reasoning-runtime-requirements.txt, compose.reasoning.yaml, reasoning.env.example}` |
| Isolated restore drill | `deploy/production/reasoning_ops/restore_drill.py` |
| Credential scan | `deploy/production/reasoning_ops/secret_scan.py` |
| Runbook pointer | `docs/PRODUCTION-RUNBOOK.md` §12 (appended; §1–11 unchanged) |
| Tests | `tests/test_reasoning_ops_deploy.py` (static), `tests/test_reasoning_ops_recovery.py` (PostgreSQL) |

**Unchanged:**
- deterministic `compose.yaml`, `nginx.conf`, `Dockerfile.app`, `Dockerfile.nginx`, `runtime-requirements.txt`, the systemd units, `atlas.env.example`;
- every `src/` file: no Phase 20-A territory and no application code;
- CI and the Makefile.

## 2. B-first independence from Phase 20-A (PM integration order: Phase 20-B first, then Phase 20-A)

Phase 20-B is independently testable and mergeable on `74c015f` alone.
- **No Phase 20-A code is involved.** No runtime module or test imports, executes or requires it. `release_checklist.py` imports no `atlas_*` module, and `test_it_neither_imports_phase20a_code_nor_derives_release_metadata` asserts this.
- **No skip depends on Phase 20-A.** The only skips are the established Docker ones.

What remains, and why it does not depend on Phase 20-A code:
- **Phase 20-A's planned flag names in the overlay.** `ATLAS_REASONING_EXECUTION`, `_AUDIENCE`, `_CARDS_PRIMARY`, `_HUMAN_CONTEXT` and `_EXECUTIVE_HOME` are passed through the Compose overlay with stage-0 defaults. They are inert environment variables on `74c015f`.
- **Labelled references in the docs.** Every mention of a Phase 20-A command or flag is labelled *planned*, and the docs give the B-only equivalent (`ATLAS_REASONING_V3=off`). They also state that no stage beyond 0 can be entered before Phase 20-A merges.
- **Kept fixes.** The collision and duplicate-ownership fixes stand. This branch's operations plan is `REASONING-V3-PRODUCTION-ROLLOUT.md`, and it does not touch Phase 20-A's `docs/REASONING-V3-ROLLOUT.md`. The release checklist derives no release metadata of its own.

**PM decision: the Phase 20-A-dependent items are pending, not PASS.** These items are:
- metadata completeness;
- the repository eligibility contract;
- rollout-stage matching.

They depend on Phase 20-A's unmerged `atlas_reasoning.release_metadata` module, its `rollout` command and their outputs. They are
formally recorded as **`PENDING_PHASE20A_RECONCILIATION`**:
- `release_checklist.py` reports them pending whatever status or evidence a record carries, so a record is never `complete` before reconciliation.
- Attached Phase 20-A outputs are opaque review evidence only.
- They become mandatory automatic blocking gates on the reconciled Phase 20-A head, using real Phase 20-A code and real Phase 20-B artifacts, with no mocks or opaque evidence (`REASONING-V3-RELEASE-CHECKLIST.md` §1).
- Tests: `test_phase20a_items_can_never_pass_before_reconciliation`, `test_b_side_complete_is_reported_but_the_record_stays_pending`, `test_the_template_records_the_pending_contract`.

## 2a. Acceptance contract

```text
B_INDEPENDENT_ACCEPTANCE       = PENDING (becomes PASS only when every gate below has passed)
A_DEPENDENT_ACCEPTANCE         = PENDING_PHASE20A_RECONCILIATION
P20A_RELEASE_METADATA_COMPLETE = PENDING
P20A_REPOSITORY_ELIGIBILITY_CONTRACT = PENDING
P20A_ROLLOUT_STAGE_MATCH       = PENDING
P20_ACTUAL_RELEASE_READY       = FALSE   (fail-closed: live evaluation, human review and approvals are a separate, explicitly authorized pre-rollout gate)
P20_ROLLOUT_AUTHORIZED         = FALSE
```

The PM's final decision supersedes the earlier `P20A_RELEASE_ELIGIBILITY_TRUE`. No live evaluation is required before the
repository-preparation merge, and repository eligibility is kept separate from actual release readiness. The reconciled Phase 20-A head
runs real automatic Phase 20-A plus Phase 20-B checks for four things:
- metadata completeness;
- exact stage matching;
- the repository eligibility contract;
- the fail-closed result: missing live-provider evaluation and/or human-review evidence gives actual release ready FALSE.

The final report is `POST_PHASE20_PREP_INTEGRATION_SHA=<sha>`, `PHASE20_REPOSITORY_PREP=PASS`, `P20_ACTUAL_RELEASE_READY=FALSE`,
`P20_ROLLOUT_AUTHORIZED=FALSE` and `PHASE20_COMPLETE=FALSE`.

`B_INDEPENDENT_ACCEPTANCE` becomes `PASS` only when every Phase 20-B gate has passed, with no live action:
- the fresh full local gate;
- the independent review;
- exact-head CI;
- the credential scan;
- the isolated backup and restore drill;
- the fake provider and Honcho outage tests;
- static deployment and configuration validation.

After Phase 20-B merges, `POST_PHASE20B_INTEGRATION_SHA` is recorded. Phase 20-A then merges it by merge commit and wires the three
gates. The full combined gate, exact-head CI and Phase 20-B's final delta review follow, and only then may Phase 20-A merge. That merge may
record only `POST_PHASE20_PREP_INTEGRATION_SHA` and `PHASE20_REPOSITORY_PREP=PASS`. That is not Phase 20 complete, and it authorizes no
deployment or live action.

Two flag-related items for Phase 20-A's reconciliation, recorded as interface assumptions rather than code dependencies:
- confirm the five flag names and defaults match its `rollout.ROLLOUT_ENVS`;
- add the drift test against that module.

Interface requirements returned to Phase 20-A or the PM (`REASONING-V3-PRODUCTION-ROLLOUT.md` §2.3):
- a production WSGI entry point for the web process (the current `web_app.main` is loopback-only preview);
- primary-surface routing per audience (proxy routes are **REQUIRES_FRESH_OPERATOR_SECURITY_APPROVAL**);
- a reviewed read-only bind of the published site into `reasoning-ops`, so that `gate` can run there.

## 3. Test evidence

### 3.1 Isolated restore drill (disposable PostgreSQL 17.11, client tools 17.11)

`IsolatedRestoreDrillTests` ran with `ATLAS_REASONING_REQUIRE_RESTORE_DRILL=1`.

**Synthetic source:**
- a complete run, its results and versions;
- the current ExecutiveBrief and its history;
- a note, an answer and a teaching;
- unsynced memory copies written during a fake Honcho outage;
- `llm_calls` and `schema_migrations`.

**Every check true:**
- `database_health_ok`;
- `migrations_match_manifest` and `migrations_match_code`;
- `migration_replay_applied_nothing`;
- `canonical_tables_identical` (30 tables, row-level sha256);
- `schema_objects_identical` (triggers, functions, constraints, indexes);
- `release_metadata_inspectable`.

**Safety properties checked:**
- Files are `0600` in a `0700` directory.
- No URL appears in the output or the manifest.
- The password never reaches a command line.
- Targets must be test-named, distinct, not the canonical URL, and must state host and port. Inherited `PG*` variables are removed.

This is **an isolated drill and not a production backup or restore test**. In CI the runner's client tools may be older than the
PostgreSQL 17 service. Then the full drill is reported skipped with that reason, and the verification and guard tests still run.

### 3.2 Offline outage scenarios

**OpenRouter** (`ProviderOutageTests`, a fake transport raising `ProviderUnavailable`; the test uses breaker threshold 1 and 1 retry):
- the outage run is `partial` / `resumable_failures`;
- at most 2 provider requests were made (asserted `≤ 2`; 2 observed), then the breaker opened;
- executive synthesis failed with `provider:circuit_open`, using 0 calls, and brief v1 was kept;
- every earlier version, diff and transition is preserved, and brief tables are identical;
- one `resume` gave `complete`, patched versions and a new brief version, with the old one still in history;
- a second resume made 0 requests.

**Honcho** (`HonchoOutageTests`, `FakeHoncho.outage()`):
- the note stayed canonical;
- the run is `degraded` / `memory_degraded`, with results committed;
- the dashboard returned 200 while memory was down;
- `memory-sync` retry left 0 unsynced copies, with canonical tables byte-identical.

### 3.3 Gates on the final tree

Final gate on staged tree `a5e96e06eecccda34219c7fc6e8e251e4199a524`. The environment:
- PostgreSQL 17.11 (disposable `atlas_reasoning_p20b_test` plus its `_restore` drill target);
- `ATLAS_REASONING_REQUIRE_DB_TESTS=1` and `ATLAS_REASONING_REQUIRE_RESTORE_DRILL=1`;
- no `OPENROUTER*`, `HONCHO*` or `ATLAS_REASONING_DATABASE_URL` set;
- no Docker daemon.

| Gate | Result |
|---|---|
| `make test` | **exit 0, 1723 tests, 41 suites**. Only skips: **4 Docker** (`ATLAS_RUN_DOCKER_TESTS`): the 3 established ones plus the new reasoning-image build test |
| `make reasoning` | **798 OK** |
| Phase 20-B tests | `test_reasoning_ops_deploy` **39**, `test_reasoning_ops_recovery` **18**. The recovery suite includes the full isolated restore drill (required), the provider and Honcho outages, capability rollback, migrations before writes, the monitoring-field walk and the drill guards |
| Production and deployment tests | `test_production_deploy` 8, `test_production_container` 10 (3 Docker skips). Deterministic deployment files are unchanged |
| Phase 19 | `test_reasoning_evaluation` 60, `test_reasoning_evaluation_runner` 43 (the golden suite, byte-equal with the 19-A driver), `test_reasoning_evaluation_live` 17 |
| Phase 18 | `test_reasoning_run_control` 26, `test_reasoning_reliability` 59; also `test_reasoning_guardrails` 60, `test_reasoning_executive` 106 |
| Migration health and replay | 10 OK, including clean, repeatable and healthy; replay is idempotent; a changed migration is refused; concurrent bootstrap is safe |
| Golden-site, deterministic, i18n, UI | All `make test` targets OK |
| Static deployment and config validation | Overlay structure, interpolation (both `:-` and `-` forms), hardening parity, no ports, secrets as files, the env template matches settings, every documented switch reaches the container |
| `ruff check src tests deploy/production/reasoning_ops` | All checks passed |
| `mypy src` / `mypy --disallow-untyped-defs deploy/production/reasoning_ops` | No issues (183 / 4 files) |
| Credential scan (`secret_scan.py`, 178 tracked files including `.github`) | **pass**, 0 findings |
| Phase 20-A independence | No `atlas_*` import in the release checklist; no Phase 20-A import, stand-in or conditional skip anywhere |

## 4. Independent adversarial self-review

A separate read-only review agent reviewed the full staged diff and read Phase 20-A's commit read-only to check for overlap. It reported
2 High, 7 Medium and 12 Low findings. All High and Medium findings are fixed, with tests where applicable:

| # | Finding | Fix |
|---|---|---|
| H1 | Collision with Phase 20-A: the same doc path, `docs/REASONING-V3-ROLLOUT.md`, and a parallel release-metadata derivation under different field names | The doc was renamed to `REASONING-V3-PRODUCTION-ROLLOUT.md`, and `code_metadata` was removed. Phase 20-A's outputs are attached as evidence; their automatic verification is paused under B-first (§2). Test: `test_it_neither_imports_phase20a_code_nor_derives_release_metadata` |
| H2 | The overlay's `environment:` allow-list dropped the documented rollback switches (model override, and 20-A's flags), because `--env-file` only feeds interpolation | All are passed through with the application defaults. Test: `test_every_documented_switch_reaches_the_container` |
| M1 | "V3=off refuses every reasoning command" was overstated | The docs list exactly what is refused (`gate`, `reason`, web) and what still runs. `MEMORY=off` is needed to stop Honcho traffic |
| M2 | The degraded-run guidance was wrong: unchanged evidence is never re-reasoned | Corrected, pointing to `backlog.unreasoned_cases` |
| M3 | The drill's in-process connection and the tools could resolve to different servers through `PG*` defaults | Host and port are required; `PG*` is removed. Test: `test_urls_must_state_their_target_and_carry_no_ssl_password` |
| M4 | Restore verification ignored triggers, functions, constraints and indexes | A schema-object fingerprint was added to the manifest and the verification. Test: `test_verification_detects_missing_schema_objects` |
| M5 | The production restore path contradicted the guard and omitted owner and grants | A separate approved manual restore into a non-test-named database, with explicit owner and grants (REQUIRES_FRESH_OPERATOR_SECURITY_APPROVAL). The drill is used only on a copy |
| M6 | `gate` cannot run in `reasoning-ops`, because no site is mounted | Documented as an interface gap needing a reviewed read-only bind. Stage 1 runs `gate` on the release workstation |
| M7 | The monitoring-field test was vacuous | `MonitoringFieldTests` walks every documented path in a real Phase 18-C report |

Lows:

| # | Finding | Outcome |
|---|---|---|
| L1 | The full drill can't run in CI (runner tool versions) | Documented. CI changes are outside this phase's ownership |
| L2 | The image is never built | A gated Docker build test was added (skipped here: no Docker) |
| L3 | The tools are not linted | Lint and types are run explicitly; see §3.3 |
| L4 | Secret-scan gaps | Fixed: libpq keyword passwords, JSON keys, driver URLs, `.github` in the surface, literal-only allow |
| L5 | Drill error handling | Fixed: exit 3 carrying the error class only; `sslpassword` refused |
| L6 | Outage numbers and breaker scope | Fixed: exact assertions and the per-process bound `threshold × (1 + retries)` |
| PR #45 L-4 | Cross-review of Phase 20-A: `${ATLAS_REASONING_EXECUTION:-on}` turned an operator's blank kill switch into `on` | Fixed in Phase 20-B's overlay with `${ATLAS_REASONING_EXECUTION-on}` (only an unset variable defaults to on). The runbook says to write `=off` explicitly. Test: `test_a_blank_kill_switch_is_never_turned_on` |
| L7 | Rollback test causes | Fixed: asserts `ReasoningDisabled` for `gate` and `reason` |
| L8 | `incomplete_runs` had no CLI | The docs use `reliability_report --latest N` |
| L9 | Location of `backlog.*` | Fixed |
| L10 | The drill command's context | Clarified: release workstation, disposable test databases only |
| L11 | Version parsing | Accepted: it fails closed |
| L12 | The OpenRouter key is mounted for every command | Accepted and documented. Per-command secret sets would need separate overlays |
