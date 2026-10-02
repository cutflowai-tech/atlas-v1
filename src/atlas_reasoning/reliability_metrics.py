"""Reasoning reliability telemetry (``REV/18`` #8): deterministic, content-free metrics of what a reasoning run cost and how it went.

    report = store.reliability_metrics.reliability_report(store, [run_id])   # reads canonical rows
    report.to_dict()                                                       # stable, machine-readable, key-sorted JSON

Every number is **derived from canonical rows** that earlier phases already write — nothing is copied into an aggregate table:

==========================  ==================================================================================================
``llm_calls``               provider calls: logical calls (one row per gateway call) vs provider attempts, retries, tokens,
                            latency, failures by error class, per purpose (``analyst``, ``update``, ``review``, ``executive``)
``reasoning_work_items``    LLM work of the run by status (pending, in progress, done, failed, ...), failures by class (the part
                            of ``last_error`` before ``:``), work closed without a model call
``reasoning_result_versions``  successful new results (``created``), updates (``patched``) and no-change reviews of the run
``reasoning_failed_candidates``  refused candidates (Phase 15), their stable validation codes, corrective re-asks
``reasoning_case_observations``  the Change Gate's decisions: ``unchanged`` cases are the zero-call skips
``executive_brief_runs``    executive synthesis runs by decision; ``unchanged`` is the zero-call preserve
``memory_injections``       contextual memory status of each reasoning call (``degraded`` / ``unavailable`` = memory degraded)
==========================  ==================================================================================================

Attribution: work, results, refusals and reasoning calls belong to the run whose Change Gate **created the work item** (the engine
passes ``item.run_id`` to every call), even when a later ``process_run`` processed it; executive rows belong to the run passed to
``ExecutiveSynthesizer.synthesize``.

What this module never does:

- read or report prompts, responses, candidates, violations' messages, notes, memory text, credentials or hidden reasoning — the
  store reads only identifiers, statuses, counts, codes and timings;
- decide a run's status. ``StatusInputs`` exposes the facts a status policy needs (Phase 18-A owns complete / partial / degraded /
  failed); nothing here writes ``reasoning_runs.status``;
- become part of a ``ReasoningResult``: telemetry is operational, never reasoning truth.

Determinism: no clock, no randomness; every mapping is emitted key-sorted, runs are ordered by ``(started_at, run_id)``, latency
statistics are integers (floor mean, nearest-rank percentiles). The same rows always give the same report, byte for byte.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

METRICS_VERSION = "reliability-metrics-v1"
REASONING_PURPOSES = ("analyst", "update")        # the engine's own calls; a work item's calls beyond its first are corrective re-asks
DEGRADED_MEMORY = ("degraded", "unavailable")
OPEN_WORK = ("pending", "in_progress")
KNOWN_WORK_STATUSES = ("pending", "in_progress", "done", "failed", "superseded", "cancelled")
EXECUTIVE_DECISIONS = ("synthesized", "synthesized_empty", "unchanged", "failed")
GATE_ACTIONS = ("unchanged", "new", "updated", "disappeared")


def _counts(values: Iterable[str | None]) -> tuple[tuple[str, int], ...]:
    """Key-sorted ``(key, count)`` pairs (hashable, deterministic); ``None`` keys are ``"unknown"``."""
    counter = Counter(value if value else "unknown" for value in values)
    return tuple(sorted(counter.items()))


def _merge(*pairs: Iterable[tuple[str, int]]) -> tuple[tuple[str, int], ...]:
    counter: Counter[str] = Counter()
    for items in pairs:
        for key, count in items:
            counter[key] += count
    return tuple(sorted(counter.items()))


def _count(pairs: Sequence[tuple[str, int]], key: str) -> int:
    return next((count for name, count in pairs if name == key), 0)


def _nearest_rank(ordered: Sequence[int], percent: int) -> int:
    return ordered[max(0, math.ceil(percent / 100 * len(ordered)) - 1)]


# --- rows (what the store reads; content-free by construction) ---------------------------------------------------------------


@dataclass(frozen=True)
class RunRows:
    """The canonical rows of one run (or, merged, of several) that the metrics are computed from. Only identifiers, statuses,
    codes, counts and timings: see ``store.reliability_metrics`` for the exact columns."""

    run: Mapping[str, Any] | None = None                       # run_id, status, started_at, gated_at, finished_at, wall_ms
    calls: tuple[Mapping[str, Any], ...] = ()                  # one per llm_calls row
    work: tuple[Mapping[str, Any], ...] = ()                   # one per work item: kind, status, requires_llm, error_class, has_call
    observations: tuple[tuple[str, int], ...] = ()             # gate action -> cases
    versions: tuple[tuple[str, int], ...] = ()                 # change_kind -> result versions written for the run's work
    refusals: tuple[Mapping[str, Any], ...] = ()               # one per refused candidate: work_item_id, purpose, attempt, error_codes
    executive: tuple[Mapping[str, Any], ...] = ()              # one per executive_brief_runs row: decision, failure_class, llm_calls
    memory: tuple[tuple[str, int], ...] = ()                   # memory_status -> injected calls

    @staticmethod
    def merged(parts: Iterable[RunRows]) -> RunRows:
        """Several runs' rows as one (no run identity): the aggregate is computed from the union, never from per-run summaries,
        so percentiles stay exact."""
        items = list(parts)
        return RunRows(None, tuple(row for part in items for row in part.calls), tuple(row for part in items for row in part.work),
                       _merge(*(part.observations for part in items)), _merge(*(part.versions for part in items)),
                       tuple(row for part in items for row in part.refusals), tuple(row for part in items for row in part.executive),
                       _merge(*(part.memory for part in items)))


# --- metrics -----------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LatencyMetrics:
    """Gateway latency of logical calls (all attempts and backoff of a call), in milliseconds. ``None`` statistics: no calls."""

    total_ms: int = 0
    max_ms: int | None = None
    mean_ms: int | None = None
    p50_ms: int | None = None
    p95_ms: int | None = None

    @staticmethod
    def of(values: Iterable[int]) -> LatencyMetrics:
        ordered = sorted(int(value) for value in values)
        if not ordered:
            return LatencyMetrics()
        total = sum(ordered)
        return LatencyMetrics(total, ordered[-1], total // len(ordered), _nearest_rank(ordered, 50), _nearest_rank(ordered, 95))

    def to_dict(self) -> dict[str, Any]:
        return {"total_ms": self.total_ms, "max_ms": self.max_ms, "mean_ms": self.mean_ms, "p50_ms": self.p50_ms, "p95_ms": self.p95_ms}


@dataclass(frozen=True)
class CallMetrics:
    """Provider calls. ``logical_calls`` = gateway calls (``llm_calls`` rows); ``attempts`` = provider attempts across them;
    ``retries`` = attempts beyond the first of each call (the gateway's bounded retries); ``retried_calls`` = calls that needed any."""

    logical_calls: int = 0
    attempts: int = 0
    retries: int = 0
    retried_calls: int = 0
    succeeded: int = 0
    failed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    calls_without_usage: int = 0                               # calls whose token usage is unknown (failed calls, or not reported)
    latency: LatencyMetrics = field(default_factory=LatencyMetrics)
    failures_by_class: tuple[tuple[str, int], ...] = ()

    @staticmethod
    def of(rows: Sequence[Mapping[str, Any]]) -> CallMetrics:
        attempts = [int(row["attempts"]) for row in rows]
        failed = [row for row in rows if row["status"] == "failed"]
        return CallMetrics(
            logical_calls=len(rows), attempts=sum(attempts), retries=sum(value - 1 for value in attempts),
            retried_calls=sum(1 for value in attempts if value > 1), succeeded=len(rows) - len(failed), failed=len(failed),
            input_tokens=sum(int(row["input_tokens"] or 0) for row in rows), output_tokens=sum(int(row["output_tokens"] or 0) for row in rows),
            calls_without_usage=sum(1 for row in rows if row["input_tokens"] is None and row["output_tokens"] is None),
            latency=LatencyMetrics.of(int(row["latency_ms"]) for row in rows), failures_by_class=_counts(row["error_class"] for row in failed))

    def to_dict(self) -> dict[str, Any]:
        return {"logical_calls": self.logical_calls, "attempts": self.attempts, "retries": self.retries, "retried_calls": self.retried_calls,
                "succeeded": self.succeeded, "failed": self.failed, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "total_tokens": self.input_tokens + self.output_tokens, "calls_without_usage": self.calls_without_usage,
                "latency": self.latency.to_dict(), "failures_by_class": dict(self.failures_by_class)}


@dataclass(frozen=True)
class ProviderMetrics:
    """All provider calls of the run, and the same split by purpose (purposes in name order)."""

    total: CallMetrics = field(default_factory=CallMetrics)
    by_purpose: tuple[tuple[str, CallMetrics], ...] = ()

    @staticmethod
    def of(rows: Sequence[Mapping[str, Any]]) -> ProviderMetrics:
        purposes = sorted({str(row["purpose"]) for row in rows})
        return ProviderMetrics(CallMetrics.of(rows), tuple((purpose, CallMetrics.of([row for row in rows if row["purpose"] == purpose]))
                                                           for purpose in purposes))

    def purpose(self, name: str) -> CallMetrics:
        return next((metrics for purpose, metrics in self.by_purpose if purpose == name), CallMetrics())

    def to_dict(self) -> dict[str, Any]:
        return {"total": self.total.to_dict(), "by_purpose": {purpose: metrics.to_dict() for purpose, metrics in self.by_purpose}}


@dataclass(frozen=True)
class WorkMetrics:
    """The run's LLM work items and what became of them. ``open`` = pending + in progress (not yet reasoned: deferred, interrupted
    or waiting); ``closed_without_call`` = done with no model call (the evidence already was the open result's, or the case
    disappeared); ``new_results`` / ``updates`` / ``no_change_reviews`` = result versions committed for the run's work."""

    llm_work_items: int = 0
    lifecycle_work_items: int = 0
    by_status: tuple[tuple[str, int], ...] = ()
    open: int = 0
    done: int = 0
    failed: int = 0
    closed_without_call: int = 0
    new_results: int = 0
    updates: int = 0
    no_change_reviews: int = 0
    failures_by_class: tuple[tuple[str, int], ...] = ()

    @staticmethod
    def of(work: Sequence[Mapping[str, Any]], versions: Sequence[tuple[str, int]]) -> WorkMetrics:
        llm = [row for row in work if row["requires_llm"]]
        by_status = _counts(str(row["status"]) for row in llm)
        failed = [row for row in llm if row["status"] == "failed"]
        return WorkMetrics(
            llm_work_items=len(llm), lifecycle_work_items=len(work) - len(llm), by_status=by_status,
            open=sum(_count(by_status, status) for status in OPEN_WORK), done=_count(by_status, "done"), failed=len(failed),
            closed_without_call=sum(1 for row in llm if row["status"] == "done" and not row["has_call"]),
            new_results=_count(versions, "created"), updates=_count(versions, "patched"), no_change_reviews=_count(versions, "no_change_review"),
            failures_by_class=_counts(row["error_class"] for row in failed))

    def to_dict(self) -> dict[str, Any]:
        statuses = {status: 0 for status in KNOWN_WORK_STATUSES} | dict(self.by_status)
        return {"llm_work_items": self.llm_work_items, "lifecycle_work_items": self.lifecycle_work_items, "by_status": statuses, "open": self.open,
                "done": self.done, "failed": self.failed, "closed_without_call": self.closed_without_call, "new_results": self.new_results,
                "updates": self.updates, "no_change_reviews": self.no_change_reviews, "failures_by_class": dict(self.failures_by_class)}


@dataclass(frozen=True)
class ValidationMetrics:
    """Phase 15 guardrail outcomes. ``refused_candidates`` = candidates refused (each attempt); ``corrective_reasks`` = model calls
    made again for a work item after a refusal; ``failed_work_items`` = work that ended ``validation:<codes>``."""

    refused_candidates: int = 0
    corrective_reasks: int = 0
    failed_work_items: int = 0
    codes: tuple[tuple[str, int], ...] = ()

    @staticmethod
    def of(refusals: Sequence[Mapping[str, Any]], calls: Sequence[Mapping[str, Any]], work: Sequence[Mapping[str, Any]]) -> ValidationMetrics:
        per_item = Counter(row["work_item_id"] for row in calls if row["purpose"] in REASONING_PURPOSES and row["work_item_id"])
        return ValidationMetrics(
            refused_candidates=len(refusals), corrective_reasks=sum(count - 1 for count in per_item.values()),
            failed_work_items=sum(1 for row in work if row["requires_llm"] and row["status"] == "failed" and row["error_class"] == "validation"),
            codes=_counts(code for row in refusals for code in row["error_codes"]))

    def to_dict(self) -> dict[str, Any]:
        return {"refused_candidates": self.refused_candidates, "corrective_reasks": self.corrective_reasks,
                "failed_work_items": self.failed_work_items, "codes": dict(self.codes)}


@dataclass(frozen=True)
class GateMetrics:
    """The Change Gate's decisions for the run's cases. ``unchanged`` cases are skipped with zero LLM work."""

    by_action: tuple[tuple[str, int], ...] = ()

    @property
    def unchanged(self) -> int:
        return _count(self.by_action, "unchanged")

    def to_dict(self) -> dict[str, Any]:
        actions = {action: 0 for action in GATE_ACTIONS} | dict(self.by_action)
        return {"observed_cases": sum(actions.values()), "skipped_unchanged": actions["unchanged"], "by_action": actions}


@dataclass(frozen=True)
class ExecutiveMetrics:
    """Executive synthesis runs (Phase 17). ``model_calls`` = calls the synthesizer reported (re-asks included); ``unchanged_zero_call``
    = runs whose input equalled the current brief and preserved it without a model call."""

    synthesis_runs: int = 0
    by_decision: tuple[tuple[str, int], ...] = ()
    model_calls: int = 0
    unchanged_zero_call: int = 0
    failures_by_class: tuple[tuple[str, int], ...] = ()

    @staticmethod
    def of(rows: Sequence[Mapping[str, Any]]) -> ExecutiveMetrics:
        return ExecutiveMetrics(len(rows), _counts(str(row["decision"]) for row in rows), sum(int(row["llm_calls"]) for row in rows),
                                sum(1 for row in rows if row["decision"] == "unchanged" and int(row["llm_calls"]) == 0),
                                _counts(row["failure_class"] for row in rows if row["decision"] == "failed"))

    def to_dict(self) -> dict[str, Any]:
        decisions = {decision: 0 for decision in EXECUTIVE_DECISIONS} | dict(self.by_decision)
        return {"synthesis_runs": self.synthesis_runs, "by_decision": decisions, "model_calls": self.model_calls,
                "unchanged_zero_call": self.unchanged_zero_call, "failures_by_class": dict(self.failures_by_class)}


@dataclass(frozen=True)
class MemoryMetrics:
    """Contextual memory of the run's reasoning calls (``memory_injections``; one per injected call). ``degraded_calls`` = calls whose
    memory was degraded or unavailable (canonical context was still used)."""

    by_status: tuple[tuple[str, int], ...] = ()

    @property
    def injected_calls(self) -> int:
        return sum(count for _, count in self.by_status)

    @property
    def degraded_calls(self) -> int:
        return sum(_count(self.by_status, status) for status in DEGRADED_MEMORY)

    def to_dict(self) -> dict[str, Any]:
        return {"injected_calls": self.injected_calls, "degraded_calls": self.degraded_calls, "degraded": self.degraded_calls > 0,
                "by_status": dict(self.by_status)}


@dataclass(frozen=True)
class StatusInputs:
    """Facts a run-status policy needs (Phase 18-A decides complete / partial / degraded / failed; nothing here does). Counts are
    of the run's LLM work items unless named otherwise."""

    llm_work_items: int = 0
    open_work_items: int = 0
    done_work_items: int = 0
    failed_work_items: int = 0
    provider_failed_work_items: int = 0
    validation_failed_work_items: int = 0
    other_failed_work_items: int = 0
    committed_versions: int = 0                                # new results + updates + no-change reviews
    provider_failed_calls: int = 0
    executive_failed_runs: int = 0
    executive_ok_runs: int = 0
    memory_degraded_calls: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in sorted(self.__dataclass_fields__)}


