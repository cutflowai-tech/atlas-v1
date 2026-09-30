"""Normalized evidence for Intelligence V2: project fact rows, item stage timelines and current open work.

Everything here is read from what the existing pipeline already built (``CycleReconstruction``, the contract's deadline
rule, the Quality occurrences). No metric is redefined:

- execution time is the cycle's first In Progress -> first Ready For Approval (D2, D3);
- the deadline result comes from ``metrics.deadline_result`` (D5, D19);
- the Video Type cohort is the cycle's (D8, D14);
- the Editor is the cycle's (D48-D51); the shared Waset Co actor is never read.

New, clearly bounded derivations (each documented in ``docs/INTELLIGENCE-V2.md``):

- **Stage timeline.** Each accepted status event opens a visit that the item's next accepted event closes. The last visit is
  open (right-censored) and never measured. A visit containing a quarantined status log (an unknown or cleared status) is
  marked invalid and never assigned to a stage: stage boundaries are never invented.
- **Execution runway.** ``selected Requested ETA - first In Progress``, with the D19 ETA. It is flagged when that ETA was
  first observed after work started.
- **Concurrent workload at start.** The number of the same Editor's *other* attributed completed first cycles whose
  interval contains this project's In Progress moment. It is a lower bound: open, unattributed and rework work is not
  visible.
- **Post-editor delivery.** The first delivered-phase status (``Sent`` / ``Done``) after the first Ready For Approval.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from atlas_commander.cycles import COMPLETED, CyclePolicy, CycleRecord, parse_time
from atlas_commander.intelligence import CAIRO, CompletedDayWindows, window_assignment
from atlas_commander.investigation.models import EvidenceRecord
from atlas_commander.metrics import MetricPolicy, cohort_benchmark_eligibility, deadline_result, speed_eligible
from atlas_commander.monday_source import dropdown_value_ids, dropdown_value_labels, requested_eta
from atlas_commander.pipeline import CycleReconstruction
from atlas_commander.profile import ACTIVE_WORK_STATUSES, AWAITING_APPROVAL_STATUS, _current_editor
from atlas_commander.quality import QualityResult
from atlas_commander.video_type import resolve_video_type

START, END = "In Progress", "Ready For Approval"
DELIVERED_PHASE = "delivered"
PRE_EDITOR, EDITOR_PHASE, POST_EDITOR, NO_CYCLE = "pre_editor", "editor", "post_editor", "no_cycle"
# Quarantine reasons that cannot hide a stage boundary (same set the cycle builder treats as harmless).
_HARMLESS_QUARANTINE = frozenset({"DUPLICATE_EVENT_ID"})
UNKNOWN_STATUS_WITHIN_VISIT = "unknown_or_cleared_status_within_visit"
OPEN_VISIT = "open_visit_right_censored"


def _t(value: str | None) -> datetime | None:
    return parse_time(value) if value else None


def _seconds(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    return int((parse_time(end) - parse_time(start)).total_seconds())


@dataclass(frozen=True)
class StageVisit:
    status: str
    entered_at: str
    left_at: str | None
    enter_event_id: str
    leave_event_id: str | None
    phase: str
    invalid_reason: str | None = None

    @property
    def duration_seconds(self) -> int | None:
        return None if self.invalid_reason or self.left_at is None else _seconds(self.entered_at, self.left_at)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "entered_at": self.entered_at, "left_at": self.left_at, "enter_event_id": self.enter_event_id,
                "leave_event_id": self.leave_event_id, "phase": self.phase, "duration_seconds": self.duration_seconds,
                "invalid_reason": self.invalid_reason}


@dataclass(frozen=True)
class ItemTimeline:
    monday_item_id: str
    visits: tuple[StageVisit, ...]
    duplicate_transitions: int
    discontinuous_transitions: int
    quarantined_logs: int

    def first(self, status: str, after: str | None = None) -> StageVisit | None:
        moment = _t(after)
        return next((visit for visit in self.visits if visit.status == status and (moment is None or parse_time(visit.entered_at) >= moment)), None)

    def after(self, moment: str) -> list[StageVisit]:
        at = parse_time(moment)
        return [visit for visit in self.visits if parse_time(visit.entered_at) > at]


@dataclass(frozen=True)
class LabelFact:
    label: str
    label_class: str
    scored: bool
    event_ids: tuple[str, ...]
    source_timestamps: tuple[str, ...]


@dataclass
class ProjectFact:
    """One completed first cycle with everything an Intelligence V2 detector may read about it."""

    monday_item_id: str
    cycle_id: str
    board_id: str
    editor_id: str | None
    cohort_key: str | None
    cohort_labels: tuple[str, ...]
    benchmark_eligible: bool
    in_progress_at: str
    ready_for_approval_at: str
    duration_seconds: int
    event_ids: Mapping[str, str | None]
    exclusions: tuple[str, ...]
    flags: tuple[str, ...]
    requested_eta: str | None
    requested_eta_issue: str | None
    requested_eta_observed_at: str | None
    requested_eta_at_start: str | None
    deadline_result: str | None
    deadline_delta_seconds: int | None
    window: str
    cairo_date: str
    cairo_month: str
    cairo_weekday: int
    labels: tuple[LabelFact, ...] = ()
    client_revisions: int = 0
    internal_revisions: int = 0
    revision_event_ids: tuple[str, ...] = ()
    concurrency_at_start: int | None = None
    concurrent_item_ids: tuple[str, ...] = ()
    created_at: str | None = None
    assigned_at: str | None = None
    review_wait_seconds: int | None = None
    delivered_at: str | None = None
    delivered_event_id: str | None = None

    @property
    def attributed(self) -> bool:
        return self.editor_id is not None

    @property
    def runway_seconds(self) -> int | None:
        return _seconds(self.in_progress_at, self.requested_eta) if self.requested_eta else None

    @property
    def eta_observed_after_start(self) -> bool:
        return bool(self.requested_eta_observed_at and parse_time(self.requested_eta_observed_at) > parse_time(self.in_progress_at))

    @property
    def late(self) -> bool | None:
        return None if self.deadline_result is None else self.deadline_result == "late"

    @property
    def deadline_classifiable(self) -> bool:
        return self.deadline_result is not None

    @property
    def speed_measurable(self) -> bool:
        """First-pass execution time that the approved Speed rules may compare (benchmark-eligible exact Video Type)."""
        return self.benchmark_eligible

    @property
    def negative_scored(self) -> tuple[LabelFact, ...]:
        return tuple(label for label in self.labels if label.label_class == "Negative" and label.scored)

    @property
    def positive_scored(self) -> tuple[LabelFact, ...]:
        return tuple(label for label in self.labels if label.label_class == "Positive" and label.scored)

    @property
    def delivered_after_eta(self) -> bool | None:
        if not self.delivered_at or not self.requested_eta:
            return None
        return parse_time(self.delivered_at) > parse_time(self.requested_eta)

    def record(self, *keys: str, extra: Mapping[str, Any] | None = None, label_events: bool = False) -> EvidenceRecord:
        """Evidence for this project: its status events (and ETA / Editor / Video Type / label events) plus the values used."""
        ids = [value for value in (self.event_ids.get("in_progress"), self.event_ids.get("ready_for_approval")) if value]
        for name in ("requested_eta", "editor", "video_type"):
            value = self.event_ids.get(name)
            if value and (name != "requested_eta" or "requested_eta" in keys or "runway_seconds" in keys or "deadline_result" in keys):
                ids.append(value)
        timestamps = [self.in_progress_at, self.ready_for_approval_at]
        if label_events:
            for label in self.labels:
                ids.extend(label.event_ids)
                timestamps.extend(label.source_timestamps)
        if "delivered_at" in keys and self.delivered_event_id:
            ids.append(self.delivered_event_id)
            if self.delivered_at:
                timestamps.append(self.delivered_at)
        values: dict[str, Any] = {}
        for key in keys:
            value = getattr(self, key)
            values[key] = [label.label for label in value] if key in ("labels", "negative_scored", "positive_scored") else value
        values.update(extra or {})
        return EvidenceRecord(self.monday_item_id, self.cycle_id, tuple(dict.fromkeys(ids)), tuple(dict.fromkeys(t for t in timestamps if t)),
                              values, self.editor_id, self.cohort_key)


@dataclass(frozen=True)
class OpenWork:
    """A project that currently needs action (D33 Active Work) or awaits approval, from the current Monday snapshot."""

    monday_item_id: str
    current_status: str
    status_entered_at: str | None
    status_event_id: str | None
    current_editor_id: str | None
    cohort_key: str | None
    benchmark_eligible: bool
    first_in_progress_at: str | None
    first_in_progress_event_id: str | None
    requested_eta: str | None
    requested_eta_issue: str | None
    snapshot_evidence_ids: tuple[str, ...]
    retrieved_at: str

    @property
    def active(self) -> bool:
        return self.current_status in ACTIVE_WORK_STATUSES

    def record(self, extra: Mapping[str, Any] | None = None) -> EvidenceRecord:
        ids = [value for value in (self.first_in_progress_event_id, self.status_event_id, *self.snapshot_evidence_ids) if value]
        timestamps = [value for value in (self.first_in_progress_at, self.status_entered_at, self.retrieved_at) if value]
        values = {"current_status": self.current_status, "status_entered_at": self.status_entered_at, "first_in_progress_at": self.first_in_progress_at,
                  "requested_eta": self.requested_eta, "requested_eta_issue": self.requested_eta_issue, "retrieved_at": self.retrieved_at,
                  **(extra or {})}
        return EvidenceRecord(self.monday_item_id, None, tuple(dict.fromkeys(ids)), tuple(dict.fromkeys(timestamps)), values,
                              self.current_editor_id, self.cohort_key)


@dataclass
class FactBase:
    """Everything detectors read, built once per run."""

    projects: list[ProjectFact]
    timelines: dict[str, ItemTimeline]
    open_work: list[OpenWork]
    windows: CompletedDayWindows
    retrieved_at: str | None
    board_id: str
    column_ids: Mapping[str, str]
    editor_names: Mapping[str, str]
    coverage: dict[str, Any] = field(default_factory=dict)

    @property
    def attributed(self) -> list[ProjectFact]:
        return [project for project in self.projects if project.attributed]

    def editors(self) -> list[str]:
        return sorted({project.editor_id for project in self.projects if project.editor_id})


# --------------------------------------------------------------------------------------------------- timelines

def _quarantine_times(entries: Iterable[Mapping[str, Any]]) -> list[datetime]:
    times = []
    for entry in entries:
        if entry.get("reason") in _HARMLESS_QUARANTINE:
            continue
        source = entry.get("raw_source")
        moment = source.get("occurred_at") if isinstance(source, Mapping) else None
        if isinstance(moment, str):
            times.append(parse_time(moment))
    return sorted(times)


def item_timeline(item_id: str, events: Sequence[Mapping[str, Any]], quarantined: Sequence[Mapping[str, Any]],
                  undo_ids: frozenset[str] = frozenset()) -> ItemTimeline:
    """Stage visits of one item from its accepted status events; boundaries come only from Monday events."""
    ordered = sorted((event for event in events if str(event["event_id"]) not in undo_ids), key=lambda e: (parse_time(e["occurred_at"]), str(e["event_id"])))
    timeline: list[Mapping[str, Any]] = []
    duplicates = discontinuous = 0
    for event in ordered:
        if timeline and timeline[-1]["to_status"] == event["to_status"]:
            duplicates += 1
            continue
        if timeline and event.get("from_status") is not None and event["from_status"] != timeline[-1]["to_status"]:
            discontinuous += 1
        timeline.append(event)
    blocked = _quarantine_times(quarantined)
    start = next((event for event in timeline if event["to_status"] == START), None)
    end = next((event for event in timeline if start is not None and event["to_status"] == END
                and _key(event) > _key(start)), None)
    visits = []
    for index, event in enumerate(timeline):
        following = timeline[index + 1] if index + 1 < len(timeline) else None
        entered, left = parse_time(event["occurred_at"]), parse_time(following["occurred_at"]) if following else None
        invalid = None
        if left is None:
            invalid = OPEN_VISIT
        elif any(entered <= moment <= left for moment in blocked):
            invalid = UNKNOWN_STATUS_WITHIN_VISIT
        if start is None:
            phase = NO_CYCLE
        elif _key(event) < _key(start):
            phase = PRE_EDITOR
        elif end is None or _key(event) < _key(end):
            phase = EDITOR_PHASE
        else:
            phase = POST_EDITOR
        visits.append(StageVisit(str(event["to_status"]), str(event["occurred_at"]), str(following["occurred_at"]) if following else None,
                                 str(event["event_id"]), str(following["event_id"]) if following else None, phase, invalid))
    return ItemTimeline(item_id, tuple(visits), duplicates, discontinuous, len(quarantined))


def _key(event: Mapping[str, Any]) -> tuple[datetime, str]:
    return (parse_time(event["occurred_at"]), str(event["event_id"]))


# --------------------------------------------------------------------------------------------------- projects

def _labels_by_item(quality: QualityResult) -> dict[str, list[LabelFact]]:
    by_item: dict[str, list[LabelFact]] = defaultdict(list)
    for metric in quality.occurrences:
        values = metric["evidence"]["source_values"]
        by_item[str(metric["evidence"]["monday_item_id"])].append(LabelFact(
            metric["performance_label"], values.get("label_class", "Negative"), bool(values.get("scoring_eligible", True)),
            tuple(str(value) for value in metric["evidence"].get("event_ids") or []),
            tuple(str(value) for value in metric["evidence"].get("source_timestamps") or [] if value)))
    return {item: sorted(labels, key=lambda label: (label.label, label.event_ids)) for item, labels in by_item.items()}


def _eta_at(cycle: CycleRecord, moment: str) -> str | None:
    """Latest valid timed Requested ETA observed at or before ``moment`` (context only; never a deadline input)."""
    at = parse_time(moment)
    best: tuple[datetime, str] | None = None
    for entry in cycle.requested_eta_history:
        observed = entry.get("occurred_at")
        eta = entry.get("requested_eta")
        if not observed or not eta:
            continue
        stamp = parse_time(observed)
        if stamp <= at and (best is None or stamp >= best[0]):
            best = (stamp, str(eta))
    return best[1] if best else None


def _creation_times(result: CycleReconstruction) -> dict[str, str]:
    created: dict[str, str] = {}
    for change in result.column_changes:
        if change.source == "create_pulse":
            current = created.get(change.item_id)
            if current is None or parse_time(change.occurred_at) < parse_time(current):
                created[change.item_id] = change.occurred_at
    return created


def build_facts(result: CycleReconstruction, contract: Mapping[str, Any], quality: QualityResult, windows: CompletedDayWindows,
                calculated_at: str) -> FactBase:
    """Project facts for every completed first cycle, stage timelines for every item and current open work."""
    metric_policy = MetricPolicy.from_contract(contract)
    board = contract["source_board"]
    # Undone status changes are ignored for timing, exactly as the cycle builder ignores them (the same activity-log IDs).
    undo_ids = frozenset(change.log_id for change in result.column_changes if change.column_id == board["status_column_id"] and change.is_undo_action)
    events_by_item: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for event in result.status_events:
        events_by_item[str(event["monday_item_id"])].append(event)
    quarantined_by_item: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for entry in result.quarantined_status_logs:
        raw_value = entry.get("raw_source")
        raw: Mapping[str, Any] = raw_value if isinstance(raw_value, Mapping) else {}
        data_value = raw.get("data")
        data: Mapping[str, Any] = data_value if isinstance(data_value, Mapping) else {}
        quarantined_by_item[str(data.get("pulse_id"))].append(entry)
    timelines = {item: item_timeline(item, events, quarantined_by_item.get(item, []), undo_ids) for item, events in sorted(events_by_item.items())}
    labels = _labels_by_item(quality)
    created = _creation_times(result)
    changes_by_id = {change.log_id: change for change in result.column_changes}
    names = {cycle.editor_id: str(cycle.editor.get("display_name")) for cycle in result.cycles if cycle.editor_id and cycle.editor}

    projects: list[ProjectFact] = []
    for cycle in sorted(result.cycles, key=lambda c: (c.ready_for_approval_at or "", c.monday_item_id)):
        if cycle.state != COMPLETED or cycle.duration_seconds is None or not cycle.in_progress_at or not cycle.ready_for_approval_at:
            continue
        deadline = deadline_result(cycle, metric_policy, calculated_at) if cycle.editor_id else None
        eligible = bool(speed_eligible(cycle) and cycle.video_type is not None
                        and cohort_benchmark_eligibility(cycle.video_type.canonical_ids, metric_policy.video_types)[0])
        local = parse_time(cycle.ready_for_approval_at).astimezone(CAIRO)
        timeline = timelines.get(cycle.monday_item_id)
        review_wait = delivered_at = delivered_id = None
        if timeline is not None:
            rfa_visit = next((visit for visit in timeline.visits if visit.enter_event_id == str((cycle.ready_for_approval_event or {}).get("event_id"))), None)
            if rfa_visit is not None and rfa_visit.invalid_reason is None:
                review_wait = rfa_visit.duration_seconds
            delivered = next((event for event in sorted(events_by_item[cycle.monday_item_id], key=_key)
                              if event.get("status_phase_to") == DELIVERED_PHASE and _key(event) > _key(cycle.ready_for_approval_event or {"occurred_at": cycle.ready_for_approval_at, "event_id": ""})), None)
            if delivered is not None:
                delivered_at, delivered_id = str(delivered["occurred_at"]), str(delivered["event_id"])
        editor_change = changes_by_id.get(cycle.editor_event_id or "")
        revision = cycle.revision_context or {}
        projects.append(ProjectFact(
            monday_item_id=cycle.monday_item_id, cycle_id=cycle.cycle_id, board_id=cycle.monday_board_id, editor_id=cycle.editor_id,
            cohort_key=cycle.cohort_key, cohort_labels=tuple(cycle.video_type.canonical_labels) if cycle.video_type else (),
            benchmark_eligible=eligible, in_progress_at=cycle.in_progress_at, ready_for_approval_at=cycle.ready_for_approval_at,
            duration_seconds=cycle.duration_seconds,
            event_ids={"in_progress": str((cycle.in_progress_event or {}).get("event_id")), "ready_for_approval": str((cycle.ready_for_approval_event or {}).get("event_id")),
                       "editor": cycle.editor_event_id, "video_type": cycle.video_type_event_id, "requested_eta": cycle.requested_eta_event_id},
            exclusions=tuple(cycle.exclusions), flags=tuple(cycle.flags),
            requested_eta=cycle.requested_eta, requested_eta_issue=cycle.requested_eta_issue, requested_eta_observed_at=cycle.requested_eta_observed_at,
            requested_eta_at_start=_eta_at(cycle, cycle.in_progress_at),
            deadline_result=deadline["metric"]["result"] if deadline else None, deadline_delta_seconds=deadline["delta_seconds"] if deadline else None,
            window=window_assignment(cycle.ready_for_approval_at, windows), cairo_date=local.date().isoformat(), cairo_month=local.strftime("%Y-%m"),
            cairo_weekday=local.isoweekday(), labels=tuple(labels.get(cycle.monday_item_id, ())),
            client_revisions=int(revision.get("client_revision_events", 0)), internal_revisions=int(revision.get("internal_revision_events", 0)),
            revision_event_ids=tuple(str(value) for value in revision.get("event_ids", [])),
            created_at=created.get(cycle.monday_item_id), assigned_at=editor_change.occurred_at if editor_change else None,
            review_wait_seconds=review_wait, delivered_at=delivered_at, delivered_event_id=delivered_id))
    _concurrency(projects)
    open_work = _open_work(result, contract, timelines, metric_policy)
    coverage = {
        "completed_first_cycles": len(projects),
        "attributed": sum(project.attributed for project in projects),
        "unattributed": sum(not project.attributed for project in projects),
        "deadline_classifiable": sum(project.deadline_classifiable for project in projects),
        "speed_measurable": sum(project.speed_measurable and project.attributed for project in projects),
        "eta_observed_after_start": sum(project.eta_observed_after_start for project in projects if project.attributed),
        "items_with_status_history": len(timelines),
        "stage_visits": sum(len(timeline.visits) for timeline in timelines.values()),
        "stage_visits_invalid": sum(visit.invalid_reason == UNKNOWN_STATUS_WITHIN_VISIT for timeline in timelines.values() for visit in timeline.visits),
        "stage_visits_open": sum(visit.invalid_reason == OPEN_VISIT for timeline in timelines.values() for visit in timeline.visits),
        "open_work_items": len(open_work),
        "not_completed_cycles": sum(cycle.state != COMPLETED for cycle in result.cycles),
    }
    return FactBase(projects, timelines, open_work, windows, result.ingestion.get("retrieved_at"), str(board["board_id"]),
                    {"status": board["status_column_id"], "editor": board["editor_column_id"], "video_type": board["video_type_column_id"],
                     "requested_eta": board["requested_eta_column_id"], "performance_issues": board["performance_issues_column_id"],
                     "for_bonus": board.get("for_bonus_column_id", "")}, dict(sorted(names.items())), coverage)


def _concurrency(projects: list[ProjectFact]) -> None:
    """Other attributed completed first cycles of the same Editor open at this project's In Progress moment (lower bound)."""
    by_editor: dict[str, list[ProjectFact]] = defaultdict(list)
    for project in projects:
        if project.editor_id:
            by_editor[project.editor_id].append(project)
    for mine in by_editor.values():
        spans = [(parse_time(project.in_progress_at), parse_time(project.ready_for_approval_at), project) for project in mine]
        for start, _end, project in spans:
            others = sorted(other.monday_item_id for other_start, other_end, other in spans
                            if other is not project and other_start <= start < other_end)
            project.concurrency_at_start = len(others)
            project.concurrent_item_ids = tuple(others)


