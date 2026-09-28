"""Read-only evidence API: GET /api/editors/<editor_id>.

The API serves stored EditorProfile documents (contracts/editor-profile.schema.json)
from an injected repository. It never recalculates metrics; it validates each profile
against the frozen contract before serving and refuses to serve anything invalid.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections.abc import Iterable, Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urlsplit

from atlas_commander.contracts import ROOT, schema_errors, semantic_codes

PROFILE_SCHEMA = "editor-profile.schema.json"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_FIXTURES = (ROOT / "fixtures/good/editor-profile.json",)
ROUTE_PREFIX = "/api/editors/"
EDITOR_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
# A work cycle without Requested ETA is valid profile content; it simply yields no deadline metric.
NON_BLOCKING_CODES = frozenset({"MISSING_REQUESTED_ETA"})


class ProfileRepository(Protocol):
    data_mode: str
    provenance: str

    def get_profile(self, editor_id: str) -> dict[str, Any] | None: ...


class ProfileValidationError(ValueError):
    def __init__(self, errors: Sequence[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = list(errors)


def profile_errors(profile: Any) -> list[str]:
    """Schema errors plus nested semantic invariants the top-level schema check cannot see."""
    errors = schema_errors(profile, PROFILE_SCHEMA)
    if errors:
        return ["SCHEMA_INVALID: " + message for message in errors]
    editor_id = profile["editor"]["editor_id"]
    nested: list[tuple[str, str, dict[str, Any]]] = [(f"work_cycles[{i}]", "work-cycle.schema.json", item) for i, item in enumerate(profile["work_cycles"])]
    for name in ("speed", "deadline", "quality"):
        nested += [(f"metrics.{name}[{i}]", f"{name}-metric.schema.json", item) for i, item in enumerate(profile["metrics"][name])]
    for location, schema_name, item in nested:
        errors += [f"{code}: {location}" for code in semantic_codes(item, schema_name) if code not in NON_BLOCKING_CODES]
        if item["editor_id"] != editor_id:
            errors.append(f"EDITOR_ID_MISMATCH: {location}")
    return errors


def validate_profile(profile: Any) -> None:
    errors = profile_errors(profile)
    if errors:
        raise ProfileValidationError(errors)


class FixtureProfileRepository:
    """Contract-valid profiles loaded from fixture files, indexed by canonical editor_id."""

    data_mode = "fixture"

    def __init__(self, paths: Iterable[Path] = DEFAULT_FIXTURES) -> None:
        self.paths = [Path(path) for path in paths]
        if not self.paths:
            raise ValueError("at least one fixture profile path is required")
        self._profiles: dict[str, dict[str, Any]] = {}
        for path in self.paths:
            profile = json.loads(path.read_text())
            try:
                validate_profile(profile)
            except ProfileValidationError as exc:
                raise ProfileValidationError([f"{path}: {error}" for error in exc.errors]) from exc
            editor_id = profile["editor"]["editor_id"]
            if editor_id in self._profiles:
                raise ValueError(f"duplicate fixture profile for editor_id {editor_id!r}: {path}")
            self._profiles[editor_id] = profile
        self.provenance = "fixture:" + ",".join(_display_path(path) for path in self.paths)

    def get_profile(self, editor_id: str) -> dict[str, Any] | None:
        profile = self._profiles.get(editor_id)
        return copy.deepcopy(profile) if profile is not None else None


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    return str(resolved.relative_to(ROOT)) if resolved.is_relative_to(ROOT) else str(resolved)


class EvidenceAPIHandler(BaseHTTPRequestHandler):
    repository: ProfileRepository
    server_version = "AtlasEvidenceAPI/1.0"

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if not path.startswith(ROUTE_PREFIX):
            self._error(HTTPStatus.NOT_FOUND, "ROUTE_NOT_FOUND", "unknown route")
            return
        raw_id = path[len(ROUTE_PREFIX):]
        editor_id = unquote(raw_id)
        if not EDITOR_ID_PATTERN.fullmatch(editor_id):
            self._error(HTTPStatus.BAD_REQUEST, "INVALID_EDITOR_ID", "editor_id must be a canonical identifier")
            return
        profile = self.repository.get_profile(editor_id)
        if profile is None:
            self._error(HTTPStatus.NOT_FOUND, "EDITOR_NOT_FOUND", f"no profile for editor_id {editor_id!r}")
            return
        errors = profile_errors(profile)
        if not errors and profile["editor"]["editor_id"] != editor_id:
            errors = ["EDITOR_ID_MISMATCH: editor"]
        if errors:
            self.log_error("refusing contract-invalid profile for %s: %s", editor_id, "; ".join(errors))
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "PROFILE_CONTRACT_VIOLATION", "stored profile failed editor-profile contract validation")
            return
        self._send(HTTPStatus.OK, profile)

    def _method_not_allowed(self) -> None:
        self._error(HTTPStatus.METHOD_NOT_ALLOWED, "METHOD_NOT_ALLOWED", "only GET is supported", extra_headers={"Allow": "GET"})

    do_POST = do_PUT = do_PATCH = do_DELETE = _method_not_allowed

    def _error(self, status: HTTPStatus, code: str, message: str, extra_headers: dict[str, str] | None = None) -> None:
        self._send(status, {"error": {"code": code, "message": message}}, extra_headers)

    def _send(self, status: HTTPStatus, body: Any, extra_headers: dict[str, str] | None = None) -> None:
        payload = json.dumps(body, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Atlas-Data-Mode", self.repository.data_mode)
        self.send_header("X-Atlas-Provenance", self.repository.provenance)
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)


def create_server(repository: ProfileRepository, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    handler = type("BoundEvidenceAPIHandler", (EvidenceAPIHandler,), {"repository": repository})
    return ThreadingHTTPServer((host, port), handler)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the Atlas evidence API from fixture profiles.")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"bind address (default {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"bind port (default {DEFAULT_PORT})")
    parser.add_argument("--fixture", action="append", type=Path, help="editor-profile fixture JSON; repeatable")
    args = parser.parse_args(argv)
    repository = FixtureProfileRepository(args.fixture or DEFAULT_FIXTURES)
    server = create_server(repository, args.host, args.port)
    host, port = server.server_address[:2]
    print(f"Atlas evidence API (data mode: FIXTURE, provenance: {repository.provenance}) on http://{host!s}:{port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
