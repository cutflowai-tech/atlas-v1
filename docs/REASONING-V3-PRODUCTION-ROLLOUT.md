# Reasoning V3 — production rollout plan (Phase 20-B, prepared, not executed)

Specification: [`REV/20`](../REV/20-production-rollout-and-controlled-migration.md).

This document prepares a later, separately approved production rollout. Nothing in it has been executed against any live system. Every
command that touches a host is marked **DO NOT EXECUTE WITHOUT LIVE-ROLLOUT APPROVAL**. Each of the six stages needs its own explicit
human approval. No command or script progresses through stages automatically.

Companion documents:
- [`REASONING-V3-RECOVERY.md`](REASONING-V3-RECOVERY.md): backup, restore drill, rollback, partial-run recovery, provider and Honcho outages.
- [`REASONING-V3-RELEASE-CHECKLIST.md`](REASONING-V3-RELEASE-CHECKLIST.md): release verification.
- [`REASONING-V3-MONITORING.md`](REASONING-V3-MONITORING.md): the monitoring checklist.
- [`PRODUCTION-RUNBOOK.md`](PRODUCTION-RUNBOOK.md): the deterministic Atlas runbook. It is unchanged; its §12 points here.
- Phase 20-A's `docs/REASONING-V3-ROLLOUT.md` (rollout controls; PR #45, **planned, merged after this phase**): the capability flags, the
  six named stages (`python -m atlas_reasoning rollout --stages`), release metadata and release eligibility. This plan references those
  planned interfaces and defines no flag of its own. **Until Phase 20-A merges they do not exist:** the flags are inert, the commands are
  absent, and the only switches available are the existing `ATLAS_REASONING_V3` and `ATLAS_REASONING_MEMORY` (every stage beyond
  stage 0 needs Phase 20-A merged first).

## 1. What exists in production today, and what Reasoning V3 adds

Today production serves **deterministic Atlas** only:
- `atlas-web` is nginx. It serves `published/current` `/en/` and `/ar/` and binds `127.0.0.1:18000` behind the host's authenticating TLS proxy.
- `atlas-runtime` is the hourly `scheduled-run`, a systemd oneshot that writes to the host data root.

There is no database, no LLM and no memory service.

Reasoning V3 adds different dependencies. All of them are off until approved:

| Dependency | Role | Configuration (existing application handling) |
|---|---|---|
| PostgreSQL | **Canonical** Reasoning V3 state: cases, results, versions, lifecycle, ExecutiveBriefs, human context, audit | `ATLAS_REASONING_DATABASE_URL_FILE` (secret file) |
| Reasoning operations process | `migrate`, `db-health`, `gate`, `reason` (orchestration, then executive synthesis), `memory-sync`, reports | `Dockerfile.reasoning`, `compose.reasoning.yaml` (profile `reasoning-operations`) |
| Reasoning web process | `/reasoning/<en|ar>/…`, `/api/reasoning/…` (dashboard, read API, management API) | `atlas_reasoning.web_app` (WSGI). **No production server yet** (§2.3) |
| OpenRouter | The pinned model (`openai/gpt-5.6-sol`) | `OPENROUTER_API_KEY_FILE`; Phase 18 limits |
| Honcho (optional) | Contextual memory. **Never canonical** | `ATLAS_REASONING_MEMORY=on`, `HONCHO_API_KEY_FILE`, `ATLAS_REASONING_ENVIRONMENT` |
| Rollout-stage controls | Which capabilities run and are visible | Phase 20-A's `rollout` module: `ATLAS_REASONING_V3`, `ATLAS_REASONING_EXECUTION`, `ATLAS_REASONING_AUDIENCE`, `ATLAS_REASONING_CARDS_PRIMARY`, `ATLAS_REASONING_HUMAN_CONTEXT`, `ATLAS_REASONING_EXECUTIVE_HOME` (§4) |

With `ATLAS_REASONING_V3=off` (the default), deterministic Atlas is byte-for-byte what it was. `atlas_sync` and `atlas_commander` never
import `atlas_reasoning`, and a test enforces this.

## 2. Target topology

