"""Synthetic Intelligence V2 fact bases for detector tests. No real names, IDs or production values.

``fact`` builds one completed first cycle directly as a ``ProjectFact`` so a test controls every value a detector reads;
the Monday -> fact path itself is covered through the real pipeline in ``test_investigation_facts``.
"""

import copy
import json
from datetime import datetime, timedelta, timezone

from atlas_commander.intelligence import CAIRO, completed_day_windows, window_assignment
from atlas_commander.investigation.baselines import Baselines
from atlas_commander.investigation.context import RunContext
from atlas_commander.investigation.facts import FactBase, LabelFact, OpenWork, ProjectFact, _concurrency
from atlas_commander.investigation.policy import CONFIG_PATH, IntelligencePolicy
from atlas_commander.metrics import classify_deadline
from atlas_commander.runtime import load_contract_version

AS_OF = "2026-09-29T12:00:00Z"          # current window 2026-08-29..2026-09-28, comparison 2026-07-30..2026-08-28 (Cairo)
CONTRACT = load_contract_version("1.5.0")
NAMES = {"editor-label-6": "Editor A", "editor-label-12": "Editor B", "editor-label-13": "Editor C", "editor-label-14": "Editor D",
         "editor-label-15": "Editor E"}
LABELS = {"4": ("Class A",), "5": ("Class B",), "6": ("Simple Short",), "8": ("Class A+",)}
A, B, C, D, E = sorted(NAMES)[:5]


def stamp(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def at(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def label(name, label_class="Negative", scored=True, item="x"):
    return LabelFact(name, label_class, scored, (f"{item}-label-{name}",), ("2026-09-20T00:00:00Z",))


def fact(item, editor=A, cohort="4", start="2026-09-10T08:00:00Z", hours=10.0, eta_hours=None, labels=(), exclusions=(),
         eligible=True, eta_observed_after_start=False, delivered_hours=None, review_hours=None, client_revisions=0):
    """One completed first cycle. ``eta_hours`` is the Requested ETA relative to first In Progress (None = no ETA)."""
    begin = at(start)
    ready = begin + timedelta(hours=hours)
    eta = stamp(begin + timedelta(hours=eta_hours)) if eta_hours is not None else None
    windows = completed_day_windows(AS_OF, 30, 30)
    result = classify_deadline(int((ready - at(eta)).total_seconds())) if eta and editor else None
    local = ready.astimezone(CAIRO)
    observed = stamp(begin + timedelta(minutes=5)) if eta_observed_after_start else stamp(begin - timedelta(hours=2))
    return ProjectFact(
        monday_item_id=str(item), cycle_id=f"cycle:5091110326:{item}", board_id="5091110326", editor_id=editor, cohort_key=cohort,
        cohort_labels=LABELS.get(cohort, (f"type-{cohort}",)), benchmark_eligible=eligible and not exclusions, in_progress_at=stamp(begin),
        ready_for_approval_at=stamp(ready), duration_seconds=int(hours * 3600),
        event_ids={"in_progress": f"{item}-ip", "ready_for_approval": f"{item}-rfa", "editor": f"{item}-ed", "video_type": f"{item}-vt",
                   "requested_eta": f"{item}-eta" if eta else None},
        exclusions=tuple(exclusions), flags=(), requested_eta=eta, requested_eta_issue=None if eta else "MISSING_REQUESTED_ETA",
        requested_eta_observed_at=observed if eta else None, requested_eta_at_start=eta, deadline_result=result,
        deadline_delta_seconds=int((ready - at(eta)).total_seconds()) if eta and editor else None,
        window=window_assignment(stamp(ready), windows), cairo_date=local.date().isoformat(), cairo_month=local.strftime("%Y-%m"),
        cairo_weekday=local.isoweekday(), labels=tuple(labels), client_revisions=client_revisions,
        review_wait_seconds=int(review_hours * 3600) if review_hours is not None else None,
        delivered_at=stamp(ready + timedelta(hours=delivered_hours)) if delivered_hours is not None else None,
        delivered_event_id=f"{item}-sent" if delivered_hours is not None else None)


def open_work(item, status="In Progress", editor=A, cohort="4", started_hours_ago=5.0, eta_in_hours=10.0, eligible=True):
    now = at(AS_OF)
    start = stamp(now - timedelta(hours=started_hours_ago))
    return OpenWork(str(item), status, start, f"{item}-status", editor, cohort, eligible, start, f"{item}-ip",
                    stamp(now + timedelta(hours=eta_in_hours)) if eta_in_hours is not None else None, None, (f"item-snapshot:{item}:status",), AS_OF)


def base(projects, open_items=()):
    projects = [copy.copy(project) for project in projects]
    _concurrency(projects)
    return FactBase(projects, {}, list(open_items), completed_day_windows(AS_OF, 30, 30), AS_OF, "5091110326",
                    {"status": "project_status", "editor": "dropdown_mm1emgt8", "video_type": "dropdown_mm062ga0", "requested_eta": "date",
                     "performance_issues": "dropdown_mm3tyk8g", "for_bonus": "dropdown_mm3tyvvc"}, dict(NAMES), {})


def config(approve=(), unapprove=(), **values):
    """The shipped V2 configuration (D53 approved) with values overridden.

    A keyword (``evidence__minimum_group_projects=12``) sets the value a mode uses: the approved value of an approved parameter,
    and the proposal of an unapproved one. ``unapprove`` returns named parameters to ``rule_not_approved`` (a governance test
    of what happens without a decision); ``approve`` marks named proposals approved under D53."""
    data = json.loads(CONFIG_PATH.read_text())
    for name, value in values.items():
        entry = data["parameters"][name.replace("__", ".")]
        entry["proposed_value"] = value
        if entry["status"] == "approved" and not entry.get("from_contract"):
            entry["value"] = value
    for name in unapprove:
        data["parameters"][name].update({"status": "rule_not_approved", "decision_id": None, "value": None})
    for name in approve:
        entry = data["parameters"][name]
        entry.update({"status": "approved", "decision_id": "D53", "value": entry["proposed_value"]})
    return data


UNAPPROVED_D53 = [name for name, entry in json.loads(CONFIG_PATH.read_text())["parameters"].items() if entry.get("decision_id") == "D53"]


def pre_d53():
    """The configuration as it stood before D53 was approved: every D53 parameter rule_not_approved."""
    return config(unapprove=UNAPPROVED_D53)


def context(facts, mode="review", data=None, profiles=None):
    policy = IntelligencePolicy.load(CONTRACT, mode, data)
    return RunContext(facts, Baselines(facts, policy.value("speed.minimum_comparator_projects"), policy.value("speed.minimum_comparator_editors")),
                      policy, profiles or {}, AS_OF)


def days_before(days, hour=8):
    """A start moment ``days`` whole days before AS_OF (UTC hour ``hour``)."""
    return stamp(at(AS_OF).replace(hour=hour, minute=0, second=0) - timedelta(days=days))
