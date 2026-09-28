# Waset Atlas production runbook

This runbook installs the Task 9 systemd wrapper around the existing Task 8 one-cycle command. It
does not change Atlas analytics, schedule retries, deliver alerts, or delete retained evidence.
Monday remains read-only and authoritative. The Task 6 production-operation lock remains the sole
authority for overlap between scheduled runs, manual sync, publish, and rollback.

## 1. Host setup and permissions

Required: Linux with systemd, Docker Engine, the Docker Compose v2 plugin at `/usr/bin/docker`, and
immutable reviewed Atlas app and web images. These commands create a dedicated numeric identity and
the fixed production paths. UID/GID 10001 must match the app container:

```sh
sudo groupadd --system --gid 10001 atlas
sudo useradd --system --uid 10001 --gid 10001 --home-dir /var/lib/waset-atlas --shell /usr/sbin/nologin atlas
sudo install -d -o root -g atlas -m 0750 /opt/waset-atlas /opt/waset-atlas/releases
sudo install -d -o root -g root -m 0700 /etc/waset-atlas /etc/waset-atlas/secrets
sudo install -d -o atlas -g atlas -m 0750 /var/lib/waset-atlas /var/lib/waset-atlas/builds /var/lib/waset-atlas/published
sudo install -d -o atlas -g atlas -m 0700 /var/lib/waset-atlas/raw /var/lib/waset-atlas/raw/monday /var/lib/waset-atlas/locks
```

Do not add `atlas` to the Docker group: that membership is root-equivalent. The root-owned systemd
wrapper talks to the Docker daemon, but the Atlas process in the hardened container runs only as
UID/GID 10001 and owns only the data paths above. Application source and release files remain
root-owned and read-only to that process. Confirm `sudo /usr/bin/docker info` and
`sudo /usr/bin/docker compose version` before enabling the timer.

## 2. Configuration and secrets

Install the tracked example, then edit only deployment values. The example includes every required
or production-significant setting; keep both image references pinned by digest.

```sh
sudo install -o root -g root -m 0600 deploy/production/atlas.env.example /etc/waset-atlas/atlas.env
sudo install -o root -g atlas -m 0640 /dev/null /etc/waset-atlas/secrets/monday_api_token
sudoedit /etc/waset-atlas/atlas.env
sudoedit /etc/waset-atlas/secrets/monday_api_token
sudo chown root:root /etc/waset-atlas/atlas.env
sudo chmod 0600 /etc/waset-atlas/atlas.env
sudo chown root:atlas /etc/waset-atlas/secrets/monday_api_token
sudo chmod 0640 /etc/waset-atlas/secrets/monday_api_token
```

The secret file contains exactly the read-only Monday token and one final newline. Never put the
token, an Authorization header, or `MONDAY_API_TOKEN=` in the environment file, unit files, image,
Compose YAML, shell history, tickets, or journals. The container sees the secret read-only at
`/run/secrets/monday_api_token`; only its path appears in configuration.

`atlas.env` is the single deployment configuration source for image digests, host data/token paths,
UID/GID, local HTTP bind, API version, board and contract versions, history start, hourly interval,
stale threshold, maximum consecutive failures, and maximum cycle duration. Inside the container,
`ATLAS_DATA_DIR=/var/lib/waset-atlas` is fixed deliberately. The application's existing configuration
derives `raw/monday`, `builds`, `published`, `locks`, `locks/alerts`, and
`locks/scheduled-cycles` from that root; do not duplicate or override those directories separately.

## 3. Data layout and truth hierarchy

The host directory `/var/lib/waset-atlas` is mounted at the identical absolute path in both containers:

```text
/var/lib/waset-atlas/
  raw/monday/                  immutable Monday evidence
  builds/                      staged immutable builds and attempt records
  published/current           authoritative live relative symlink
  published/CURRENT.json      operational metadata, not the live pointer
  published/history/          immutable publication history
  locks/production.lock       Task 6 shared operation lock
  locks/scheduled-cycles/      immutable scheduled-cycle journal
  locks/alerts/state.json      atomically replaced alert lifecycle state
```