def _open_work(result: CycleReconstruction, contract: Mapping[str, Any], timelines: Mapping[str, ItemTimeline],
               metric_policy: MetricPolicy) -> list[OpenWork]:
    board = contract["source_board"]
    statuses = result.item_snapshots.get(board["status_column_id"], {})
    editors = result.item_snapshots.get(board["editor_column_id"], {})
    etas = result.item_snapshots.get(board["requested_eta_column_id"], {})
    types = result.item_snapshots.get(board["video_type_column_id"], {})
    policy = CyclePolicy.from_contract(contract)
    rows = []
    for item_id, snapshot in sorted(statuses.items()):
        status = str(snapshot.get("text") or "")
        if status not in (*ACTIVE_WORK_STATUSES, AWAITING_APPROVAL_STATUS):
            continue
        timeline = timelines.get(item_id)
        current_visit = timeline.visits[-1] if timeline and timeline.visits and timeline.visits[-1].status == status else None
        first_start = timeline.first(START) if timeline else None
        eta, issue = requested_eta((etas.get(item_id) or {}).get("value"))
        type_value = (types.get(item_id) or {}).get("value")
        resolution = resolve_video_type(metric_policy.video_types, dropdown_value_ids(type_value), dropdown_value_labels(type_value)) \
            if metric_policy.video_types and dropdown_value_ids(type_value) else None
        cohort = resolution.cohort_key if resolution is not None and resolution.resolved else None
        eligible = bool(resolution is not None and resolution.resolved and cohort_benchmark_eligibility(resolution.canonical_ids, metric_policy.video_types)[0])
        evidence = tuple(str(value["evidence_id"]) for value in (snapshot, editors.get(item_id), etas.get(item_id), types.get(item_id))
                         if value and value.get("evidence_id"))
        rows.append(OpenWork(item_id, status, current_visit.entered_at if current_visit else None, current_visit.enter_event_id if current_visit else None,
                             _current_editor(editors.get(item_id), policy), cohort, eligible,
                             first_start.entered_at if first_start else None, first_start.enter_event_id if first_start else None,
                             eta, issue, evidence, str(result.ingestion.get("retrieved_at") or snapshot.get("retrieved_at") or "")))
    return rows
