"""Reasoning V3 operations-readiness tooling (Phase 20-B). Repository and staging tools only — nothing here contacts production.

    restore_drill      logical backup (pg_dump) of the canonical Reasoning V3 schema with a verifiable manifest, and an isolated restore
                       drill into a disposable database (health, migrations, canonical fingerprints, release metadata)
    release_checklist  the release-verification checklist and a validator for a filled-in release verification record
    secret_scan        a credential-pattern scan that reports only file, line and pattern name — never a matched value

Run from a repository checkout with ``PYTHONPATH=src:deploy/production``. See ``docs/REASONING-V3-RECOVERY.md`` and
``docs/REASONING-V3-RELEASE-CHECKLIST.md``.
"""
