"""Descriptive baselines: team, Video Type, Editor self-history and time (Tasks 8-11).

A baseline is what has been *normal* in the ingested history. It is never a target or an SLA (D15, D36). Every figure
carries its sample size, execution-time figures stay inside one exact Video Type, and team figures that are compared with
one Editor exclude that Editor (leave-one-out, D36).

Periods (all Cairo, D24):

- ``current``: the last 30 completed days (the contract's current window);
- ``comparison``: the 30 completed days before it;
- ``history``: every completed project before the current window (comparison window included);
- monthly series: Cairo months, the month containing the retrieval time marked ``partial`` with its covered days, so it
  is never silently compared with a full month.
"""

from __future__ import annotations

import calendar
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from atlas_commander.cycles import parse_time
from atlas_commander.intelligence import CAIRO
from atlas_commander.investigation.facts import FactBase, ProjectFact
from atlas_commander.investigation.stats import distribution, median, rate, rate_summary, shown

CURRENT, COMPARISON, HISTORY = "current", "comparison", "history"


def in_period(project: ProjectFact, period: str) -> bool:
    if period == CURRENT:
        return project.window == "current"
    if period == COMPARISON:
        return project.window == "comparison"
    if period == HISTORY:
        return project.window in ("comparison", "outside")
    raise ValueError(period)


@dataclass(frozen=True)
class Typical:
    """Leave-one-out typical execution time of one exact Video Type (the D36 benchmark over the whole ingested history)."""

    cohort_key: str
    excluded_editor: str | None
    median_seconds: int | None
    projects: int
    editors: int
    valid: bool
    records: tuple[ProjectFact, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"cohort_key": self.cohort_key, "excluded_editor": self.excluded_editor, "median_seconds": self.median_seconds,
                "projects": self.projects, "editors": self.editors, "valid": self.valid}


class Baselines:
    """Baseline lookups for one run; results are cached so every detector sees identical values."""

    def __init__(self, facts: FactBase, minimum_comparator_projects: int | None, minimum_comparator_editors: int | None) -> None:
        self.facts = facts
        self.minimum_projects = minimum_comparator_projects
        self.minimum_editors = minimum_comparator_editors
        self._typical: dict[tuple[str, str | None], Typical] = {}
        self.speed_projects = [project for project in facts.attributed if project.speed_measurable]

    def typical(self, cohort_key: str, excluded_editor: str | None) -> Typical:
        """Median first-pass execution time of the *other* Editors in this exact Video Type (valid only at the D52 minimums)."""
        key = (cohort_key, excluded_editor)
        if key not in self._typical:
            rows = tuple(sorted((project for project in self.speed_projects
                                 if project.cohort_key == cohort_key and project.editor_id != excluded_editor),
                                key=lambda p: (p.editor_id or "", p.monday_item_id)))
            editors = len({project.editor_id for project in rows})
            valid = (self.minimum_projects is not None and self.minimum_editors is not None
                     and len(rows) >= self.minimum_projects and editors >= self.minimum_editors)
            self._typical[key] = Typical(cohort_key, excluded_editor, median(project.duration_seconds for project in rows), len(rows), editors, valid, rows)
        return self._typical[key]


def _group_summary(projects: Sequence[ProjectFact]) -> dict[str, Any]:
    classifiable = [project for project in projects if project.deadline_classifiable]
    late = sum(bool(project.late) for project in classifiable)
    measurable = [project for project in projects if project.speed_measurable]
    return {
        "projects": len(projects),
        "editors": len({project.editor_id for project in projects if project.editor_id}),
        "execution_seconds": distribution(project.duration_seconds for project in measurable),
        "deadline": {**rate_summary(late, len(classifiable)), "classifiable": len(classifiable)},
        "negative_label_occurrences": sum(len(project.negative_scored) for project in projects),
        "negative_label_rate": shown(rate(sum(len(project.negative_scored) for project in projects), len(projects))),
        "positive_label_occurrences": sum(len(project.positive_scored) for project in projects),
        "client_revision_projects": sum(project.client_revisions > 0 for project in projects),       # context only (D31)
        "concurrency_at_start_median": median(project.concurrency_at_start for project in projects if project.concurrency_at_start is not None),
    }


def team_baseline(facts: FactBase) -> dict[str, Any]:
    attributed = facts.attributed
    return {period: _group_summary([project for project in attributed if in_period(project, period)]) for period in (CURRENT, COMPARISON, HISTORY)} | {
        "all": _group_summary(attributed)}


