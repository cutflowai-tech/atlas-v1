"""CEO Dashboard view model: a summary layer over Editor Profiles (presentation only).

Every value here is copied or counted from editor-profile documents, which the metric engine
built. Nothing is recomputed from Monday data, no metric is redefined, and no judgement is
added: slots for unapproved management rules come from ``atlas_commander.management`` and are
always empty. Each block names the profile field it was taken from (``source``), so any number
on the dashboard can be traced to the Editor Profile and from there to Monday events.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Mapping
from typing import Any

from atlas_commander.management import editor_intelligence, team_intelligence

DASHBOARD_VERSION = "ceo-dashboard-v0.1"
COMPARED = ("faster_than_team_median", "slower_than_team_median", "equal_to_team_median")


def month_name(month: str) -> str:
    """``2026-09`` -> ``September 2026``."""
    year, number = month.split("-")
    return f"{calendar.month_name[int(number)]} {year}"


def _item_id(cycle_id: str) -> str:
    return cycle_id.rsplit(":", 1)[-1]


def _speed(profile: Mapping[str, Any]) -> dict[str, Any]:
    speed = profile["speed"]
    cohorts = []
    for cohort in sorted(speed["cohorts"], key=lambda c: (-c["editor_sample_size"], c["cohort_key"])):  # display order only
        alone = cohort["comparison_status"] == "no_other_editors_in_cohort"
        cohorts.append({
            "cohort_key": cohort["cohort_key"], "labels": list(cohort["cohort_labels"]),
            "editor_sample_size": cohort["editor_sample_size"], "editor_median_seconds": cohort["editor_median_seconds"],
            "team_sample_size": cohort["team_sample_size"], "team_editor_count": cohort["team_editor_count"],
            "team_median_seconds": None if alone else cohort["team_median_seconds"],
            "editor_vs_team_median_pct": None if alone else cohort["editor_vs_team_median_pct"],
            "conclusion": cohort["conclusion"], "comparison_status": cohort["comparison_status"],
            "benchmark_eligible": cohort.get("benchmark_eligible"),
            "team_typical_range_seconds": None if alone else cohort.get("team_typical_range_seconds"),
            "editor_project_ids": [_item_id(cycle_id) for cycle_id in cohort.get("editor_cycle_ids") or []],
        })
    status_counts: dict[str, int] = {}
    for cohort in cohorts:
        status_counts[cohort["comparison_status"]] = status_counts.get(cohort["comparison_status"], 0) + 1
    return {"source": "speed.cohorts", "benchmark_statistic": speed["benchmark_statistic"],
            "minimum_editor_sample_size": speed["minimum_editor_sample_size"], "cohorts": cohorts,
            "compared_cohorts": [c for c in cohorts if c["conclusion"] in COMPARED], "comparison_status_counts": status_counts,
            **({"leave_one_out": speed.get("leave_one_out"),
                "minimum_comparator_sample_size": speed.get("minimum_comparator_sample_size"),
                "component": speed.get("component")} if "leave_one_out" in speed else {})}


def _deadline(profile: Mapping[str, Any]) -> dict[str, Any]:
    summary = profile["deadline"]["summary"]
    keys = ("evaluated", "early", "on_time", "late", "early_rate", "on_time_rate", "late_rate", "median_delta_seconds",
            "not_classifiable_insufficient_eta_precision", "not_classifiable_missing_eta", "not_evaluated_other")
    return {"source": "deadline.summary", "rule_version": profile["deadline"]["rule_version"],
            "requested_eta_selection": profile["deadline"].get("requested_eta_selection"), **{key: summary.get(key) for key in keys}}


def _quality(profile: Mapping[str, Any]) -> dict[str, Any]:
    quality = profile["quality"]
    negative = quality["negative"]
    result = {"source": "quality", "total_occurrences": negative["total_occurrences"], "projects_with_issues": negative["projects_with_issues"],
            "completed_projects_attributed": negative["completed_projects_attributed"],
            "by_label": [{"label": row["label"], "occurrences": row["occurrences"], "monday_item_ids": list(row["monday_item_ids"])}
                         for row in negative["by_label"]],
            "for_bonus_context_projects": len(quality["for_bonus_context"]["projects"])}
    if "context" in quality:
        def block(name: str) -> dict[str, Any]:
            value = quality[name]
            return {
                "total_occurrences": value["total_occurrences"],
                "projects_with_labels": value["projects_with_issues"],
                "completed_projects_attributed": value["completed_projects_attributed"],
                "by_label": [
                    {"label": row["label"], "occurrences": row["occurrences"], "monday_item_ids": list(row["monday_item_ids"])}
                    for row in value["by_label"]
                ],
            }

        result.update({
            "taxonomy_enabled": True,
            "negative": block("negative"),
            "positive": block("positive"),
            "context": block("context"),
            "rates": quality.get("rates"),
            "component": quality.get("component"),
        })
    return result


PROJECT_FIELDS = ("monday_item_id", "state", "in_progress_at", "ready_for_approval_at", "duration_seconds", "cohort_key", "cohort_labels",
                  "speed_eligible", "requested_eta", "requested_eta_issue", "requested_eta_observed_at", "deadline_result", "deadline_delta_seconds",
                  "quality_labels", "client_revision_events", "exclusions", "flags", "evidence_event_ids",
                  "requested_eta_changes_ignored_after_ready_for_approval")


def _projects(profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The profile's project rows (the evidence behind every figure), most recent Ready For Approval first."""
    rows = [{key: row.get(key) for key in PROJECT_FIELDS} for row in profile["projects"]]
    return sorted(rows, key=lambda row: (row["ready_for_approval_at"] or "", row["monday_item_id"]), reverse=True)


