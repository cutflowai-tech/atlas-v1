"""Verdict inputs: the existing Atlas metrics of one snapshot, normalized per Editor and for the team (redesign T2.4).

Nothing here is a new metric. Every value is read from ``dashboard.json`` (copied from the Editor Profiles) or from the published
``intelligence-v2.json`` of the same snapshot; the team values are sums of the Editors' own counts. See ``docs/redesign/DECISIONS.md``
(T0.3) for where each input lives.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from atlas_commander.verdict.config import VerdictConfig

NOT_CLASSIFIABLE = "not_classifiable"
SECONDS_PER_HOUR = 3600


def _hours(seconds: float | None) -> float | None:
    return None if seconds is None else seconds / SECONDS_PER_HOUR


@dataclass(frozen=True)
class Speed:
    """The Editor's primary Video Type comparison: the same row the overview card shows (first classified, else the largest)."""

    labels: tuple[str, ...]
    classified: bool
    delta_pct: float | None
    editor_hours: float | None
    peer_hours: float | None
    editor_projects: int


@dataclass(frozen=True)
class Overdue:
    project_id: str
    status: str
    requested_eta: str | None
    hours_past_eta: float | None
    video_type: str | None = None   # the item's Video Type label, when Intelligence V2 recorded it


@dataclass(frozen=True)
class OwnChange:
    """A published Intelligence V2 change of this Editor against their own baseline."""

    finding_id: str
    measure: str          # late_rate | median_execution
    against: str          # history | comparison
    sample: int
    difference: float     # rate: absolute difference; duration: percent change
    team_difference: float | None
    cohort_label: str | None
    before: float | None = None        # rate or hours, the Editor's baseline
    now: float | None = None           # rate or hours, the Editor's current value
    team_before: float | None = None   # rates only: the other Editors over the same periods
    team_now: float | None = None


@dataclass(frozen=True)
class EditorInputs:
    editor_id: str
    display_name: str
    completed: int
    active: int
    lifetime_completed: int
    deadline_classifiable: int
    late_count: int | None
    late_rate: float | None
    previous_classifiable: int
    previous_late: int | None
    speed: Speed | None
    quality_approved: bool
    quality_state: str | None
    quality_positive_rate: float | None
    quality_negative_rate: float | None
    runway_late: int | None
    runway_late_short: int | None
    overdue: tuple[Overdue, ...]
    changes: tuple[OwnChange, ...]
    headline_contradictions: tuple[str, ...]   # published findings that qualify this Editor's late-rate headline
    finding_ids: tuple[str, ...]


@dataclass(frozen=True)
class TeamInputs:
    late: int
    classifiable: int
    previous_late: int
    previous_classifiable: int
    overdue: tuple[tuple[str, Overdue], ...]            # (editor_id, project)
    runway: Mapping[str, Any] | None                    # the team short-runway split (Intelligence V2), or None
    runway_finding_id: str | None
    intelligence_available: bool
    findings: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    @property
    def late_rate(self) -> float | None:
        return self.late / self.classifiable if self.classifiable else None

    @property
    def previous_late_rate(self) -> float | None:
        return self.previous_late / self.previous_classifiable if self.previous_classifiable else None


# --------------------------------------------------------------------------------------------------- reading

def _primary_speed(view: Mapping[str, Any]) -> Speed | None:
    rows = view["components"]["speed"]["video_types"]
    row = next((r for r in rows if r["verdict"] != NOT_CLASSIFIABLE), rows[0] if rows else None)
    if row is None:
        return None
    return Speed(labels=tuple(row["cohort_labels"]), classified=row["verdict"] != NOT_CLASSIFIABLE, delta_pct=row["editor_vs_comparator_pct"],
                 editor_hours=_hours(row["editor_median_seconds"]), peer_hours=_hours(row["comparator_median_seconds"]),
                 editor_projects=row["editor_projects"])


def _late_change(view: Mapping[str, Any]) -> Mapping[str, Any] | None:
    return next((c for c in view.get("recent_change") or [] if c["measurement"] == "late_rate" and not c.get("cohort_key")), None)


def _count(rate: float | None, sample: int) -> int | None:
    """A count from a published rate and its sample. Rates carry 4 decimals, so the product is within 0.5 of the exact count for
    any sample below 5,000 projects."""
    return None if rate is None else round(rate * sample)


def _statement(finding: Mapping[str, Any], code: str) -> Mapping[str, Any] | None:
    return next((s["params"] for s in finding.get("statements") or [] if s["code"] == code), None)


def _findings_by_type(intelligence: Mapping[str, Any] | None, finding_type: str) -> list[Mapping[str, Any]]:
    return [f for f in (intelligence or {}).get("findings") or [] if f["finding_type"] == finding_type]