```text
browser ──TLS──► host authenticating reverse proxy (existing; TLS, authentication, actor identity)
                   ├── /, /en/, /ar/        ──► 127.0.0.1:18000  atlas-web (unchanged, static)
                   └── /reasoning/, /api/reasoning/   (NOT routed until Stage 2 is approved; §2.3)
                                             ──► reasoning web process (future), loopback only
host systemd (future, per stage) ──► one-shot reasoning-ops <command> (compose overlay, profile reasoning-operations)
reasoning-ops / reasoning web ──► PostgreSQL (canonical) ──► OpenRouter (pinned model) ──► Honcho (optional memory)
```

### 2.1 Repository artifacts prepared by Phase 20-B

| Artifact | Purpose | Safety properties (tested in `tests/test_reasoning_ops_deploy.py`) |
|---|---|---|
| `deploy/production/Dockerfile.reasoning` | Reasoning operations image | The same pinned base as `Dockerfile.app`. Non-root `10001`, read-only source, `ENTRYPOINT python -m atlas_reasoning`, `CMD --help` (no connection at start) |
| `deploy/production/reasoning-runtime-requirements.txt` | Exact pins (`psycopg==3.3.6`, `psycopg-binary==3.3.6`) plus the deterministic set | The deterministic image and its requirements are unchanged, with no psycopg |
| `deploy/production/compose.reasoning.yaml` | Overlay with one service, `reasoning-ops` | Profile-gated (never started by `up`), `restart: "no"`, default command `db-health` (read-only), **no `ports:`**, `read_only`, `no-new-privileges`, `cap_drop: ALL`, secrets as read-only files |
| `deploy/production/reasoning.env.example` | Configuration template, `/etc/waset-atlas/reasoning.env` | Only real setting names. `ATLAS_REASONING_V3=off`, `ATLAS_REASONING_MEMORY=off`. Credentials only as `*_FILE`. Placeholder digest |
| `deploy/production/reasoning_ops/` | Restore drill, release-checklist validator, secret scan | Repository and staging tools; never contact production |

### 2.2 Secrets and configuration

- **Secret files.** Each credential is a root-owned file under `/etc/waset-atlas/secrets/` (mode `0640`, group `atlas`). The overlay mounts it read-only at `/run/secrets/…`, and the application reads it through its existing `*_FILE` handling: `reasoning_database_url`, `openrouter_api_key`, `honcho_api_key` (an empty file while memory is off) and, for the web process, `reasoning_csrf_secret`. This follows the same pattern and permissions as the Monday token (`PRODUCTION-RUNBOOK.md` §2).
- **Never inline.** No credential value appears in YAML, `reasoning.env`, units, images, shell history or tickets. Verification commands print redacted URLs only (`db-health`), and `provider-health --dry-run` never sends the key.
- **Database role.** `reasoning_database_url` names a dedicated PostgreSQL role for the `atlas_reasoning` schema. It is never the evaluation or test database: the runner and the drill refuse it.
- **Database reachability.** How the containers reach PostgreSQL (a host socket, a private network, or a managed instance) is a host decision. Any change to the PostgreSQL listen address, `pg_hba.conf`, a firewall or a Docker network exposure is **REQUIRES_FRESH_OPERATOR_SECURITY_APPROVAL** and is not implemented here.

### 2.3 Interface requirements (not implemented by Phase 20-B)

- **Reasoning web server.** `atlas_reasoning.web_app` is a WSGI application whose `main` is local preview only (loopback, refuses other addresses). Production needs an application-owned production WSGI entry point and process definition. That belongs to the application owner, Phase 20-A, as part of its capability selection; Phase 20-B does not define it, to avoid overlap.
  - Proxy route requirements, once it exists: the existing host proxy authenticates, sets `REMOTE_USER` (or the header named by `ATLAS_REASONING_ACTOR_HEADER`) and **strips that header from client requests**.
  - The process binds loopback only, and `ATLAS_REASONING_ALLOWED_ORIGINS` lists exactly the public origin.
  - New proxy routes are **REQUIRES_FRESH_OPERATOR_SECURITY_APPROVAL**.
- **Stage controls and release metadata (Phase 20-A).** The capability flags, `rollout` / `rollout --stages` (validation, exit 2 when invalid), `release-metadata` and `release-eligibility` are Phase 20-A's application interfaces. The overlay passes the flags through unchanged with the application's defaults, and the release checklist takes the metadata, eligibility and rollout outputs as attached evidence (their automatic verification is paused
  until a PM-approved contract or merge order). Nothing here redefines a flag or a metadata field, and nothing here imports or runs Phase
  20-A code.
