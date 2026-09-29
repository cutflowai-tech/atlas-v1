from __future__ import annotations

import http.client
import json
import os
import random as _random
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
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

_NAME = re.compile(r"[_A-Za-z][_0-9A-Za-z]*")
# Matched case-insensitively: stricter than GraphQL (whose keywords are lower-case) and never looser.
_WRITE_OPERATIONS = frozenset({"mutation", "subscription"})


class ReadOnlyViolation(ValueError):
    pass


class MondayError(RuntimeError):
    """A Monday read failed. ``category`` names the failure kind; messages never contain the token or request headers."""

    category = "monday_error"
    retryable = False

    def __init__(self, message: str, *, status: int | None = None, codes: tuple[str, ...] = (), retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status, self.codes, self.retry_after = status, codes, retry_after


class MissingAccess(MondayError):
    """No usable Monday access: no token configured, or Monday rejected the token or its permissions."""

    category = "missing_access"


class AuthenticationFailed(MissingAccess):
    category = "authentication"


class PermissionDenied(MissingAccess):
    category = "permission"


class RateLimited(MondayError):
    """Monday's rate or complexity limit. Retryable unless Monday says the wait is too long (e.g. a daily limit)."""

    category = "rate_limited"

    def __init__(self, message: str, *, temporary: bool = True, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.retryable = temporary


class TransientApiError(MondayError):
    """A server-side failure (HTTP 5xx, internal error, unreadable response) that may succeed if repeated."""

    category = "transient_api"
    retryable = True


class TransportError(MondayError):
    """The request did not complete (connection, DNS, TLS, timeout)."""

    category = "transport"
    retryable = True


class PermanentApiError(MondayError):
    """Monday rejected the request in a way repeating it cannot fix (invalid query, bad argument, not found)."""

    category = "permanent_api"


class ApiVersionError(PermanentApiError):
    """Monday rejected the configured API-Version. Never retried and never switched automatically."""

    category = "api_version"


class InvalidMondaySetting(ValueError):
    """A Monday setting (token source or API version) is present but unusable. Messages never contain the token."""

    category = "invalid_configuration"


class HttpFailure(Exception):
    """Raised by a transport for a non-2xx HTTP response; carries only the status, body and Retry-After header."""

    def __init__(self, status: int, body: bytes = b"", retry_after: str | None = None) -> None:
        super().__init__(f"HTTP {status}")
        self.status, self.body, self.retry_after = status, body, retry_after


@dataclass(frozen=True)
class RetryPolicy:
    """Request-level retries. ``max_attempts`` counts the first attempt. Backoff is exponential with equal jitter,
    capped at ``max_backoff_seconds``; a Monday-provided wait is honoured as given unless it exceeds
    ``max_server_delay_seconds``, in which case the request fails instead of waiting."""

    max_attempts: int = 4
    base_delay_seconds: float = 1.0
    max_backoff_seconds: float = 60.0
    max_server_delay_seconds: float = 300.0

    def backoff(self, attempt: int, unit_random: float) -> float:
        ceiling = min(self.max_backoff_seconds, self.base_delay_seconds * 2 ** (attempt - 1))
        return min(self.max_backoff_seconds, ceiling / 2 + ceiling / 2 * unit_random)


@dataclass
class RequestStats:
    """Safe request metadata for later sync reporting: counts and categories only, never tokens, headers or bodies."""

    requests: int = 0
    retries: int = 0
    succeeded: int = 0
    failed: int = 0
    slept_seconds: float = 0.0
    failures_by_category: dict[str, int] = field(default_factory=dict)
    last_failure_category: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"requests": self.requests, "retries": self.retries, "succeeded": self.succeeded, "failed": self.failed,
                "slept_seconds": round(self.slept_seconds, 3), "failures_by_category": dict(sorted(self.failures_by_category.items())),
                "last_failure_category": self.last_failure_category}


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


def _graphql_names(query: str) -> list[str]:
    """The Name tokens of a GraphQL document, read left to right as the GraphQL lexer does.

    Comments, strings and block strings are skipped in document order, so a quote inside a comment or a
    ``#`` inside a string cannot hide a token. A string that is not closed is refused rather than guessed at."""
    names: list[str] = []
    index, length = 0, len(query)
    while index < length:
        char = query[index]
        if char == "#":   # a comment runs to the end of the line
            while index < length and query[index] not in "\r\n":
                index += 1
        elif query.startswith('"""', index):   # block string; only \""" escapes a closing quote
            index += 3
            while not query.startswith('"""', index):
                if index >= length:
                    raise ReadOnlyViolation("GraphQL block string is not terminated")
                index += 4 if query.startswith('\\"""', index) else 1
            index += 3
        elif char == '"':   # string; may not span lines
            index += 1
            while index < length and query[index] != '"':
                if query[index] in "\r\n" or query.startswith(("\\\r", "\\\n"), index):
                    break
                index += 2 if query[index] == "\\" else 1
            if index >= length or query[index] != '"':
                raise ReadOnlyViolation("GraphQL string is not terminated")
            index += 1
        elif (match := _NAME.match(query, index)) is not None:
            names.append(match.group())
            index = match.end()
        else:
            index += 1
    return names


def assert_read_only(query: str) -> None:
    """Reject anything that is not a plain GraphQL query before it can leave the process."""
    if any(name.lower() in _WRITE_OPERATIONS for name in _graphql_names(query)):
        raise ReadOnlyViolation("Monday probe only issues read-only GraphQL queries")


_RATE_CODES = {"COMPLEXITY_BUDGET_EXHAUSTED", "COMPLEXITYEXCEPTION", "RATE_LIMIT_EXCEEDED", "RATELIMITEXCEEDED", "IP_RATE_LIMIT_EXCEEDED",
               "MAX_CONCURRENCY_EXCEEDED", "MAXCONCURRENCYEXCEEDED", "CONCURRENCY_LIMIT_EXCEEDED"}
_LONG_RATE_CODES = {"DAILY_LIMIT_EXCEEDED", "DAILYLIMITEXCEEDED"}
_AUTH_CODES = {"UNAUTHENTICATED", "NOT_AUTHENTICATED", "INVALID_TOKEN", "AUTHENTICATION_ERROR"}
_PERMISSION_CODES = {"USER_UNAUTHORIZED", "USERUNAUTHORIZEDEXCEPTION", "FORBIDDEN", "USER_ACCESS_DENIED", "MISSING_REQUIRED_PERMISSIONS"}
_TRANSIENT_CODES = {"INTERNAL_SERVER_ERROR", "INTERNALSERVERERROR", "SERVICE_UNAVAILABLE"}
_VERSION_MESSAGE = re.compile(r"api[- _]?version", re.IGNORECASE)
_RESET_IN = re.compile(r"reset in (\d+(?:\.\d+)?) seconds?", re.IGNORECASE)
_MAX_MESSAGE = 300


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _entries(payload: Any) -> list[dict[str, Any]]:
    """Monday error entries in either the GraphQL (``errors``) or the legacy (``error_code``) response shape."""
    if not isinstance(payload, dict):
        return []
    entries: list[dict[str, Any]] = []
    for error in payload.get("errors") or []:
        entries.append(error if isinstance(error, dict) else {"message": str(error)})
    if payload.get("error_code") or payload.get("error_message"):
        entries.append({"message": payload.get("error_message"), "extensions": {"code": payload.get("error_code"),
                                                                                 "retry_in_seconds": payload.get("retry_in_seconds")}})
    return entries


def _classify(entries: list[dict[str, Any]], status: int | None, header_retry_after: str | None, redact: Callable[[str], str]) -> MondayError:
    codes = tuple(str((e.get("extensions") or {}).get("code") or e.get("code") or "").upper() for e in entries)
    codes = tuple(c for c in codes if c)
    messages = [str(e.get("message") or "") for e in entries]
    retry_after = next((n for n in ((e.get("extensions") or {}).get("retry_in_seconds") for e in entries) if _number(n) is not None), None)
    retry = _number(retry_after) if retry_after is not None else _number(header_retry_after)
    if retry is None:
        retry = next((float(m.group(1)) for m in map(_RESET_IN.search, messages) if m), None)
    detail = "; ".join(filter(None, messages))[:_MAX_MESSAGE]
    text = redact(f"Monday API {'HTTP ' + str(status) + ' ' if status else ''}{'[' + ', '.join(codes) + '] ' if codes else ''}{detail}".strip())
    code_set = {c.replace(" ", "_") for c in codes}
    lowered = " ".join(messages).lower()
    kwargs: dict[str, Any] = {"status": status, "codes": codes, "retry_after": retry}
    if code_set & _LONG_RATE_CODES:
        return RateLimited(text, temporary=False, **kwargs)
    if code_set & _RATE_CODES or status == 429 or "complexity budget" in lowered or "rate limit" in lowered:
        return RateLimited(text, **kwargs)
    if code_set & _AUTH_CODES or status == 401 or "not authenticated" in lowered:
        return AuthenticationFailed(text, **kwargs)
    if code_set & _PERMISSION_CODES or status == 403:
        return PermissionDenied(text, **kwargs)
    if _VERSION_MESSAGE.search(" ".join(messages)):
        return ApiVersionError(text, **kwargs)
    if code_set & _TRANSIENT_CODES or status == 408 or (status is not None and status >= 500):
        return TransientApiError(text, **kwargs)
    return PermanentApiError(text or "Monday API rejected the request", **kwargs)


def _urllib_transport(token: str, api_version: str = DEFAULT_API_VERSION) -> Transport:
    def send(query: str, variables: dict[str, Any]) -> bytes:
        body = json.dumps({"query": query, "variables": variables}).encode()
        request = urllib.request.Request(API_URL, data=body, method="POST", headers={
            "Authorization": token, "Content-Type": "application/json", "API-Version": api_version,
        })
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload: bytes = response.read()
                return payload
        except urllib.error.HTTPError as error:
            # Only the status, body and Retry-After header leave here; the request (with its Authorization header) never does.
            failure = HttpFailure(error.code, error.read() if error.fp else b"", error.headers.get("Retry-After") if error.headers else None)
        raise failure
    return send


class ReadOnlyMondayClient:
    """Monday GraphQL client that can only read. Raw response bytes are returned untouched for retention.

    Every query passes the read-only guard before anything else, then is sent with request-level retries
    for transient failures only (see :class:`RetryPolicy`). ``stats`` exposes safe request metadata."""

    def __init__(self, transport: Transport, api_version: str = DEFAULT_API_VERSION, *, retry_policy: RetryPolicy | None = None,
                 sleep: Callable[[float], None] = time.sleep, random: Callable[[], float] = _random.random,
                 redact: Callable[[str], str] | None = None) -> None:
        self._transport = transport
        self.api_version = api_version
        self.retry_policy = retry_policy or RetryPolicy()
        self._sleep, self._random = sleep, random
        self._redact = redact or (lambda text: text)
        self.stats = RequestStats()

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, **options: Any) -> ReadOnlyMondayClient:
        """Client for MONDAY_API_TOKEN or MONDAY_API_TOKEN_FILE, at MONDAY_API_VERSION (default DEFAULT_API_VERSION)."""
        env = environ if environ is not None else dict(os.environ)
        return cls.from_token(token_from_environment(env), env.get(API_VERSION_ENV) or DEFAULT_API_VERSION, **options)

    @classmethod
    def from_token(cls, token: str, api_version: str = DEFAULT_API_VERSION, **options: Any) -> ReadOnlyMondayClient:
        if not token:
            raise MissingAccess("no Monday API token was provided")
        version = validate_api_version(api_version)
        return cls(_urllib_transport(token, version), version, redact=lambda text: text.replace(token, "<redacted>"), **options)

    def __repr__(self) -> str:
        return "ReadOnlyMondayClient(<redacted>)"

    def _attempt(self, query: str, variables: dict[str, Any]) -> tuple[bytes | None, MondayError | None]:
        try:
            raw = self._transport(query, variables)
        except urllib.error.HTTPError as error:   # a custom transport that lets urllib's error through
            return self._attempt_failed(HttpFailure(error.code, b"", error.headers.get("Retry-After") if error.headers else None))
        except HttpFailure as failure:
            return self._attempt_failed(failure)
        except (OSError, http.client.HTTPException) as error:   # URLError, timeouts, resets, TLS and protocol errors
            reason = getattr(error, "reason", None) or error
            return None, TransportError(self._redact(f"Monday request did not complete: {type(error).__name__}: {reason}"[:_MAX_MESSAGE]))
        try:
            payload = json.loads(raw)
        except ValueError:
            return None, TransientApiError("Monday API returned a response that is not JSON")
        entries = _entries(payload)
        legacy_status = payload.get("status_code") if isinstance(payload, dict) and isinstance(payload.get("status_code"), int) else None
        return (raw, None) if not entries else (None, _classify(entries, legacy_status, None, self._redact))

    def _attempt_failed(self, failure: HttpFailure) -> tuple[None, MondayError]:
        try:
            payload = json.loads(failure.body) if failure.body else None
        except ValueError:
            payload = None
        return None, _classify(_entries(payload), failure.status, failure.retry_after, self._redact)

    def query(self, query: str, variables: dict[str, Any]) -> bytes:
        assert_read_only(query)   # first, always: a write never reaches the transport
        policy = self.retry_policy
        attempt = 0
        while True:
            attempt += 1
            self.stats.requests += 1
            raw, error = self._attempt(query, variables)
            if error is None:
                assert raw is not None
                self.stats.succeeded += 1
                return raw
            self.stats.failures_by_category[error.category] = self.stats.failures_by_category.get(error.category, 0) + 1
            delay: float | None = None
            if error.retryable and attempt < policy.max_attempts:
                if error.retry_after is not None:
                    delay = error.retry_after if error.retry_after <= policy.max_server_delay_seconds else None
                else:
                    delay = policy.backoff(attempt, self._random())
            if delay is None:
                self.stats.failed += 1
                self.stats.last_failure_category = error.category
                raise error
            self.stats.retries += 1
            self.stats.slept_seconds += delay
            self._sleep(delay)

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
