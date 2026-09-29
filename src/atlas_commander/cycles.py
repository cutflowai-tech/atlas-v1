"""Editor work-cycle reconstruction (CYCLE-001).

One Monday item yields at most one work cycle under the approved rules:

* the cycle starts at the first transition into ``In Progress``;
* it ends at the first transition into ``Ready For Approval`` after that start;
* repeated ``In Progress``/``Create File`` and post-revision transitions stay in
  that original cycle and never open a new one;
* a cycle without an end is retained as open (right-censored) and excluded from
  completed-duration aggregates;
* duplicate, discontinuous and undone transitions are ignored for timing and flagged.

Only the first completed cycle is measured; later ``In Progress -> Ready For
Approval`` rounds are retained as evidence (``post_cycle_event_ids``) and are never
added to, or substituted for, the first cycle. Duration is elapsed clock time.

The Editor and Video Type of a cycle are the values in effect at the ``Ready For
Approval`` event, taken only from Monday column-change events (policy
``cycle-attributes-v1.0``); a missing event history is unresolved. The Requested ETA
is the latest available value for the item (management decision): the current item
snapshot when ingestion supplies one, otherwise the last logged change. Every ETA
value observed in the ingested evidence is kept as history, and the history is marked
complete only when ingestion metadata proves it. Nothing here computes a metric.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from atlas_commander.contracts import validate
from atlas_commander.identity import EditorObservation, IdentityMapping, resolve_editor
from atlas_commander.monday_source import REQUESTED_ETA_DATE_ONLY, ColumnChange, dropdown_value_ids, dropdown_value_labels, requested_eta
from atlas_commander.video_type import VideoTypeMapping, VideoTypeResolution, resolve_video_type

CONTRACT_VERSION = "1.0.0"
START_STATUS = "In Progress"
END_STATUS = "Ready For Approval"
CLIENT_REVISION_STATUS = "Revisions"
INTERNAL_REVISION_STATUS = "Internal Revisions"
CAPTION_STATUSES = frozenset({"Captions Revisions", "Captions In Progress", "Waiting For Captions", "Captions Done"})
DELIVERED_PHASE = "delivered"

COMPLETED = "completed"
OPEN = "open"
INVALID = "invalid"

# Exclusion reasons: the cycle is retained but kept out of the named aggregates.
OPEN_CYCLE = "OPEN_CYCLE"
MISSING_IN_PROGRESS = "MISSING_IN_PROGRESS"
NON_POSITIVE_DURATION = "NON_POSITIVE_DURATION"
MISSING_EDITOR_EVENT = "MISSING_EDITOR_EVENT"
EDITOR_CHANGED_WITHIN_CYCLE = "EDITOR_CHANGED_WITHIN_CYCLE"
MISSING_VIDEO_TYPE_EVENT = "MISSING_VIDEO_TYPE_EVENT"

# Informational flags: the cycle stays in aggregates and the flag travels with it.
REPEATED_IN_PROGRESS = "REPEATED_IN_PROGRESS"
DUPLICATE_TRANSITION = "DUPLICATE_TRANSITION"
DISCONTINUOUS_TRANSITION = "DISCONTINUOUS_TRANSITION"
UNDO_ACTION_IGNORED = "UNDO_ACTION_IGNORED"
UNMAPPED_STATUS_IN_HISTORY = "UNMAPPED_STATUS_IN_HISTORY"
UNMAPPED_STATUS_WITHIN_CYCLE_WINDOW = "UNMAPPED_STATUS_WITHIN_CYCLE_WINDOW"
STATUS_CLEARED_IN_HISTORY = "STATUS_CLEARED_IN_HISTORY"
UNRESOLVED_PREVIOUS_STATUS = "UNRESOLVED_PREVIOUS_STATUS"
# Quarantine reasons that cannot hide a cycle boundary: exact duplicates (the first copy is kept)
# and transitions into a cleared, label-less status (which cannot be In Progress or Ready For Approval).
_HARMLESS_QUARANTINE = frozenset({"DUPLICATE_EVENT_ID", "STATUS_CLEARED"})
CAPTIONS_WITHIN_CYCLE = "CAPTIONS_WITHIN_CYCLE"
DELIVERED_BEFORE_READY_FOR_APPROVAL = "DELIVERED_BEFORE_READY_FOR_APPROVAL"
READY_FOR_APPROVAL_BEFORE_START = "READY_FOR_APPROVAL_BEFORE_START"
CLIENT_REVISION_WITHIN_CYCLE = "CLIENT_REVISION_WITHIN_CYCLE"
VIDEO_TYPE_CHANGED_AFTER_READY_FOR_APPROVAL = "VIDEO_TYPE_CHANGED_AFTER_READY_FOR_APPROVAL"
INITIAL_STATUS_AT_CREATION = "INITIAL_STATUS_AT_CREATION"

# Requested ETA selection rules (contract ``deadline.requested_eta_selection``).
LATEST_ETA = "latest-available-requested-eta"
ETA_AT_READY_FOR_APPROVAL = "latest-valid-requested-eta-at-or-before-first-ready-for-approval"
NO_ETA_AT_OR_BEFORE_READY_FOR_APPROVAL = "NO_REQUESTED_ETA_AT_OR_BEFORE_READY_FOR_APPROVAL"


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class CyclePolicy:
    policy_version: str
    identity: IdentityMapping
    video_types: VideoTypeMapping
    editor_column_id: str
    video_type_column_id: str
    requested_eta_column_id: str
    status_column_id: str = "project_status"
    requested_eta_selection: str = LATEST_ETA

    @classmethod
    def from_contract(cls, contract: Mapping[str, Any]) -> CyclePolicy:
        boundaries = contract["cycle_boundaries"]
        if (boundaries.get("start_label"), boundaries.get("end_label")) != (START_STATUS, END_STATUS):
            raise ValueError("cycle boundaries must be In Progress -> Ready For Approval")
        attributes = contract["cycle_attributes"]
        board = contract["source_board"]
        identity = IdentityMapping.from_contract(contract)
        selection = (contract.get("deadline") or {}).get("requested_eta_selection", LATEST_ETA)
        if selection not in {LATEST_ETA, ETA_AT_READY_FOR_APPROVAL}:
            raise ValueError(f"unknown Requested ETA selection rule {selection!r}")
        return cls(attributes["policy_version"], identity, VideoTypeMapping.from_contract(contract), board["editor_column_id"],
                   board["video_type_column_id"], board["requested_eta_column_id"], board["status_column_id"], selection)


@dataclass
class CycleRecord:
    cycle_id: str
    monday_board_id: str
    monday_item_id: str
    state: str
    policy_version: str
    in_progress_event: Mapping[str, Any] | None = None
    ready_for_approval_event: Mapping[str, Any] | None = None
    duration_seconds: int | None = None
    editor: dict[str, Any] | None = None
    editor_exception: dict[str, Any] | None = None
    editor_event_id: str | None = None
    video_type: VideoTypeResolution | None = None
    video_type_event_id: str | None = None
    video_type_source: str | None = None
    video_type_skipped_event_ids: list[str] = field(default_factory=list)
    requested_eta: str | None = None
    requested_eta_event_id: str | None = None
    requested_eta_issue: str | None = None
    requested_eta_source: str | None = None
    requested_eta_history: list[dict[str, Any]] = field(default_factory=list)
    requested_eta_history_coverage: dict[str, Any] = field(default_factory=dict)
    requested_eta_selection: str = LATEST_ETA
    requested_eta_observed_at: str | None = None
    requested_eta_skipped_event_ids: list[str] = field(default_factory=list)
    requested_eta_ignored_after_ready_for_approval: list[dict[str, Any]] = field(default_factory=list)
    revision_context: dict[str, Any] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    status_event_ids: list[str] = field(default_factory=list)
    post_cycle_event_ids: list[str] = field(default_factory=list)
    later_ready_for_approval_event_ids: list[str] = field(default_factory=list)

    @property
    def editor_id(self) -> str | None:
        return self.editor["editor_id"] if self.editor else None

    @property
    def cohort_key(self) -> str | None:
        return self.video_type.cohort_key if self.video_type else None

    @property
    def in_progress_at(self) -> str | None:
        return self.in_progress_event["occurred_at"] if self.in_progress_event else None

    @property
    def ready_for_approval_at(self) -> str | None:
        return self.ready_for_approval_event["occurred_at"] if self.ready_for_approval_event else None

    def to_contract(self) -> dict[str, Any] | None:
        """WorkCycle contract record, or None when the cycle cannot satisfy the contract."""
        if self.state != COMPLETED or not self.editor_id or not self.cohort_key or self.duration_seconds is None:
            return None
        assert self.in_progress_event is not None and self.ready_for_approval_event is not None
        cycle = {
            "contract_version": CONTRACT_VERSION,
            "cycle_id": self.cycle_id,
            "editor_id": self.editor_id,
            "video_type": self.cohort_key,
            "monday_board_id": self.monday_board_id,
            "monday_item_id": self.monday_item_id,
            "start_status": START_STATUS,
            "end_status": END_STATUS,
            "in_progress_event_id": self.in_progress_event["event_id"],
            "ready_for_approval_event_id": self.ready_for_approval_event["event_id"],
            "in_progress_at": self.in_progress_at,
            "ready_for_approval_at": self.ready_for_approval_at,
            "duration_seconds": self.duration_seconds,
            "requested_eta": self.requested_eta,
            "revision_context": self.revision_context,
        }
        errors = validate(cycle, "work-cycle.schema.json")
        if [error for error in errors if error != "MISSING_REQUESTED_ETA"]:
            raise ValueError(f"reconstructed cycle violates work-cycle contract: {errors}")
        return cycle

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "monday_board_id": self.monday_board_id,
            "monday_item_id": self.monday_item_id,
            "state": self.state,
            "policy_version": self.policy_version,
            "in_progress_event_id": self.in_progress_event["event_id"] if self.in_progress_event else None,
            "in_progress_at": self.in_progress_at,
            "ready_for_approval_event_id": self.ready_for_approval_event["event_id"] if self.ready_for_approval_event else None,
            "ready_for_approval_at": self.ready_for_approval_at,
            "duration_seconds": self.duration_seconds,
            "editor_id": self.editor_id,
            "editor_mapping_version": self.editor["mapping_version"] if self.editor else None,
            "editor_exception": self.editor_exception,
            "editor_event_id": self.editor_event_id,
            "video_type": self.video_type.to_dict() if self.video_type else None,
            "video_type_event_id": self.video_type_event_id,
            "video_type_source": self.video_type_source,
            "video_type_skipped_event_ids": list(self.video_type_skipped_event_ids),
            "requested_eta": self.requested_eta,
            "requested_eta_event_id": self.requested_eta_event_id,
            "requested_eta_issue": self.requested_eta_issue,
            "requested_eta_source": self.requested_eta_source,
            "requested_eta_history": list(self.requested_eta_history),
            "requested_eta_history_coverage": dict(self.requested_eta_history_coverage),
            "requested_eta_selection": self.requested_eta_selection,
            "requested_eta_observed_at": self.requested_eta_observed_at,
            "requested_eta_skipped_event_ids": list(self.requested_eta_skipped_event_ids),
            "requested_eta_ignored_after_ready_for_approval": list(self.requested_eta_ignored_after_ready_for_approval),
            "revision_context": self.revision_context,
            "flags": list(self.flags),
            "exclusions": list(self.exclusions),
            "status_event_ids": list(self.status_event_ids),
            "post_cycle_event_ids": list(self.post_cycle_event_ids),
            "later_ready_for_approval_event_ids": list(self.later_ready_for_approval_event_ids),
        }


def _event_key(event: Mapping[str, Any]) -> tuple[datetime, str]:
    return (parse_time(event["occurred_at"]), str(event["event_id"]))


def _as_of(changes: Sequence[ColumnChange], moment: datetime) -> ColumnChange | None:
    """Latest column change at or before ``moment`` (changes must be time-ordered)."""
    current = None
    for change in changes:
        if parse_time(change.occurred_at) <= moment:
            current = change
        else:
            break
    return current


def _add(target: list[str], code: str) -> None:
    if code not in target:
        target.append(code)


def build_item_cycle(
    board_id: str,
    item_id: str,
    status_events: Iterable[Mapping[str, Any]],
    column_changes: Iterable[ColumnChange],
    policy: CyclePolicy,
    undo_event_ids: Iterable[str] = (),
    quarantined_status_logs: Iterable[Mapping[str, Any]] = (),
    eta_snapshot: Mapping[str, Any] | None = None,
    history_coverage: Mapping[str, Any] | None = None,
) -> CycleRecord | None:
    """Reconstruct the single work cycle for one item from its accepted normalized status events.

    ``quarantined_status_logs`` are this item's normalization quarantine entries
    (``{"reason", "raw_source"}``). An unmapped status, or any other quarantined log that
    could hide a boundary, occurring at or before the cycle's Ready For Approval excludes the
    cycle from metrics (``UNMAPPED_STATUS_WITHIN_CYCLE_WINDOW``) instead of letting an unknown
    state silently move its start or end.
    """
    undo = {str(value) for value in undo_event_ids}
    all_events = sorted((event for event in status_events if event["monday_item_id"] == item_id), key=_event_key)
    if not all_events:
        return None
    record = CycleRecord(f"cycle:{board_id}:{item_id}", board_id, item_id, INVALID, policy.policy_version)
    quarantined = list(quarantined_status_logs)
    if any(entry.get("reason") == "STATUS_CLEARED" for entry in quarantined):
        _add(record.flags, STATUS_CLEARED_IN_HISTORY)
    blocking_quarantine = [entry for entry in quarantined if entry.get("reason") not in _HARMLESS_QUARANTINE]
    if blocking_quarantine:
        _add(record.flags, UNMAPPED_STATUS_IN_HISTORY)

    timeline: list[Mapping[str, Any]] = []
    for event in all_events:
        if str(event["event_id"]) in undo:
            _add(record.flags, UNDO_ACTION_IGNORED)
            continue
        if timeline and timeline[-1]["to_status"] == event["to_status"]:
            _add(record.flags, DUPLICATE_TRANSITION)
            continue
        if timeline and event.get("from_status") is not None and event["from_status"] != timeline[-1]["to_status"]:
            _add(record.flags, DISCONTINUOUS_TRANSITION)
        timeline.append(event)

    revisions = [event for event in timeline if event["to_status"] in (CLIENT_REVISION_STATUS, INTERNAL_REVISION_STATUS)]
    record.revision_context = {
        "context_only": True,
        "client_revision_events": sum(1 for event in revisions if event["to_status"] == CLIENT_REVISION_STATUS),
        "internal_revision_events": sum(1 for event in revisions if event["to_status"] == INTERNAL_REVISION_STATUS),
        "client_revision_event_ids": [event["event_id"] for event in revisions if event["to_status"] == CLIENT_REVISION_STATUS],
        "internal_revision_event_ids": [event["event_id"] for event in revisions if event["to_status"] == INTERNAL_REVISION_STATUS],
        "event_ids": [event["event_id"] for event in revisions],
    }

    start_index = next((index for index, event in enumerate(timeline) if event["to_status"] == START_STATUS), None)
    if start_index is None:
        if any(event["to_status"] == END_STATUS for event in timeline):
            _add(record.flags, READY_FOR_APPROVAL_BEFORE_START)
            _add(record.exclusions, MISSING_IN_PROGRESS)
            return record
        return None
    if any(event["to_status"] == END_STATUS for event in timeline[:start_index]):
        _add(record.flags, READY_FOR_APPROVAL_BEFORE_START)
    start = timeline[start_index]
    record.in_progress_event = start
    end_index = next((index for index in range(start_index + 1, len(timeline)) if timeline[index]["to_status"] == END_STATUS), None)
    within = timeline[start_index + 1:end_index] if end_index is not None else timeline[start_index + 1:]
    for event in within:
        if event["to_status"] == START_STATUS:
            _add(record.flags, REPEATED_IN_PROGRESS)
        if event["to_status"] in CAPTION_STATUSES:
            _add(record.flags, CAPTIONS_WITHIN_CYCLE)
        if event.get("status_phase_to") == DELIVERED_PHASE:
            _add(record.flags, DELIVERED_BEFORE_READY_FOR_APPROVAL)
        if event["to_status"] == CLIENT_REVISION_STATUS:
            _add(record.flags, CLIENT_REVISION_WITHIN_CYCLE)
    record.status_event_ids = [event["event_id"] for event in timeline[start_index:(end_index + 1 if end_index is not None else None)]]
    window_end = parse_time(timeline[end_index]["occurred_at"]) if end_index is not None else None
    for event in timeline[:(end_index + 1 if end_index is not None else None)]:
        if event.get("from_status") is None and event.get("raw_from_status") is not None:
            _add(record.flags, UNRESOLVED_PREVIOUS_STATUS)
    for entry in blocking_quarantine:
        source = entry.get("raw_source")
        moment = source.get("occurred_at") if isinstance(source, Mapping) else None
        if window_end is None or not isinstance(moment, str) or parse_time(moment) <= window_end:
            _add(record.exclusions, UNMAPPED_STATUS_WITHIN_CYCLE_WINDOW)
    if end_index is not None:
        later = timeline[end_index + 1:]
        record.post_cycle_event_ids = [event["event_id"] for event in later]
        record.later_ready_for_approval_event_ids = [event["event_id"] for event in later if event["to_status"] == END_STATUS]

    if end_index is None:
        record.state = OPEN
        _add(record.exclusions, OPEN_CYCLE)
        attribute_moment = None
    else:
        end = timeline[end_index]
        record.ready_for_approval_event = end
        duration = int((parse_time(end["occurred_at"]) - parse_time(start["occurred_at"])).total_seconds())
        if duration < 1:
            _add(record.exclusions, NON_POSITIVE_DURATION)
            return record
        record.state = COMPLETED
        record.duration_seconds = duration
        attribute_moment = parse_time(end["occurred_at"])

    changes = [change for change in column_changes if change.item_id == item_id]
    by_column: dict[str, list[ColumnChange]] = {}
    for change in sorted(changes, key=lambda change: change.sort_key):
        if change.is_undo_action:
            _add(record.flags, UNDO_ACTION_IGNORED)
            continue
        by_column.setdefault(change.column_id, []).append(change)
    # A status an item was created with (e.g. a duplicated item) is not a transition; it is kept as a flag only.
    if any(change.source == "create_pulse" and change.value for change in by_column.get(policy.status_column_id, [])):
        _add(record.flags, INITIAL_STATUS_AT_CREATION)
    eta_changes = by_column.get(policy.requested_eta_column_id, [])
    _resolve_latest_eta(record, eta_changes, eta_snapshot, history_coverage)
    if policy.requested_eta_selection == ETA_AT_READY_FOR_APPROVAL:
        _select_eta_at_ready_for_approval(record, eta_changes, eta_snapshot, attribute_moment)
    if attribute_moment is None:
        return record
    _resolve_editor(record, by_column.get(policy.editor_column_id, []), policy, parse_time(start["occurred_at"]), attribute_moment)
    _resolve_video_type(record, by_column.get(policy.video_type_column_id, []), policy, attribute_moment)
    return record


def _resolve_editor(record: CycleRecord, changes: list[ColumnChange], policy: CyclePolicy, start: datetime, end: datetime) -> None:
    current = _as_of(changes, end)
    if current is None:
        _add(record.exclusions, MISSING_EDITOR_EVENT)
        return
    in_effect = _as_of(changes, start)
    def identity_key(change: ColumnChange) -> tuple[tuple[str, ...], tuple[str, ...]] | tuple[str, ...]:
        ids = dropdown_value_ids(change.value)
        if policy.identity.strict_name_key:
            return ids, dropdown_value_labels(change.value)
        return ids

    values = {identity_key(change) for change in changes if start < parse_time(change.occurred_at) <= end}
    if in_effect is not None:
        values.add(identity_key(in_effect))
    if policy.identity.strict_name_key:
        nonempty = {value for value in values if value[0]}
    else:
        nonempty = {value for value in values if value}
    if len(nonempty) > 1:
        _add(record.exclusions, EDITOR_CHANGED_WITHIN_CYCLE)
    record.editor_event_id = current.log_id
    observation = EditorObservation(current.board_id, current.item_id, current.column_id, dropdown_value_ids(current.value),
                                    "editor_column_event", current.log_id, current.occurred_at, dropdown_value_labels(current.value))
    resolution = resolve_editor(observation, policy.identity)
    if resolution.identity is not None and EDITOR_CHANGED_WITHIN_CYCLE not in record.exclusions:
        record.editor = resolution.identity
    elif resolution.exception is not None:
        record.editor_exception = resolution.exception.to_dict()
        _add(record.exclusions, resolution.exception.code)


def _resolve_video_type(record: CycleRecord, changes: list[ColumnChange], policy: CyclePolicy, end: datetime) -> None:
    """Latest valid (non-empty) Video Type observed at or before Ready For Approval (approved rule).

    A value set after Ready For Approval never changes the completed cycle's cohort. Empty
    (cleared) observations are skipped and recorded as evidence; an unmapped value is not
    skipped - it is the value in effect and is quarantined.
    """
    known = [change for change in changes if parse_time(change.occurred_at) <= end]
    if not known:
        _add(record.exclusions, MISSING_VIDEO_TYPE_EVENT)
        return
    valid = [change for change in known if dropdown_value_ids(change.value)]
    record.video_type_skipped_event_ids = [change.log_id for change in known if not dropdown_value_ids(change.value) and (not valid or
                                           parse_time(change.occurred_at) >= parse_time(valid[-1].occurred_at))]
    if not valid:
        record.video_type_event_id = known[-1].log_id
        record.video_type = resolve_video_type(policy.video_types, ())
        _add(record.exclusions, record.video_type.reason or MISSING_VIDEO_TYPE_EVENT)
        return
    current = valid[-1]
    record.video_type_event_id = current.log_id
    record.video_type_source = current.source
    record.video_type = resolve_video_type(policy.video_types, dropdown_value_ids(current.value), dropdown_value_labels(current.value))
    if any(parse_time(change.occurred_at) > end and dropdown_value_ids(change.value) != dropdown_value_ids(current.value) for change in changes):
        _add(record.flags, VIDEO_TYPE_CHANGED_AFTER_READY_FOR_APPROVAL)
    if record.video_type.reason:
        _add(record.exclusions, record.video_type.reason)


SNAPSHOT_DIFFERS_FROM_LOG = "REQUESTED_ETA_SNAPSHOT_DIFFERS_FROM_LOG"
OBSERVED_IN_INGESTED_EVIDENCE = "observed_in_ingested_evidence"
COMPLETE = "complete"


def _changed_at(value: Any) -> str | None:
    """Monday's own ``changed_at`` inside a date value, when present; never synthesized."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    changed = value.get("changed_at") if isinstance(value, dict) else None
    return changed if isinstance(changed, str) and changed else None


