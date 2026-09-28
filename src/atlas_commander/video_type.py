"""Exact Video Type cohort resolution against a versioned Monday mapping.

Monday's Video Type column is a multi-select dropdown whose stored value is a list
of label IDs (``{"ids": [5, 8]}``). The cohort of an item is the exact normalized
full set of canonical IDs, keyed by the string-sorted IDs joined with ``:``. ``[8]`` and
``[5, 8]`` are therefore different cohorts and are never merged, and no primary
type or global fallback is ever inferred.

Anything that cannot be resolved exactly is returned as an unresolved resolution
carrying the raw source values and a reason code, so callers can quarantine it
from cohort comparisons without losing the evidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

MISSING_VIDEO_TYPE = "MISSING_VIDEO_TYPE"
UNMAPPED_VIDEO_TYPE = "UNMAPPED_VIDEO_TYPE"
DUPLICATE_VIDEO_TYPE = "DUPLICATE_VIDEO_TYPE"
LABEL_ID_MISMATCH = "VIDEO_TYPE_LABEL_ID_MISMATCH"
INVALID_VIDEO_TYPE_VALUE = "INVALID_VIDEO_TYPE_VALUE"


@dataclass(frozen=True)
class VideoTypeMapping:
    mapping_version: str
    label_to_id: Mapping[str, str]
    # Former Monday names of the same label ID; used only to cross-check logs that also carry the ID.
    historical_names: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    # Business classification per ID: "base", "modifier", or absent (unconfirmed).
    classification: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_contract(cls, contract: Mapping[str, Any]) -> VideoTypeMapping:
        section = contract["video_type_cohorts"]
        if section.get("multi_select_policy") != "exact-normalized-full-set":
            raise ValueError("video type mapping must use the exact-normalized-full-set policy")
        version = section.get("mapping_version")
        labels = section.get("label_to_id")
        if not isinstance(version, str) or not version or not isinstance(labels, dict) or not labels:
            raise ValueError("video type mapping requires mapping_version and label_to_id")
        ids = [str(value) for value in labels.values()]
        if len(set(ids)) != len(ids):
            raise ValueError("video type mapping assigns one Monday label ID to several labels")
        historical = {str(key): tuple(str(name) for name in names) for key, names in (section.get("historical_label_names") or {}).items()}
        if any(key not in ids for key in historical):
            raise ValueError("historical_label_names refers to an unmapped label ID")
        classification: dict[str, str] = {}
        for role, key in (("base", "confirmed_base_ids"), ("modifier", "confirmed_modifier_ids")):
            for value in (section.get("classification") or {}).get(key) or []:
                value = str(value)
                if value not in ids or value in classification:
                    raise ValueError(f"invalid or conflicting Video Type classification for label ID {value}")
                classification[value] = role
        return cls(version, {str(label): str(value) for label, value in labels.items()}, historical, classification)

    @property
    def id_to_label(self) -> dict[str, str]:
        return {value: label for label, value in self.label_to_id.items()}


@dataclass(frozen=True)
class VideoTypeResolution:
    """Outcome of resolving one item's Video Type value; cohort_key is None when unresolved."""

    mapping_version: str
    raw_ids: tuple[str, ...]
    raw_labels: tuple[str, ...]
    cohort_key: str | None = None
    canonical_ids: tuple[str, ...] = ()
    canonical_labels: tuple[str, ...] = ()
    reason: str | None = None
    unmapped: tuple[str, ...] = field(default=())

    @property
    def resolved(self) -> bool:
        return self.cohort_key is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_version": self.mapping_version,
            "cohort_key": self.cohort_key,
            "canonical_ids": list(self.canonical_ids),
            "canonical_labels": list(self.canonical_labels),
            "raw_ids": list(self.raw_ids),
            "raw_labels": list(self.raw_labels),
            "reason": self.reason,
            "unmapped": list(self.unmapped),
        }


