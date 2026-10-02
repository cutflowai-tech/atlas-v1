"""Management write API for human context (``REV/12``-``REV/14``): transport-neutral request handling.

Atlas is published as a static site behind nginx and has no application server yet, so this module is not mounted anywhere: it
is the request handler a later phase (16, rollout in 20) mounts behind the authenticating proxy. It owns every rule a write
endpoint needs, so mounting it adds no new security decisions:

- **Authentication** is the proxy's: ``Request.actor`` is the identity the proxy authenticated (never read from the body). No
  actor → 401.
- **Authorization**: only identities listed in ``ATLAS_REASONING_MANAGERS`` may read or write human context → 403 otherwise.
- **CSRF**: every write needs ``Content-Type: application/json`` (a cross-site HTML form cannot send it), an ``Origin`` (when the
  browser sends one) listed in ``ATLAS_REASONING_ALLOWED_ORIGINS``, and an ``X-Atlas-CSRF`` token bound to the actor
  (HMAC-SHA256 with ``ATLAS_REASONING_CSRF_SECRET``; ``GET /api/reasoning/csrf`` issues it) → 403 otherwise.
- **Input**: bodies are limited (``max_body_bytes``, 413), must be a JSON object with only the documented fields (400
  ``UNKNOWN_FIELD``), and text is validated by ``user_text`` (400 with a stable code). Stored text is plain text; every page
  escapes it when rendering.
- **Audit identity**: the author of every write is the authenticated actor.
- **Responses** are JSON with ``Cache-Control: no-store`` and ``X-Content-Type-Options: nosniff``; errors carry a code and never
  internal details or credentials. No provider or Honcho credential is reachable from here.

Routes (prefix ``/api/reasoning``):

==========  ======================================  ==================================================
GET         /csrf                                   CSRF token for the current actor
GET         /results/{result_id}/notes              notes on a result
POST        /results/{result_id}/notes              create a note ``{"body"}``
PUT         /notes/{note_id}                        edit ``{"body", "expected_revision"}``
GET         /notes/{note_id}/history                every revision
==========  ======================================  ==================================================
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from atlas_reasoning.manager_notes import ManagerNotes, NoteConflict
from atlas_reasoning.settings import ReasoningConfigError, secret_value
from atlas_reasoning.store.repository import NotFound
from atlas_reasoning.user_text import InvalidText

PREFIX = "/api/reasoning"
CSRF_HEADER = "x-atlas-csrf"
MANAGERS_ENV = "ATLAS_REASONING_MANAGERS"
CSRF_SECRET_ENV = "ATLAS_REASONING_CSRF_SECRET"
CSRF_SECRET_FILE_ENV = "ATLAS_REASONING_CSRF_SECRET_FILE"
ORIGINS_ENV = "ATLAS_REASONING_ALLOWED_ORIGINS"
SECURITY_HEADERS = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def _identity(value: str) -> str:
    return value.strip().casefold()


@dataclass(frozen=True)
class ApiSettings:
    managers: frozenset[str]
    csrf_secret: bytes = field(repr=False)
    allowed_origins: frozenset[str] = frozenset()
    max_body_bytes: int = 32768

    def __post_init__(self) -> None:
        if len(self.csrf_secret) < 32:
            raise ReasoningConfigError(f"{CSRF_SECRET_ENV} must be at least 32 bytes")


def api_settings(env: Mapping[str, str] | None = None) -> ApiSettings:
    env = os.environ if env is None else env
    secret = secret_value(env, CSRF_SECRET_ENV, CSRF_SECRET_FILE_ENV)
    assert secret is not None
    managers = frozenset(_identity(item) for item in env.get(MANAGERS_ENV, "").split(",") if item.strip())
    origins = frozenset(item.strip().rstrip("/") for item in env.get(ORIGINS_ENV, "").split(",") if item.strip())
    return ApiSettings(managers=managers, csrf_secret=secret.encode(), allowed_origins=origins)


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    actor: str | None = None                       # set by the authenticating proxy, never by the client
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""


@dataclass(frozen=True)
class Response:
    status: int
    payload: Any
    headers: Mapping[str, str] = field(default_factory=lambda: dict(SECURITY_HEADERS))

    @property
    def body(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False, sort_keys=True).encode()


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.status, self.code = status, code


Handler = Callable[[dict[str, str], dict[str, Any], str], Any]


@dataclass(frozen=True)
class Route:
    method: str
    pattern: re.Pattern[str]
    handler: Handler
    fields: frozenset[str] = frozenset()
    required: frozenset[str] = frozenset()


_ID = r"(?P<{}>[A-Za-z0-9_]{{1,80}})"


class ManagementAPI:
    def __init__(self, settings: ApiSettings, *, notes: ManagerNotes) -> None:
        self.settings = settings
        self.notes = notes
        self.routes: list[Route] = []
        self.add("GET", "/csrf", lambda params, body, actor: {"token": self.csrf_token(actor)})
        self.add("GET", "/results/{result_id}/notes", lambda p, b, a: {"notes": [n.to_dict() for n in notes.for_result(p["result_id"])]})
        self.add("POST", "/results/{result_id}/notes", self._create_note, fields={"body"}, required={"body"})
        self.add("PUT", "/notes/{note_id}", self._update_note, fields={"body", "expected_revision"}, required={"body", "expected_revision"})
        self.add("GET", "/notes/{note_id}/history", lambda p, b, a: {"revisions": notes.history(p["note_id"])})

    def add(self, method: str, template: str, handler: Handler, *, fields: set[str] | frozenset[str] = frozenset(),
            required: set[str] | frozenset[str] = frozenset()) -> None:
        regex = re.sub(r"\\\{(\w+)\\\}", lambda m: _ID.format(m.group(1)), re.escape(PREFIX + template))
        self.routes.append(Route(method, re.compile(f"^{regex}$"), handler, frozenset(fields), frozenset(required)))

    # --- security ---------------------------------------------------------------------------------------------------------

    def csrf_token(self, actor: str) -> str:
        return hmac.new(self.settings.csrf_secret, f"atlas-csrf-v1|{_identity(actor)}".encode(), hashlib.sha256).hexdigest()

    def _authorize(self, request: Request) -> str:
        if not request.actor or not request.actor.strip():
            raise ApiError(401, "UNAUTHENTICATED")
        if _identity(request.actor) not in self.settings.managers:
            raise ApiError(403, "FORBIDDEN")
        return request.actor.strip()

    def _check_write(self, request: Request, headers: Mapping[str, str], actor: str) -> dict[str, Any]:
        if headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise ApiError(415, "JSON_REQUIRED")
        origin = headers.get("origin")
        if origin is not None and origin.rstrip("/") not in self.settings.allowed_origins:
            raise ApiError(403, "ORIGIN_NOT_ALLOWED")
        if not hmac.compare_digest(headers.get(CSRF_HEADER, ""), self.csrf_token(actor)):
            raise ApiError(403, "CSRF_TOKEN_INVALID")
        if len(request.body) > self.settings.max_body_bytes:
            raise ApiError(413, "BODY_TOO_LARGE")
        try:
            payload = json.loads(request.body.decode("utf-8") or "null")
        except (UnicodeDecodeError, ValueError):
            raise ApiError(400, "INVALID_JSON") from None
        if not isinstance(payload, dict):
            raise ApiError(400, "INVALID_JSON", "the body must be a JSON object")
        return payload

    # --- dispatch ---------------------------------------------------------------------------------------------------------

    def handle(self, request: Request) -> Response:
        try:
            return Response(200, self._dispatch(request))
        except ApiError as error:
            return Response(error.status, {"error": error.code, "message": str(error) if str(error) != error.code else None})
        except InvalidText as error:
            return Response(400, {"error": error.code, "message": str(error)})
        except NotFound:
            return Response(404, {"error": "NOT_FOUND", "message": None})
        except NoteConflict:
            return Response(409, {"error": "CONFLICT", "message": "the item changed since it was read; reload and retry"})
        except ValueError as error:
            return Response(400, {"error": "INVALID_REQUEST", "message": str(error)[:300]})

    def _dispatch(self, request: Request) -> Any:
        method = request.method.upper()
        if method not in ("GET", "POST", "PUT"):
            raise ApiError(405, "METHOD_NOT_ALLOWED")
        actor = self._authorize(request)
        headers = {key.lower(): value for key, value in request.headers.items()}
        path = request.path.split("?", 1)[0]
        matched = [route for route in self.routes if route.pattern.match(path)]
        if not matched:
            raise ApiError(404, "NOT_FOUND")
        route = next((route for route in matched if route.method == method), None)
        if route is None:
            raise ApiError(405, "METHOD_NOT_ALLOWED")
        params = route.pattern.match(path).groupdict()  # type: ignore[union-attr]
        body: dict[str, Any] = {}
        if method != "GET":
            body = self._check_write(request, headers, actor)
            unknown = sorted(set(body) - route.fields)
            if unknown:
                raise ApiError(400, "UNKNOWN_FIELD", f"unknown fields: {unknown}")
            missing = sorted(route.required - set(body))
            if missing:
                raise ApiError(400, "MISSING_FIELD", f"missing fields: {missing}")
        return route.handler(params, body, actor)

    # --- handlers ---------------------------------------------------------------------------------------------------------

    def _create_note(self, params: dict[str, str], body: dict[str, Any], actor: str) -> Any:
        written = self.notes.create(params["result_id"], body["body"], author=actor)
        return {"note": written.note.to_dict(), "memory_sync": [outcome.status for outcome in written.sync]}

    def _update_note(self, params: dict[str, str], body: dict[str, Any], actor: str) -> Any:
        revision = body["expected_revision"]
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ApiError(400, "INVALID_FIELD", "expected_revision must be a positive integer")
        written = self.notes.update(params["note_id"], body["body"], author=actor, expected_revision=revision)
        return {"note": written.note.to_dict(), "memory_sync": [outcome.status for outcome in written.sync]}