- **Primary-surface routing.** Which surface is primary per audience (`RolloutConfig.primary_surface`) is Phase 20-A's proposal; the proxy routes and allow-lists that implement it are **REQUIRES_FRESH_OPERATOR_SECURITY_APPROVAL**.
- **`gate` inside `reasoning-ops`.** `gate <site_dir>` reads a built site. The overlay deliberately mounts no data directory, so `gate` cannot run in `reasoning-ops` yet. Running it in production needs a reviewed read-only bind of the published site (`/var/lib/waset-atlas/published/current`) into the reasoning container — a topology change to approve with Stage 1; until then Stage 1 verification runs `gate` on the release workstation against a copy of the published site.

## 3. Migrations before writes (REV/20 #3)

**Rule:** before any stage that lets Reasoning V3 write (Stage 1 onward), the canonical database must report `db-health` ok with no pending
and no changed migration. Migration commands work with `ATLAS_REASONING_V3=off`, so the schema is prepared before anything can write.

How the code enforces it, as tested in `tests/test_reasoning_ops_recovery.py::MigrationsBeforeWritesTests`:
- An unmigrated database is unhealthy (`ok: false`, every migration pending), and a Change Gate write against it fails.
- `migrate` applies every migration under an advisory lock. `db-health` is then `ok: true, pending: []`.
- A second `migrate` applies nothing: replay is idempotent, and a changed applied migration is refused (`test_reasoning_store`).

Pre-enable procedure. The backup step comes first, `REASONING-V3-RECOVERY.md` §2:

```sh
# DO NOT EXECUTE WITHOUT LIVE-ROLLOUT APPROVAL
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --env-file /etc/waset-atlas/reasoning.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml -f /opt/waset-atlas/current/deploy/production/compose.reasoning.yaml --profile reasoning-operations run --rm --no-deps reasoning-ops db-health
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --env-file /etc/waset-atlas/reasoning.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml -f /opt/waset-atlas/current/deploy/production/compose.reasoning.yaml --profile reasoning-operations run --rm --no-deps reasoning-ops migrate
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --env-file /etc/waset-atlas/reasoning.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml -f /opt/waset-atlas/current/deploy/production/compose.reasoning.yaml --profile reasoning-operations run --rm --no-deps reasoning-ops db-health
```

Proceed only when the last command prints `"ok": true` and `"pending": []`. This repository has executed the equivalent
`python -m atlas_reasoning migrate` and `python -m atlas_reasoning db-health` only against disposable test databases.

## 4. Capability switches (existing settings, and Phase 20-A's planned flags)

Rows marked *planned* are Phase 20-A interfaces: inert until Phase 20-A merges. Before that, the only rollback switch is
`ATLAS_REASONING_V3=off` (and `ATLAS_REASONING_MEMORY=off` for Honcho).

| Switch | Off (or rolled back) means | Owner |
|---|---|---|
| `ATLAS_REASONING_V3` (master) | Every capability below is off. `gate` and `reason` exit 2 (`ReasoningDisabled`); the web app refuses to start. **Still runs:** `migrate`, `db-health`, debug lookups, `memory-sync`, `provider-health`, `memory-health`, `evaluate` | existing |
| `ATLAS_REASONING_EXECUTION` | The processing kill switch: `gate` and `reason` exit 2 (`ExecutionDisabled`); stored results stay readable | Phase 20-A (*planned*) |
| `ATLAS_REASONING_AUDIENCE` (`none` / `internal` / `management`) | `none` = shadow: nothing is presented | Phase 20-A (*planned*) |
| `ATLAS_REASONING_CARDS_PRIMARY` | Reasoning cards are not the primary card experience | Phase 20-A (*planned*) |
| `ATLAS_REASONING_HUMAN_CONTEXT` | No notes / answers / Teach Atlas interaction (UI and management API); existing human context stays canonical | Phase 20-A (*planned*) |
| `ATLAS_REASONING_EXECUTIVE_HOME` | The ExecutiveBrief does not lead the home; brief history stays | Phase 20-A (*planned*) |
| `ATLAS_REASONING_MEMORY` | No Honcho traffic at all (also stops `memory-sync` sending); canonical context only | existing |
| `ATLAS_REASONING_MODEL` + `ATLAS_REASONING_ALLOW_MODEL_OVERRIDE` | The pinned model | existing |

