# Waset Atlas production runbook

This runbook installs the Task 9 systemd wrapper around the existing Task 8 one-cycle command. It
does not change Atlas analytics, schedule retries, deliver alerts, or delete retained evidence.
Monday remains read-only and authoritative. The Task 6 production-operation lock remains the sole
authority for overlap between scheduled runs, manual sync, publish, and rollback.

## 1. Host setup and permissions

Required: Linux with systemd, Docker Engine, the Docker Compose v2 plugin at `/usr/bin/docker`, and
an immutable reviewed Atlas image whose entrypoint is `python -m atlas_sync`. These commands create
a dedicated non-login account and the fixed production paths:

```sh
sudo useradd --system --home-dir /var/lib/waset-atlas --shell /usr/sbin/nologin atlas
sudo usermod -aG docker atlas
sudo install -d -o root -g atlas -m 0750 /opt/waset-atlas /opt/waset-atlas/releases
sudo install -d -o root -g atlas -m 0750 /etc/waset-atlas /etc/waset-atlas/secrets
sudo install -d -o atlas -g atlas -m 0700 /var/lib/waset-atlas
```

Membership in the system Docker group is root-equivalent. Prefer a separately managed rootless
Docker daemon for `atlas` where the platform supports it; if the system daemon is used, restrict
membership to this dedicated account and audit it. Log out/restart the user manager after changing
group membership. Confirm `sudo -u atlas /usr/bin/docker info` and
`sudo -u atlas /usr/bin/docker compose version` before enabling the timer.

## 2. Configuration and secrets

Install the tracked example, then edit only deployment values. The example includes every required
or production-significant setting; keep `ATLAS_IMAGE` pinned by digest.

```sh
sudo install -o root -g atlas -m 0640 deploy/production/atlas.env.example /etc/waset-atlas/atlas.env
sudo install -o root -g atlas -m 0640 /dev/null /etc/waset-atlas/secrets/monday_api_token
sudoedit /etc/waset-atlas/atlas.env
sudoedit /etc/waset-atlas/secrets/monday_api_token
sudo chown root:atlas /etc/waset-atlas/atlas.env /etc/waset-atlas/secrets/monday_api_token
sudo chmod 0640 /etc/waset-atlas/atlas.env /etc/waset-atlas/secrets/monday_api_token
```

The secret file contains exactly the read-only Monday token and one final newline. Never put the
token, an Authorization header, or `MONDAY_API_TOKEN=` in the environment file, unit files, image,
Compose YAML, shell history, tickets, or journals. The container sees the secret read-only at
`/run/secrets/monday_api_token`; only its path appears in configuration.

## 3. Data layout and truth hierarchy

The host directory `/var/lib/waset-atlas` is mounted at `/var/lib/atlas` in the container:

```text
/var/lib/waset-atlas/
  raw/monday/                  immutable Monday evidence
  builds/                      staged immutable builds and attempt records
  published/current           authoritative live relative symlink
  published/CURRENT.json      operational metadata, not the live pointer
  published/history/          immutable publication history
  locks/atlas-production.lock Task 6 shared operation lock
  locks/scheduled-cycles/      immutable scheduled-cycle journal
  locks/alerts/state.json      atomically replaced alert lifecycle state
```

The actual `published/current` symlink is authoritative for what is served. Task 7 status is
authoritative for current health/freshness. Scheduled-cycle records are authoritative for cycle
outcomes; alert state is the durable incident lifecycle. The systemd journal is execution output,
not a replacement for those persisted records.

## 4. Deploy a release

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
sudo -u atlas /usr/bin/docker compose --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml config --quiet
sudo -u atlas /usr/bin/docker compose --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml pull atlas-runtime
sudo systemctl daemon-reload
sudo systemctl enable --now waset-atlas.timer
```

`compose config --quiet` validates interpolation without starting Atlas. The timer is hourly,
persistent across downtime, and applies one stable 0–10 minute randomized delay. systemd does not
start a second copy of an already-active oneshot service, and Task 6 also refuses any competing
production operation with exit 75. Missed timer intervals are not replayed as a catch-up storm.

## 5. Normal operation

```sh
systemctl list-timers waset-atlas.timer
systemctl status waset-atlas.timer waset-atlas.service
journalctl -u waset-atlas.service --since today --output=short-iso
sudo -u atlas /usr/bin/docker compose --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps atlas-runtime status --json
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

