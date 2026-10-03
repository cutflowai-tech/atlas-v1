# Reasoning V3 — live topology

This is the production topology that the rollout added (REV/20). It is built on the Phase 20-B artifacts and the plan in
[`REASONING-V3-PRODUCTION-ROLLOUT.md`](REASONING-V3-PRODUCTION-ROLLOUT.md), and does not change either. The deterministic Atlas
deployment (`compose.yaml`, `nginx.conf`, the hourly `waset-atlas.timer`) is unchanged.

## 1. Services

`deploy/production/compose.reasoning-live.yaml` is loaded together with `compose.yaml` and `compose.reasoning.yaml`.

| Service | Role | Exposure |
|---|---|---|
| `reasoning-db` | Canonical Reasoning V3 PostgreSQL 17 (pinned digest), database and role `atlas_reasoning` | Internal `reasoning-db` network only: no port and no outbound route |
| `reasoning-web` | `gunicorn atlas_reasoning.wsgi:application` on the reasoning image, with the `reasoning-ops` hardening and environment allow-list plus the web settings. The entry point is exactly `web_app.create_app()` | `127.0.0.1:${ATLAS_REASONING_WEB_PORT:-18002}` for the host reverse proxy |
| `reasoning-ops` | The Phase 20-B operations service, unchanged commands (`migrate`, `db-health`, `gate`, `reason`, …) | No port. It joins `reasoning-db` and reads `/var/lib/waset-atlas` read-only for `gate` |

`reasoning-db` and `reasoning-web` use the `reasoning-live` profile. `reasoning-ops` keeps `reasoning-operations`. A plain `up` of
`compose.yaml` still starts only `atlas-web`.

## 2. Host files

Every credential is a file under `/etc/waset-atlas/secrets/` and is mounted read-only. No value appears in YAML or in `reasoning.env`.

| File | Reader |
|---|---|
| `reasoning_database_url` | `reasoning-ops`, `reasoning-web` (role and database `atlas_reasoning` on host `reasoning-db`, port 5432) |
| `reasoning_db_password` | `reasoning-db` (uid 999) |
| `openrouter_api_key`, `honcho_api_key` | `reasoning-ops`, `reasoning-web` |
| `reasoning_csrf_secret` | `reasoning-web` (at least 32 bytes) |

`/etc/waset-atlas/reasoning.env` holds the stage switches (`python -m atlas_reasoning rollout --stages`) and the web settings
`ATLAS_REASONING_MANAGERS`, `ATLAS_REASONING_ALLOWED_ORIGINS`, `ATLAS_REASONING_ACTOR_HEADER` and `ATLAS_REASONING_MONDAY_ITEM_URL`.
The database data directory is `/var/lib/waset-atlas-reasoning/postgres`, owned by uid 999.

## 3. Reverse proxy

The host nginx routes `/reasoning/` and `/api/reasoning/` to `reasoning-web`. Every other path still goes to `atlas-web`.

- The proxy sets the header named by `ATLAS_REASONING_ACTOR_HEADER`. Because `proxy_set_header` replaces it, a client can never supply its own value.
- `ATLAS_REASONING_ALLOWED_ORIGINS` is exactly `https://atlas.wasetco.com`.
- CSRF, Origin, the manager allow-list and the security headers stay the application's own.

**Operator decision (2026-10-03).** atlas.wasetco.com has no login. The operator chose to serve the reasoning surface publicly, as the
deterministic dashboard already is. The proxy therefore sets one fixed shared actor, which is the only entry in `ATLAS_REASONING_MANAGERS`.
As a result:

- Notes, answers and teachings are attributed to that shared actor, not to a person.
- Anyone who can reach the site can write human context. CSRF and Origin still stop cross-site writes.

Adding authentication later changes only the proxy, which then sets the authenticated user, and the allow-list.

## 4. Operations

`C` below stands for `docker compose --env-file /etc/waset-atlas/atlas.env --env-file /etc/waset-atlas/reasoning.env --project-directory
/opt/waset-atlas/current -f deploy/production/compose.yaml -f deploy/production/compose.reasoning.yaml -f
deploy/production/compose.reasoning-live.yaml`.

- **Start or refresh:** `C up -d reasoning-db reasoning-web`.
- **Database:** `C run --rm reasoning-ops migrate`, then `db-health`.
- **Reasoning:**
  - `C run --rm reasoning-ops gate /var/lib/waset-atlas/published/current` prints the run id.
  - `C run --rm reasoning-ops reason <run_id>` reasons that run (Phase 18 budget and breaker).
  - Unchanged evidence creates no work.
- **Stage change:**
  1. Edit `reasoning.env`.
  2. Validate with `C run --rm reasoning-ops rollout`.
  3. Restart the web process with `C up -d reasoning-web`.
- **Backup:** `C exec reasoning-db pg_dump --format=custom --schema=atlas_reasoning --no-owner --no-privileges -U atlas_reasoning atlas_reasoning`
  writes to a root-only file. Keep the release record with it (`REASONING-V3-RECOVERY.md` §2).

## 5. Daily schedule

Reasoning runs **once per day** by operator decision (2026-10-03). The hourly deterministic sync (`waset-atlas.timer`) is unchanged.

- `waset-atlas-reasoning.timer` runs at 03:40 UTC (06:40 Cairo) and starts `waset-atlas-reasoning.service`, a hardened oneshot.
- The service runs `deploy/production/reasoning-daily.sh`:
  1. `gate` on `/var/lib/waset-atlas/published/current`.
  2. `reason <run_id>`, only when the gate created LLM or lifecycle work.
- Unchanged evidence therefore makes no LLM call. Budgets, the breaker and the rollout switches are the application's.
- To pause, run `systemctl disable --now waset-atlas-reasoning.timer`, or set `ATLAS_REASONING_EXECUTION=off`. With execution off,
  `gate` exits 2 and the unit reports the refusal.

## 6. Rollback

Rollback follows `REASONING-V3-ROLLOUT.md` §4 and `REASONING-V3-RECOVERY.md` §3. It never deletes reasoning rows.

1. **Lower a stage.** Set the switch to `off` in the documented order (`EXECUTIVE_HOME` → `HUMAN_CONTEXT` → `CARDS_PRIMARY` →
   `AUDIENCE` → `EXECUTION` → `ATLAS_REASONING_V3`), then restart `reasoning-web`.
2. **Hide the surface.** Remove the `/reasoning/` and `/api/reasoning/` locations from the host nginx and reload it, then
   `C stop reasoning-web`. The deterministic dashboard is unaffected.
3. **Stop everything.** Run `C stop reasoning-web reasoning-db`. The data directory is kept.
