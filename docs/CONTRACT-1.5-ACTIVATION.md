# Contract 1.5.0 activation and rollback runbook

**Status: not executed. Nothing in this document is authorized until the Atlas business owner approves activation in writing
and that approval is recorded in `docs/DECISIONS.md`.** Production runs contract **1.4.0**. This runbook separates five steps
that are often confused; each has its own approval and none implies the next.

| Step | What changes | Production effect |
|---|---|---|
| 1. Merge PR #25 into `integration` | Repository only | None |
| 2. Promote `integration` → `main` (separate promotion PR) | Repository only | None |
| 3. Deploy the promoted code | New images/release on the host, still contract 1.4.0 | None visible: 1.4 output is byte-identical (`fixtures/golden`, `tests/test_contract_v14_compat.py`) |
| 4. Activate contract 1.5.0 | Code allow-list + host configuration | Dashboard switches to the 1.5 interpretation layer after the next successful cycle |
| 5. Roll back to 1.4.0 | Host configuration + explicit rollback | Last 1.4 publication is live again |

All host commands below use the compose prefix from [`PRODUCTION-RUNBOOK.md`](PRODUCTION-RUNBOOK.md):

```sh
COMPOSE="sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml"
```

## 1–2. Merge and promotion

- PR #25 targets `integration`. Required before merge: CI green (`make test`, including `contract-v14-compat`,
  `profile-publication-v15` and `contract-v15-release`), review approval, and an accurate PR description.
- Promotion is a separate `integration → main` pull request (`main-promotion-policy` in CI enforces the route).
- Neither step touches the host.

## 3. Deploy the promoted code on contract 1.4.0

Follow `PRODUCTION-RUNBOOK.md` §4 (new release) or §9 (upgrade). `atlas.env` keeps `ATLAS_CONTRACT_VERSION=1.4.0`. Then verify
that nothing changed for 1.4:

```sh
$COMPOSE run --rm --no-deps atlas-runtime status --json     # live_usable true; no build_tampered; contract_version 1.4.0
sudo -u atlas ls /var/lib/waset-atlas/published/current/     # no publication.json (1.4 builds never have one)
```

After the next scheduled cycle, `status --json` must again be healthy and the new build must still have no `publication.json`.
The explicit rollback in §5 must also work against a publication made before the deploy (covered in CI by
`LegacyBuildOperationsTests`). If any of these fail, roll back the release (§9 of the production runbook) — do not continue.

## 4. Activate contract 1.5.0

### 4.1 Preconditions (all required)

1. Written activation approval from the Atlas business owner, recorded in `docs/DECISIONS.md`.
2. Threshold state understood and accepted. Activation is possible while thresholds are unapproved: every component then shows its
   facts with "rule not approved", and Overall Status shows "Not enough approved logic to classify" (D25). Approving any threshold
   is a separate decision and a new contract version; never edit `config/monday-contract-v1.5.json` values in place on the host.
3. Shadow review of a 1.5 build of recent production data, made **offline** on a read-only copy of a verified raw run (never
   against Monday, never on the production data directory):

   ```sh
   PYTHONPATH=src python3 -m atlas_commander.profile_cli --contract 1.5.0 dashboard COPY_OF_RUN/extract.json /tmp/atlas-shadow-15
   ```

   Review `en/` and `ar/` for every Editor (Overall Status, why, components, Recent Change, evidence). Record the expected
   **Editor count** and the Editor list (the attested identities raise it; e.g. 14 on the 2026-09-29 production copy versus 5
   under 1.4.0). Confirm no Editor appears twice and quarantined identities (`New`, `Done`, `El Baz`) are absent.
4. A 1.4.0 publication exists that you can roll back to (the current publication is pinned regardless of age). Record its
   `ATTEMPT_ID` from `status --json` → `current_publication.attempt_id` **before** activating.

### 4.2 Activation change set (a reviewed code change plus configuration)

Setting `ATLAS_CONTRACT_VERSION=1.5.0` alone is refused ("not allowed for production sync"). Activation needs a reviewed commit,
through the same merge → promotion → deploy path, that changes exactly:

| File | Line today | Activation change |
|---|---|---|
| `src/atlas_sync/config.py` | `PRODUCTION_CONTRACT_VERSIONS = ("1.4.0",)` | `("1.4.0", "1.5.0")` — both allowed, so rollback is a configuration change |
| `src/atlas_sync/config.py` (module docstring) | "production accepts only 1.4.0" | document both versions |
| `src/atlas_commander/runtime.py` | `ACTIVE_CONTRACT_VERSION = "1.4.0"` | leave at 1.4.0 until 1.5 has run successfully in production; change in a later release |
| `deploy/production/compose.yaml` | `${ATLAS_CONTRACT_VERSION:-1.4.0}` | keep the 1.4.0 default (explicit opt-in only) |
| `deploy/production/atlas.env.example` | `ATLAS_CONTRACT_VERSION=1.4.0` | unchanged in the repository |
| host `/etc/waset-atlas/atlas.env` | `ATLAS_CONTRACT_VERSION=1.4.0` | `ATLAS_CONTRACT_VERSION=1.5.0` (the actual activation switch) |