Every switch reaches the container through the overlay's `environment:` allow-list (tested; the planned names are passed through and
ignored until Phase 20-A merges). After changing `reasoning.env`, validate with `python -m atlas_reasoning rollout` (Phase 20-A,
*planned*; exit 2 on an invalid combination) **before** the next run; a change takes effect
at the next process start (every `reasoning-ops` run is a new process).

## 5. The six stages (Phase 20-A's named stages; each needs its own approval)

The stages depend on Phase 20-A's controls, so **no stage can be entered before Phase 20-A is merged** (with Phase 20-B alone only stage 0
exists). The exact variable values of each stage are `python -m atlas_reasoning rollout --stages` (Phase 20-A, *planned*); this section
adds the operations around them.
Common to every stage:
- The release checklist is complete for the target stage. It never authorizes deployment itself.
- The pre-enable backup was taken, and the isolated restore drill passed on the release SHA.
- Monitoring (`REASONING-V3-MONITORING.md`) is reviewed after each run.
- Rollback never deletes reasoning rows: it changes switches back (Phase 20-A's rollback order: `EXECUTIVE_HOME` → `HUMAN_CONTEXT` →
  `CARDS_PRIMARY` → `AUDIENCE` → `EXECUTION` → `ATLAS_REASONING_V3`) or redeploys a previous release (`REASONING-V3-RECOVERY.md` §3).

### Stage 1 — Shadow reasoning (invisible)

- **Prerequisite**:
  - §3 migrations healthy; pre-enable backup and isolated drill PASS.
  - `release-eligibility` eligible on the SHA (Phase 19 release PASS, complete metadata, valid rollout).
  - The `reasoning-ops` image is pinned by digest.
  - Stage `shadow`: `ATLAS_REASONING_V3=on`, `ATLAS_REASONING_AUDIENCE=none`, every other capability off, `ATLAS_REASONING_MEMORY=off`.
  - No reasoning proxy route.
- **Expected visible behaviour**: none. Deterministic pages are unchanged; reasoning writes only to PostgreSQL; nothing serves it
  (`nginx.conf` serves only `/`, `/en/`, `/ar/`; the overlay publishes no port).
- **Verification**:
  - `rollout` reports stage `shadow`; `db-health` ok.
  - After an operator-run `gate` (§2.3) and `reason <run_id>`, the run status is `complete`, or `partial` with known reasons.
  - EN/AR pages are byte-identical to the deterministic build.
- **Monitoring**: calls, tokens, latency, failures, breaker, budget, run status, validation rejection, skipped unchanged cases, churn.
- **Rollback condition**: a monitoring threshold breached, cost above the approved budget, or any change to a deterministic page.
- **Rollback target**: `ATLAS_REASONING_EXECUTION=off` (pause) or `ATLAS_REASONING_V3=off` (stage 0). Canonical rows are kept.
- **Approval**: explicit named operator approval for Stage 1 only.

### Stage 2 — Internal review page

- **Prerequisite**:
  - Stage 1 stable for the approved period.
  - The production WSGI entry point exists (§2.3) and the proxy route for `/reasoning/` and `/api/reasoning/` was approved
    (**REQUIRES_FRESH_OPERATOR_SECURITY_APPROVAL**); `ATLAS_REASONING_MANAGERS` lists only internal reviewers.
  - Stage `internal_review`: `ATLAS_REASONING_AUDIENCE=internal`.
- **Expected visible behaviour**: internal reviewers see the reasoning surface, marked as internal review. Everyone else sees no
  change; deterministic pages remain primary.
- **Verification**: unauthenticated 401, non-listed actor 403, listed reviewer 200; `no-store`, CSP, `frame-ancestors 'none'`; a write
  without CSRF is refused.
- **Monitoring**: as Stage 1, plus web errors and the human review checklist (`evaluate review-validate`).
- **Rollback condition**: an authorization or CSRF defect, an incorrect or harmful card, or a reviewer-reported fails item.
- **Rollback target**: `ATLAS_REASONING_AUDIENCE=none` (Stage 1), and the approved removal of the proxy route.
- **Approval**: explicit operator and security approval.

### Stage 3 — Management beta

