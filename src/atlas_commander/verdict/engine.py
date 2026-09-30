"""Build the verdict document of one snapshot (redesign Phase 2)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DOCUMENT_VERSION = "1.0.0"
VERDICT_VERSION = "verdict-v1.0"
SCHEMA = "verdict-v1.schema.json"
NOTE = ("Judgment layer of the Atlas redesign (D54). Computed at build time from this snapshot's dashboard and Intelligence V2 "
        "documents; it never changes a metric, component state, Overall Status, Trend or finding. Low data lowers confidence and "
        "never silences a verdict.")


def build_verdicts(dashboard: Mapping[str, Any], intelligence: Mapping[str, Any] | None, generated_at: str) -> dict[str, Any]:
    """The verdict document for ``dashboard`` (and its Intelligence V2 document, when one was published)."""
    source = dashboard["source"]
    editors = dashboard["editors"]
    window = editors[0]["interpretation"]["window"] if editors else None
    return {
        "document_version": DOCUMENT_VERSION,
        "verdict_version": VERDICT_VERSION,
        "generated_at": generated_at,
        "executable_contract_version": source["executable_contract_version"],
        "source": {"retrieved_at": source.get("retrieved_at"), "dashboard_version": dashboard["dashboard_version"],
                   "intelligence_version": intelligence.get("intelligence_version") if intelligence else None},
        "windows": {"timezone": "Africa/Cairo",
                    "current": _window(window["current"]) if window else {"start_date": "1970-01-01", "end_date_exclusive": "1970-01-01"},
                    "comparison": _window(window["comparison"]) if window else {"start_date": "1970-01-01", "end_date_exclusive": "1970-01-01"}},
        "config": {"version": "verdict-config-v0", "decision_id": "D54", "values": {}},
        "team": None,
        "editors": [],
        "decisions": [],
        "decision_candidates": [],
        "findings": {"hide_from_overview": [], "duplicates": []},
        "note": NOTE,
    }


def _window(window: Mapping[str, Any]) -> dict[str, str]:
    return {"start_date": window["start_date"], "end_date_exclusive": window["end_date_exclusive"]}
