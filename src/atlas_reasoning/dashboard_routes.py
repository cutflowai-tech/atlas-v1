"""Stable addresses of the reasoning-first dashboard (Phase 16): the interface later phases (17's ExecutiveBrief) link through.

Every reasoning card has one canonical address per locale, derived from its ``result_id`` alone:

==============================================  ==================================================================
``/reasoning/<locale>/``                        reasoning-first home (current cards, then resolved / superseded history)
``/reasoning/<locale>/results/<result_id>``     one ReasoningResult card at its current version (``#result-<result_id>``)
``...?version=<n>``                             the same card as it was at version ``n`` (marked historical)
``.../results/<result_id>/evidence[?version=n]`` evidence drill-down: result → case → Intelligence V2 findings → metrics → Monday IDs
``.../results/<result_id>/history``             version history and lifecycle transitions
``/reasoning/<locale>/teach``                   Teach Atlas
``/api/reasoning/read/...``                     the same canonical state as JSON (``reasoning_read_api``)
==============================================  ==================================================================

On the home page every card is the element ``id="result-<result_id>"``, so ``/reasoning/<locale>/#result-<result_id>`` also lands on
it. Functions here refuse anything that is not a canonical result ID, so a link can never carry injected path or markup.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

BASE = "/reasoning"
LOCALES = ("en", "ar")
RESULT_ID = re.compile(r"^rr1_[0-9a-f]{32}$")
# The locale the bare ``/reasoning/`` address opens: Arabic, the redesigned Atlas site's default language (D54).
DEFAULT_LOCALE = "ar"


class InvalidRoute(ValueError):
    """A locale or result ID that no dashboard address can carry."""


def _check(locale: str, result_id: str | None = None) -> None:
    if locale not in LOCALES:
        raise InvalidRoute(f"unknown locale {locale!r}")
    if result_id is not None and not RESULT_ID.match(result_id):
        raise InvalidRoute("not a canonical result ID")


def card_anchor(result_id: str) -> str:
    """The element ID of a result card (home page and card page)."""
    _check(LOCALES[0], result_id)
    return f"result-{result_id}"


def home_path(locale: str) -> str:
    _check(locale)
    return f"{BASE}/{locale}/"


def card_path(locale: str, result_id: str, *, version: int | None = None) -> str:
    """The card of ``result_id``: the current version, or ``version`` (historical) when given."""
    _check(locale, result_id)
    query = ""
    if version is not None:
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise InvalidRoute("version must be a positive integer")
        query = f"?version={version}"
    return f"{BASE}/{locale}/results/{result_id}{query}#{card_anchor(result_id)}"


def evidence_path(locale: str, result_id: str, *, version: int | None = None) -> str:
    """The evidence drill-down of the current version, or of ``version`` (a historical card audits its own evidence)."""
    _check(locale, result_id)
    query = ""
    if version is not None:
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise InvalidRoute("version must be a positive integer")
        query = f"?version={version}"
    return f"{BASE}/{locale}/results/{result_id}/evidence{query}"


def history_path(locale: str, result_id: str) -> str:
    _check(locale, result_id)
    return f"{BASE}/{locale}/results/{result_id}/history"


def teach_path(locale: str) -> str:
    _check(locale)
    return f"{BASE}/{locale}/teach"


def result_links(locale: str, result_ids: Iterable[str]) -> list[dict[str, str]]:
    """Card, evidence and history addresses for each result a statement cites (in the given order, duplicates removed). Phase 17's
    executive statements carry ``result_ids``; this is how they link to the cards. Raises ``InvalidRoute`` for any non-canonical ID;
    whether the result exists is the caller's to check against canonical state (``DashboardService.card`` raises ``NotFound``)."""
    links, seen = [], set()
    for result_id in result_ids:
        if result_id in seen:
            continue
        seen.add(result_id)
        links.append({"result_id": result_id, "card": card_path(locale, result_id), "evidence": evidence_path(locale, result_id),
                      "history": history_path(locale, result_id)})
    return links


def parse_result_id(value: str) -> str:
    if not RESULT_ID.match(value):
        raise InvalidRoute("not a canonical result ID")
    return value
