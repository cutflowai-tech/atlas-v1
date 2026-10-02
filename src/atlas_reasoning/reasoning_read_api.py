"""Read API for canonical reasoning state (Phase 16): transport-neutral, JSON, read-only.

Kept apart from the write-oriented ``management_api`` so reads never weaken its write rules. It serves exactly the view objects the
dashboard pages render (``dashboard.DashboardService``), so the JSON, the English page and the Arabic page carry the same canonical
records. It never computes a metric, confidence, lifecycle or comparison, and it never returns a refused Phase 15 candidate.

Security is the management API's: the actor comes from the authenticating proxy (``Request.actor``), must be an allowed manager
(``management_api.authorize_actor``: 401 / 403), only ``GET`` is accepted (405), identifiers must be canonical (``rr1_…``; 404
otherwise) and errors are codes without internal detail (``READ_FAILED`` 503 when PostgreSQL cannot be read). Responses carry the
same no-store / nosniff headers. No provider or Honcho credential is reachable from here.

Routes (prefix ``/api/reasoning/read``):

==========  ===========================================  =========================================================
GET         /results                                     home: current cards, resolved/superseded history, memory backlog
GET         /results/{result_id}[?version=n]             one card (current or version ``n``) with its human context
GET         /results/{result_id}/evidence[?version=n]    evidence drill-down: result → case → V2 findings → metrics → Monday IDs
GET         /results/{result_id}/history                 versions and lifecycle transitions
GET         /links?locale=en&result_id=…[&result_id=…]   per ID: exists, lifecycle, current version, replacement, and addresses
==========  ===========================================  =========================================================
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from atlas_reasoning import dashboard_routes as routes
from atlas_reasoning.dashboard import DashboardService, DashboardUnavailable
from atlas_reasoning.management_api import ApiError, ApiSettings, Request, Response, authorize_actor
from atlas_reasoning.store.repository import NotFound

PREFIX = "/api/reasoning/read"
_RESULT = r"(?P<result_id>[A-Za-z0-9_]{1,80})"
_VERSION = re.compile(r"^[1-9][0-9]{0,5}$")
MAX_LINKS = 50


def parse_version(query: dict[str, list[str]]) -> int | None:
    values = query.get("version")
    if not values:
        return None
    if len(values) != 1 or not _VERSION.fullmatch(values[0]):
        raise ApiError(400, "INVALID_VERSION")
    return int(values[0])


class ReasoningReadAPI:
    def __init__(self, settings: ApiSettings, service: DashboardService) -> None:
        self.settings = settings
        self.service = service
        self.routes = [
            (re.compile(f"^{PREFIX}/results$"), self._home),
            (re.compile(f"^{PREFIX}/results/{_RESULT}$"), self._card),
            (re.compile(f"^{PREFIX}/results/{_RESULT}/evidence$"), self._evidence),
            (re.compile(f"^{PREFIX}/results/{_RESULT}/history$"), self._history),
            (re.compile(f"^{PREFIX}/links$"), self._links),
        ]

    def handle(self, request: Request) -> Response:
        try:
            return Response(200, self._dispatch(request))
        except ApiError as error:
            return Response(error.status, {"error": error.code, "message": None})
        except (NotFound, routes.InvalidRoute):
            return Response(404, {"error": "NOT_FOUND", "message": None})
        except DashboardUnavailable:
            return Response(503, {"error": DashboardUnavailable.code, "message": None})

    def _dispatch(self, request: Request) -> Any:
        if request.method.upper() != "GET":
            raise ApiError(405, "METHOD_NOT_ALLOWED")
        authorize_actor(self.settings, request.actor)
        path, _, raw_query = request.path.partition("?")
        try:
            query = urllib.parse.parse_qs(raw_query, max_num_fields=MAX_LINKS + 2, strict_parsing=False)
        except ValueError:
            raise ApiError(400, "INVALID_QUERY") from None
        for pattern, handler in self.routes:
            match = pattern.fullmatch(path)
            if match:
                params = match.groupdict()
                if "result_id" in params:
                    routes.parse_result_id(params["result_id"])            # canonical IDs only, before any read
                return handler(params, query)
        raise ApiError(404, "NOT_FOUND")

    def _home(self, params: dict[str, str], query: dict[str, list[str]]) -> Any:
        return self.service.home().to_dict()

    def _card(self, params: dict[str, str], query: dict[str, list[str]]) -> Any:
        card = self.service.card(params["result_id"], parse_version(query))
        return {"card": card.to_dict(), "human_context": self.service.human_context(params["result_id"]).to_dict()}

    def _evidence(self, params: dict[str, str], query: dict[str, list[str]]) -> Any:
        return {"evidence": self.service.evidence(params["result_id"], parse_version(query)).to_dict()}

    def _history(self, params: dict[str, str], query: dict[str, list[str]]) -> Any:
        return {"history": self.service.history(params["result_id"]).to_dict()}

    def _links(self, params: dict[str, str], query: dict[str, list[str]]) -> Any:
        """Per cited result ID: its state (exists, lifecycle, current version, replacement) and, when it exists, its card, evidence and
        history addresses. One unknown ID never hides the others."""
        locale = (query.get("locale") or [routes.LOCALES[0]])[-1]
        if locale not in routes.LOCALES:
            raise ApiError(400, "INVALID_LOCALE")
        result_ids = query.get("result_id") or []
        if not result_ids or len(result_ids) > MAX_LINKS:
            raise ApiError(400, "INVALID_QUERY")
        try:
            addresses = {link["result_id"]: link for link in routes.result_links(locale, result_ids)}
        except routes.InvalidRoute:
            raise ApiError(400, "INVALID_RESULT_ID") from None
        states = self.service.result_states(list(addresses))
        return {"links": [{**states[result_id], **({key: value for key, value in link.items() if key != "result_id"} if states[result_id]["exists"] else {})}
                          for result_id, link in addresses.items()]}