The actual `published/current` symlink is authoritative for what is served. Task 7 status is
authoritative for current health/freshness. Scheduled-cycle records are authoritative for cycle
outcomes; alert state is the durable incident lifecycle. The systemd journal is execution output,
not a replacement for those persisted records.

## 4. Deploy a release

In CI or on the approved release workstation, build the two repository Dockerfiles from the repository
root, run the image tests, publish them to the approved registry, and record the immutable digests:

```sh
docker build -f deploy/production/Dockerfile.app -t REGISTRY/waset-atlas-app:RELEASE_ID .
docker build -f deploy/production/Dockerfile.nginx -t REGISTRY/waset-atlas-web:RELEASE_ID .
```

Registry authentication, push, signing, and digest approval follow the platform's release process.
Production Compose deliberately contains no local build fallback: the server only pulls the reviewed
digests configured in `atlas.env`, so deployment cannot accidentally upload a broad source context.

Copy a reviewed checkout to a versioned root-owned directory; do not run from a mutable developer
checkout. Replace `RELEASE_ID` below with the reviewed commit ID.

```sh
sudo install -d -o root -g atlas -m 0750 /opt/waset-atlas/releases/RELEASE_ID
sudo cp -a deploy docs /opt/waset-atlas/releases/RELEASE_ID/
sudo chown -R root:atlas /opt/waset-atlas/releases/RELEASE_ID
sudo chmod -R u=rwX,g=rX,o= /opt/waset-atlas/releases/RELEASE_ID
sudo ln -sfn /opt/waset-atlas/releases/RELEASE_ID /opt/waset-atlas/current
sudo install -o root -g root -m 0644 deploy/production/waset-atlas.service /etc/systemd/system/waset-atlas.service
sudo install -o root -g root -m 0644 deploy/production/waset-atlas.timer /etc/systemd/system/waset-atlas.timer
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml config --quiet
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml pull atlas-runtime atlas-web
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml up -d --no-deps atlas-web
sudo systemctl daemon-reload
sudo systemctl enable --now waset-atlas.timer
```

`compose config --quiet` validates interpolation without starting Atlas. Starting `atlas-web` only
serves the existing `published/current`; it never starts Atlas or contacts Monday. The timer is hourly,
persistent across downtime, and applies one stable 0–10 minute randomized delay. systemd does not
start a second copy of an already-active oneshot service, and Task 6 also refuses any competing
production operation with exit 75. Missed timer intervals are not replayed as a catch-up storm.

The Compose service binds only `127.0.0.1:18000` by default. To expose the target public URL
`https://atlas.wasetco.com`, provision the approved host reverse proxy and a valid TLS certificate,
then proxy that hostname to `http://127.0.0.1:18000`. TLS termination, DNS, certificate renewal, and
internet firewall rules are host prerequisites and are intentionally not embedded in this repository.
Do not expose port 18000 directly. The web container serves the real relative
`published/current` symlink—there is no second copied web tree. `/` returns the generated deterministic
root page, which leads to English; `/ar/` remains the Arabic route. No browser-language detection is
performed.

## 5. Normal operation

```sh
systemctl list-timers waset-atlas.timer
systemctl status waset-atlas.timer waset-atlas.service
journalctl -u waset-atlas.service --since today --output=short-iso
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps atlas-runtime status --json
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml logs --no-log-prefix --tail=200 atlas-web
```

The service executes exactly one `scheduled-run --json`. Exit 75 is accepted by systemd because it
means a lock-contention skip, not a scheduled failure; the JSON and immutable locked cycle record
remain the audit truth. Any other non-zero status marks the oneshot failed:

