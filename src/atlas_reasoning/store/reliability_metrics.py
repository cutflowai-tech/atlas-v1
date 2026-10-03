"""Read-only SQL for reasoning reliability telemetry (``atlas_reasoning.reliability_metrics``). Nothing here writes.

Every query names its columns: identifiers, statuses, codes, counts and timings only. Never a prompt, a response, a candidate, a
violation message, a note, memory text or a credential; of ``last_error`` and ``failure`` only the class before the first ``:`` is
read. A report reads in **one** ``REPEATABLE READ READ ONLY`` transaction, so its numbers come from a single consistent snapshot.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from atlas_reasoning.reliability_metrics import Backlog, ReliabilityReport, RunRows, build_report
from atlas_reasoning.store.repository import NotFound, ReasoningStore, StoreTransaction
from atlas_reasoning.store.run_control import REFUSALS


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def _pairs(rows: Sequence[dict[str, Any]], key: str) -> tuple[tuple[str, int], ...]:
    return tuple(sorted((str(row[key]), int(row["n"])) for row in rows))


def run_row(tx: StoreTransaction, run_id: str) -> dict[str, Any]:
    row = tx._one("""SELECT run_id, status, started_at, gated_at, finished_at,
                            (extract(epoch FROM finished_at - started_at) * 1000)::bigint AS wall_ms
                     FROM reasoning_runs WHERE run_id = %s""", (run_id,))
    if row is None:
        raise NotFound(f"run {run_id} does not exist")
    return {key: _iso(value) for key, value in row.items()}


def run_rows(tx: StoreTransaction, run_id: str) -> RunRows:
    """Every canonical row the metrics of ``run_id`` are computed from (``RunRows``)."""
    run = run_row(tx, run_id)
    # ``pass_id``: the Phase 18-A orchestration pass whose time window holds the call (NULL outside any pass). Corrective re-asks are
    # counted per (work item, pass): a work item deferred by the budget and processed again in a later pass starts afresh.
    calls = tx._all("""SELECT c.request_id, c.work_item_id, c.purpose, c.status, c.error_class, c.attempts, c.latency_ms, c.input_tokens,
                              c.output_tokens, p.pass_id
                       FROM llm_calls c
                       LEFT JOIN LATERAL (SELECT pass_id FROM reasoning_run_passes p WHERE c.started_at >= p.started_at
                                            AND (p.finished_at IS NULL OR c.started_at <= p.finished_at)
                                          ORDER BY p.started_at DESC, p.pass_id DESC LIMIT 1) p ON true
                       WHERE c.run_id = %s ORDER BY c.started_at, c.call_id""", (run_id,))
    # ``refused``: failed because the Phase 18-B controls refused the call before any request (breaker / budget) — not a provider failure.
    work = tx._all("""SELECT w.work_item_id, w.kind, w.status, w.requires_llm,
                             CASE WHEN w.status = 'failed' THEN nullif(split_part(coalesce(w.last_error, ''), ':', 1), '') END AS error_class,
                             (w.status = 'failed' AND w.last_error = ANY(%s)) AS refused,
                             EXISTS (SELECT 1 FROM llm_calls c WHERE c.work_item_id = w.work_item_id) AS has_call
                      FROM reasoning_work_items w WHERE w.run_id = %s ORDER BY w.created_at, w.work_item_id""", (list(REFUSALS), run_id))
    observations = tx._all("SELECT action, count(*) AS n FROM reasoning_case_observations WHERE run_id = %s GROUP BY action", (run_id,))
    # Versions written for the run's own work (an engine run may process older work: it counts for the run that created the item).
    versions = tx._all("""SELECT v.change_kind, count(*) AS n FROM reasoning_result_versions v
                          JOIN reasoning_work_items w ON w.work_item_id = v.work_item_id
                          WHERE w.run_id = %s GROUP BY v.change_kind""", (run_id,))
    refusals = tx._all("""SELECT f.work_item_id, f.purpose, f.attempt, f.error_codes FROM reasoning_failed_candidates f
                          WHERE f.run_id = %s ORDER BY f.created_at, f.candidate_id""", (run_id,))
    executive = tx._all("""SELECT decision, nullif(split_part(coalesce(failure, ''), ':', 1), '') AS failure_class, llm_calls
                           FROM executive_brief_runs WHERE run_id = %s ORDER BY created_at, synthesis_id""", (run_id,))
    memory = tx._all("SELECT memory_status, count(*) AS n FROM memory_injections WHERE run_id = %s GROUP BY memory_status", (run_id,))
    # Phase 18-A orchestration: the run's passes (budget, calls, admission, status reasons; counters only) and the retries of its work.
    passes = tx._all("""SELECT kind, call_budget, calls_used, admitted, deferred, retries, run_status, reasons, outcome
                        FROM reasoning_run_passes WHERE run_id = %s ORDER BY started_at, pass_id""", (run_id,))
    retries = tx._all("""SELECT split_part(r.failure, ':', 1) AS failure_class, r.attempt FROM reasoning_work_retries r
                         JOIN reasoning_work_items w ON w.work_item_id = r.retry_work_item_id WHERE w.run_id = %s
                         ORDER BY r.created_at, r.retry_work_item_id""", (run_id,))
    return RunRows(run, tuple(calls), tuple(work), _pairs(observations, "action"), _pairs(versions, "change_kind"),
                   tuple({**row, "error_codes": tuple(row["error_codes"])} for row in refusals), tuple(executive), _pairs(memory, "memory_status"),
                   tuple({**row, "reasons": tuple(row["reasons"])} for row in passes), tuple(retries))


def backlog(tx: StoreTransaction) -> Backlog:
    rows = tx._all("""SELECT status, count(*) AS n FROM reasoning_work_items WHERE requires_llm AND status IN ('pending', 'in_progress')
                      GROUP BY status""")
    return Backlog(_pairs(rows, "status"), len(tx.unreasoned_cases()))


def recent_run_ids(tx: StoreTransaction, limit: int) -> list[str]:
    """The ``limit`` most recently started runs, oldest first."""
    rows = tx._all("SELECT run_id FROM reasoning_runs ORDER BY started_at DESC, run_id DESC LIMIT %s", (int(limit),))
    return [row["run_id"] for row in reversed(rows)]


def reliability_report(store: ReasoningStore, run_ids: Sequence[str] | None = None, *, latest: int | None = None) -> ReliabilityReport:
    """The report of ``run_ids`` (each must exist), or of the ``latest`` runs, read from one consistent snapshot."""
    with store.transaction() as tx:
        tx._exec("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        ids = list(dict.fromkeys(run_ids)) if run_ids is not None else recent_run_ids(tx, latest or 1)
        return build_report([run_rows(tx, run_id) for run_id in ids], backlog(tx))
