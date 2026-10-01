"""A disposable PostgreSQL database for Reasoning V3 tests.

Tests that need PostgreSQL read ``ATLAS_REASONING_TEST_DATABASE_URL``. Without it they are skipped, unless
``ATLAS_REASONING_REQUIRE_DB_TESTS=1`` (set in CI), which turns a missing database into a failure so the database tests can never
be silently skipped where they must run. Every test starts from an empty ``atlas_reasoning`` schema; the URL must name a database
whose name contains ``test``, so a real database can never be wiped by mistake.

    ATLAS_REASONING_TEST_DATABASE_URL=postgresql://atlas@127.0.0.1:5432/atlas_reasoning_test make reasoning
"""

from __future__ import annotations

import os
import unittest
from urllib.parse import urlparse

TEST_DB_ENV = "ATLAS_REASONING_TEST_DATABASE_URL"
REQUIRE_ENV = "ATLAS_REASONING_REQUIRE_DB_TESTS"


def test_database_url() -> str | None:
    url = os.environ.get(TEST_DB_ENV, "").strip()
    if not url:
        if os.environ.get(REQUIRE_ENV) == "1":
            raise RuntimeError(f"{REQUIRE_ENV}=1 but {TEST_DB_ENV} is not set: the Reasoning V3 database tests must run here")
        return None
    name = urlparse(url).path.lstrip("/")
    if "test" not in name:
        raise RuntimeError(f"{TEST_DB_ENV} must name a disposable test database (its name must contain 'test'), not {name!r}")
    return url


def requires_db(cls: type) -> type:
    return unittest.skipUnless(test_database_url(), f"{TEST_DB_ENV} not set (Reasoning V3 database tests)")(cls)


def fresh_database():  # type: ignore[no-untyped-def]
    """An empty, fully migrated Reasoning V3 schema."""
    from atlas_reasoning.store.db import SCHEMA, Database
    from atlas_reasoning.store.migrate import apply_migrations

    url = test_database_url()
    assert url is not None
    db = Database(url)
    with db.transaction() as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    apply_migrations(db)
    return db
