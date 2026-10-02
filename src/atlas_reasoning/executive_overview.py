"""The executive overview's read model (Phase 17 UI, ``REV/17`` #10): the persisted canonical ExecutiveBrief, ready to present.

Read-only. ``ExecutiveOverviewService.overview()`` reads the **current** brief through the Phase 17 core store
(``ExecutiveTransaction.current_brief``) and never creates, synthesizes, validates or rewrites one: no gateway, no provider, no Honcho,
no write. It derives presentation only:

- the brief's sections and statements, verbatim (model text stays untrusted text; the HTML layer escapes it);
- for every result a statement cites, the result **version the synthesis saw** (the brief's own ``input_results``) and that version's
  stored title, plus the result's state now (``DashboardService.result_states``: current version, lifecycle, ``superseded_by``), so a
  statement links to the card and evidence of the version it was written from and says plainly when the card has moved on, been
  resolved or been replaced — without changing the statement;
- safe provenance (brief ID, version, run, generator, model, prompt and validator versions, creation time, input size);
- whether the latest synthesis run failed while this brief stayed current (decision and failure *class* only).

It computes no fact, metric, confidence or conclusion. A refused executive candidate is never read (``executive_brief_runs`` is read for
its decision and failure class only).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from atlas_reasoning.contracts import ContractViolation
from atlas_reasoning.dashboard import DashboardService, DashboardUnavailable
from atlas_reasoning.executive_contracts import COMPANY_SCOPE, EDITOR_SECTION, SECTIONS, ExecutiveBrief
from atlas_reasoning.store import executive_read as sql
from atlas_reasoning.store.db import DatabaseError
from atlas_reasoning.store.executive import ExecutiveTransaction
from atlas_reasoning.store.repository import ReasoningStore

LOG = logging.getLogger("atlas_reasoning.executive_overview")


@dataclass(frozen=True)
class CitedResult:
    """One result a statement cites: the version the synthesis saw, and the result's canonical state now."""

    result_id: str
    pinned_version: int | None              # from the brief's input_results (None: not in the input — never expected)
    pinned_lifecycle: str | None
    pinned_title: str
    exists: bool
    current_version: int | None
    current_lifecycle: str | None
    superseded_by: str | None

    @property
    def moved_on(self) -> bool:
        """The card has a newer version than the one the statement was synthesized from."""
        return self.exists and self.pinned_version is not None and self.current_version is not None and self.current_version != self.pinned_version

    def to_dict(self) -> dict[str, Any]:
        return {"result_id": self.result_id, "pinned_version": self.pinned_version, "pinned_lifecycle": self.pinned_lifecycle,
                "pinned_title": self.pinned_title, "exists": self.exists, "current_version": self.current_version,
                "current_lifecycle": self.current_lifecycle, "superseded_by": self.superseded_by, "moved_on": self.moved_on}


@dataclass(frozen=True)
class StatementView:
    statement_id: str
    section: str
    text: str                               # stored model text, untrusted
    editor_id: str | None
    cited: tuple[CitedResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"statement_id": self.statement_id, "section": self.section, "text": self.text, "editor_id": self.editor_id,
                "cited": [row.to_dict() for row in self.cited]}


@dataclass(frozen=True)
class Overview:
    """The executive overview: ``state`` is ``brief`` (a current brief), ``none`` (no brief yet) or ``unavailable`` (read failed)."""

    state: str
    brief: ExecutiveBrief | None = None
    sections: tuple[tuple[str, tuple[StatementView, ...]], ...] = ()     # non-empty canonical sections, in contract order
    latest_run_failed: bool = False

    @property
    def statement_count(self) -> int:
        return sum(len(rows) for _, rows in self.sections)

    def provenance(self) -> dict[str, Any]:
        brief = self.brief
        if brief is None:
            return {}
        return {"brief_id": brief.brief_id, "version": brief.version, "run_id": brief.run_id, "generator": brief.generator.kind,
                "provider": brief.generator.provider, "model": brief.generator.model, "prompt_version": brief.prompt_version,
                "validator_version": brief.validator_version, "created_at": brief.created_at, "input_results": len(brief.input_results),
                "omitted_results": brief.omitted_result_count}

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state, "provenance": self.provenance(), "latest_run_failed": self.latest_run_failed,
                "sections": [{"section": name, "statements": [row.to_dict() for row in rows]} for name, rows in self.sections]}


def _db_error(error: BaseException) -> bool:
    return isinstance(error, DatabaseError) or type(error).__module__.split(".")[0] == "psycopg"


class ExecutiveOverviewService:
    """Reads the persisted canonical ExecutiveBrief for presentation. Never writes, never calls a model or Honcho."""

    def __init__(self, store: ReasoningStore, dashboard: DashboardService, *, scope: str = COMPANY_SCOPE) -> None:
        self.store = store
        self.dashboard = dashboard
        self.scope = scope

    def overview(self) -> Overview:
        try:
            return self._overview()
        except DashboardUnavailable:
            return Overview("unavailable")
        except Exception as error:
            # A database failure, or a stored brief that no longer satisfies its contract (``ContractViolation`` from
            # ``ExecutiveBrief.from_dict``): the overview is unavailable; the reasoning cards below must still render.
            if _db_error(error) or isinstance(error, ContractViolation):
                LOG.error("executive overview unavailable error=%s", type(error).__name__)
                return Overview("unavailable")
            raise

    def _overview(self) -> Overview:
        with self.store.transaction() as tx:
            tx.conn.execute("SET TRANSACTION READ ONLY")      # a page GET never writes
            brief = ExecutiveTransaction(tx.conn).current_brief(self.scope)
            if brief is None:
                return Overview("none")
            latest = sql.latest_synthesis_run(tx, self.scope)
            pinned = {row.result_id: row for row in brief.input_results}
            titles = sql.pinned_titles(tx, [(row.result_id, row.result_version) for row in brief.input_results
                                            if row.result_id in set(brief.referenced_result_ids)])
        states = self.dashboard.result_states(list(brief.referenced_result_ids)) if brief.referenced_result_ids else {}
        failed = bool(latest and latest["decision"] == "failed" and latest["brief_id"] == brief.brief_id and latest["brief_version"] == brief.version)
        sections = []
        for name in SECTIONS:
            rows = tuple(self._statement(name, statement, pinned, titles, states) for statement in getattr(brief.sections, name))
            if rows:
                sections.append((name, rows))
        return Overview("brief", brief, tuple(sections), failed)

    @staticmethod
    def _statement(section: str, statement: Any, pinned: dict[str, Any], titles: dict[tuple[str, int], str],
                   states: dict[str, dict[str, Any]]) -> StatementView:
        cited = []
        for result_id in statement.result_ids:
            row = pinned.get(result_id)
            state = states.get(result_id) or {}
            version = row.result_version if row is not None else None
            cited.append(CitedResult(result_id, version, row.lifecycle_status.value if row is not None else None,
                                     titles.get((result_id, version), "") if version is not None else "", bool(state.get("exists")),
                                     state.get("current_version"), state.get("lifecycle_status"), state.get("superseded_by")))
        return StatementView(statement.statement_id, section, statement.text, statement.editor_id if section == EDITOR_SECTION else None, tuple(cited))


def overview_or_none(service: ExecutiveOverviewService | None) -> Overview | None:
    """``None`` when the web application runs without an executive reader (Phase 16 behaviour unchanged)."""
    return service.overview() if service is not None else None

