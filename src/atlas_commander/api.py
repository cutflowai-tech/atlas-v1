"""Fixture-backed evidence transport; metric values are supplied by the repository."""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Protocol
from urllib.parse import unquote, urlsplit

from .contracts import ROOT, schema_errors, semantic_codes


class ProfileRepository(Protocol):
    def get(self, editor_id: str) -> dict[str, Any] | None:
        """Return a precomputed profile, or None when the canonical ID is absent."""
        ...


def validate_profile(profile: dict[str, Any], editor_id: str) -> None:
    """Validate the frozen schema and nested semantics without rewriting values."""
    if schema_errors(profile, "editor-profile.schema.json"):
        raise ValueError("Invalid editor profile schema")
    if profile["editor"]["editor_id"] != editor_id:
        raise ValueError("Repository returned a different editor")
    groups = [("work-cycle", profile["work_cycles"])]
    groups.extend((f"{name}-metric", values) for name, values in profile["metrics"].items())
    for name, values in groups:
        for value in values:
            if value["editor_id"] != editor_id:
                raise ValueError("Nested editor identity mismatch")
            codes = semantic_codes(value, f"{name}.schema.json")
            # A cycle may lack ETA; the deadline metric schema still requires it.
            if any(code != "MISSING_REQUESTED_ETA" for code in codes):
                raise ValueError("Invalid nested profile semantics")


def fixture_repository() -> dict[str, dict[str, Any]]:
    """Load the checked-in example records unchanged, without computing metrics."""
    directory = ROOT / "fixtures" / "good"
    profile = json.loads((directory / "editor-profile.json").read_text())
    profile["work_cycles"] = [json.loads((directory / "work-cycle.json").read_text())]
    for name in ("speed", "deadline", "quality"):
        profile["metrics"][name] = [json.loads((directory / f"{name}-metric.json").read_text())]
    editor_id = profile["editor"]["editor_id"]
    validate_profile(profile, editor_id)
    return {editor_id: profile}


def create_server(repository: ProfileRepository, host: str = "127.0.0.1", port: int = 8000) -> HTTPServer:
    """Bind a stdlib fixture server; the caller owns serving and closing it."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def reply(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Atlas-Provenance", "fixture")
            self.send_header("Cache-Control", "no-store")
            if status == 405:
                self.send_header("Allow", "GET")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self) -> None:
            try:
                path = unquote(urlsplit(self.path).path, errors="strict")
            except (ValueError, UnicodeError):
                self.reply(400, {"error": "invalid_path"})
                return
            parts = path.split("/")
            if len(parts) != 4 or parts[:3] != ["", "api", "editors"] or not parts[3]:
                self.reply(404, {"error": "not_found"})
                return
            editor_id = parts[3]
            try:
                profile = deepcopy(repository.get(editor_id))
                if profile is None:
                    self.reply(404, {"error": "editor_not_found"})
                    return
                validate_profile(profile, editor_id)
                # Check JSON encoding before emitting any response headers.
                json.dumps(profile, allow_nan=False)
            except Exception:  # noqa: BLE001 - repository failures must not leak through HTTP
                self.reply(500, {"error": "profile_unavailable"})
                return
            self.reply(200, profile)

        def unsupported(self) -> None:
            self.reply(405, {"error": "method_not_allowed"})

        do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = unsupported

    return HTTPServer((host, port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Atlas fixture evidence API (not live Monday data)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    with create_server(fixture_repository(), args.host, args.port) as server:
        print(f"Atlas FIXTURE evidence API at http://{server.server_name}:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
