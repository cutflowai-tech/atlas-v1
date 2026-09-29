#!/usr/bin/env python3
"""Reproduce the contract-1.5 Round 4 distribution analysis.

This script reads an immutable production extraction, applies the management
identity attestations supplied for Round 4 in memory, and emits aggregate JSON.
It never edits the extraction, the contract, or Monday.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Any

from atlas_commander.cycles import COMPLETED, CycleRecord, parse_time
from atlas_commander.ingest_verify import verify
from atlas_commander.intelligence import (
    completed_day_windows,
    evaluation_cohort,
    quality_rates,
    speed_benchmarks_v15,
)
from atlas_commander.metrics import MetricPolicy, cohort_benchmark_eligibility, deadline_result, speed_eligible
from atlas_commander.monday_source import dropdown_value_ids, dropdown_value_labels
from atlas_commander.pipeline import reconstruct_cycles, reconstruct_quality

ATTESTED_TUPLES: tuple[dict[str, Any], ...] = (
    {"source_label_id": "4", "logged_name": "Mario", "editor_id": "editor-label-4", "display_name": "Mario", "first_day": "2026-03-14", "last_day": "2026-09-28"},
    {"source_label_id": "5", "logged_name": "Anas", "editor_id": "editor-label-5", "display_name": "Anas", "first_day": "2026-05-18", "last_day": "2026-09-28"},
    {"source_label_id": "7", "logged_name": "Martin", "editor_id": "editor-label-7", "display_name": "Martin", "first_day": "2026-05-12", "last_day": "2026-09-28"},
    {"source_label_id": "8", "logged_name": "Samra", "editor_id": "editor-label-8", "display_name": "Samra", "first_day": "2026-03-14", "last_day": "2026-08-11"},
    {"source_label_id": "9", "logged_name": "Ibrahim", "editor_id": "editor-label-9", "display_name": "Ibrahim", "first_day": "2026-05-03", "last_day": "2026-09-29"},
    {"source_label_id": "10", "logged_name": "Amir", "editor_id": "editor-label-10", "display_name": "Amir", "first_day": "2026-04-22", "last_day": "2026-09-28"},
    {"source_label_id": "11", "logged_name": "Refaat", "editor_id": "editor-label-11", "display_name": "Refaat", "first_day": "2026-06-29", "last_day": "2026-09-28"},
    {"source_label_id": "5", "logged_name": "Ahmed", "editor_id": "editor-label-12", "display_name": "Ahmed", "first_day": "2026-03-14", "last_day": "2026-05-04"},
    {"source_label_id": "7", "logged_name": "Mans", "editor_id": "editor-label-14", "display_name": "Mansour", "first_day": "2026-03-14", "last_day": "2026-05-06"},
    {"source_label_id": "9", "logged_name": "Michael", "editor_id": "editor-label-13", "display_name": "Michael", "first_day": "2026-03-14", "last_day": "2026-05-02"},
)

ATTESTATION_SOURCE = "Waset management attestation recorded 2026-09-29 in docs/evidence/IDENTITY-ATTESTATION-REQUEST.md"

QUARANTINED_TUPLES = (
    ("11", "New", "invalid workflow residue"),
    ("2", "Done", "invalid workflow residue"),
    ("1", "El Baz", "unresolved historical identity"),
)

PRIOR_ANALYSIS = {
    "source": "docs/evidence/CONTRACT-1.5-IDENTITY.md and docs/evidence/BENCHMARK-STATISTIC-ANALYSIS.md",
    "completed_cycles": 861,
    "identity_attributed_cycles": 170,
    "speed_eligible_cycles": 147,
    "timing_valid_cycles": 740,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def distribution(values: Iterable[float | int]) -> dict[str, Any]:
    numbers = [float(value) for value in values]
    if not numbers:
        return {"n": 0, "min": None, "q1": None, "median": None, "q3": None, "max": None, "mean": None}
    return {
        "n": len(numbers),
        "min": _round(min(numbers)),
        "q1": _round(_quantile(numbers, 0.25)),
        "median": _round(statistics.median(numbers)),
        "q3": _round(_quantile(numbers, 0.75)),
        "max": _round(max(numbers)),
        "mean": _round(statistics.fmean(numbers)),
    }


def _tuple_ranges(column_changes: Sequence[Any], editor_column_id: str) -> dict[tuple[str, str], dict[str, Any]]:
    observed: dict[tuple[str, str], dict[str, Any]] = {}
    for change in column_changes:
        if change.column_id != editor_column_id:
            continue
        ids = dropdown_value_ids(change.value)
        labels = dropdown_value_labels(change.value)
        for source_id, logged_name in zip(ids, labels):
            key = (source_id, logged_name)
            occurred_at = parse_time(change.occurred_at)
            row = observed.setdefault(
                key,
                {"first_observed_at": occurred_at, "last_observed_at": occurred_at, "item_ids": set(), "observations": 0},
            )
            row["first_observed_at"] = min(row["first_observed_at"], occurred_at)
            row["last_observed_at"] = max(row["last_observed_at"], occurred_at)
            row["item_ids"].add(change.item_id)
            row["observations"] += 1
    return observed


def contract_with_attestations(contract: Mapping[str, Any], tuple_ranges: Mapping[tuple[str, str], Mapping[str, Any]]) -> dict[str, Any]:
    overlaid = copy.deepcopy(contract)
    editor_identity = overlaid["editor_attribution"]
    identities = editor_identity["entries"]
    existing = {(str(row.get("source_label_id")), str(row.get("logged_name"))): row for row in identities}
    overlaid_count = 0
    for attested in ATTESTED_TUPLES:
        key = (attested["source_label_id"], attested["logged_name"])
        if key not in tuple_ranges:
            raise RuntimeError(f"attested tuple absent from copied run: {key!r}")
        observed = tuple_ranges[key]
        actual = {
            "first_day": observed["first_observed_at"].date().isoformat(),
            "last_day": observed["last_observed_at"].date().isoformat(),
        }
        expected = {field: attested[field] for field in ("first_day", "last_day")}
        if actual != expected:
            raise RuntimeError(f"attested tuple range mismatch for {key!r}: expected {expected!r}, got {actual!r}")
        if key in existing:
            mapped = existing[key]
            try:
                bounds_match = (
                    parse_time(str(mapped.get("first_observed_at"))) == observed["first_observed_at"]
                    and parse_time(str(mapped.get("last_observed_at"))) == observed["last_observed_at"]
                )
            except (TypeError, ValueError):
                bounds_match = False
            if (mapped.get("editor_id") != attested["editor_id"]
                    or (mapped.get("canonical_editor_name") or mapped.get("display_name")) != attested["display_name"]
                    or mapped.get("role") != "editor"
                    or mapped.get("decision_id") != "D49"
                    or mapped.get("attestation_source") != ATTESTATION_SOURCE
                    or not bounds_match):
                raise RuntimeError(f"contract mapping conflicts with management attestation for {key!r}")
            continue
        identities.append(
            {
                "editor_id": attested["editor_id"],
                "display_name": attested["display_name"],
                "canonical_editor_name": attested["display_name"],
                "source_label_id": attested["source_label_id"],
                "logged_name": attested["logged_name"],
                "monday_person_id": attested["source_label_id"],
                "role": "editor",
                "label_names": [attested["logged_name"]],
                "first_observed_at": observed["first_observed_at"].isoformat(),
                "last_observed_at": observed["last_observed_at"].isoformat(),
                "attestation_source": ATTESTATION_SOURCE,
                "decision_id": "D49",
            }
        )
        overlaid_count += 1
    attested_keys = {(row["source_label_id"], row["logged_name"]) for row in ATTESTED_TUPLES}
    editor_identity["named_unresolved_identities"] = [
        row for row in editor_identity.get("named_unresolved_identities", [])
        if (str(row.get("source_label_id")), str(row.get("logged_name"))) not in attested_keys
    ]
    if overlaid_count:
        editor_identity["mapping_version"] = f'{editor_identity["mapping_version"]}-round4-analysis'
    return overlaid


def contract_before_attestations(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Recreate the prior identity-only baseline for an apples-to-apples replay.

    The authoritative contract now contains D49.  Removing only those ten entries lets
    this analysis measure their effect on the same immutable extraction without relying
    on a stale checkout or changing any source file.
    """
    baseline = copy.deepcopy(contract)
    attribution = baseline["editor_attribution"]
    attested_keys = {(row["source_label_id"], row["logged_name"]) for row in ATTESTED_TUPLES}
    attribution["entries"] = [
        row for row in attribution["entries"]
        if (str(row.get("source_label_id")), str(row.get("logged_name"))) not in attested_keys
    ]
    attribution["named_unresolved_identities"] = [
        {"source_label_id": source_label_id, "logged_name": logged_name, "reason": "UNMAPPED_EDITOR"}
        for source_label_id, logged_name in sorted(attested_keys)
    ]
    attribution["mapping_version"] = "monday-editor-v1.2-analysis-baseline"
    return baseline


