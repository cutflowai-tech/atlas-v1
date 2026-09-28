from __future__ import annotations

import json
import os
import re
import urllib.request
from collections.abc import Callable
from typing import Any

API_URL = "https://api.monday.com/v2"
TOKEN_ENV = "MONDAY_API_TOKEN"

Transport = Callable[[str, dict[str, Any]], bytes]

_COMMENT = re.compile(r"#[^\n]*")
_STRING = re.compile(r'"""[\s\S]*?"""|"(?:\\.|[^"\\])*"')
_WRITE_OPERATION = re.compile(r"\b(mutation|subscription)\b", re.IGNORECASE)


class ReadOnlyViolation(ValueError):
    pass


class MissingAccess(RuntimeError):
    pass


def assert_read_only(query: str) -> None:
    """Reject anything that is not a plain GraphQL query before it can leave the process."""
    stripped = _COMMENT.sub("", _STRING.sub('""', query))
    if _WRITE_OPERATION.search(stripped):
        raise ReadOnlyViolation("Monday probe only issues read-only GraphQL queries")


def _urllib_transport(token: str) -> Transport:
    def send(query: str, variables: dict[str, Any]) -> bytes:
        body = json.dumps({"query": query, "variables": variables}).encode()
        request = urllib.request.Request(API_URL, data=body, method="POST", headers={
            "Authorization": token, "Content-Type": "application/json", "API-Version": "2025-04",
        })
        with urllib.request.urlopen(request, timeout=60) as response:
            payload: bytes = response.read()
            return payload
    return send


class ReadOnlyMondayClient:
    """Monday GraphQL client that can only read. Raw response bytes are returned untouched for retention."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> ReadOnlyMondayClient:
        token = (environ if environ is not None else dict(os.environ)).get(TOKEN_ENV, "")
        if not token:
            raise MissingAccess(f"{TOKEN_ENV} is not set; no scoped Monday API token is available to this runtime")
        return cls(_urllib_transport(token))

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
