"""Read-only SQL for the executive overview (Phase 17 UI). Bounded reads of canonical rows; nothing here writes.

The current brief itself is read through ``store.executive.ExecutiveTransaction.current_brief`` (the Phase 17 core interface); these are
the two small reads the presentation needs beside it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from atlas_reasoning.store.repository import StoreTransaction


def latest_synthesis_run(tx: StoreTransaction, scope: str) -> dict[str, Any] | None:
    """The most recent executive synthesis run of ``scope`` that is not a lost version conflict (a conflict means another writer produced the
    current brief): its decision, the class of its failure (the part before ``:``; never the detail, never a refused candidate) and the
    brief version current after it."""
    return tx._one("""SELECT decision, split_part(coalesce(failure, ''), ':', 1) AS failure_class, brief_id, brief_version, created_at
                      FROM executive_brief_runs WHERE scope = %s AND coalesce(failure, '') NOT LIKE 'conflict:%%'
                      ORDER BY created_at DESC, synthesis_id DESC LIMIT 1""", (scope,))


def pinned_titles(tx: StoreTransaction, pairs: Sequence[tuple[str, int]]) -> dict[tuple[str, int], str]:
    """The stored title of each (result_id, version) a brief synthesized from: one query, bounded by the brief's input."""
    if not pairs:
        return {}
    rows = tx._all("""SELECT v.result_id, v.version, v.document ->> 'title' AS title
                      FROM reasoning_result_versions v
                      JOIN unnest(%s::text[], %s::integer[]) AS pinned (result_id, version) USING (result_id, version)""",
                   ([pair[0] for pair in pairs], [pair[1] for pair in pairs]))
    return {(row["result_id"], row["version"]): str(row["title"] or "") for row in rows}
