"""The plain data-health line of the redesign (T4.7, `ATLAS-DATA-001`): one of "Data is safe to use", "Data is delayed (last refresh X)"
or "Data unavailable", read from the build's existing status snapshot (Task 7: ``freshness_state``, ``system_state``,
``current_publication.monday_retrieved_at``). Nothing is recomputed: the snapshot already classified the freshness; this only words it.
"""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
from typing import Any

from atlas_commander.i18n import Html, Loc

SAFE, DELAYED, UNAVAILABLE = "safe", "delayed", "unavailable"


def data_health(status_snapshot: Mapping[str, Any] | None, retrieved_at: str | None) -> tuple[str, str | None]:
    """The plain state and the last refresh (the Monday retrieval time) it may cite.

    - unavailable: no Monday data behind the page, or the snapshot reports a failed system;
    - safe: the snapshot classified the data as fresh;
    - delayed: anything else, including a freshness nobody could confirm (no snapshot, or ``unknown``): the page never claims more
      than the snapshot proves."""
    current = (status_snapshot or {}).get("current_publication") or {}
    last = current.get("monday_retrieved_at") or current.get("retrieved_at") or retrieved_at
    if not last or (status_snapshot or {}).get("system_state") == "failed":
        return UNAVAILABLE, None
    if (status_snapshot or {}).get("freshness_state") == "fresh":
        return SAFE, last
    return DELAYED, last


def health_line(state: str, last: str | None, loc: Loc) -> Html:
    if state == DELAYED:
        return loc.t("ui.v.health.delayed", date=Html(loc.when(last)))
    return loc.t("ui.v.health." + state)


def health_link(status_snapshot: Mapping[str, Any] | None, retrieved_at: str | None, loc: Loc) -> str:
    """The top bar's data-health link to More details › Data health."""
    state, last = data_health(status_snapshot, retrieved_at)
    return (f'<a class="fresh v-health" data-health="{state}" href="#/system" title="{escape(loc.text("ui.data_status"), quote=True)}">'
            f'<i></i><span>{health_line(state, last, loc)}</span></a>')