def _completed(cycles: Iterable[CycleRecord]) -> list[CycleRecord]:
    return [cycle for cycle in cycles if cycle.state == COMPLETED]


def _attributed(cycles: Iterable[CycleRecord]) -> list[CycleRecord]:
    return [cycle for cycle in cycles if cycle.editor_id is not None]


def _common_metric_cohort(cycles: Iterable[CycleRecord]) -> list[CycleRecord]:
    result: list[CycleRecord] = []
    for cycle in cycles:
        if cycle.state != COMPLETED or cycle.editor_id is None:
            continue
        blocking = [
            reason for reason in cycle.exclusions
            if "VIDEO_TYPE" not in reason and "REQUESTED_ETA" not in reason and not reason.startswith("MISSING_ETA")
        ]
        if not blocking:
            result.append(cycle)
    return result


def _exclusion_counts(cycles: Iterable[CycleRecord]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for cycle in cycles:
        for reason in cycle.exclusions:
            counts[reason] += 1
    return dict(sorted(counts.items()))


def _editor_name(cycle: CycleRecord) -> str:
    return str((cycle.editor or {}).get("display_name") or cycle.editor_id or "unattributed")


def _deadline_rows(cycles: Sequence[CycleRecord], policy: MetricPolicy, calculated_at: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cycle in cycles:
        result = deadline_result(cycle, policy, calculated_at)
        if result is None:
            continue
        metric = result["metric"]
        rows.append(
            {
                "editor_id": cycle.editor_id,
                "editor_name": _editor_name(cycle),
                "classification": metric["result"],
                "delta_seconds": result["delta_seconds"],
            }
        )
    return rows


def _deadline_by_editor(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["editor_id"])].append(row)
    result: dict[str, dict[str, Any]] = {}
    for editor_id, values in sorted(grouped.items()):
        counts = Counter(str(value["classification"]) for value in values)
        n = len(values)
        peer = [row for row in rows if row["editor_id"] != editor_id]
        peer_late = sum(row["classification"] == "late" for row in peer)
        late_rate = counts["late"] / n
        peer_rate = (peer_late / len(peer)) if peer else None
        result[editor_id] = {
            "editor_name": values[0]["editor_name"],
            "n": n,
            "early": counts["early"],
            "on_time": counts["on_time"],
            "late": counts["late"],
            "late_rate": _round(late_rate),
            "median_delta_hours": _round(statistics.median(row["delta_seconds"] for row in values) / 3600),
            "other_editors_n": len(peer),
            "other_editors_late_rate": _round(peer_rate),
            "late_rate_difference": _round(late_rate - peer_rate) if peer_rate is not None else None,
        }
    return result


def _quality_by_editor(cycles: Sequence[CycleRecord], occurrences: Sequence[Any]) -> dict[str, dict[str, Any]]:
    editor_ids = sorted({str(cycle.editor_id) for cycle in cycles if cycle.editor_id is not None})
    result: dict[str, dict[str, Any]] = {}
    for editor_id in editor_ids:
        facts = quality_rates(editor_id=editor_id, occurrences=occurrences, eligible_cycles=cycles)
        name = next(_editor_name(cycle) for cycle in cycles if cycle.editor_id == editor_id)
        result[editor_id] = {
            "editor_name": name,
            "eligible_projects": facts["eligible_completed_projects"],
            "scored_positive_occurrences": facts["positive_count"],
            "scored_negative_occurrences": facts["negative_count"],
            "positive_project_rate": _round(facts["positive_rate"]),
            "negative_project_rate": _round(facts["negative_rate"]),
        }
    return result


def _revision_by_editor(cycles: Sequence[CycleRecord]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[CycleRecord]] = defaultdict(list)
    for cycle in cycles:
        if cycle.editor_id is not None:
            grouped[str(cycle.editor_id)].append(cycle)
    result: dict[str, dict[str, Any]] = {}
    for editor_id, records in sorted(grouped.items()):
        client_projects = [cycle for cycle in records if int(cycle.revision_context.get("client_revision_events", 0)) > 0]
        internal_projects = [cycle for cycle in records if int(cycle.revision_context.get("internal_revision_events", 0)) > 0]
        result[editor_id] = {
            "editor_name": _editor_name(records[0]),
            "eligible_projects": len(records),
            "client_revision_projects": len(client_projects),
            "client_revision_events": sum(int(cycle.revision_context.get("client_revision_events", 0)) for cycle in records),
            "client_revision_project_rate": _round(len(client_projects) / len(records)),
            "internal_revision_projects": len(internal_projects),
            "internal_revision_events": sum(int(cycle.revision_context.get("internal_revision_events", 0)) for cycle in records),
            "internal_revision_project_rate": _round(len(internal_projects) / len(records)),
            "context_only": True,
            "affects_scoring": False,
        }
    return result


def _speed_by_editor(cycles: Sequence[CycleRecord], policy: MetricPolicy, rule: Mapping[str, Any], calculated_at: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for editor_id in sorted({str(cycle.editor_id) for cycle in cycles if cycle.editor_id is not None}):
        editor_name = next(_editor_name(cycle) for cycle in cycles if cycle.editor_id == editor_id)
        facts = speed_benchmarks_v15(editor_id=editor_id, cycles=cycles, mapping=policy.video_types, rule=rule, calculated_at=calculated_at)
        for benchmark in facts["cohorts"]:
            rows.append(
                {
                    "editor_id": editor_id,
                    "editor_name": editor_name,
                    "video_type": benchmark["cohort_key"],
                    "editor_projects": benchmark["editor_sample_size"],
                    "editor_median_hours": _round(benchmark["editor_median_seconds"] / 3600),
                    "other_editors_projects": benchmark["comparator_sample_size"],
                    "other_editors_count": benchmark["comparator_editor_count"],
                    "other_editors_median_hours": _round(benchmark["comparator_median_seconds"] / 3600) if benchmark["comparator_median_seconds"] is not None else None,
                    "relative_difference": _round(benchmark["editor_vs_comparator_pct"]),
                    "state": benchmark["verdict"],
                    "reason": benchmark["reason"],
                }
            )
    return rows


def _window_analysis(cycles: Sequence[CycleRecord], occurrences: Sequence[Any], policy: MetricPolicy, contract: Mapping[str, Any], calculated_at: str) -> dict[str, Any]:
    deadline_rows = _deadline_rows(cycles, policy, calculated_at)
    quality = _quality_by_editor(cycles, occurrences)
    revisions = _revision_by_editor(cycles)
    speed = _speed_by_editor(cycles, policy, {**contract["speed_benchmark"], **contract["speed_benchmark"]["component"]}, calculated_at)
    return {
        "eligible_projects": len(cycles),
        "projects_by_editor": dict(sorted(Counter(_editor_name(cycle) for cycle in cycles).items())),
        "quality_by_editor": quality,
        "revision_context_by_editor": revisions,
        "deadline_by_editor": _deadline_by_editor(deadline_rows),
        "speed_by_editor_and_video_type": speed,
        "distributions": {
            "projects_per_editor": distribution(row["eligible_projects"] for row in quality.values()),
            "quality_positive_project_rate": distribution(row["positive_project_rate"] for row in quality.values()),
            "quality_negative_project_rate": distribution(row["negative_project_rate"] for row in quality.values()),
            "client_revision_project_rate": distribution(row["client_revision_project_rate"] for row in revisions.values()),
            "internal_revision_project_rate": distribution(row["internal_revision_project_rate"] for row in revisions.values()),
            "deadline_projects_per_editor": distribution(row["n"] for row in _deadline_by_editor(deadline_rows).values()),
            "deadline_late_rate": distribution(row["late_rate"] for row in _deadline_by_editor(deadline_rows).values()),
            "deadline_late_rate_difference": distribution(row["late_rate_difference"] for row in _deadline_by_editor(deadline_rows).values() if row["late_rate_difference"] is not None),
            "speed_editor_projects_per_pair": distribution(row["editor_projects"] for row in speed),
            "speed_other_editor_projects_per_pair": distribution(row["other_editors_projects"] for row in speed),
            "speed_relative_difference": distribution(row["relative_difference"] for row in speed if row["relative_difference"] is not None),
        },
    }


def _quality_label_counts(occurrences: Sequence[Any], cohort: Sequence[CycleRecord]) -> dict[str, Any]:
    item_ids = {cycle.monday_item_id for cycle in cohort}
    relevant = [occurrence for occurrence in occurrences if occurrence["evidence"]["monday_item_id"] in item_ids]
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for occurrence in relevant:
        taxonomy = str(occurrence["evidence"]["source_values"].get("label_class") or "Negative")
        label = str(occurrence["performance_label"])
        key = (taxonomy, label)
        row = rows.setdefault(key, {"taxonomy": taxonomy, "label": label, "occurrences": 0, "projects": set()})
        row["occurrences"] += 1
        row["projects"].add(occurrence["evidence"]["monday_item_id"])
    return {
        "by_label": [
            {"taxonomy": row["taxonomy"], "label": row["label"], "occurrences": row["occurrences"], "projects": len(row["projects"])}
            for _, row in sorted(rows.items())
        ],
        "by_taxonomy": dict(sorted(Counter(str(occurrence["evidence"]["source_values"].get("label_class") or "Negative") for occurrence in relevant).items())),
    }


def _trend(current: Mapping[str, Any], comparison: Mapping[str, Any]) -> dict[str, Any]:
    quality_rows: list[dict[str, Any]] = []
    current_quality = current["quality_by_editor"]
    comparison_quality = comparison["quality_by_editor"]
    for editor_id in sorted(set(current_quality) & set(comparison_quality)):
        current_row = current_quality[editor_id]
        prior_row = comparison_quality[editor_id]
        quality_rows.append(
            {
                "editor_id": editor_id,
                "editor_name": current_row["editor_name"],
                "current_n": current_row["eligible_projects"],
                "comparison_n": prior_row["eligible_projects"],
                "positive_rate_change": _round(current_row["positive_project_rate"] - prior_row["positive_project_rate"]),
                "negative_rate_change": _round(current_row["negative_project_rate"] - prior_row["negative_project_rate"]),
            }
        )
    deadline_rows: list[dict[str, Any]] = []
    current_deadline = current["deadline_by_editor"]
    comparison_deadline = comparison["deadline_by_editor"]
    for editor_id in sorted(set(current_deadline) & set(comparison_deadline)):
        now = current_deadline[editor_id]
        prior = comparison_deadline[editor_id]
        deadline_rows.append(
            {
                "editor_id": editor_id,
                "editor_name": now["editor_name"],
                "current_n": now["n"],
                "comparison_n": prior["n"],
                "late_rate_change": _round(now["late_rate"] - prior["late_rate"]),
            }
        )
    def speed_key(row: Mapping[str, Any]) -> tuple[str, str]:
        return str(row["editor_id"]), str(row["video_type"])
    now_speed = {speed_key(row): row for row in current["speed_by_editor_and_video_type"]}
    prior_speed = {speed_key(row): row for row in comparison["speed_by_editor_and_video_type"]}
    speed_rows: list[dict[str, Any]] = []
    for key in sorted(set(now_speed) & set(prior_speed)):
        now = now_speed[key]
        prior = prior_speed[key]
        speed_rows.append(
            {
                "editor_id": key[0],
                "editor_name": now["editor_name"],
                "video_type": key[1],
                "current_n": now["editor_projects"],
                "comparison_n": prior["editor_projects"],
                "median_hours_change": _round(now["editor_median_hours"] - prior["editor_median_hours"]),
            }
        )
    return {
        "quality": quality_rows,
        "deadline": deadline_rows,
        "speed": speed_rows,
        "distributions": {
            "quality_positive_rate_change": distribution(row["positive_rate_change"] for row in quality_rows),
            "quality_negative_rate_change": distribution(row["negative_rate_change"] for row in quality_rows),
            "deadline_late_rate_change": distribution(row["late_rate_change"] for row in deadline_rows),
            "speed_median_hours_change": distribution(row["median_hours_change"] for row in speed_rows),
        },
    }


def _symmetric_class(value: float, band: float, low: str, middle: str, high: str) -> str:
    return low if value < -band else high if value > band else middle


def _speed_sensitivity(cycles: Sequence[CycleRecord], policy: MetricPolicy) -> list[dict[str, Any]]:
    eligible = [
        cycle for cycle in cycles
        if speed_eligible(cycle) and cycle.video_type is not None
        and cohort_benchmark_eligibility(cycle.video_type.canonical_ids, policy.video_types)[0]
    ]
    by_type: dict[str, list[CycleRecord]] = defaultdict(list)
    for cycle in eligible:
        assert cycle.cohort_key is not None
        by_type[cycle.cohort_key].append(cycle)
    grids: list[dict[str, Any]] = []
    for editor_min, comparator_min, comparator_editors_min, band in product(
        (3, 5, 8, 10), (5, 10, 15), (1, 2), (10.0, 15.0, 20.0, 25.0, 30.0)
    ):
        pairs = 0
        stable_pairs = 0
        agreements = 0
        perturbations = 0
        for cohort in by_type.values():
            for editor_id in sorted({str(cycle.editor_id) for cycle in cohort}):
                mine = [int(cycle.duration_seconds) for cycle in cohort if cycle.editor_id == editor_id and cycle.duration_seconds is not None]
                peers = [int(cycle.duration_seconds) for cycle in cohort if cycle.editor_id != editor_id and cycle.duration_seconds is not None]
                peer_editor_count = len({cycle.editor_id for cycle in cohort if cycle.editor_id != editor_id})
                if len(mine) < editor_min or len(peers) < comparator_min or peer_editor_count < comparator_editors_min:
                    continue
                base_pct = 100 * (statistics.median(mine) - statistics.median(peers)) / statistics.median(peers)
                base = _symmetric_class(base_pct, band, "faster", "similar", "slower")
                outcomes: list[str] = []
                for index in range(len(mine)):
                    reduced = mine[:index] + mine[index + 1:]
                    if len(reduced) < editor_min:
                        outcomes.append("not_classifiable")
                    else:
                        pct = 100 * (statistics.median(reduced) - statistics.median(peers)) / statistics.median(peers)
                        outcomes.append(_symmetric_class(pct, band, "faster", "similar", "slower"))
                for index in range(len(peers)):
                    reduced = peers[:index] + peers[index + 1:]
                    if len(reduced) < comparator_min:
                        outcomes.append("not_classifiable")
                    else:
                        pct = 100 * (statistics.median(mine) - statistics.median(reduced)) / statistics.median(reduced)
                        outcomes.append(_symmetric_class(pct, band, "faster", "similar", "slower"))
                pairs += 1
                stable_pairs += bool(outcomes) and all(outcome == base for outcome in outcomes)
                agreements += sum(outcome == base for outcome in outcomes)
                perturbations += len(outcomes)
        grids.append(
            {
                "minimum_editor_projects": editor_min,
                "minimum_comparator_projects": comparator_min,
                "minimum_comparator_editors": comparator_editors_min,
                "symmetric_band_percent": band,
                "classifiable_editor_type_pairs": pairs,
                "fully_stable_pairs": stable_pairs,
                "fully_stable_pair_rate": _round(stable_pairs / pairs) if pairs else None,
                "leave_one_project_out_agreement": _round(agreements / perturbations) if perturbations else None,
                "perturbations": perturbations,
            }
        )
    return grids


def _deadline_sensitivity(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        grouped[str(row["editor_id"])].append(int(row["classification"] == "late"))
    grids: list[dict[str, Any]] = []
    for editor_min, comparator_min, band in product((5, 8, 10, 12), (30, 60, 100), (0.10, 0.15, 0.20, 0.25)):
        editors = 0
        stable_editors = 0
        agreements = 0
        perturbations = 0
        for editor_id, mine in sorted(grouped.items()):
            peers = [value for other_id, values in grouped.items() if other_id != editor_id for value in values]
            if len(mine) < editor_min or len(peers) < comparator_min:
                continue
            base_difference = statistics.fmean(mine) - statistics.fmean(peers)
            base = _symmetric_class(base_difference, band, "better", "similar", "worse")
            outcomes: list[str] = []
            for index in range(len(mine)):
                reduced = mine[:index] + mine[index + 1:]
                if len(reduced) < editor_min:
                    outcomes.append("not_classifiable")
                else:
                    outcomes.append(_symmetric_class(statistics.fmean(reduced) - statistics.fmean(peers), band, "better", "similar", "worse"))
            for index in range(len(peers)):
                reduced = peers[:index] + peers[index + 1:]
                if len(reduced) < comparator_min:
                    outcomes.append("not_classifiable")
                else:
                    outcomes.append(_symmetric_class(statistics.fmean(mine) - statistics.fmean(reduced), band, "better", "similar", "worse"))
            editors += 1
            stable_editors += bool(outcomes) and all(outcome == base for outcome in outcomes)
            agreements += sum(outcome == base for outcome in outcomes)
            perturbations += len(outcomes)
        grids.append(
            {
                "minimum_editor_projects": editor_min,
                "minimum_comparator_projects": comparator_min,
                "symmetric_band_rate_points": band,
                "classifiable_editors": editors,
                "fully_stable_editors": stable_editors,
                "fully_stable_editor_rate": _round(stable_editors / editors) if editors else None,
                "leave_one_project_out_agreement": _round(agreements / perturbations) if perturbations else None,
                "perturbations": perturbations,
            }
        )
    return grids


def _proposed_overall_lookup() -> dict[str, str]:
    """A transparent semantic candidate for D37/D41; this is not activated here."""
    states = ("Positive", "Neutral", "Negative", "Not classifiable")
    lookup: dict[str, str] = {}
    for quality, speed, deadline in product(states, repeat=3):
        values = (quality, speed, deadline)
        classifiable = [value for value in values if value != "Not classifiable"]
        if len(classifiable) < 2:
            continue
        negatives = classifiable.count("Negative")
        positives = classifiable.count("Positive")
        if negatives >= 2:
            status = "Below Expectations"
        elif negatives == 1:
            status = "Mixed"
        elif positives >= 2:
            status = "Strong"
        else:
            status = "Good"
        lookup["|".join(values)] = status
    return dict(sorted(lookup.items()))


def _matching_grid(grids: Sequence[Mapping[str, Any]], **values: Any) -> Mapping[str, Any]:
    return next(row for row in grids if all(row[key] == value for key, value in values.items()))


def _threshold_assessment(
    current: Mapping[str, Any],
    comparison: Mapping[str, Any],
    trend: Mapping[str, Any],
    current_speed_sensitivity: Sequence[Mapping[str, Any]],
    comparison_speed_sensitivity: Sequence[Mapping[str, Any]],
    current_deadline_sensitivity: Sequence[Mapping[str, Any]],
    comparison_deadline_sensitivity: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    quality = current["quality_by_editor"]
    comparison_quality = comparison["quality_by_editor"]
    speed = current["speed_by_editor_and_video_type"]
    comparison_speed = comparison["speed_by_editor_and_video_type"]
    deadline = current["deadline_by_editor"]

    def speed_eligible_editors(rows: Sequence[Mapping[str, Any]]) -> list[str]:
        return sorted({
            str(row["editor_id"])
            for row in rows
            if row["editor_projects"] >= 5 and row["other_editors_projects"] >= 10 and row["other_editors_count"] >= 2
        })

    current_speed_editors = speed_eligible_editors(speed)
    comparison_speed_editors = speed_eligible_editors(comparison_speed)
    current_deadline_editors = sorted(editor_id for editor_id, row in deadline.items()
                                      if row["n"] >= 10 and row["other_editors_n"] >= 60)
    comparison_deadline_editors = sorted(editor_id for editor_id, row in comparison["deadline_by_editor"].items()
                                         if row["n"] >= 10 and row["other_editors_n"] >= 60)
    return {
        "quality": {
            "status": "leave_open",
            "sample_floor_candidate": 10,
            "observations": {
                "editors": len(quality),
                "editors_with_scored_positive_occurrence": sum(row["scored_positive_occurrences"] > 0 for row in quality.values()),
                "editors_with_scored_negative_occurrence": sum(row["scored_negative_occurrences"] > 0 for row in quality.values()),
                "editors_meeting_sample_candidate_current": sum(row["eligible_projects"] >= 10 for row in quality.values()),
                "editors_meeting_sample_candidate_comparison": sum(row["eligible_projects"] >= 10 for row in comparison_quality.values()),
            },
            "reason": "A ten-project floor is a reviewable sampling candidate (one occurrence changes a rate by at most ten percentage points, and seven Editors meet it in each window), but N and P remain open. Only two current Editors have any scored positive occurrence and two have any scored negative occurrence, label completeness is unproven, and no independent outcome identifies acceptable rate cutoffs. Without N and P the Quality component remains Not classifiable.",
        },
        "speed": {
            "status": "proposed_for_management_approval",
            "proposed_values": {
                "minimum_editor_sample_size": 5,
                "minimum_comparator_sample_size": 10,
                "minimum_comparator_editor_count": 2,
                "faster_band": -25.0,
                "similar_band": 0.0,
                "slower_band": 25.0,
            },
            "stability_evidence": {
                "current": _matching_grid(current_speed_sensitivity, minimum_editor_projects=5, minimum_comparator_projects=10, minimum_comparator_editors=2, symmetric_band_percent=25.0),
                "comparison": _matching_grid(comparison_speed_sensitivity, minimum_editor_projects=5, minimum_comparator_projects=10, minimum_comparator_editors=2, symmetric_band_percent=25.0),
            },
            "observations": {
                "editor_video_type_pairs": len(speed),
                "pairs_with_editor_n_at_least_5": sum(row["editor_projects"] >= 5 for row in speed),
                "pairs_with_other_projects_at_least_5": sum(row["other_editors_projects"] >= 5 for row in speed),
                "pairs_with_other_editors_at_least_2": sum(row["other_editors_count"] >= 2 for row in speed),
                "eligible_editors_current": current_speed_editors,
                "eligible_editors_comparison": comparison_speed_editors,
            },
            "reason": "This candidate is a calibration proposal, not an approved truth boundary: it requires at least five subject projects and ten peer projects from at least two other Editors, preventing a nominal team comparison from being one person's history. It treats relative differences inside ±25% as Similar. It retains nine current pairs with 91.7% perturbation agreement and ten comparison pairs with 100% agreement; management must still approve the materiality meaning.",
        },
        "deadline": {
            "status": "proposed_for_management_approval",
            "proposed_values": {
                "minimum_editor_sample_size": 10,
                "minimum_comparator_sample_size": 60,
                "better_band": -0.15,
                "similar_band": 0.0,
                "worse_band": 0.15,
            },
            "stability_evidence": {
                "current": _matching_grid(current_deadline_sensitivity, minimum_editor_projects=10, minimum_comparator_projects=60, symmetric_band_rate_points=0.15),
                "comparison": _matching_grid(comparison_deadline_sensitivity, minimum_editor_projects=10, minimum_comparator_projects=60, symmetric_band_rate_points=0.15),
            },
            "observations": {
                "editors": len(deadline),
                "editors_with_n_at_least_5": sum(row["n"] >= 5 for row in deadline.values()),
                "editors_with_n_at_least_10": sum(row["n"] >= 10 for row in deadline.values()),
                "eligible_editors_current": current_deadline_editors,
                "eligible_editors_comparison": comparison_deadline_editors,
            },
            "reason": "This candidate requires ten subject and sixty peer deadline-classifiable projects and treats a ±15 percentage-point leave-one-out late-rate difference as Similar. It is supported as a stability calibration by the cited perturbation row, but the business meaning still requires approval.",
        },
        "trend": {
            "status": "leave_open",
            "sample_floor_candidate": {"current_window": 10, "comparison_window": 10},
            "combination_candidate": "Once component-specific material thresholds exist and at least two components are classifiable: more Improving than Declining => Improving; more Declining than Improving => Declining; a tie => Stable. Counts are symmetric and no magnitudes are averaged.",
            "observations": {
                "quality_editors_with_both_windows": len(trend["quality"]),
                "deadline_editors_with_both_windows": len(trend["deadline"]),
                "speed_pairs_with_both_windows": len(trend["speed"]),
            },
            "reason": "Ten projects in each window is a sampling candidate and seven Editors have paired factual inputs, but all material-change thresholds remain open. Only one adjacent pair of windows is available, with no labelled durable-change outcome. More importantly, the current contract has one material_change_threshold applied to both rates (unitless proportions) and speed (seconds), so one defensible scalar cannot represent all measurements. Zero Trend labels are currently eligible because no materiality rule is approved.",
        },
        "overall": {
            "status": "proposed_for_management_approval",
            "proposed_semantics": {
                "minimum_classifiable_components": 2,
                "rule": "two or more Negative => Below Expectations; exactly one Negative => Mixed; otherwise two or more Positive => Strong; otherwise => Good",
                "lookup_table": _proposed_overall_lookup(),
            },
            "candidate_eligible_editors": {
                "current": sorted(set(current_speed_editors) & set(current_deadline_editors)),
                "comparison": sorted(set(comparison_speed_editors) & set(comparison_deadline_editors)),
            },
            "reason": "The lookup is an explicit, auditable semantic proposal rather than a fitted numeric score. It preserves D41's two-component minimum and gives any single Negative a visible Mixed result. It remains rule_not_approved until management accepts it and the component rules.",
        },
    }


def analyze(run_dir: Path, contract_path: Path) -> dict[str, Any]:
    verification = verify(run_dir, require_production=True)
    if not verification["passed"]:
        raise RuntimeError(f"copied production run failed verification: {verification['failures']}")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    extract = json.loads((run_dir / "extract.json").read_text(encoding="utf-8"))
    baseline = reconstruct_cycles(
        extract["activity"],
        contract_before_attestations(contract),
        items_payload=extract.get("items"),
        ingestion=extract.get("ingestion"),
    )
    editor_column_id = contract["source_board"]["editor_column_id"]
    tuple_ranges = _tuple_ranges(baseline.column_changes, editor_column_id)
    contract_identity_keys = {
        (str(row.get("source_label_id")), str(row.get("logged_name")))
        for row in contract["editor_attribution"]["entries"]
    }
    overlaid_contract = contract_with_attestations(contract, tuple_ranges)
    reconstructed = reconstruct_cycles(
        extract["activity"],
        overlaid_contract,
        items_payload=extract.get("items"),
        ingestion=extract.get("ingestion"),
    )
    calculated_at = str(verification["retrieved_at"])
    quality = reconstruct_quality(reconstructed, overlaid_contract, calculated_at)
    policy = MetricPolicy.from_contract(overlaid_contract)
    as_of = datetime.fromisoformat(calculated_at.replace("Z", "+00:00"))
    window_days = int(overlaid_contract["time_windows"]["current_window"]["completed_days"])
    windows = completed_day_windows(as_of=as_of, days=window_days)
    partitioned = evaluation_cohort(reconstructed.cycles, as_of=as_of, days=window_days, rule_version=overlaid_contract["time_windows"]["rule_version"])
    current = partitioned["current"]
    comparison = partitioned["comparison"]
    current_analysis = _window_analysis(current, quality.occurrences, policy, overlaid_contract, calculated_at)
    comparison_analysis = _window_analysis(comparison, quality.occurrences, policy, overlaid_contract, calculated_at)
    trend = _trend(current_analysis, comparison_analysis)
    current_deadline_rows = _deadline_rows(current, policy, calculated_at)
    comparison_deadline_rows = _deadline_rows(comparison, policy, calculated_at)
    current_speed_sensitivity = _speed_sensitivity(current, policy)
    comparison_speed_sensitivity = _speed_sensitivity(comparison, policy)
    current_deadline_sensitivity = _deadline_sensitivity(current_deadline_rows)
    comparison_deadline_sensitivity = _deadline_sensitivity(comparison_deadline_rows)
    baseline_completed = _completed(baseline.cycles)
    completed = _completed(reconstructed.cycles)
    all_time_cohort = _common_metric_cohort(completed)
    all_time_analysis = _window_analysis(all_time_cohort, quality.occurrences, policy, overlaid_contract, calculated_at)
    quarantined_counts = {
        f"({source_id},{name})": {
            "reason": reason,
            "projects": len(tuple_ranges.get((source_id, name), {}).get("item_ids", set())),
            "first_observed_at": tuple_ranges.get((source_id, name), {}).get("first_observed_at").isoformat() if (source_id, name) in tuple_ranges else None,
            "last_observed_at": tuple_ranges.get((source_id, name), {}).get("last_observed_at").isoformat() if (source_id, name) in tuple_ranges else None,
        }
        for source_id, name, reason in QUARANTINED_TUPLES
    }
    all_time_speed_eligible = [
        cycle for cycle in completed
        if speed_eligible(cycle)
    ]
    label_counts = {
        "current": _quality_label_counts(quality.occurrences, current),
        "comparison": _quality_label_counts(quality.occurrences, comparison),
    }
    report: dict[str, Any] = {
        "analysis_version": "round4-distribution-v1",
        "sources": {
            "production_run": verification["run_id"],
            "run_id": verification["run_id"],
            "retrieved_at": verification["retrieved_at"],
            "manifest_sha256": _sha256(run_dir / "manifest.json"),
            "contract": contract_path.name,
            "contract_sha256": _sha256(contract_path),
            "contract_version": contract["contract_version"],
        },
        "verification": {
            "status": "passed",
            "raw_files_checked": verification["raw_files_checked"],
            "update_windows": verification["windows"]["read"],
            "split_windows": verification["windows"]["split"],
            "update_events": verification["activity_logs"].get("update_column_value", 0),
            "snapshot_items": verification["items"],
            "items_with_complete_history": verification["complete_history_items"],
            "items_without_complete_history": verification["items"] - verification["complete_history_items"],
        },
        "identity": {
            "attestations_asserted": [
                {
                    **{key: row[key] for key in ("source_label_id", "logged_name", "editor_id", "display_name")},
                    "mapping_source": "contract" if (row["source_label_id"], row["logged_name"]) in contract_identity_keys else "analysis_overlay",
                    "first_observed_at": tuple_ranges[(row["source_label_id"], row["logged_name"])]["first_observed_at"].isoformat(),
                    "last_observed_at": tuple_ranges[(row["source_label_id"], row["logged_name"])]["last_observed_at"].isoformat(),
                    "projects": len(tuple_ranges[(row["source_label_id"], row["logged_name"])]["item_ids"]),
                }
                for row in ATTESTED_TUPLES
            ],
            "quarantined": quarantined_counts,
        },
        "coverage": {
            "completed_cycles": len(completed),
            "baseline_identity_attributed_cycles": len(_attributed(baseline_completed)),
            "post_attestation_identity_attributed_cycles": len(_attributed(completed)),
            "post_attestation_unattributed_cycles": len(completed) - len(_attributed(completed)),
            "all_time_common_metric_cohort": len(all_time_cohort),
            "all_time_speed_eligible_cycles": len(all_time_speed_eligible),
            "completed_cycle_exclusions": _exclusion_counts(completed),
            "window_partition": {
                "current_projects": partitioned["coverage"]["current_projects"],
                "comparison_projects": partitioned["coverage"]["comparison_projects"],
                "excluded_projects": partitioned["coverage"]["excluded_projects"],
                "outside_window_projects": partitioned["coverage"]["outside_window_projects"],
                "excluded_reasons": dict(sorted(Counter(reason for row in partitioned["coverage"]["exclusions"] for reason in row["reasons"]).items())),
                "metric_specific_exclusion_reasons": dict(sorted(Counter(reason for row in partitioned["coverage"]["metric_specific_exclusions"] for reason in row["reasons"]).items())),
            },
            "quality_quarantine_reasons": dict(sorted(Counter(str(row["reason"]) for row in quality.quarantined).items())),
        },
        "windows": {
            "timezone": windows.timezone,
            "current": {"start": windows.current_start.isoformat(), "end": windows.current_end.isoformat()},
            "comparison": {"start": windows.comparison_start.isoformat(), "end": windows.comparison_end.isoformat()},
        },
        "current": current_analysis,
        "comparison": comparison_analysis,
        "all_time": all_time_analysis,
        "quality_labels": label_counts,
        "trend": trend,
        "sensitivity": {
            "method": "Deterministic leave-one-project-out perturbation of each otherwise classifiable Editor/Video-Type or Editor deadline comparison in both windows; dropping below a candidate sample floor counts as a classification disagreement.",
            "current": {"speed": current_speed_sensitivity, "deadline": current_deadline_sensitivity},
            "comparison": {"speed": comparison_speed_sensitivity, "deadline": comparison_deadline_sensitivity},
        },
    }
    report["threshold_assessment"] = _threshold_assessment(
        current_analysis,
        comparison_analysis,
        trend,
        current_speed_sensitivity,
        comparison_speed_sensitivity,
        current_deadline_sensitivity,
        comparison_deadline_sensitivity,
    )
    report["prior_comparison"] = {
        "prior": PRIOR_ANALYSIS,
        "current_completed_cycles_delta": len(completed) - PRIOR_ANALYSIS["completed_cycles"],
        "identity_attributed_cycles_delta": len(_attributed(completed)) - PRIOR_ANALYSIS["identity_attributed_cycles"],
        "speed_eligible_cycles_delta": len(all_time_speed_eligible) - PRIOR_ANALYSIS["speed_eligible_cycles"],
        "note": "The copied run is newer than the prior reports and the identity overlay is broader; deltas are not solely identity effects unless completed-cycle counts are equal.",
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=Path("config/monday-contract-v1.5.json"))
    args = parser.parse_args()
    report = analyze(args.run_dir.resolve(), args.contract.resolve())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