## 6. Manual operations

Run an immediate normal cycle through systemd:

```sh
sudo systemctl start waset-atlas.service
sudo systemctl status waset-atlas.service
```

For diagnosis, first run read-only status. Manual staging never publishes; manual publish and
rollback revalidate the target and acquire the same Task 6 lock:

```sh
sudo -u atlas /usr/bin/docker compose --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps atlas-runtime status --json
sudo -u atlas /usr/bin/docker compose --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps atlas-runtime run-once --json
sudo -u atlas /usr/bin/docker compose --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps atlas-runtime publish ATTEMPT_ID --json
sudo -u atlas /usr/bin/docker compose --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps atlas-runtime rollback --json
```

Never edit `current`, `CURRENT.json`, publication history, build markers, scheduled-cycle records,
or alert state manually. Never publish “the newest” directory without an explicit validated ID.

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

## 8. Metadata inconsistency recovery

Stop new timer triggers, wait for the oneshot to finish, and record the current status and pointer:

```sh
sudo systemctl stop waset-atlas.timer
systemctl is-active waset-atlas.service
sudo -u atlas /usr/bin/docker compose --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps atlas-runtime status --json
sudo -u atlas readlink /var/lib/waset-atlas/published/current
```

If the relative pointer resolves to an intact completed build and only CURRENT/history metadata is
inconsistent, explicitly republish that exact `ATTEMPT_ID` to generate a new verified publication
record:

```sh
sudo -u atlas /usr/bin/docker compose --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps atlas-runtime publish ATTEMPT_ID --json
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
sudo -u atlas /usr/bin/docker compose --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml pull atlas-runtime
sudo systemctl daemon-reload
sudo -u atlas /usr/bin/docker compose --project-directory /opt/waset-atlas/current -f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps atlas-runtime status --json
sudo systemctl start waset-atlas.timer
```

Wait until `systemctl is-active waset-atlas.service` reports `inactive` before changing the release
symlink or image digest. To restart scheduling only, use `systemctl restart waset-atlas.timer`; never
configure `Restart=always` for the oneshot.

## 10. Security, disk, and backups

- Review Docker-group/rootless-daemon access, `/etc/waset-atlas` ownership, image digest, and token
  scope regularly. Rotate the token in its external secret file, then trigger one controlled cycle.
- Monitor `df -h /var/lib/waset-atlas`, `df -i /var/lib/waset-atlas`, and
  `du -sh /var/lib/waset-atlas/*`. Atlas performs no retention deletion in Task 9. Never improvise
  deletion of raw evidence, builds, publication history, scheduled cycles, or alert history.
- Before a backup, stop the timer and confirm the service is inactive. Back up
  `/var/lib/waset-atlas` with permissions, timestamps, and symlinks preserved. Back up
  `/etc/waset-atlas` separately into an encrypted secret store with stricter access. Restore into a
  staging host first and run `status --json`; do not point production at an unverified restore.
- Journals and Atlas JSON outputs are designed to contain safe categories, never exception text or
  tokens. Treat them as operationally sensitive anyway and use the host's approved journal policy.

## 11. Task 10 preparation — do not execute yet

Task 10 may consume durable alert events for notification delivery. Preserve `event_id`,
`incident_id`, action, severity, occurrence count, timestamps, and the active/resolved distinction so
a transport can be idempotent. Decide recipients, escalation policy, acknowledgement ownership,
delivery credentials, retry/dead-letter behavior, and a test endpoint before enabling anything.
Do not add email, Slack, webhook, or other delivery credentials to this Task 9 deployment.