def _select_eta_at_ready_for_approval(record: CycleRecord, changes: list[ColumnChange], snapshot: Mapping[str, Any] | None,
                                      ready_at: datetime | None) -> None:
    """deadline-v1.2: the latest valid Requested ETA observed at or before the first Ready For Approval.

    Replaces the latest-ETA selection made by ``_resolve_latest_eta`` (whose history and coverage
    are kept). Logged values (activity-log changes and create_pulse initial values) are placed by
    their Monday timestamp. The current item snapshot is used only when the item has no logged ETA
    value at all and Monday's own ``changed_at`` for it is at or before Ready For Approval. Cleared
    or invalid values are skipped and recorded; a date-only value is selected and stays
    unclassifiable. Changes after Ready For Approval are recorded as ignored and never backfill.
    """
    record.requested_eta_selection = ETA_AT_READY_FOR_APPROVAL
    record.requested_eta = record.requested_eta_event_id = record.requested_eta_issue = record.requested_eta_source = None
    if ready_at is None:
        return
    before: list[tuple[str, str, Any, str]] = []
    for change in changes:
        moment = parse_time(change.occurred_at)
        if moment <= ready_at:
            before.append((change.occurred_at, change.log_id, change.value, "activity_log" if change.source == "update_column_value" else change.source))
        else:
            eta, issue = requested_eta(change.value)
            record.requested_eta_ignored_after_ready_for_approval.append(
                {"source": "activity_log" if change.source == "update_column_value" else change.source, "event_id": change.log_id,
                 "occurred_at": change.occurred_at, "requested_eta": eta, "issue": issue})
    if snapshot is not None:
        changed_at = _changed_at(snapshot.get("value"))
        eta, issue = requested_eta(snapshot.get("value"))
        if not changes and changed_at and parse_time(changed_at) <= ready_at:
            before.append((changed_at, str(snapshot["evidence_id"]), snapshot.get("value"), "item_snapshot"))
        elif not changes and (eta or issue):
            record.requested_eta_ignored_after_ready_for_approval.append(
                {"source": "item_snapshot", "event_id": str(snapshot["evidence_id"]), "occurred_at": changed_at, "requested_eta": eta, "issue": issue})
    for observed_at, event_id, value, source in reversed(before):
        eta, issue = requested_eta(value)
        if eta is None and issue != REQUESTED_ETA_DATE_ONLY:
            record.requested_eta_skipped_event_ids.append(event_id)  # cleared or invalid: not a valid ETA
            continue
        record.requested_eta, record.requested_eta_issue = eta, issue
        record.requested_eta_event_id, record.requested_eta_source = event_id, source
        record.requested_eta_observed_at = observed_at
        return
    record.requested_eta_issue = NO_ETA_AT_OR_BEFORE_READY_FOR_APPROVAL if (before or record.requested_eta_ignored_after_ready_for_approval) else "MISSING_REQUESTED_ETA"