def _events(profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Dated facts already in the profile: each completed project's first Ready For Approval (with its deadline result, if
    classified) and each Monday Performance Issues label, at the time it was added. Revision events are not dated in the
    profile, so they appear only as context on their project."""
    events = [{"kind": "delivery", "at": row["ready_for_approval_at"], "monday_item_id": row["monday_item_id"],
               "deadline_result": row["deadline_result"], "deadline_delta_seconds": row["deadline_delta_seconds"],
               "cohort_labels": list(row["cohort_labels"]), "client_revision_events": row["client_revision_events"]}
              for row in profile["projects"] if row["state"] == "completed" and row["ready_for_approval_at"]]
    for occurrence in profile["quality"]["occurrences"]:
        timestamps = occurrence["evidence"].get("source_timestamps") or []
        label_class = str((occurrence["evidence"].get("source_values") or {}).get("label_class") or "Negative").title()
        kind = {"Positive": "positive_label", "Negative": "issue_label", "Context": "context_label"}.get(label_class, "context_label")
        events.append({"kind": kind, "label_class": label_class, "at": timestamps[0] if timestamps else None,
                       "monday_item_id": occurrence["evidence"]["monday_item_id"], "label": occurrence["performance_label"],
                       "column_id": occurrence.get("label_column_id"),
                       "event_ids": list(occurrence["evidence"].get("event_ids") or [])})
    return sorted((event for event in events if event["at"]), key=lambda event: (event["at"], event["kind"], event["monday_item_id"]))


def _revisions(profile: Mapping[str, Any]) -> dict[str, Any]:
    revisions = profile["revisions"]
    return {"source": "revisions", "context_only": True, "completed_projects": revisions["completed_projects"],
            "monday_item_ids_with_client_revisions": list(revisions.get("monday_item_ids_with_client_revisions") or []),
            "projects_with_client_revisions": revisions["projects_with_client_revisions"],
            "client_revision_events": revisions["client_revision_events"], "internal_revision_events": revisions.get("internal_revision_events"),
            "note": revisions["note"]}


def _workload(profile: Mapping[str, Any]) -> dict[str, Any]:
    workload = profile["current_workload"]
    summary = {"source": "current_workload.by_current_status", "as_of": workload["as_of"],
            "by_current_status": {status: len(items) for status, items in sorted(workload["by_current_status"].items(), key=lambda p: (-len(p[1]), p[0]))},
            "note": workload["note"]}
    if "active_work" in workload:
        summary.update({
            "active_work_count": workload["active_work"]["count"],
            "awaiting_approval_count": workload["awaiting_approval"]["count"],
            "awaiting_approval_status": workload["awaiting_approval"]["status"],
            "capacity_classification": dict(workload["capacity_classification"]),
        })
    return summary


def _monthly(profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    trend = profile["trend"]
    labels = {cohort["cohort_key"]: list(cohort["cohort_labels"]) for cohort in profile["speed"]["cohorts"]}
    months: dict[str, dict[str, Any]] = {}
    for row in trend["deadline_by_month"]:
        months.setdefault(row["month"], {"speed_by_cohort": []})["deadline"] = dict(row)
    for row in trend["speed_by_cohort_month"]:
        months.setdefault(row["month"], {"speed_by_cohort": []})["speed_by_cohort"].append(
            {"cohort_key": row["cohort_key"], "labels": labels.get(row["cohort_key"], []), "projects": row["projects"], "median_seconds": row["median_seconds"]})
    retrieved = str(profile["source"].get("retrieved_at") or "")[:7]
    return [{"month": month, "month_name": month_name(month), "partial": month == retrieved, "deadline": data.get("deadline"),
             "speed_by_cohort": data["speed_by_cohort"]} for month, data in sorted(months.items(), reverse=True)]  # most recent first


def _warnings(profile: Mapping[str, Any], speed: Mapping[str, Any], deadline: Mapping[str, Any], monthly: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Data-confidence notes, each a restatement of a profile fact; none is a judgement.

    ``params`` holds the same facts in structured form so a localized page can state them without reusing the English ``text``."""
    coverage = profile["coverage"]
    minimum = speed["minimum_editor_sample_size"]
    warnings: list[dict[str, Any]] = []
    if minimum and coverage["completed_projects"] < minimum:
        warnings.append({"code": "SMALL_SAMPLE", "source": "coverage.completed_projects",
                         "text": f"Only {coverage['completed_projects']} completed projects; the approved minimum for a speed conclusion is {minimum} per Video Type.",
                         "params": {"completed_projects": coverage["completed_projects"], "minimum": minimum}})
    if not speed["compared_cohorts"]:
        warnings.append({"code": "NO_SPEED_COMPARISON", "source": "speed.cohorts",
                         "text": "No Video Type cohort allows a speed comparison with other Editors.", "params": {}})
    unclassified = (deadline.get("not_classifiable_insufficient_eta_precision") or 0) + (deadline.get("not_classifiable_missing_eta") or 0)
    if unclassified:
        warnings.append({"code": "DEADLINE_NOT_CLASSIFIABLE", "source": "deadline.summary",
                         "text": f"{unclassified} completed projects have no Requested ETA with a time and are not classified for deadline.",
                         "params": {"unclassified": unclassified}})
    excluded = sum(coverage["exclusions_by_reason"].values())
    if excluded:
        reasons = ", ".join(f"{reason} {count}" for reason, count in coverage["exclusions_by_reason"].items())
        warnings.append({"code": "PROJECTS_EXCLUDED", "source": "coverage.exclusions_by_reason",
                         "text": f"{excluded} attributed projects are excluded from metrics ({reasons}).",
                         "params": {"excluded": excluded, "reasons": dict(coverage["exclusions_by_reason"])}})
    if monthly and monthly[0]["partial"]:
        warnings.append({"code": "PARTIAL_MONTH", "source": "source.retrieved_at",
                         "text": f"{monthly[0]['month_name']} is still in progress (data retrieved {profile['source'].get('retrieved_at')}).",
                         "params": {"month": monthly[0]["month"], "retrieved_at": profile["source"].get("retrieved_at")}})
    return warnings


