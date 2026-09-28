# Production container interface

The default Compose deployment starts only the unprivileged static web service.
It serves `/en/` and `/ar/` exclusively from the shared volume's authoritative
`published/current` relative symlink. An empty volume therefore serves no dashboard.

The operations image is opt-in and performs no sync at startup. After provisioning
the external Docker secret and persistent volume, an operator or external scheduler
may explicitly run `scheduled-run`; this repository does not install a scheduler:

```text
docker compose -f deploy/production/compose.yaml --profile operations run --rm atlas-ops scheduled-run --json
```

Redeploy with ordinary `up -d`; never use `down -v` in production. The named volume
is intentionally external to image replacement and contains raw evidence, builds,
publication history, locks, scheduled-cycle records, and the live relative symlink.