- **Prerequisite**: the Stage 2 review is complete (a valid `reasoning-management-review-v1` record bound to the release evaluation);
  management opt-in list approved; stage `management_beta`: `ATLAS_REASONING_AUDIENCE=management`.
- **Expected visible behaviour**: beta managers see reasoning cards as a beta; the deterministic dashboard stays primary and unchanged.
- **Verification**: card evidence links resolve; questions are not duplicated; lifecycle states are correct.
- **Monitoring**: as Stage 2, plus result churn and duplicate-question rate.
- **Rollback condition**: usefulness or fairness concerns; a churn or duplicate-question threshold breached; grounding failures.
- **Rollback target**: `ATLAS_REASONING_AUDIENCE=internal` (Stage 2).
- **Approval**: explicit management and operator approval.

### Stage 4 — Reasoning-first cards become primary

- **Prerequisite**: Stage 3 accepted; management approved the change of primary view; the legacy Intelligence V2 technical views stay
  reachable (REV/20 #10); stage `cards_primary`: `ATLAS_REASONING_CARDS_PRIMARY=on`.
- **Expected visible behaviour**: reasoning cards are the primary card experience for authorized managers; deterministic evidence and
  technical views remain one click away.
- **Verification**: primary and fallback views both render; deterministic outputs are unchanged.
- **Monitoring**: as Stage 3.
- **Rollback condition**: any regression in evidence visibility, or management request.
- **Rollback target**: `ATLAS_REASONING_CARDS_PRIMARY=off` (Stage 3).
- **Approval**: explicit management approval.

### Stage 5 — Notes, Q&A and Teach Atlas enabled

- **Prerequisite**:
  - Stage 4 stable; the CSRF secret file is provisioned; `ATLAS_REASONING_ALLOWED_ORIGINS` is exact.
  - Stage `human_context`: `ATLAS_REASONING_HUMAN_CONTEXT=on`.
  - Memory decision recorded: Honcho on needs `ATLAS_REASONING_MEMORY=on`, the Honcho key file and `ATLAS_REASONING_ENVIRONMENT=production`
    (one workspace); otherwise memory stays off.
- **Expected visible behaviour**: managers can add notes, answer Atlas Questions and teach Atlas; writes are canonical in PostgreSQL,
  with memory copies when Honcho is on.
- **Verification**: a note, an answer and a teaching round-trip through the management API; `memory-sync` reports no failed copies.
- **Monitoring**: as Stage 4, plus `memory.degraded_calls` and pending or failed memory copies.
- **Rollback condition**: a human-context write defect, a memory policy issue, or a Honcho outage that is not recoverable.
- **Rollback target**: `ATLAS_REASONING_HUMAN_CONTEXT=off` (Stage 4); `ATLAS_REASONING_MEMORY=off` for memory-only problems. Notes stay
  canonical.
- **Approval**: explicit management and operator approval.

### Stage 6 — Executive synthesis becomes the primary home view

- **Prerequisite**: Stage 5 stable; the ExecutiveBrief reviewed by management for the approved period; `ATLAS_REASONING_EXECUTIVE_CALL_BUDGET`
  approved; stage `executive_home`: `ATLAS_REASONING_EXECUTIVE_HOME=on`.
- **Expected visible behaviour**: the ExecutiveBrief leads the reasoning home for authorized managers; card and deterministic views
  remain reachable.
- **Verification**: every statement cites results; an unchanged input makes zero executive calls (`executive.unchanged_zero_call`); a
  failed synthesis keeps the current brief.
- **Monitoring**: as Stage 5, plus `executive.model_calls` and `executive.by_decision`.
- **Rollback condition**: an unfaithful or harmful brief, a synthesis failure trend, or management request.
- **Rollback target**: `ATLAS_REASONING_EXECUTIVE_HOME=off` (Stage 5). The brief history is kept.
- **Approval**: explicit management approval.

## 6. Release record (REV/20 #11)

The release record is Phase 20-A's (*planned*) `python -m atlas_reasoning release-metadata --commit SHA` output (commit, model, prompt / contract /
validator versions, evaluation schema, thresholds, migrations, rollout), and the release gate is its `release-eligibility --evaluation
RUN.json`. `deploy/production/reasoning_ops/release_checklist.py validate` takes both (and `rollout`) as attached evidence, adds the deployment identities (CI run, image
digests) and the operational items (`REASONING-V3-RELEASE-CHECKLIST.md`).