def _overdue(intelligence: Mapping[str, Any] | None, names: Mapping[str, str]) -> list[tuple[str, Overdue]]:
    """Open projects already past their Requested ETA (Intelligence V2 ``risk.open_work``, a direct fact of the snapshot). The
    finding's evidence records give each item's Editor ID and Video Type; the Editor's name is the fallback."""
    out: list[tuple[str, Overdue]] = []
    by_name = {name: editor_id for editor_id, name in names.items()}
    video_types = (intelligence or {}).get("video_types") or {}
    for finding in _findings_by_type(intelligence, "risk.open_work"):
        params = _statement(finding, "risk_past_eta") or {}
        records = {str(r["monday_item_id"]): r for evidence in finding.get("supporting_evidence") or [] if evidence["code"] == "open_work_past_eta"
                   for r in evidence.get("records") or []}
        for item in params.get("items") or []:
            record = records.get(str(item["monday_item_id"])) or {}
            editor_id = record.get("editor_id") if record.get("editor_id") in names else by_name.get(item["editor_name"])
            if editor_id is not None:
                out.append((editor_id, Overdue(project_id=str(item["monday_item_id"]), status=item["status"],
                                               requested_eta=item.get("requested_eta"), hours_past_eta=item.get("hours_past_eta"),
                                               video_type=video_types.get(str(record.get("cohort_key"))))))
    return out


def _changes(intelligence: Mapping[str, Any] | None, editor_id: str) -> list[OwnChange]:
    out = []
    for finding in _findings_by_type(intelligence, "change.editor"):
        if finding["affected_editors"] != [editor_id]:
            continue
        rate = _statement(finding, "late_rate_changed")
        duration = _statement(finding, "median_execution_changed")
        if rate is not None:
            out.append(OwnChange(finding["finding_id"], "late_rate", rate["against"], finding["sample_size"], rate["difference"],
                                 rate.get("team_difference"), None, rate.get("baseline"), rate.get("current"), rate.get("team_baseline"),
                                 rate.get("team_current")))
        elif duration is not None:
            out.append(OwnChange(finding["finding_id"], "median_execution", duration["against"], finding["sample_size"], duration["pct_change"],
                                 duration.get("team_pct_change"), duration.get("cohort_label"), duration.get("baseline_hours"),
                                 duration.get("current_hours")))
    return out


def normalize(dashboard: Mapping[str, Any], intelligence: Mapping[str, Any] | None) -> tuple[list[EditorInputs], TeamInputs]:
    names = {s["editor_id"]: s["display_name"] for s in dashboard["editors"]}
    overdue = _overdue(intelligence, names)
    fairness = {e["editor_id"]: e for e in (intelligence or {}).get("editors") or []}
    contradictions: dict[str, list[str]] = {}
    for finding in _findings_by_type(intelligence, "contradiction.bad_headline"):
        for editor_id in finding["affected_editors"]:
            if finding.get("contradicting_evidence"):
                contradictions.setdefault(editor_id, []).append(finding["finding_id"])
    editors = []
    for s in dashboard["editors"]:
        view = s["interpretation"]
        deadline = view["components"]["deadline"]["facts"]
        quality = view["components"]["quality"]
        change = _late_change(view)
        runway = ((fairness.get(s["editor_id"]) or {}).get("fairness_context") or {}).get("runway") or {}
        classifiable = deadline.get("deadline_classifiable_projects") or 0
        previous_classifiable = (change or {}).get("comparison_sample") or 0
        editors.append(EditorInputs(
            editor_id=s["editor_id"], display_name=s["display_name"], completed=view["coverage"]["current_projects"],
            active=s["current_workload"].get("active_work_count") or 0, lifetime_completed=s["sample"]["completed_projects"],
            deadline_classifiable=classifiable, late_count=deadline.get("late") if classifiable else None,
            late_rate=deadline.get("absolute_late_rate") if classifiable else None,
            previous_classifiable=previous_classifiable,
            previous_late=_count((change or {}).get("comparison"), previous_classifiable) if previous_classifiable else None,
            speed=_primary_speed(view), quality_approved=quality.get("rule_status") == "approved", quality_state=quality.get("state"),
            quality_positive_rate=(quality.get("facts") or {}).get("positive_rate"),
            quality_negative_rate=(quality.get("facts") or {}).get("negative_rate"),
            runway_late=runway.get("late"), runway_late_short=runway.get("late_with_short_runway"),
            overdue=tuple(o for editor_id, o in overdue if editor_id == s["editor_id"]),
            changes=tuple(_changes(intelligence, s["editor_id"])),
            headline_contradictions=tuple(contradictions.get(s["editor_id"], [])),
            finding_ids=tuple((fairness.get(s["editor_id"]) or {}).get("finding_ids") or [])))
    runway_findings = _findings_by_type(intelligence, "bottleneck.pre_editor_runway")
    team = TeamInputs(
        late=sum(e.late_count or 0 for e in editors), classifiable=sum(e.deadline_classifiable for e in editors),
        previous_late=sum(e.previous_late or 0 for e in editors), previous_classifiable=sum(e.previous_classifiable for e in editors),
        overdue=tuple(overdue), runway=_statement(runway_findings[0], "late_projects_with_short_runway") if runway_findings else None,
        runway_finding_id=runway_findings[0]["finding_id"] if runway_findings else None, intelligence_available=intelligence is not None,
        findings={f["finding_id"]: f for f in (intelligence or {}).get("findings") or []})
    return editors, team