def _resolve_latest_eta(record: CycleRecord, changes: list[ColumnChange], snapshot: Mapping[str, Any] | None,
                        coverage: Mapping[str, Any] | None) -> None:
    """Use the latest available Requested ETA; keep every observed value as history.

    ``snapshot`` is the item's current column value as returned by the Monday items API:
    ``{"value", "evidence_id", "retrieved_at"}``. It is the latest available value by
    definition (it is the item's present state), so it wins over logged changes without any
    timestamp being invented for it; a disagreement with the last logged value is flagged.
    """
    for change in changes:
        eta, issue = requested_eta(change.value)
        record.requested_eta_history.append({"source": "activity_log" if change.source == "update_column_value" else change.source, "event_id": change.log_id, "occurred_at": change.occurred_at,
                                             "source_changed_at": _changed_at(change.value), "retrieved_at": None, "requested_eta": eta,
                                             "issue": issue, "previous_value": change.previous_value, "value": change.value})
    latest_value: Any = None
    latest_id: str | None = None
    if changes:
        latest_value, latest_id = changes[-1].value, changes[-1].log_id
        record.requested_eta_source = "activity_log"
    if snapshot is not None:
        snapshot_eta = requested_eta(snapshot.get("value"))
        if changes and snapshot_eta != requested_eta(latest_value):
            _add(record.flags, SNAPSHOT_DIFFERS_FROM_LOG)
        record.requested_eta_history.append({"source": "item_snapshot", "event_id": str(snapshot["evidence_id"]), "occurred_at": None,
                                             "source_changed_at": _changed_at(snapshot.get("value")), "retrieved_at": snapshot.get("retrieved_at"),
                                             "requested_eta": snapshot_eta[0], "issue": snapshot_eta[1], "previous_value": None,
                                             "value": snapshot.get("value")})
        latest_value, latest_id = snapshot.get("value"), str(snapshot["evidence_id"])
        record.requested_eta_source = "item_snapshot"
    proven = bool(coverage and coverage.get("complete_history"))
    record.requested_eta_history_coverage = {
        "status": COMPLETE if proven else OBSERVED_IN_INGESTED_EVIDENCE,
        "activity_log_window": dict(coverage["activity_log_window"]) if coverage and coverage.get("activity_log_window") else None,
        "basis": (coverage or {}).get("basis") if proven else "only Requested ETA values present in the ingested activity logs and item snapshot",
    }
    if latest_id is None:
        record.requested_eta_issue = "MISSING_REQUESTED_ETA"
        return
    eta, issue = requested_eta(latest_value)
    record.requested_eta = eta
    record.requested_eta_event_id = latest_id
    record.requested_eta_issue = None if eta else (issue or "MISSING_REQUESTED_ETA")