def _as_tuple(values: Any) -> tuple[Any, ...] | None:
    if values is None:
        return ()
    if isinstance(values, (str, int)) and not isinstance(values, bool):
        return (values,)
    if isinstance(values, (list, tuple)):
        return tuple(values)
    return None


def _id_text(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    return text if text.isdigit() else None


def resolve_video_type(mapping: VideoTypeMapping, ids: Iterable[Any] | Any = None, labels: Iterable[Any] | Any = None) -> VideoTypeResolution:
    """Resolve Monday Video Type label IDs (authoritative) and/or label texts to an exact cohort.

    When both IDs and texts are supplied they must describe the same set, otherwise the
    value is quarantined as a mismatch rather than trusting either side.
    """
    raw_id_values = _as_tuple(ids)
    raw_label_values = _as_tuple(labels)
    if raw_id_values is None or raw_label_values is None:
        return VideoTypeResolution(mapping.mapping_version, (), (), reason=INVALID_VIDEO_TYPE_VALUE)
    raw_ids = tuple(str(value) for value in raw_id_values)
    raw_labels = tuple(str(value) for value in raw_label_values)

    def unresolved(reason: str, unmapped: tuple[str, ...] = ()) -> VideoTypeResolution:
        return VideoTypeResolution(mapping.mapping_version, raw_ids, raw_labels, reason=reason, unmapped=unmapped)

    if any(_id_text(value) is None for value in raw_id_values) or any(not isinstance(value, str) or not value for value in raw_label_values):
        return unresolved(INVALID_VIDEO_TYPE_VALUE)
    if not raw_ids and not raw_labels:
        return unresolved(MISSING_VIDEO_TYPE)

    id_to_label = mapping.id_to_label
    from_ids: list[str] = []
    from_labels: list[str] = []
    unmapped: list[str] = []
    for value in raw_ids:
        if value in id_to_label:
            from_ids.append(value)
        else:
            unmapped.append(f"id:{value}")
    # With IDs present, a text may be the current or a former name of one of those IDs.
    names_for_ids = {name: value for value in raw_ids if value in id_to_label for name in (id_to_label[value], *mapping.historical_names.get(value, ()))}
    for label in raw_labels:
        if raw_ids and label in names_for_ids:
            from_labels.append(names_for_ids[label])
        elif label in mapping.label_to_id:
            from_labels.append(mapping.label_to_id[label])
        else:
            unmapped.append(f"label:{label}")
    if unmapped:
        return unresolved(UNMAPPED_VIDEO_TYPE, tuple(unmapped))
    if (raw_ids and len(set(from_ids)) != len(from_ids)) or (raw_labels and len(set(from_labels)) != len(from_labels)):
        return unresolved(DUPLICATE_VIDEO_TYPE)
    if raw_ids and raw_labels and set(from_ids) != set(from_labels):
        return unresolved(LABEL_ID_MISMATCH)
    # v1.1 cohort keys sort canonical IDs as strings ("16:5"); keep that for reproducibility.
    canonical = tuple(sorted(set(from_ids or from_labels)))
    return VideoTypeResolution(
        mapping.mapping_version,
        raw_ids,
        raw_labels,
        cohort_key=":".join(canonical),
        canonical_ids=canonical,
        canonical_labels=tuple(id_to_label[value] for value in canonical),
    )


def partition_by_cohort(records: Iterable[Mapping[str, Any]], key: str = "video_type") -> tuple[dict[str, list[Mapping[str, Any]]], list[Mapping[str, Any]]]:
    """Group records by their exact cohort key; records without a key are returned separately.

    Grouping is by string equality only, so a mixed set such as ``5:8`` never shares a
    group with ``8`` or ``5``.
    """
    cohorts: dict[str, list[Mapping[str, Any]]] = {}
    unresolved: list[Mapping[str, Any]] = []
    for record in records:
        cohort = record.get(key)
        if isinstance(cohort, str) and cohort:
            cohorts.setdefault(cohort, []).append(record)
        else:
            unresolved.append(record)
    return cohorts, unresolved