@dataclass(frozen=True)
class RunMetrics:
    """The metrics of one run (``run`` set) or of several runs together (``run`` None: the aggregate)."""

    run: Mapping[str, Any] | None
    provider: ProviderMetrics
    work: WorkMetrics
    validation: ValidationMetrics
    gate: GateMetrics
    executive: ExecutiveMetrics
    memory: MemoryMetrics

    @staticmethod
    def of(rows: RunRows) -> RunMetrics:
        return RunMetrics(dict(rows.run) if rows.run is not None else None, ProviderMetrics.of(rows.calls), WorkMetrics.of(rows.work, rows.versions),
                          ValidationMetrics.of(rows.refusals, rows.calls, rows.work), GateMetrics(rows.observations),
                          ExecutiveMetrics.of(rows.executive), MemoryMetrics(rows.memory))

    @property
    def status_inputs(self) -> StatusInputs:
        work, failures = self.work, dict(self.work.failures_by_class)
        provider_failed, validation_failed = failures.get("provider", 0), failures.get("validation", 0)
        decisions = dict(self.executive.by_decision)
        return StatusInputs(
            llm_work_items=work.llm_work_items, open_work_items=work.open, done_work_items=work.done, failed_work_items=work.failed,
            provider_failed_work_items=provider_failed, validation_failed_work_items=validation_failed,
            other_failed_work_items=work.failed - provider_failed - validation_failed,
            committed_versions=work.new_results + work.updates + work.no_change_reviews, provider_failed_calls=self.provider.total.failed,
            executive_failed_runs=decisions.get("failed", 0), executive_ok_runs=self.executive.synthesis_runs - decisions.get("failed", 0),
            memory_degraded_calls=self.memory.degraded_calls)

    def to_dict(self) -> dict[str, Any]:
        return {"run": dict(self.run) if self.run is not None else None, "provider_calls": self.provider.to_dict(), "work": self.work.to_dict(),
                "validation": self.validation.to_dict(), "gate": self.gate.to_dict(), "executive": self.executive.to_dict(),
                "memory": self.memory.to_dict(), "status_inputs": self.status_inputs.to_dict()}


