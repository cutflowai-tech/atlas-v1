"""The Reasoning V3 web application (Phase 16): the smallest safe mounting of the dashboard, the read API and the management API.

A standard WSGI application (stdlib only), separate from the static Atlas site: the deterministic site is still built and published
exactly as before, and nothing in ``atlas_commander`` / ``atlas_sync`` imports this module. Production topology (process manager,
reverse proxy, TLS, rollout) is Phase 20's; this module makes no deployment decision.

=========================================  ==============================================================
``/reasoning/`` → ``/reasoning/ar/``        redirect to the default locale
``/reasoning/<en|ar>/…``                   dashboard pages (``dashboard_routes``), GET / HEAD
``/reasoning/assets/dashboard.css|js``     static assets
``/api/reasoning/read/…``                  ``reasoning_read_api.ReasoningReadAPI`` (GET)
``/api/reasoning/…``                       ``management_api.ManagementAPI`` (notes, questions, Teach Atlas)
=========================================  ==============================================================

Security assumptions (unchanged from Phases 12-14, now enforced for every route):

- **Authentication is the proxy's.** The actor is the WSGI ``REMOTE_USER`` set by the server behind the authenticating proxy, or —
  only when ``ATLAS_REASONING_ACTOR_HEADER`` names one — that request header, which the proxy must set and strip from clients.
  Never the request body or a query parameter.
- **Authorization**: every page and API route requires an actor in ``ATLAS_REASONING_MANAGERS`` (401 / 403). Assets are static.
- **Writes** go only through ``ManagementAPI``: JSON content type, allowed ``Origin`` (``ATLAS_REASONING_ALLOWED_ORIGINS`` must list the
  dashboard's origin), actor-bound ``X-Atlas-CSRF`` token, bounded bodies (only ``max_body_bytes + 1`` bytes are ever read).
- **Responses**: ``no-store``, ``nosniff``, ``frame-ancestors 'none'`` and a Content-Security-Policy allowing only same-origin scripts,
  styles and requests (no inline script or style). Errors are plain-language pages or JSON codes, never internals.
- **No credential** (database URL, OpenRouter or Honcho key, CSRF secret) is ever written to a response.

With ``ATLAS_REASONING_V3`` off, ``create_app`` refuses to start (``ReasoningDisabled``); legacy Atlas needs none of this.

Local preview only: ``python -m atlas_reasoning.web_app --port 8765`` (loopback addresses only).
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import urllib.parse
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from atlas_reasoning import dashboard_html as html
from atlas_reasoning import dashboard_routes as routes
from atlas_reasoning.dashboard import DashboardService, DashboardUnavailable
from atlas_reasoning.dashboard_assets import CSS, JS
from atlas_reasoning.management_api import ApiError, ApiSettings, ManagementAPI, Request, Response, api_settings, authorize_actor
from atlas_reasoning.reasoning_read_api import ReasoningReadAPI, parse_version
from atlas_reasoning.settings import ReasoningConfigError
from atlas_reasoning.store.repository import NotFound

LOG = logging.getLogger("atlas_reasoning.web_app")

ACTOR_HEADER_ENV = "ATLAS_REASONING_ACTOR_HEADER"
DIAGNOSTICS_URL_ENV = "ATLAS_REASONING_DIAGNOSTICS_URL"
MONDAY_ITEM_URL_ENV = "ATLAS_REASONING_MONDAY_ITEM_URL"
DEFAULT_DIAGNOSTICS_URL = "/{locale}/dashboard.html"

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; form-action 'self'; "
       "base-uri 'none'; frame-ancestors 'none'")
BASE_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": CSP}
STATUS_TEXT = {200: "OK", 302: "Found", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed",
               409: "Conflict", 413: "Payload Too Large", 415: "Unsupported Media Type", 500: "Internal Server Error", 503: "Service Unavailable"}
_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_SAFE_URL = re.compile(r"^[^\s\"'<>\\`]+$")
_PAGE = re.compile(r"^/reasoning/(?P<locale>en|ar)/(?:(?P<teach>teach)|results/(?P<result_id>[A-Za-z0-9_]{1,80})(?P<sub>/evidence|/history)?)?$")
ASSETS = {"/reasoning/assets/dashboard.css": ("text/css; charset=utf-8", CSS), "/reasoning/assets/dashboard.js": ("text/javascript; charset=utf-8", JS)}

StartResponse = Callable[..., Any]


@dataclass(frozen=True)
class WebSettings:
    api: ApiSettings
    actor_header: str | None = None
    diagnostics_url: str = DEFAULT_DIAGNOSTICS_URL
    monday_item_url: str | None = field(default=None)

    def __post_init__(self) -> None:
        if self.actor_header is not None and not _HEADER_NAME.match(self.actor_header):
            raise ReasoningConfigError(f"{ACTOR_HEADER_ENV} must be a header name")
        url = self.diagnostics_url
        if not _SAFE_URL.match(url) or not (url.startswith("https://") or (url.startswith("/") and not url.startswith("//"))):
            raise ReasoningConfigError(f"{DIAGNOSTICS_URL_ENV} must be a site path (/...) or an https URL")
        item = self.monday_item_url
        if item is not None and (not _SAFE_URL.match(item) or not item.startswith("https://") or "{item_id}" not in item):
            raise ReasoningConfigError(f"{MONDAY_ITEM_URL_ENV} must be an https URL containing {{item_id}}")


def web_settings(env: Mapping[str, str] | None = None) -> WebSettings:
    env = os.environ if env is None else env
    return WebSettings(api=api_settings(env), actor_header=env.get(ACTOR_HEADER_ENV, "").strip() or None,
                       diagnostics_url=env.get(DIAGNOSTICS_URL_ENV, "").strip() or DEFAULT_DIAGNOSTICS_URL,
                       monday_item_url=env.get(MONDAY_ITEM_URL_ENV, "").strip() or None)


class ReasoningWebApp:
    """The WSGI callable. Built by ``create_app`` (or directly in tests, with any ``DashboardService`` and ``ManagementAPI``)."""

    def __init__(self, settings: WebSettings, service: DashboardService, management: ManagementAPI) -> None:
        self.settings = settings
        self.service = service
        self.management = management
        self.read_api = ReasoningReadAPI(settings.api, service)

    # --- WSGI ---------------------------------------------------------------------------------------------------------------

    def __call__(self, environ: Mapping[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        try:
            status, headers, body = self.route(environ, method)
        except Exception as error:  # noqa: BLE001 - never leak internals; the class is logged for engineering
            LOG.error("unhandled web error error=%s", type(error).__name__)
            status, headers, body = 500, {"Content-Type": "text/plain; charset=utf-8"}, b"Internal Server Error"
        merged = {**BASE_HEADERS, **headers, "Content-Length": str(len(body))}
        start_response(f"{status} {STATUS_TEXT.get(status, 'Error')}", list(merged.items()))
        return [b""] if method == "HEAD" else [body]

    def actor(self, environ: Mapping[str, Any]) -> str | None:
        if self.settings.actor_header:
            value = environ.get("HTTP_" + self.settings.actor_header.upper().replace("-", "_"))
        else:
            value = environ.get("REMOTE_USER")
        text = str(value).strip() if value else ""
        # One identity only: a comma (duplicate headers joined) or a control character is never an actor.
        if not text or "," in text or any(ord(char) < 32 or ord(char) == 127 for char in text):
            return None
        return text

    def route(self, environ: Mapping[str, Any], method: str) -> tuple[int, dict[str, str], bytes]:
        path = str(environ.get("PATH_INFO") or "/")
        query = str(environ.get("QUERY_STRING") or "")
        if path in ASSETS:
            if method not in ("GET", "HEAD"):
                return 405, {"Content-Type": "text/plain; charset=utf-8", "Allow": "GET, HEAD"}, b"Method Not Allowed"
            content_type, content = ASSETS[path]
            return 200, {"Content-Type": content_type, "Cache-Control": "no-cache"}, content.encode()
        if path in ("/reasoning", "/reasoning/"):
            return 302, {"Location": routes.home_path(routes.DEFAULT_LOCALE), "Content-Type": "text/plain; charset=utf-8"}, b""
        if path.startswith(routes.BASE + "/"):
            return self.page(environ, method, path, query)
        if path == "/api/reasoning/read" or path.startswith("/api/reasoning/read/"):
            return self._json(self.read_api.handle(self._request(environ, method, path, query, body=False)))
        if path.startswith("/api/reasoning/"):
            return self._json(self.management.handle(self._request(environ, method, path, query, body=True)))
        return 404, {"Content-Type": "text/plain; charset=utf-8"}, b"Not Found"

    # --- API mounting ---------------------------------------------------------------------------------------------------------

    def _request(self, environ: Mapping[str, Any], method: str, path: str, query: str, *, body: bool) -> Request:
        headers = {key[5:].replace("_", "-").lower(): str(value) for key, value in environ.items() if key.startswith("HTTP_")}
        if environ.get("CONTENT_TYPE"):
            headers["content-type"] = str(environ["CONTENT_TYPE"])
        if self.settings.actor_header:
            headers.pop(self.settings.actor_header.lower(), None)
        data = self._body(environ) if body and method not in ("GET", "HEAD") else b""
        return Request(method="GET" if method == "HEAD" else method, path=f"{path}?{query}" if query else path, actor=self.actor(environ),
                       headers=headers, body=data)

    def _body(self, environ: Mapping[str, Any]) -> bytes:
        """At most ``max_body_bytes + 1`` bytes: enough for the API to refuse an oversized body (413) without reading it."""
        limit = self.settings.api.max_body_bytes + 1
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        stream = environ.get("wsgi.input")
        if stream is None or length <= 0:
            return b""
        data: bytes = stream.read(min(length, limit))
        return data

    @staticmethod
    def _json(response: Response) -> tuple[int, dict[str, str], bytes]:
        return response.status, dict(response.headers), response.body

    # --- pages ------------------------------------------------------------------------------------------------------------------

    def _context(self, locale: str, actor: str | None, path: str, version: int | None) -> html.PageContext:
        switch = path.replace(f"/{locale}/", f"/{'ar' if locale == 'en' else 'en'}/", 1) + (f"?version={version}" if version else "")
        return html.PageContext(locale, csrf_token=self.management.csrf_token(actor) if actor else "", diagnostics_url=self.settings.diagnostics_url,
                                monday_item_url=self.settings.monday_item_url, switch_path=switch)

    @staticmethod
    def _html(status: int, page: str, extra: Mapping[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        return status, {"Content-Type": "text/html; charset=utf-8", **(extra or {})}, page.encode()

    def page(self, environ: Mapping[str, Any], method: str, path: str, query: str) -> tuple[int, dict[str, str], bytes]:
        match = _PAGE.match(path)
        locale = match.group("locale") if match else routes.DEFAULT_LOCALE
        error_ctx = html.PageContext(locale, diagnostics_url=self.settings.diagnostics_url)
        if method not in ("GET", "HEAD"):
            return self._html(405, html.error_page("method", error_ctx), {"Allow": "GET, HEAD"})
        try:
            actor = authorize_actor(self.settings.api, self.actor(environ))
        except ApiError as error:
            return self._html(error.status, html.error_page("unauthenticated" if error.status == 401 else "forbidden", error_ctx))
        if match is None:
            return self._html(404, html.error_page("not_found", error_ctx))
        try:
            version = parse_version(urllib.parse.parse_qs(query, max_num_fields=4))
        except (ApiError, ValueError):
            return self._html(404, html.error_page("not_found", error_ctx))
        ctx = self._context(locale, actor, path, version)
        try:
            return self._html(200, self._render(match, ctx, version))
        except (NotFound, routes.InvalidRoute):
            return self._html(404, html.error_page("not_found", error_ctx))
        except DashboardUnavailable:
            return self._html(503, html.error_page("unavailable", error_ctx))

    def _render(self, match: re.Match[str], ctx: html.PageContext, version: int | None) -> str:
        if match.group("teach"):
            return html.teach_page(self.service.teachings_list(), ctx)
        result_id = match.group("result_id")
        if result_id is None:
            return html.home_page(self.service.home(), ctx)
        routes.parse_result_id(result_id)
        sub = match.group("sub")
        if sub == "/history":
            return html.history_page(self.service.history(result_id), ctx)
        card = self.service.card(result_id, version)
        trace = self.service.evidence(result_id, card.shown_version)
        if sub == "/evidence":
            return html.evidence_page(card, trace, ctx)
        return html.card_page(card, self.service.human_context(result_id), trace, self.service.history(result_id), ctx)


def create_app(env: Mapping[str, str] | None = None) -> ReasoningWebApp:
    """The configured application. Refuses to start with Reasoning V3 off; opens no connection until a request needs one."""
    from atlas_reasoning import human_context, settings
    from atlas_reasoning.atlas_questions import AtlasQuestions
    from atlas_reasoning.honcho_client import backend_from_env
    from atlas_reasoning.manager_notes import ManagerNotes
    from atlas_reasoning.store.db import Database
    from atlas_reasoning.store.repository import ReasoningStore
    from atlas_reasoning.teach_atlas import TeachAtlas

    settings.require_enabled(env)
    web = web_settings(env)
    store = ReasoningStore(Database(settings.database_url(env)))
    sync = human_context.sync_service(store, backend_from_env(env))
    notes, questions, teachings = ManagerNotes(store, sync), AtlasQuestions(store, sync), TeachAtlas(store, sync)
    service = DashboardService(store, notes=notes, questions=questions, teachings=teachings)
    return ReasoningWebApp(web, service, ManagementAPI(web.api, notes=notes, questions=questions, teachings=teachings))


LOOPBACK = ("127.0.0.1", "::1", "localhost")


def main(argv: list[str] | None = None) -> int:
    """Local preview server (wsgiref). Loopback only: production serving and the proxy are Phase 20's."""
    from wsgiref.simple_server import make_server

    parser = argparse.ArgumentParser(prog="python -m atlas_reasoning.web_app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--dev-actor", default=None, help="local preview only: act as this manager (no proxy on a developer machine)")
    args = parser.parse_args(argv)
    if args.host not in LOOPBACK:
        parser.error("the preview server binds loopback addresses only; production serving is REV/20")
    app = create_app()
    served: Any = app
    if args.dev_actor:
        actor = args.dev_actor

        hosts = {f"{name}:{args.port}" for name in ("127.0.0.1", "localhost", "[::1]")}

        def served(environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
            if str(environ.get("HTTP_HOST", "")).lower() not in hosts:      # no DNS rebinding onto the preview's built-in actor
                start_response("400 Bad Request", [("Content-Type", "text/plain; charset=utf-8")])
                return [b"Bad Request"]
            environ = {**environ, "REMOTE_USER": actor}
            return app(environ, start_response)

        print(f"preview: every request acts as {actor!r} (local preview only)", file=sys.stderr)
    with make_server(args.host, args.port, served) as server:
        print(f"Atlas reasoning preview on http://{args.host}:{args.port}/reasoning/", file=sys.stderr)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
