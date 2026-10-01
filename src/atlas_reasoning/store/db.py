"""PostgreSQL access for the canonical Reasoning V3 state.

All Reasoning V3 tables live in their own PostgreSQL schema (``atlas_reasoning``), so the database may be shared without name
clashes and a test database can be reset by dropping one schema. Every connection runs with that schema on its ``search_path``.

``psycopg`` (``requirements-reasoning.txt``) is imported only when a database is actually opened: Atlas without Reasoning V3, and
the production sync image, never need it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from atlas_reasoning.settings import ReasoningConfigError

if TYPE_CHECKING:
    import psycopg

SCHEMA = "atlas_reasoning"
APPLICATION_NAME = "atlas-reasoning"
_PASSWORD = re.compile(r"(://[^:/@]+:)[^@]*@")


class DatabaseError(RuntimeError):
    """A Reasoning V3 database operation failed. Messages never contain the database password."""


def redact_url(url: str) -> str:
    """The URL with any password replaced, safe for logs and health output."""
    return _PASSWORD.sub(r"\1***@", url)


def _driver() -> Any:
    try:
        import psycopg
    except ImportError:  # pragma: no cover - exercised only without the optional dependency
        raise ReasoningConfigError("Reasoning V3 needs psycopg: pip install -r requirements-reasoning.txt") from None
    return psycopg


class Database:
    """Opens connections to one PostgreSQL database. A transaction is the unit of every write."""

    def __init__(self, url: str, *, connect_timeout: int = 10, statement_timeout_ms: int = 30000) -> None:
        self._url = url
        self.connect_timeout = connect_timeout
        self.statement_timeout_ms = statement_timeout_ms

    def __repr__(self) -> str:
        return f"Database({redact_url(self._url)!r})"

    @property
    def display_url(self) -> str:
        return redact_url(self._url)

    def connect(self) -> psycopg.Connection[dict[str, Any]]:
        psycopg = _driver()
        from psycopg.rows import dict_row

        try:
            conn = psycopg.connect(self._url, connect_timeout=self.connect_timeout, application_name=APPLICATION_NAME, row_factory=dict_row,
                                   options=f"-c search_path={SCHEMA},public -c statement_timeout={int(self.statement_timeout_ms)}")
        except psycopg.Error as error:
            raise DatabaseError(f"cannot connect to {self.display_url}: {type(error).__name__}: {redact_url(str(error)).strip()}") from None
        return conn

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        """One connection, one transaction: committed when the block ends, rolled back (completely) when it raises."""
        conn = self.connect()
        try:
            with conn.transaction():
                yield conn
        finally:
            conn.close()