@dataclass(frozen=True)
class Backlog:
    """Open reasoning work at read time, across every run: LLM work items still pending or in progress, and present cases whose open
    result is not on their current evidence and that have no open work (the resume candidates of ``unreasoned_cases``)."""

    open_by_status: tuple[tuple[str, int], ...] = ()
    unreasoned_cases: int = 0

    def to_dict(self) -> dict[str, Any]:
        statuses = {status: 0 for status in OPEN_WORK} | dict(self.open_by_status)
        return {"open_llm_work_items": sum(statuses.values()), "open_by_status": statuses, "unreasoned_cases": self.unreasoned_cases}


@dataclass(frozen=True)
class ReliabilityReport:
    """Per-run metrics in ``(started_at, run_id)`` order, their aggregate, and the backlog at read time."""

    runs: tuple[RunMetrics, ...]
    aggregate: RunMetrics
    backlog: Backlog = field(default_factory=Backlog)
    metrics_version: str = METRICS_VERSION

    def run(self, run_id: str) -> RunMetrics:
        return next(metrics for metrics in self.runs if metrics.run is not None and metrics.run["run_id"] == run_id)

    def to_dict(self) -> dict[str, Any]:
        return {"metrics_version": self.metrics_version, "run_ids": [metrics.run["run_id"] for metrics in self.runs if metrics.run is not None],
                "runs": [metrics.to_dict() for metrics in self.runs], "aggregate": self.aggregate.to_dict(), "backlog": self.backlog.to_dict()}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _run_order(rows: RunRows) -> tuple[str, str]:
    run = rows.run or {}
    return (str(run.get("started_at") or ""), str(run.get("run_id") or ""))


def build_report(per_run: Iterable[RunRows], backlog: Backlog | None = None) -> ReliabilityReport:
    """The report from each run's rows. Pure: the same rows give the same report, whatever order they come in."""
    ordered = sorted(per_run, key=_run_order)
    return ReliabilityReport(tuple(RunMetrics.of(rows) for rows in ordered), RunMetrics.of(RunRows.merged(ordered)), backlog or Backlog())