- `2`: configuration/lock configuration;
- `3`: sync failed, last good publication unchanged;
- `4`: publication rejected or failed before switch;
- `5`: pointer switched but publication durability/metadata is inconsistent;
- `6`: status or alert-state evaluation/persistence failed;
- `7`: scheduled-cycle record write failed.

Task 8 alerts are persisted at `locks/alerts/state.json` and their active types appear in safe
`status --json` / `scheduled-run --json` output and therefore in the systemd journal. Alerts are not delivered externally
in Task 9: no email, Slack, or webhook transport is configured or claimed.
Operators must monitor service failures, freshness, and active alert types through the commands above
until an approved external destination is implemented.

## 6. Manual operations

Run an immediate normal cycle through systemd:

```sh
sudo systemctl start waset-atlas.service
sudo systemctl status waset-atlas.service
```

For diagnosis, first run read-only status. Manual staging never publishes; manual publish and
rollback revalidate the target and acquire the same Task 6 lock:

```sh
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps atlas-runtime status --json
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps atlas-runtime run-once --json
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps atlas-runtime publish ATTEMPT_ID --json
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps atlas-runtime rollback --json
```

Never edit `current`, `CURRENT.json`, publication history, build markers, scheduled-cycle records,
or alert state manually. Never publish “the newest” directory without an explicit validated ID.

Normal production is `timer -> scheduled-run`, which syncs, validates, and atomically publishes one
exact attempt. `run-once` is manual staging only. `publish ATTEMPT_ID` is a separate explicit switch,
and `rollback [ATTEMPT_ID]` is an explicit operator recovery action.

## 7. Failure response

1. Capture `systemctl status waset-atlas.service` and the relevant journal window.
2. Run the read-only `status --json` command above.
3. Inspect the latest immutable JSON in `/var/lib/waset-atlas/locks/scheduled-cycles/` and the
   allow-listed `/var/lib/waset-atlas/locks/alerts/state.json`; do not paste secrets or raw responses.
4. Confirm the live pointer with `sudo -u atlas readlink /var/lib/waset-atlas/published/current`.
5. Fix the classified cause. Trigger one cycle; do not add a whole-cycle retry loop.

For exit 3/4, the previous live dashboard remains authoritative. For exit 5, the pointer may already
have switched: do not assume rollback, and do not republish until the actual pointer and selected
build have been verified. For exit 6/7, preserve the operational files; a later run reconstructs
the scheduled-failure evidence from the journal where possible.

Classify common failures as follows:

- **Monday unavailable:** an exit 3 network/rate-limit/source failure leaves the last good site live.
  Preserve its cycle record, wait for the upstream or approved rate-limit window, then trigger one
  controlled cycle. Never add a shell retry loop.
- **Stale data:** confirm `freshness_state`, `age_seconds`, the last successful attempt, and timer
  activity. A live but stale page remains the last validated truth; investigate missed/failed cycles
  before running one controlled cycle.
- **Consecutive failures:** inspect the active alert types and the latest immutable cycle outcomes.
  Correct the repeated typed cause; do not clear alert state by hand. A later success resolves the
  lifecycle according to Task 8.
- **Build failure:** exit 3 with a build/dashboard category never switches `current`. Preserve raw and
  the failed attempt evidence, correct code/config, and retry later with a new attempt.
- **Publish failure:** exit 4 leaves the prior site live. Validate the explicit staged attempt before
  using `publish ATTEMPT_ID`; never scan for or publish a fallback automatically.
- **Metadata inconsistency:** exit 5 means the live pointer may have switched. Follow section 8.
- **Lock contention:** exit 75 is a deliberate no-op. Identify the current Task 6 lock holder, wait
  for it to finish, and invoke at most one later cycle. Never delete a live lock file.

## 8. Metadata inconsistency recovery

Stop new timer triggers, wait for the oneshot to finish, and record the current status and pointer:

```sh
sudo systemctl stop waset-atlas.timer
systemctl is-active waset-atlas.service
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps atlas-runtime status --json
sudo -u atlas readlink /var/lib/waset-atlas/published/current
sudo -u atlas cat /var/lib/waset-atlas/published/CURRENT.json
sudo -u atlas ls -1 /var/lib/waset-atlas/published/history
```

If the relative pointer resolves to an intact completed build and only CURRENT/history metadata is
inconsistent, explicitly republish that exact `ATTEMPT_ID` to generate a new verified publication
record:

```sh
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps atlas-runtime publish ATTEMPT_ID --json
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps atlas-runtime status --json
sudo systemctl start waset-atlas.timer
```

If the pointer or artifacts fail validation, publish a separately identified known-good completed
attempt, or run explicit `rollback ATTEMPT_ID`. Do not repair hashes, manifests, symlinks, or metadata
by hand. Escalate if no validated target exists.

## 9. Upgrade and restart

There is no long-running Atlas daemon to restart. For an application/image or unit upgrade:

```sh
sudo systemctl stop waset-atlas.timer
systemctl is-active waset-atlas.service
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml pull atlas-runtime atlas-web
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml up -d --no-deps atlas-web
sudo systemctl daemon-reload
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps atlas-runtime status --json
sudo systemctl start waset-atlas.timer
```

Wait until `systemctl is-active waset-atlas.service` reports `inactive` before changing the release
symlink or image digest. To restart scheduling only, use `systemctl restart waset-atlas.timer`; never
configure `Restart=always` for the oneshot.

To restart only the static container, use the same `up -d --no-deps atlas-web` command; the persistent
host data and `current` pointer are not replaced. After a host reboot, Docker restores `atlas-web`
because of its restart policy and systemd resumes the persistent timer. Verify both explicitly; a
missed interval produces at most one activation, not one activation per missed hour.

## 10. Security, disk, and backups

- Review Docker daemon access, `/etc/waset-atlas` ownership, image digests, and token
  scope regularly. Rotate the token in its external secret file, then trigger one controlled cycle.
- Before release approval, scan the Git diff, Docker build contexts, `docker image inspect`,
  `docker history --no-trunc`, generated site, Compose config, unit files, and captured test output
  for credential patterns. Report only pass/fail and safe identifiers—never echo a discovered value.
- Monitor `df -h /var/lib/waset-atlas`, `df -i /var/lib/waset-atlas`, and
  `du -sh /var/lib/waset-atlas/*`. Atlas performs no retention deletion in Task 9. Never improvise
  deletion of raw evidence, builds, publication history, scheduled cycles, or alert history.
- Before a backup, stop the timer and confirm the service is inactive. Back up
  `/var/lib/waset-atlas` with permissions, timestamps, and symlinks preserved. Back up
  `/etc/waset-atlas` separately into an encrypted secret store with stricter access. Restore into a
  staging host first and run `status --json`; do not point production at an unverified restore.
- Journals and Atlas JSON outputs are designed to contain scheduled result, safe attempt/publication
  IDs, freshness/status, typed failure categories, and active alert types—never exception text,
  Authorization headers, or tokens. Treat them as operationally sensitive anyway. Use the host's
  bounded journald retention/rotation policy; do not add unbounded container log files.

## 11. Task 10 preparation — controlled live Monday validation, do not execute yet

Before Task 10, approve the production host, reviewed image digests, read-only token scope, board ID,
contract `1.4.0`, history start, maintenance window, and named operator. Back up the existing data root,
stop the timer, and capture `status --json`. Task 10 may then run exactly one controlled command:

```sh
sudo systemctl stop waset-atlas.timer
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps atlas-runtime scheduled-run --json
sudo /usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps atlas-runtime status --json
```

Task 10 must verify the actual source run, publication pointer, EN/AR pages, evidence coverage, and
absence of secrets before restarting the timer. None of these live commands is executed in Task 9.