def video_type_baselines(facts: FactBase) -> list[dict[str, Any]]:
    """Normal behaviour of each exact Video Type across all Editors: descriptive, never an official target (Task 10)."""
    by_type: dict[str, list[ProjectFact]] = defaultdict(list)
    for project in facts.attributed:
        if project.cohort_key:
            by_type[project.cohort_key].append(project)
    rows = []
    for key, projects in sorted(by_type.items(), key=lambda pair: (-len(pair[1]), pair[0])):
        rows.append({"cohort_key": key, "cohort_labels": list(projects[0].cohort_labels), "benchmark_eligible": projects[0].benchmark_eligible,
                     "all": _group_summary(projects),
                     **{period: _group_summary([project for project in projects if in_period(project, period)]) for period in (CURRENT, HISTORY)}})
    return rows


def editor_baselines(facts: FactBase) -> list[dict[str, Any]]:
    """Each Editor against their own history (Task 8): recent (current window) vs history, per exact Video Type for speed."""
    rows = []
    for editor in facts.editors():
        mine = [project for project in facts.attributed if project.editor_id == editor]
        per_type = []
        for key in sorted({project.cohort_key for project in mine if project.speed_measurable and project.cohort_key}):
            typed = [project for project in mine if project.cohort_key == key and project.speed_measurable]
            per_type.append({"cohort_key": key, "cohort_labels": list(typed[0].cohort_labels),
                             CURRENT: distribution(p.duration_seconds for p in typed if in_period(p, CURRENT)),
                             HISTORY: distribution(p.duration_seconds for p in typed if in_period(p, HISTORY))})
        mix = Counter(project.cohort_key for project in mine if project.cohort_key)
        rows.append({"editor_id": editor, "display_name": facts.editor_names.get(editor), "all": _group_summary(mine),
                     CURRENT: _group_summary([p for p in mine if in_period(p, CURRENT)]),
                     HISTORY: _group_summary([p for p in mine if in_period(p, HISTORY)]),
                     "execution_by_video_type": per_type,
                     "project_mix": [{"cohort_key": key, "projects": count, "share": shown(rate(count, len(mine)))}
                                     for key, count in sorted(mix.items(), key=lambda pair: (-pair[1], pair[0]))]})
    return rows


def monthly_series(facts: FactBase) -> list[dict[str, Any]]:
    """Cairo-month team figures (Task 11). The month holding the retrieval time is partial and says how many days it covers."""
    retrieved = parse_time(facts.retrieved_at).astimezone(CAIRO).date() if facts.retrieved_at else None
    by_month: dict[str, list[ProjectFact]] = defaultdict(list)
    for project in facts.attributed:
        by_month[project.cairo_month].append(project)
    rows = []
    for month, projects in sorted(by_month.items()):
        year, number = (int(part) for part in month.split("-"))
        days = calendar.monthrange(year, number)[1]
        partial = retrieved is not None and (retrieved.year, retrieved.month) == (year, number)
        covered = (retrieved - date(year, number, 1)).days if partial and retrieved else days
        rows.append({"month": month, "partial": partial, "days_in_month": days, "completed_days_covered": covered, **_group_summary(projects)})
    return rows


def window_projects(projects: Iterable[ProjectFact], period: str) -> list[ProjectFact]:
    return [project for project in projects if in_period(project, period)]


def baselines_document(facts: FactBase, baselines: Baselines) -> dict[str, Any]:
    typical = []
    for key in sorted({project.cohort_key for project in baselines.speed_projects if project.cohort_key}):
        value = baselines.typical(key, None)
        typical.append({**value.to_dict(), "note": "all Editors, whole ingested history; comparisons with one Editor exclude that Editor"})
    return {
        "team": team_baseline(facts),
        "video_types": video_type_baselines(facts),
        "editors": editor_baselines(facts),
        "monthly": monthly_series(facts),
        "typical_execution": typical,
        "note": ("Baselines describe what has been normal in the ingested history. They are never targets or SLAs; execution times stay inside "
                 "one exact Video Type; comparisons with one Editor exclude that Editor (D36)."),
        "periods": {CURRENT: facts.windows.range("current"), COMPARISON: facts.windows.range("comparison"),
                    HISTORY: {"description": "every completed project before the current window", "end_date_exclusive": facts.windows.current_start.isoformat()}},
    }


def group_by(projects: Iterable[ProjectFact], key: str) -> dict[Any, list[ProjectFact]]:
    groups: dict[Any, list[ProjectFact]] = defaultdict(list)
    for project in projects:
        groups[getattr(project, key)].append(project)
    return dict(groups)


def share_table(projects: Sequence[ProjectFact], key: str, outcome: str) -> Mapping[Any, tuple[int, int]]:
    """Per group: (outcome count, projects) where ``outcome`` is a boolean ProjectFact attribute."""
    table: dict[Any, tuple[int, int]] = {}
    for group, members in group_by(projects, key).items():
        table[group] = (sum(bool(getattr(project, outcome)) for project in members), len(members))
    return table
