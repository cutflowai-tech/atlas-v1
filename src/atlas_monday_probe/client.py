from __future__ import annotations

import json
import os
import re
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

API_URL = "https://api.monday.com/v2"
TOKEN_ENV = "MONDAY_API_TOKEN"
# A file holding the token, e.g. a Docker secret mounted at /run/secrets/<name>. Set this or TOKEN_ENV, never both.
TOKEN_FILE_ENV = "MONDAY_API_TOKEN_FILE"
API_VERSION_ENV = "MONDAY_API_VERSION"
# The Monday API version every validated run so far used; deployments may pin another with MONDAY_API_VERSION.
DEFAULT_API_VERSION = "2025-04"
_API_VERSION = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

Transport = Callable[[str, dict[str, Any]], bytes]

_COMMENT = re.compile(r"#[^\n]*")
_STRING = re.compile(r'"""[\s\S]*?"""|"(?:\\.|[^"\\])*"')
_WRITE_OPERATION = re.compile(r"\b(mutation|subscription)\b", re.IGNORECASE)


class ReadOnlyViolation(ValueError):
    pass


class MissingAccess(RuntimeError):
    pass


class InvalidMondaySetting(ValueError):
    """A Monday setting (token source or API version) is present but unusable. Messages never contain the token."""


def validate_api_version(value: str) -> str:
    if not isinstance(value, str) or not _API_VERSION.match(value):
        raise InvalidMondaySetting(f"{API_VERSION_ENV} must look like YYYY-MM, got {value!r}")
    return value


def token_from_environment(environ: Mapping[str, str]) -> str:
    """The Monday API token from TOKEN_ENV or from the file named by TOKEN_FILE_ENV.

    Fails closed: no source, both sources, an unreadable or empty file, or a malformed token raises
    without ever including the token (or the file's contents) in the message."""
    direct, file_name = environ.get(TOKEN_ENV, ""), environ.get(TOKEN_FILE_ENV, "")
    if direct and file_name:
        raise InvalidMondaySetting(f"set either {TOKEN_ENV} or {TOKEN_FILE_ENV}, not both")
    if file_name:
        path = Path(file_name)
        if not path.is_file():
            raise MissingAccess(f"{TOKEN_FILE_ENV} does not name a readable file: {path}")
        try:
            token = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            raise MissingAccess(f"{TOKEN_FILE_ENV} could not be read: {path}") from None
        source = f"{TOKEN_FILE_ENV} ({path})"
    else:
        token, source = direct.strip(), TOKEN_ENV
    if not token:
        raise MissingAccess(f"{TOKEN_ENV} is not set; no scoped Monday API token is available to this runtime"
                            + (f" ({source} is empty)" if file_name or direct else ""))
    if any(char.isspace() for char in token):
        raise InvalidMondaySetting(f"the Monday API token from {source} contains whitespace; expected a single token")
    return token


def assert_read_only(query: str) -> None:
    """Reject anything that is not a plain GraphQL query before it can leave the process."""
    stripped = _COMMENT.sub("", _STRING.sub('""', query))
    if _WRITE_OPERATION.search(stripped):
        raise ReadOnlyViolation("Monday probe only issues read-only GraphQL queries")


def _urllib_transport(token: str, api_version: str = DEFAULT_API_VERSION) -> Transport:
    def send(query: str, variables: dict[str, Any]) -> bytes:
        body = json.dumps({"query": query, "variables": variables}).encode()
        request = urllib.request.Request(API_URL, data=body, method="POST", headers={
            "Authorization": token, "Content-Type": "application/json", "API-Version": api_version,
        })
        with urllib.request.urlopen(request, timeout=60) as response:
            payload: bytes = response.read()
            return payload
    return send


class ReadOnlyMondayClient:
    """Monday GraphQL client that can only read. Raw response bytes are returned untouched for retention."""

    def __init__(self, transport: Transport, api_version: str = DEFAULT_API_VERSION) -> None:
        self._transport = transport
        self.api_version = api_version

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ReadOnlyMondayClient:
        """Client for MONDAY_API_TOKEN or MONDAY_API_TOKEN_FILE, at MONDAY_API_VERSION (default DEFAULT_API_VERSION)."""
        env = environ if environ is not None else dict(os.environ)
        return cls.from_token(token_from_environment(env), env.get(API_VERSION_ENV) or DEFAULT_API_VERSION)

    @classmethod
    def from_token(cls, token: str, api_version: str = DEFAULT_API_VERSION) -> ReadOnlyMondayClient:
        if not token:
            raise MissingAccess("no Monday API token was provided")
        version = validate_api_version(api_version)
        return cls(_urllib_transport(token, version), version)

    def __repr__(self) -> str:
        return "ReadOnlyMondayClient(<redacted>)"

    def query(self, query: str, variables: dict[str, Any]) -> bytes:
        assert_read_only(query)
        raw = self._transport(query, variables)
        errors = json.loads(raw).get("errors")
        if errors:
            raise MissingAccess(f"Monday API returned errors: {[error.get('message') for error in errors]}")
        return raw

    def status_activity(self, board_id: str, item_ids: list[str], column_id: str, since: str, until: str, page: int = 1) -> bytes:
        return self.query(STATUS_ACTIVITY_QUERY, {
            "board": board_id, "items": item_ids, "columns": [column_id], "from": since, "to": until, "page": page,
        })

    def items(self, item_ids: list[str], column_ids: list[str]) -> bytes:
        return self.query(ITEMS_QUERY, {"items": item_ids, "columns": column_ids})

    def users_and_columns(self, board_id: str, user_ids: list[str], column_ids: list[str]) -> bytes:
        return self.query(USERS_COLUMNS_QUERY, {"board": board_id, "users": user_ids, "columns": column_ids})


STATUS_ACTIVITY_QUERY = """
query ($board: ID!, $items: [ID!], $columns: [String], $from: ISO8601DateTime, $to: ISO8601DateTime, $page: Int) {
  boards(ids: [$board]) {
    activity_logs(item_ids: $items, column_ids: $columns, from: $from, to: $to, limit: 200, page: $page) {
      id event entity user_id account_id created_at data
    }
  }
}
"""

ITEMS_QUERY = """
query ($items: [ID!], $columns: [String!]) {
  items(ids: $items) {
    id created_at updated_at board { id } group { id } creator_id
    column_values(ids: $columns) { id type text value }
  }
}
"""

USERS_COLUMNS_QUERY = """
query ($board: ID!, $users: [ID], $columns: [String]) {
  users(ids: $users) { id name }
  boards(ids: [$board]) { columns(ids: $columns) { id title type settings_str } }
}
"""
