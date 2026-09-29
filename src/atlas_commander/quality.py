"""Quality occurrences from the Monday Performance Issues labels (V1 rule: 1 occurrence = 1 point).

An occurrence is one Performance Issues label present on an item. The item's current
Monday value is authoritative (a removed label is a correction and does not count); the
activity log that added the label is its evidence. Labels are resolved by Monday label ID
with a versioned registry; unknown IDs are quarantined, never guessed. There are no
severity weights, and revisions never enter the value (``revision_context`` is display-only).

Each occurrence is attributed to the Editor of the item's first completed work cycle. When
that Editor is unresolved, the occurrence is quarantined with the cycle's reasons.
Contracts through 1.4 treat ``For Bonus`` as unclassified context and do not read it.
From 1.5 onward, a contract may provide an explicit per-label registry for that column;
those labels are parsed individually as Positive or Context without changing historical
contract output.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from atlas_commander.contracts import validate
from atlas_commander.cycles import COMPLETED, CycleRecord
from atlas_commander.monday_source import ColumnChange, dropdown_value_ids, dropdown_value_labels

CONTRACT_VERSION = "1.0.0"
UNMAPPED_QUALITY_LABEL = "UNMAPPED_QUALITY_LABEL"
QUALITY_LABEL_NAME_MISMATCH = "QUALITY_LABEL_NAME_MISMATCH"
NO_COMPLETED_CYCLE = "NO_COMPLETED_CYCLE"
EDITOR_UNRESOLVED = "EDITOR_UNRESOLVED"


@dataclass(frozen=True)
class QualityPolicy:
    rule_version: str
    mapping_version: str
    column_id: str
    id_to_label: Mapping[str, str]
    historical_names: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    label_sources: tuple[QualityLabelSource, ...] = ()
    taxonomy_enabled: bool = False

    @classmethod
    def from_contract(cls, contract: Mapping[str, Any]) -> QualityPolicy:
        section = contract["quality_labels"]
        if section.get("weighting") != "one-occurrence-per-label-per-item-equal-weight":
            raise ValueError("quality labels must use equal weight, one occurrence per label per item")
        labels = {str(key): str(value) for key, value in section["id_to_label"].items()}
        historical = {str(key): tuple(str(name) for name in names) for key, names in (section.get("historical_label_names") or {}).items()}
        if any(key not in labels for key in historical):
            raise ValueError("historical_label_names refers to an unmapped quality label ID")
        primary = QualityLabelSource(section["column_id"], section["mapping_version"], labels, historical, {key: "Negative" for key in labels})
        sources = [primary]
        taxonomy_enabled = _contract_at_least(contract, (1, 5, 0))
        if taxonomy_enabled:
            sources = _configured_sources(section, primary)
        return cls(section["rule_version"], section["mapping_version"], section["column_id"], labels, historical, tuple(sources), taxonomy_enabled)

    def names(self, label_id: str) -> set[str]:
        return {self.id_to_label[label_id], *self.historical_names.get(label_id, ())} if label_id in self.id_to_label else set()


@dataclass(frozen=True)
class QualityLabelSource:
    column_id: str
    mapping_version: str
    id_to_label: Mapping[str, str]
    historical_names: Mapping[str, tuple[str, ...]]
    class_by_id: Mapping[str, str]

    def names(self, label_id: str) -> set[str]:
        return {self.id_to_label[label_id], *self.historical_names.get(label_id, ())} if label_id in self.id_to_label else set()


def _contract_at_least(contract: Mapping[str, Any], required: tuple[int, int, int]) -> bool:
    try:
        version = tuple(int(part) for part in str(contract.get("contract_version", "0.0.0")).split(".")[:3])
    except ValueError:
        return False
    return version >= required


def _label_entries(section: Mapping[str, Any], default_class: str) -> tuple[dict[str, str], dict[str, str]]:
    labels = {str(key): str(value) for key, value in (section.get("id_to_label") or {}).items()}
    classes = {str(key): str(value).title() for key, value in (section.get("class_by_id") or section.get("label_class_by_id") or {}).items()}
    entries = section.get("labels")
    if isinstance(entries, Mapping):
        for key, value in entries.items():
            if isinstance(value, Mapping):
                labels[str(key)] = str(value.get("label") or value.get("name"))
                classes[str(key)] = str(value.get("class") or value.get("classification") or default_class).title()
            else:
                labels[str(key)] = str(value)
    for label_id in labels:
        classes.setdefault(label_id, default_class)
    invalid = sorted({value for value in classes.values() if value not in {"Positive", "Negative", "Context"}})
    if invalid:
        raise ValueError(f"invalid quality label classes: {invalid}")
    return labels, classes


def _source(section: Mapping[str, Any], fallback: QualityLabelSource, default_class: str) -> QualityLabelSource:
    labels, classes = _label_entries(section, default_class)
    if not labels:
        labels, classes = dict(fallback.id_to_label), dict(fallback.class_by_id)
    historical = {str(key): tuple(str(name) for name in names) for key, names in (section.get("historical_label_names") or {}).items()}
    return QualityLabelSource(str(section.get("column_id") or fallback.column_id), str(section.get("mapping_version") or fallback.mapping_version), labels,
                              historical or fallback.historical_names, classes)


def _configured_sources(section: Mapping[str, Any], primary: QualityLabelSource) -> list[QualityLabelSource]:
    """Read common v1.5 config shapes while requiring explicit IDs and classes."""
    registries = section.get("registries")
    if isinstance(registries, Mapping):
        grouped: dict[str, dict[str, Any]] = {}
        for class_name in ("positive", "negative", "context"):
            entries = registries.get(class_name)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                column_id = str(entry.get("column_id") or "")
                label_id = str(entry.get("source_label_id") or "")
                label = entry.get("label")
                if not column_id or not label_id or not isinstance(label, str) or not label:
                    raise ValueError("quality registry entries require column_id, source_label_id and label")
                group = grouped.setdefault(column_id, {"labels": {}, "classes": {}})
                if label_id in group["labels"]:
                    raise ValueError(f"duplicate quality label key {(column_id, label_id)!r}")
                group["labels"][label_id] = label
                group["classes"][label_id] = class_name.title()
        if grouped:
            registry_sources = []
            for column_id, values in sorted(grouped.items()):
                is_primary = column_id == primary.column_id
                registry_sources.append(QualityLabelSource(
                    column_id,
                    primary.mapping_version if is_primary else str(section.get("mapping_version")),
                    values["labels"],
                    primary.historical_names if is_primary else {},
                    values["classes"],
                ))
            if not any(source.column_id == primary.column_id for source in registry_sources):
                registry_sources.insert(0, primary)
            return registry_sources
    configured = section.get("columns") or section.get("label_sources")
    sources: list[QualityLabelSource] = []
    if isinstance(configured, Mapping):
        for name, value in configured.items():
            if isinstance(value, Mapping):
                sources.append(_source(value, primary, "Negative" if "performance" in str(name).lower() else "Context"))
    elif isinstance(configured, list):
        for value in configured:
            if isinstance(value, Mapping):
                sources.append(_source(value, primary, "Context"))
    if not sources:
        sources.append(_source(section, primary, "Negative"))
        bonus = section.get("for_bonus")
        if isinstance(bonus, Mapping) and (bonus.get("id_to_label") or bonus.get("labels")):
            sources.append(_source(bonus, primary, "Context"))
    if not any(source.column_id == primary.column_id for source in sources):
        sources.insert(0, primary)
    return sources


@dataclass
class QualityResult:
    occurrences: list[dict[str, Any]] = field(default_factory=list)
    quarantined: list[dict[str, Any]] = field(default_factory=list)


def _add_events(changes: list[ColumnChange]) -> dict[str, ColumnChange]:
    """Latest observation that added each label ID (present in value, absent from previous value)."""
    added: dict[str, ColumnChange] = {}
    for change in sorted(changes, key=lambda change: change.sort_key):
        if change.is_undo_action:
            continue
        before = set(dropdown_value_ids(change.previous_value))
        for label_id in dropdown_value_ids(change.value):
            if label_id not in before:
                added[label_id] = change
    return added


def quality_occurrences(cycles: Iterable[CycleRecord], column_changes: Iterable[ColumnChange], policy: QualityPolicy, calculated_at: str,
                        snapshots: Mapping[str, Mapping[str, Any]] | Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None) -> QualityResult:
    """Contract-valid quality metrics (one per label occurrence) plus quarantined occurrences.

    ``snapshots`` maps item ID to the current Performance Issues column value from the items
    API (``item_column_snapshots``). Without a snapshot the latest logged value is used.
    """
    sources = policy.label_sources or (QualityLabelSource(policy.column_id, policy.mapping_version, policy.id_to_label, policy.historical_names,
                                                           {key: "Negative" for key in policy.id_to_label}),)
    source_by_column = {source.column_id: source for source in sources}
    by_column_item: dict[str, dict[str, list[ColumnChange]]] = defaultdict(lambda: defaultdict(list))
    for change in column_changes:
        if change.column_id in source_by_column:
            by_column_item[change.column_id][change.item_id].append(change)
    cycle_by_item = {cycle.monday_item_id: cycle for cycle in cycles}
    result = QualityResult()
    snapshot_values = snapshots or {}
    nested_snapshots = any(key in source_by_column for key in snapshot_values)
    for source in sources:
        column_snapshots = snapshot_values.get(source.column_id, {}) if nested_snapshots else snapshot_values
        for item_id in sorted(set(by_column_item[source.column_id]) | set(column_snapshots)):
            changes = sorted(by_column_item[source.column_id].get(item_id, []), key=lambda change: change.sort_key)
            snapshot = column_snapshots.get(item_id)
            current_ids: tuple[str, ...]
            current_names: tuple[str, ...]
            if snapshot is not None:
                current_ids, current_names = dropdown_value_ids(snapshot.get("value")), ()
                current_source, current_id, current_time = "item_snapshot", str(snapshot["evidence_id"]), snapshot.get("retrieved_at")
            elif changes:
                current_ids, current_names = dropdown_value_ids(changes[-1].value), dropdown_value_labels(changes[-1].value)
                current_source, current_id, current_time = "activity_log", changes[-1].log_id, changes[-1].occurred_at
            else:
                continue
            added = _add_events(changes)
            cycle = cycle_by_item.get(item_id)
            for position, label_id in enumerate(current_ids):
                event = added.get(label_id)
                raw_name = current_names[position] if position < len(current_names) else None
                base = {"monday_item_id": item_id, "label_id": label_id, "raw_label": raw_name, "current_value_source": current_source,
                        "current_value_evidence_id": current_id, "added_event_id": event.log_id if event else None}
                if label_id not in source.id_to_label:
                    detail = {**base, "reason": UNMAPPED_QUALITY_LABEL}
                    if policy.taxonomy_enabled:
                        detail["column_id"] = source.column_id
                    result.quarantined.append(detail)
                    continue
                if raw_name is not None and raw_name not in source.names(label_id):
                    detail = {**base, "reason": QUALITY_LABEL_NAME_MISMATCH}
                    if policy.taxonomy_enabled:
                        detail["column_id"] = source.column_id
                    result.quarantined.append(detail)
                    continue
                if cycle is None or cycle.state != COMPLETED:
                    result.quarantined.append({**base, "reason": NO_COMPLETED_CYCLE})
                    continue
                editor_reasons = [reason for reason in cycle.exclusions if "EDITOR" in reason]
                if cycle.editor_id is None or editor_reasons:
                    result.quarantined.append({**base, "reason": EDITOR_UNRESOLVED, "cycle_reasons": sorted(set(cycle.exclusions))})
                    continue
                timestamp = event.occurred_at if event else current_time
                if not isinstance(timestamp, str):
                    result.quarantined.append({**base, "reason": "MISSING_EVIDENCE_TIMESTAMP"})
                    continue
                label = source.id_to_label[label_id]
                label_class = source.class_by_id[label_id]
                event_ids = [event.log_id] if event else []
                if current_id not in event_ids:
                    event_ids.append(current_id)
                source_values = {"label_id": label_id, "label": label, "raw_label_at_add": list(dropdown_value_labels(event.value)) if event else None,
                                 "current_value_source": current_source, "weight": 1,
                                 "attribution": "editor of the item's first completed cycle", "cycle_id": cycle.cycle_id}
                if policy.taxonomy_enabled:
                    source_values.update({"label_class": label_class,
                                          "scoring_eligible": label_class != "Context" and label not in {"Late Delivery", "On Time Delivery"}})
                metric = {
                    "contract_version": CONTRACT_VERSION,
                    "metric_name": "quality",
                    "editor_id": cycle.editor_id,
                    "performance_label": label,
                    "label_column_id": source.column_id,
                    "label_mapping_version": source.mapping_version,
                    "revision_context": dict(cycle.revision_context),
                    "evidence": {
                        "source": "monday",
                        "monday_board_id": cycle.monday_board_id,
                        "monday_item_id": item_id,
                        "column_ids": [source.column_id],
                        "event_ids": event_ids,
                        "source_timestamps": [timestamp],
                        "source_values": source_values,
                        "rule_version": policy.rule_version,
                        "calculated_at": calculated_at,
                    },
                }
                errors = validate(metric, "quality-metric.schema.json")
                if errors:
                    raise ValueError(f"quality metric violates contract: {errors}")
                result.occurrences.append(metric)
    return result


def quality_summary(editor_id: str, result: QualityResult, cycles: Iterable[CycleRecord]) -> dict[str, Any]:
    """Equal-weight counts per label for one Editor, with the projects behind each count."""
    mine = [metric for metric in result.occurrences if metric["editor_id"] == editor_id]
    projects = sorted({cycle.monday_item_id for cycle in cycles if cycle.state == COMPLETED and cycle.editor_id == editor_id and
                       not [reason for reason in cycle.exclusions if "EDITOR" in reason]})
    by_label: dict[str, list[str]] = defaultdict(list)
    for metric in mine:
        by_label[metric["performance_label"]].append(metric["evidence"]["monday_item_id"])
    return {
        "editor_id": editor_id,
        "weighting": "1 occurrence = 1 point; no severity weights",
        "total_occurrences": len(mine),
        "completed_projects_attributed": len(projects),
        "projects_with_issues": len({metric["evidence"]["monday_item_id"] for metric in mine}),
        "by_label": [{"label": label, "occurrences": len(items), "monday_item_ids": sorted(items)} for label, items in sorted(by_label.items(), key=lambda pair: (-len(pair[1]), pair[0]))],
    }


def revision_context_summary(editor_id: str, cycles: Iterable[CycleRecord]) -> dict[str, Any]:
    """Client revision activity for the Editor's completed projects. Context only, never a penalty."""
    mine = [cycle for cycle in cycles if cycle.state == COMPLETED and cycle.editor_id == editor_id]
    with_revisions = [cycle for cycle in mine if cycle.revision_context.get("client_revision_events", 0) > 0]
    return {
        "context_only": True,
        "note": "A revision records that a client asked for changes; its cause is not known and it never affects Editor scoring.",
        "completed_projects": len(mine),
        "projects_with_client_revisions": len(with_revisions),
        "client_revision_events": sum(cycle.revision_context.get("client_revision_events", 0) for cycle in mine),
        "internal_revision_events": sum(cycle.revision_context.get("internal_revision_events", 0) for cycle in mine),
        "client_revision_rate": round(len(with_revisions) / len(mine), 4) if mine else None,
        "monday_item_ids_with_client_revisions": sorted(cycle.monday_item_id for cycle in with_revisions),
    }