def _snapshot(speed: Mapping[str, Any], deadline: Mapping[str, Any], quality: Mapping[str, Any], workload: Mapping[str, Any],
              coverage: Mapping[str, Any], intelligence: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The five management questions. Each answer lists only engine facts; unapproved judgements stay empty.

    ``facts`` are the English sentences; ``fact_data`` holds the same facts in structured form for localized pages."""
    faster = [c for c in speed["compared_cohorts"] if c["conclusion"] == "faster_than_team_median"]
    slower = [c for c in speed["compared_cohorts"] if c["conclusion"] == "slower_than_team_median"]
    labels = " + ".join
    evidence = [f"{coverage['completed_projects']} completed projects, {coverage['speed_eligible_projects']} measurable for speed.",
                f"{deadline['evaluated']} deadlines classified: {deadline['early']} early, {deadline['on_time']} on time, {deadline['late']} late."]
    blocks = [
        {"key": "doing_well", "question": "What is this Editor doing well?", "judgement": intelligence["positive_signals"],
         "facts": [f"Faster than the team median in {labels(c['labels'])} ({c['editor_sample_size']} projects)." for c in faster],
         "fact_data": [{"code": "speed_faster", "labels": list(c["labels"]), "projects": c["editor_sample_size"]} for c in faster]},
        {"key": "attention", "question": "Is there anything that may need management attention?", "judgement": intelligence["needs_attention"],
         "facts": [f"Slower than the team median in {labels(c['labels'])} ({c['editor_sample_size']} projects)." for c in slower]
                  + [f"{row['occurrences']} × {row['label']} (Monday Performance Issues)." for row in quality["by_label"]],
         "fact_data": [{"code": "speed_slower", "labels": list(c["labels"]), "projects": c["editor_sample_size"]} for c in slower]
                      + [{"code": "issue_label", "label": row["label"], "occurrences": row["occurrences"]} for row in quality["by_label"]]},
        {"key": "evidence", "question": "What does the available evidence say?", "judgement": None, "facts": evidence,
         "fact_data": [{"code": "evidence_projects", "completed": coverage["completed_projects"], "measurable": coverage["speed_eligible_projects"]},
                       {"code": "evidence_deadlines", "evaluated": deadline["evaluated"], "early": deadline["early"], "on_time": deadline["on_time"],
                        "late": deadline["late"]}]},
        {"key": "over_time", "question": "Is the Editor improving or declining over time?", "judgement": intelligence["trend_direction"],
         "facts": ["Monthly figures are shown below with their sample sizes."], "fact_data": [{"code": "monthly_note"}]},
        {"key": "workload", "question": "Is there relevant workload context?", "judgement": intelligence["workload_capacity"],
         "facts": [f"{count} item(s) currently {status}." for status, count in workload["by_current_status"].items()],
         "fact_data": [{"code": "workload", "status": status, "count": count} for status, count in workload["by_current_status"].items()]},
    ]
    return blocks


def editor_summary(profile: Mapping[str, Any], profile_ref: str | None = None) -> dict[str, Any]:
    """One Editor's dashboard summary, copied from their Editor Profile."""
    editor = profile["editor"]
    coverage = profile["coverage"]
    speed, deadline, quality = _speed(profile), _deadline(profile), _quality(profile)
    workload, monthly = _workload(profile), _monthly(profile)
    intelligence = editor_intelligence(profile)
    return {
        "editor_id": editor["editor_id"], "display_name": editor["display_name"], "monday_label": editor["monday_person_id"],
        "mapping_version": editor.get("mapping_version"), "profile_ref": profile_ref,
        "profile_contract_version": profile["contract_version"], "profile_generated_at": profile["generated_at"],
        "sample": {"source": "coverage", "completed_projects": coverage["completed_projects"], "open_projects": coverage["open_projects"],
                   "speed_eligible_projects": coverage["speed_eligible_projects"], "exclusions_by_reason": dict(coverage["exclusions_by_reason"])},
        "speed": speed, "deadline": deadline, "quality": quality, "revisions": _revisions(profile), "current_workload": workload,
        "monthly": monthly, "warnings": _warnings(profile, speed, deadline, monthly), "intelligence": intelligence,
        "projects": _projects(profile), "events": _events(profile),
        "snapshot": _snapshot(speed, deadline, quality, workload, coverage, intelligence),
    }


def _team(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    labels: dict[str, dict[str, int]] = {}
    labels_by_class: dict[str, dict[str, dict[str, int]]] = {name: {} for name in ("negative", "positive", "context")}
    for summary in summaries:
        for row in summary["quality"]["by_label"]:
            labels.setdefault(row["label"], {})[summary["editor_id"]] = row["occurrences"]
        for class_name, class_labels in labels_by_class.items():
            block = summary["quality"].get(class_name)
            if not isinstance(block, Mapping):
                continue
            for row in block.get("by_label") or []:
                class_labels.setdefault(row["label"], {})[summary["editor_id"]] = row["occurrences"]
    statuses = sorted({status for s in summaries for status in s["current_workload"]["by_current_status"]})
    months = sorted({m["month"] for s in summaries for m in s["monthly"] if m["deadline"]}, reverse=True)
    return {
        "issue_labels_by_editor": [{"label": label, "editors": counts, "editor_count": len(counts)}
                                   for label, counts in sorted(labels.items(), key=lambda p: (-len(p[1]), p[0]))],
        "quality_labels_by_class": {
            class_name: [{"label": label, "editors": counts, "editor_count": len(counts)}
                         for label, counts in sorted(class_labels.items(), key=lambda pair: (-len(pair[1]), pair[0]))]
            for class_name, class_labels in labels_by_class.items()
        },
        "workload_by_editor": {"statuses": statuses,
                               "rows": {s["editor_id"]: s["current_workload"]["by_current_status"] for s in summaries}},
        "deadline_by_editor_month": {"months": [{"month": month, "month_name": month_name(month)} for month in months],
                                     "rows": {s["editor_id"]: {m["month"]: m["deadline"] for m in s["monthly"] if m["deadline"]} for s in summaries}},
        "intelligence": team_intelligence(),
    }


def build_dashboard(profiles: Iterable[Mapping[str, Any]], generated_at: str, *, mapped_editors: Iterable[Mapping[str, Any]] = (),
                    attribution_coverage: Mapping[str, Any] | None = None, profile_refs: Mapping[str, str] | None = None,
                    publication: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Dashboard document for a set of Editor Profiles built from one dataset snapshot.

    ``mapped_editors`` are the contract's Editor mapping entries; the ones without a profile are
    listed as having no attributable data. ``attribution_coverage`` optionally describes the
    completed projects that no verified Editor could be attributed to."""
    profiles = list(profiles)
    sources = {(p["source"].get("retrieved_at"), p["executable_contract_version"]) for p in profiles}
    if len(sources) > 1:
        raise ValueError(f"profiles come from different snapshots or contracts: {sorted(map(str, sources))}")
    retrieved_at, contract_version = next(iter(sources)) if sources else (None, None)
    summaries = [editor_summary(p, (profile_refs or {}).get(p["editor"]["editor_id"])) for p in profiles]
    summaries.sort(key=lambda s: (-s["sample"]["completed_projects"], s["display_name"]))  # display order only
    profiled = {s["editor_id"] for s in summaries}
    return {
        "dashboard_version": DASHBOARD_VERSION,
        "generated_at": generated_at,
        "publication": dict(publication) if publication else None,
        "source": {"retrieved_at": retrieved_at, "executable_contract_version": contract_version,
                   "activity_log_window": profiles[0]["source"]["history_coverage"].get("activity_log_window") if profiles else None,
                   "statement": "Summary of Atlas Editor Profiles built from one Monday snapshot; the profiles and their Monday evidence are the source of every figure."},
        "editors": summaries,
        "editors_without_attributable_data": [{"editor_id": e["editor_id"], "display_name": e["display_name"], "monday_label": e["monday_person_id"]}
                                              for e in mapped_editors if e["editor_id"] not in profiled],
        "attribution_coverage": dict(attribution_coverage) if attribution_coverage else None,
        "team": _team(summaries),
    }
