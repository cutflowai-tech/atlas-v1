"""PostgreSQL access for the canonical Reasoning V3 state.

All Reasoning V3 tables live in their own PostgreSQL schema (``atlas_reasoning``), so the database may be shared without name
clashes and a test database can be reset by dropping one schema. Every connection runs with that schema on its ``search_path``.

``psycopg`` (``requirements-reasoning.txt``) is imported only when a database is actually opened: Atlas without Reasoning V3, and
the production sync image, never need it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from atlas_reasoning.settings import ReasoningConfigError

if TYPE_CHECKING:
    import psycopg

SCHEMA = "atlas_reasoning"
APPLICATION_NAME = "atlas-reasoning"


class DatabaseError(RuntimeError):
    """A Reasoning V3 database operation failed. Messages never contain the database password."""


def redact_url(url: str) -> str:
    """The URL with any credentials replaced (userinfo password, ``password=`` query parameters), safe for logs and health output."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparseable database URL>"
    netloc = parts.netloc
    if "@" in netloc:
        userinfo, host = netloc.rsplit("@", 1)
        user = userinfo.split(":", 1)[0]
        netloc = f"{user}:***@{host}" if ":" in userinfo else f"{user}@{host}"
    query = urlencode([(key, "***" if key.lower() in ("password", "passfile", "sslpassword") else value)
                       for key, value in parse_qsl(parts.query, keep_blank_values=True)])
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


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
            raise DatabaseError(f"cannot connect to {self.display_url}: {type(error).__name__}: {_scrub(str(error), self._url)}") from None
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


def _scrub(message: str, url: str) -> str:
    """A driver message with the URL's password (in any position) removed."""
    try:
        password = urlsplit(url).password
    except ValueError:
        password = None
    secrets = [password] if password else []
    secrets += [value for key, value in parse_qsl(urlsplit(url).query) if key.lower() == "password" and value]
    for secret in secrets:
        message = message.replace(secret, "***")
    return message.strip()
