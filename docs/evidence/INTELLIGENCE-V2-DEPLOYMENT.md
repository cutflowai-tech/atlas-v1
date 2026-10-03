# Intelligence V2 production deployment (D53), 2026-09-29 UTC

Deployment of `feat/atlas-intelligence-v2` to the Atlas production host, following `docs/PRODUCTION-RUNBOOK.md` §4, §9, §10 and
§10b. No secret, token or Monday response appears here. Monday was read only (one scheduled cycle); nothing was written to it.

## Code

| Item | Value |
|---|---|
| Deployed commit (tested, pushed) | `ee0c19b3b5c64d8e340d1e191252c78737d5d646` (`origin/feat/atlas-intelligence-v2`, local HEAD == remote HEAD) |
| Base | `ui-ux` `eccaa8c9735d51f92a866103b0c094774ade4f61` (unchanged); `main` `d9918d105fb0b130bd47dfcc996723341d8ac989` (unchanged, not merged) |
| Local gate on that commit | `make test`: 751 tests, 0 failures, 3 skipped (Docker runtime tests without `ATLAS_RUN_DOCKER_TESTS=1`); ruff and mypy clean |
| Remote CI | not triggered: CI runs on pull requests and on pushes to `main` / `integration` only |

This record is a documentation-only commit on top of the deployed commit; it changes no runtime file.

## Release

| Item | Value |
|---|---|
| Release directory | `/opt/waset-atlas/releases/ee0c19b3b5c64d8e340d1e191252c78737d5d646` (from `git archive`; 254 files, SHA-256 identical to the commit, plus the marker `.atlas/RELEASE_SHA`) |
| App image | `waset-atlas-app:ee0c19b` `sha256:f2ac8a17a221c7dc09e186d72be48336363338573096caf06f505effaadf35ce`, label `org.opencontainers.image.revision=ee0c19b…`; `src/`, `config/`, `contracts/` SHA-256 identical to the release tree except `demo.py` (excluded by `Dockerfile.app.dockerignore`) |
| Web image | `waset-atlas-web:ee0c19b` `sha256:ccdd964417927abb17754c64955b8e6ff7037363465ef2a086a77ff1daea2551`, same label |
| Configuration | `/etc/waset-atlas/atlas.env`: only `ATLAS_APP_IMAGE` / `ATLAS_WEB_IMAGE` changed (mode 0600, root); `ATLAS_CONTRACT_VERSION=1.5.0` unchanged |
| Units | `waset-atlas.service` / `.timer` byte-identical to the release; not reinstalled |

## Rollback point recorded before the switch

| Item | Value |
|---|---|
| Previous release | `/opt/waset-atlas/releases/d9918d105fb0b130bd47dfcc996723341d8ac989` |
| Previous images | app `sha256:49b69fe3398cfcf655e45a0214a42b8ab8ddfa892d621f80ccd8876a664ab2c8` (`waset-atlas-app:d9918d1`), web `sha256:02c0fe0c14730f1180b3ecd56dde52545980273f67e5d20861c598153c9986de` (`waset-atlas-web:d9918d1`) |
| Previous publication | attempt `20260929T220732Z-c879e514b8a2`, publication `20260929T221204Z-3c24b487db7f` (pinned as the previous publication) |
| Backup | `/var/backups/waset-atlas/pre-ee0c19b-20260929T223930Z.tar.gz` (whole `/var/lib/waset-atlas`, permissions and symlinks preserved, 330 MB, root 0600), taken with the timer stopped and the service inactive; `atlas.env` copy `/etc/waset-atlas/atlas.env.pre-ee0c19b-20260929T223930Z` (0600) |

## Sequence (UTC)

1. 22:37 read-only `status --json`: live, fresh, no failures or alerts; service inactive.
2. Release tree staged and verified; images built on the host from it and verified.
3. 22:39 timer stopped, service confirmed inactive, backup taken.
4. `atlas.env` image IDs updated; `/opt/waset-atlas/current` → the new release; `compose config --quiet`; `up -d --no-deps atlas-web`.
5. `status --json` with the new app image: still live on the previous publication.
6. 22:41-22:46 one documented cycle, `systemctl start waset-atlas.service` (fresh read-only ingest, build, validation, atomic
   publish): exit 0, `published`.
7. Timer restarted.
8. 23:07 first timer-driven cycle on the new release: attempt `20260929T230731Z-d11875f2668e` published (result `success`,
   exit 0), `intelligence-v2.json` approved_only with 55 findings, release `release-575488820be745841630`; status live, fresh, no
   failures or alerts.

## Result

| Item | Value |
|---|---|
| Publication | attempt `20260929T224132Z-371d40ff48fa`, publication `20260929T224626Z-5208d5fda5cc`, source run `20260929T224132Z-59516f38819c`, Monday retrieved 2026-09-29T22:44:18Z, contract 1.5.0 |
| Release ID | `release-2b3009af948114e89d50`, identical on `/`, `/en/`, `/ar/` and in `publication.json` |
| Intelligence V2 | `intelligence-v2.json` `approved_only`, `publishable`, same run and contract; 55 findings; Top 5: open work past ETA (Strong), late projects start with too little runway (Strong), Refaat's Simple Short execution (Moderate), Will's and Mario's late-rate headlines need context (Moderate) |
| Status | `live_usable` true, `fresh`, no failure categories, no active alerts, 0 consecutive failures |
| Live site | `https://atlas.wasetco.com/` EN and AR: 5 Top cards, evidence drawers and project drawers, Editor Profile Intelligence sections, Data & rules card; RTL; no overflow at 375 px; no console errors; no external requests |

## Rollback

1. Pages without Intelligence, same code: `atlas-runtime rollback 20260929T220732Z-c879e514b8a2` (runbook §6) — the previous
   publication (old UI, no artifact) stays valid.
2. Previous code: stop the timer, restore the two image IDs above in `atlas.env` (or copy back
   `/etc/waset-atlas/atlas.env.pre-ee0c19b-20260929T223930Z`), point `/opt/waset-atlas/current` at the `d9918d1…` release,
   `up -d --no-deps atlas-web`, then `rollback 20260929T220732Z-c879e514b8a2`, `status --json`, start the timer (runbook §9).
3. Feature off in code: `publication.include_in_site_build: false` through the normal release path (runbook §10b).
