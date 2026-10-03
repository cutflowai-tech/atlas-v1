"""Database access of the Phase 19-B evaluation runner's scenario steps (``evaluation_runner``): SQL and the driver stay in the store.

Only the runner uses this, only on a disposable evaluation database that ``evaluation_runner.check_disposable`` accepted.
"""

from __future__ import annotations

from typing import Any

from atlas_reasoning.store.db import SCHEMA, Database
from atlas_reasoning.store.migrate import apply_migrations
from atlas_reasoning.store.repository import ReasoningStore


def connection_target(url: str) -> dict[str, str]:
    """The connection parameters libpq resolves from ``url`` (query parameters such as ``?dbname=`` override the path). Raises the
    driver's error for an unparseable URL; the caller reports it without echoing the URL."""
    from psycopg.conninfo import conninfo_to_dict

    return {key: str(value) for key, value in conninfo_to_dict(url).items()}


def reset_schema(url: str) -> Database:
    """Drop the Reasoning V3 schema and migrate it again: an empty, fully migrated database for one golden case."""
    db = Database(url)
    with db.transaction() as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    apply_migrations(db)
    return db


def case_id_for(store: ReasoningStore, identity_key: str) -> str | None:
    with store.transaction() as tx:
        row = tx._one("SELECT case_id FROM reasoning_cases WHERE identity_key = %s", (identity_key,))
    return str(row["case_id"]) if row is not None else None


def first_open_question(store: ReasoningStore, case_id: str) -> str | None:
    """The case's open Atlas Question with the lowest dedup key (the golden driver's choice)."""
    with store.transaction() as tx:
        row: dict[str, Any] | None = tx._one(
            "SELECT question_id FROM atlas_questions WHERE case_id = %s AND state = 'open' ORDER BY dedup_key LIMIT 1", (case_id,))
    return str(row["question_id"]) if row is not None else None


def age_claims(store: ReasoningStore, seconds: float) -> None:
    """Make every in-progress claim ``seconds`` old (a worker that claimed work and died that long ago)."""
    with store.transaction() as tx:
        tx._exec("UPDATE reasoning_work_items SET updated_at = now() - make_interval(secs => %s) WHERE status = 'in_progress'", (seconds,))
