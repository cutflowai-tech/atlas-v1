# Production container interface

The default Compose deployment starts only the unprivileged static web service.
It serves `/en/` and `/ar/` exclusively from the shared volume's authoritative
`published/current` relative symlink. An empty volume therefore serves no dashboard.

The operations image is opt-in and performs no sync at startup. After provisioning
the external read-only token file and persistent host data directory, an operator or systemd
may explicitly run `scheduled-run`; this repository does not install a scheduler:

```text
docker compose --env-file /etc/waset-atlas/atlas.env --project-directory . -f deploy/production/compose.yaml --profile operations run --rm --no-deps atlas-runtime scheduled-run --json
```

Production Compose intentionally has no local build fallback: build the two reviewed Dockerfiles in
CI/release preparation, publish immutable images, and place their digests in `atlas.env`. This keeps
the server deployment from sending an unintended source tree as a build context.

Redeploy with ordinary `up -d`; never delete the host data root in production. The bind-mounted
`/var/lib/waset-atlas` tree is external to image replacement and contains raw evidence, builds,
publication history, locks, scheduled-cycle records, and the live relative symlink.