# --------------------------------------------------------------------------------------------------- EditorVerdict.metrics

def msg(key: str, **params: Any) -> dict[str, Any]:
    return {"key": key, "params": params}


def _round(value: float | None, digits: float) -> float | None:
    return None if value is None else round(value, int(digits))


def own_speed_change(editor: EditorInputs) -> OwnChange | None:
    """The Editor's published speed change against their own history, on their primary Video Type when there is one."""
    changes = [c for c in editor.changes if c.measure == "median_execution"]
    primary = " + ".join(editor.speed.labels) if editor.speed else None
    return next((c for c in changes if c.cohort_label == primary), max(changes, key=lambda c: c.sample, default=None))


def late_tone(late_rate: float | None, team_late_rate: float | None, config: VerdictConfig) -> str:
    """The late-rate bar's colour (T3.3), decided here so the page only renders it: bad above the team rate plus
    ``display.late_bad_above_team_pp``, warn above the team rate, good otherwise."""
    if late_rate is None or team_late_rate is None:
        return "neutral"
    above = round((late_rate - team_late_rate) * 100, int(config["precision.rate_digits"]) - 2)
    if above > config["display.late_bad_above_team_pp"]:
        return "bad"
    return "warn" if above > 0 else "good"


def speed_reading(delta_pct: float | None, classified: bool, config: VerdictConfig) -> dict[str, str | None]:
    """How the speed pill reads (T3.4), decided here so the page only renders it. The band follows the value; the tone judges it only
    when the approved Speed rule classifies the comparison (D52), so a one-project comparison is shown but never coloured."""
    if delta_pct is None:
        return {"speed_band": None, "speed_tone": "neutral"}
    if abs(delta_pct) < config["display.speed_same_band_pct"]:
        return {"speed_band": "same", "speed_tone": "neutral"}
    band = "faster" if delta_pct < 0 else "slower"
    if not classified:
        tone = "neutral"
    elif band == "faster":
        tone = "good"
    else:
        tone = "bad" if delta_pct > config["display.speed_bad_above_pct"] else "warn"
    return {"speed_band": band, "speed_tone": tone}


def metrics(editor: EditorInputs, team: TeamInputs, config: VerdictConfig) -> dict[str, Any]:
    rate_digits, pct_digits = config["precision.rate_digits"], config["precision.pct_digits"]
    speed = editor.speed
    label = None
    if speed is not None and speed.peer_hours is not None and speed.editor_hours is not None:
        label = msg("verdict.speed.label", labels=list(speed.labels), editor_hours=_round(speed.editor_hours, pct_digits),
                    peer_hours=_round(speed.peer_hours, pct_digits), n=speed.editor_projects)
    own = own_speed_change(editor)
    quality = None
    if editor.quality_approved and editor.quality_state:
        quality = msg("verdict.quality.state." + editor.quality_state)
    elif editor.quality_positive_rate:
        quality = msg("verdict.quality.positive_notes", positive_pct=_round(editor.quality_positive_rate * 100, pct_digits))
    return {
        "completed": editor.completed,
        "active": editor.active,
        "lifetime_completed": editor.lifetime_completed,
        "late_rate": _round(editor.late_rate, rate_digits),
        "late_count": editor.late_count,
        "deadline_classifiable": editor.deadline_classifiable,
        "team_late_rate": _round(team.late_rate, rate_digits),
        "speed_delta_pct": _round(speed.delta_pct, pct_digits) if speed and speed.peer_hours is not None else None,
        "speed_label": label,
        "speed_classified": bool(speed and speed.classified and speed.delta_pct is not None),
        "own_speed_delta_pct": _round(own.difference, pct_digits) if own else None,
        "quality": quality,
        "late_tone": late_tone(editor.late_rate, team.late_rate, config),
        **speed_reading(speed.delta_pct if speed and speed.peer_hours is not None else None, bool(speed and speed.classified), config),
    }


def median(values: Sequence[float]) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