The systemd unit and timer carry no contract version and do not change.

### 4.3 Switch and fresh 1.5 ingest

A 1.5 build must come from a 1.5 ingest: publication refuses a build whose raw run manifest names another contract. Every
cycle ingests afresh, so the first cycle after the switch is the fresh 1.5 ingest.

```sh
sudo systemctl stop waset-atlas.timer
systemctl is-active waset-atlas.service                       # wait for "inactive"
$COMPOSE run --rm --no-deps atlas-runtime status --json         # record current_publication.attempt_id (the 1.4 rollback target)
sudoedit /etc/waset-atlas/atlas.env                             # ATLAS_CONTRACT_VERSION=1.5.0
sudo systemctl start waset-atlas.service                        # one scheduled-run: fresh 1.5 ingest, build, validate, publish
sudo systemctl status waset-atlas.service
sudo systemctl start waset-atlas.timer
```

Until that cycle succeeds, `status --json` reports the 1.4 live build as `wrong_contract` for the new configuration; that is
expected for the minutes between the switch and the first 1.5 publication. If the cycle fails, go to §5.

### 4.4 Smoke test (after the first 1.5 publication)

```sh
$COMPOSE run --rm --no-deps atlas-runtime status --json
curl -fsS http://127.0.0.1:18000/            | grep -o 'atlas-release-id" content="[^"]*"'
curl -fsS http://127.0.0.1:18000/en/         | grep -o 'atlas-release-id" content="[^"]*"'
curl -fsS http://127.0.0.1:18000/ar/         | grep -o 'atlas-release-id" content="[^"]*"'
# publication.json and dashboard.json are not served publicly (nginx serves only /, /en/ and /ar/); read them on the host
sudo -u atlas cat /var/lib/waset-atlas/published/current/publication.json
sudo -u atlas cat /var/lib/waset-atlas/published/current/dashboard.json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d["editors"]), sorted(e["display_name"] for e in d["editors"]))'
```

Pass only if all hold:

- `status --json`: `live_usable` true, no failure categories, `current_publication.contract_version` `1.5.0`, freshness `fresh`,
  and `current_publication.source_run_id` is the run ingested by the §4.3 cycle (**latest ingest**).
- The release ID is identical on `/`, `/en/` and `/ar/` and equals `publication.json` → `release_id`; `publication.json` names
  `executable_contract_version` `1.5.0`, and its `source.retrieved_at` equals `current_publication.monday_retrieved_at` in
  `status --json` (**same snapshot across routes**).
- The Editor count and list equal the shadow review in §4.1 (**Editor count**); no Editor appears twice.
- One English and one Arabic Editor Profile each show the Overall Status section, "Why this status", the three components with
  their reasons, the Deadline line with the absolute late rate, and Recent Change.

Any failure: §5.

## 5. Roll back to contract 1.4.0

Publication and rollback accept only builds of the configured contract. Rolling back therefore switches the configuration first
and then the pointer, to the 1.4 publication recorded in §4.1 (pinned regardless of age):

```sh
sudo systemctl stop waset-atlas.timer
systemctl is-active waset-atlas.service                       # wait for "inactive"
sudoedit /etc/waset-atlas/atlas.env                             # ATLAS_CONTRACT_VERSION=1.4.0
$COMPOSE run --rm --no-deps atlas-runtime rollback ATTEMPT_ID_1_4 --json
$COMPOSE run --rm --no-deps atlas-runtime status --json         # live_usable true, contract_version 1.4.0
sudo systemctl start waset-atlas.timer
```

If the recorded 1.4 attempt is no longer available (it left retention and is not the pinned previous publication), do not
hand-edit anything: with the 1.4.0 configuration in place, run one normal cycle (`sudo systemctl start waset-atlas.service`), which
ingests and publishes a fresh 1.4 build.

To roll back the **code** as well (for example if the deployed release itself misbehaves on 1.4.0), follow §9 of the production
runbook with the previous release's image digests; 1.4 builds published by either release remain valid for status, publication
and rollback.

## 6. Restore a previous published release (either contract)

```sh
sudo -u atlas ls -1 /var/lib/waset-atlas/published/history      # publication records, newest last
$COMPOSE run --rm --no-deps atlas-runtime rollback --json          # back to the previous publication
$COMPOSE run --rm --no-deps atlas-runtime rollback ATTEMPT_ID --json   # or to an explicit earlier publication of the configured contract
$COMPOSE run --rm --no-deps atlas-runtime status --json
```

A rollback revalidates the target (artifacts, raw evidence, contract, publication identity for 1.5 builds) under the Task 6 lock
and never edits `current`, `CURRENT.json` or history by hand.

## 7. What this runbook never does

It never mutates Monday, never approves or edits a threshold, never changes a published build, and never activates 1.5.0
without the recorded approval in §4.1.
