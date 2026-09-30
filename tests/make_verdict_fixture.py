"""Write ``fixtures/verdict/september-2026.json``: the spec §9 test fixture (redesign T2.3).

    PYTHONPATH=src:tests python3 tests/make_verdict_fixture.py

A minimal subset of one snapshot's ``dashboard.json`` and ``intelligence-v2.json`` holding only the fields the verdict engine reads.
The six Editors of `02-VERDICT-ENGINE-SPEC.md` §9 (Will, Anas, Refaat, Sobhy, Mohamed Mansour, Samra) carry the spec's numbers.
Six more Editors are added only so the team totals reproduce §9 (late 59% was 75%, 3 overdue open projects held by Michael,
Refaat and Mario, 328 of 424 late projects with short runway, 73% of 448 vs 55% of 91); their values are chosen to be unremarkable
and are not taken from any real Editor.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "verdict" / "september-2026.json"
RETRIEVED = "2026-09-30T13:10:00Z"
WINDOW = {"current": {"window": "current", "timezone": "Africa/Cairo", "start_date": "2026-08-31", "end_date_exclusive": "2026-09-30", "completed_days": 30},
          "comparison": {"window": "comparison", "timezone": "Africa/Cairo", "start_date": "2026-08-01", "end_date_exclusive": "2026-08-31", "completed_days": 30}}
H = 3600

# editor_id, name, lifetime, active, (late, classifiable) now, (late, classifiable) before, speed row or None, positive quality rate, runway (late, short)
EDITORS = [
    ("editor-label-6", "Will", 158, 2, (12, 22), (21, 24), ("Class A", "similar", 30.0, 39.1, 8, 30), 0.182, (40, 28)),
    ("editor-label-5", "Anas", 39, 1, (7, 13), (12, 16), ("Simple Short", "similar", 43.4, 35.2, 9, 20), 0.0, (20, 13)),
    ("editor-label-11", "Refaat", 45, 1, (12, 14), (10, 14), ("Simple Short", "slower", 41.6, 29.1, 11, 16), 0.0, (33, 24)),
    ("editor-label-15", "Sobhy", 6, 1, (4, 6), (0, 0), ("2* + Class A", "not_classifiable", 53.7, None, 1, 0), 0.0, (4, 2)),
    ("editor-label-18", "Mohamed Mansour (Office)", 2, 1, (1, 2), (0, 0), ("2* + Ai + Class A", "not_classifiable", 29.1, 28.3, 1, 30), 0.0, (1, 0)),
    ("editor-label-8", "Samra", 60, 0, (0, 0), (0, 0), None, None, (30, 20)),
    ("editor-label-13", "Michael", 2, 1, (0, 0), (0, 0), None, None, (1, 1)),
    ("editor-label-4", "Mario", 143, 1, (7, 15), (14, 18), None, 0.0, (60, 40)),
    ("editor-label-9", "Ibrahim", 103, 1, (14, 24), (18, 26), ("Class A", "similar", 37.9, 39.1, 18, 30), 0.0, (50, 35)),
    ("editor-label-7", "Martin", 48, 1, (11, 18), (14, 21), ("Premium Short", "similar", 40.4, 38.5, 13, 26), 0.0, (25, 18)),
    ("editor-label-10", "Amir", 60, 1, (8, 15), (8, 10), ("Premium Short", "slower", 37.9, 28.0, 10, 29), 0.0, (33, 23)),
    ("editor-label-12", "Ahmed", 15, 0, (0, 0), (0, 0), None, None, (10, 7)),
]
OVERDUE = [("editor-label-13", "Michael", "3109734616", "Revisions", "2026-09-28T11:49:00Z", 49.4),
           ("editor-label-11", "Refaat", "3202025538", "Revisions", "2026-09-25T14:19:56Z", 118.8),
           ("editor-label-4", "Mario", "3248937694", "In Progress", "2026-09-30T09:00:00Z", 4.2)]


def rate(late: int, total: int) -> float | None:
    return round(late / total, 4) if total else None


def summary(editor_id, name, lifetime, active, now, before, speed, positive, _runway):
    rows = []
    if speed:
        label, verdict, mine, peers, n, peer_n = speed
        pct = round((mine / peers - 1) * 100, 1) if peers else None
        rows.append({"cohort_key": label, "cohort_labels": label.split(" + "), "verdict": verdict,
                     "reason": None if verdict != "not_classifiable" else "insufficient_sample",
                     "editor_projects": n, "editor_median_seconds": int(mine * H), "comparator_projects": peer_n,
                     "comparator_editor_count": 3 if peer_n else 0, "comparator_median_seconds": int(peers * H) if peers else None,
                     "editor_vs_comparator_pct": pct})
    quality_facts = {"negative_rate": 0.0 if now[1] else None, "positive_rate": positive, "eligible_completed_projects": now[1]}
    return {
        "editor_id": editor_id, "display_name": name,
        "sample": {"completed_projects": lifetime},
        "current_workload": {"active_work_count": active},
        "interpretation": {
            "window": WINDOW,
            "coverage": {"current_projects": now[1]},
            "components": {
                "deadline": {"state": "neutral", "rule_status": "approved",
                             "facts": {"deadline_classifiable_projects": now[1], "late": now[0], "absolute_late_rate": rate(*now)}},
                "speed": {"state": "neutral", "rule_status": "approved", "video_types": rows},
                "quality": {"state": "not_classifiable", "reason": "rule_not_approved", "rule_status": "rule_not_approved", "facts": quality_facts},
            },
            "recent_change": [{"measurement": "late_rate", "cohort_key": None, "current": rate(*now), "comparison": rate(*before),
                               "current_sample": now[1], "comparison_sample": before[1]}],
        },
    }


def statement(code: str, params: dict) -> dict:
    return {"code": code, "level": "metric", "params": params}


def finding(finding_id: str, finding_type: str, editors: list[str], sample: int, statements: list[dict], *, contradicting: int = 0,
            category: str = "editor_specific_pattern") -> dict:
    return {"finding_id": finding_id, "finding_type": finding_type, "category": category, "affected_editors": editors, "sample_size": sample,
            "statements": statements, "cluster": None,
            "contradicting_evidence": [{"code": "contradicting", "records": [{"monday_item_id": str(3000000000 + i)} for i in range(contradicting)]}]
            if contradicting else []}


def change(editor_id: str, name: str, against: str, before: tuple, now: tuple, team_before: float, team_now: float, sample: int) -> dict:
    difference = round(now[0] / now[1] - before[0] / before[1], 4)
    team_difference = round(team_now - team_before, 4)
    params = {"against": against, "measure": "late_rate", "editor_id": editor_id, "editor_name": name, "baseline": rate(*before),
              "baseline_sample": before[1], "current": rate(*now), "current_sample": now[1], "difference": difference,
              "team_baseline": team_before, "team_current": team_now, "team_difference": team_difference,
              "editor_minus_team_change": round(difference - team_difference, 4), "material_difference": 0.15,
              "team_comparison_available": True, "status": "improving"}
    return finding(f"change.editor:anas-{against}", "change.editor", [editor_id], sample, [statement("late_rate_changed", params)], category="hidden_context")


def intelligence() -> dict:
    items = [{"editor_name": name, "monday_item_id": item, "status": status, "requested_eta": eta, "hours_past_eta": hours}
             for _, name, item, status, eta, hours in OVERDUE]
    findings = [
        finding("risk.open_work:fixture", "risk.open_work", sorted({e for e, *_ in OVERDUE}), 3,
                [statement("risk_past_eta", {"items": items, "projects": 3, "retrieved_at": RETRIEVED})], category="emerging_risk"),
        finding("bottleneck.pre_editor_runway:fixture", "bottleneck.pre_editor_runway", [e[0] for e in EDITORS], 328,
                [statement("late_projects_with_short_runway", {"late": 424, "short_runway": 448, "short_runway_late": 328, "short_runway_late_rate": 0.7321,
                                                               "adequate_runway": 91, "adequate_runway_late": 50, "adequate_runway_late_rate": 0.5495,
                                                               "share_of_late_with_short_runway": 0.7736})], contradicting=50, category="system_pattern"),
        finding("change.editor:refaat-speed", "change.editor", ["editor-label-11"], 38,
                [statement("median_execution_changed", {"against": "history", "measure": "median_execution", "editor_id": "editor-label-11",
                                                        "cohort_label": "Simple Short", "baseline_hours": 33.0, "current_hours": 41.6, "pct_change": 26.3,
                                                        "team_pct_change": -4.1, "material_pct": 25.0, "team_comparison_available": True})],
                category="needs_attention"),
        change("editor-label-5", "Anas", "history", (18, 26), (7, 13), 0.7564, 0.5902, 39),
        change("editor-label-5", "Anas", "comparison", (12, 16), (7, 13), 0.7257, 0.5902, 29),
        finding("contradiction.bad_headline:will", "contradiction.bad_headline", ["editor-label-6"], 129,
                [statement("headline_needs_context", {"editor_id": "editor-label-6", "measure": "late_rate"})], contradicting=30, category="hidden_context"),
        finding("contradiction.bad_headline:refaat", "contradiction.bad_headline", ["editor-label-11"], 45,
                [statement("headline_needs_context", {"editor_id": "editor-label-11", "measure": "late_rate"})], contradicting=3, category="hidden_context"),
    ]
    editors = [{"editor_id": e[0], "display_name": e[1], "finding_ids": [f["finding_id"] for f in findings if e[0] in f["affected_editors"]],
                "fairness_context": {"runway": {"late": e[8][0], "late_with_short_runway": e[8][1]}}} for e in EDITORS]
    return {"intelligence_version": "intelligence-v2.0.0", "mode": "approved_only", "publishable": True, "findings": findings, "editors": editors,
            "sections": {"top_findings": {"finding_ids": [findings[0]["finding_id"], findings[1]["finding_id"]]}}}


def main() -> None:
    fixture = {
        "note": __doc__.strip(),
        "dashboard": {"dashboard_version": "ceo-dashboard-v0.1", "generated_at": RETRIEVED,
                      "source": {"retrieved_at": RETRIEVED, "executable_contract_version": "1.5.0"},
                      "editors": [summary(*e) for e in EDITORS]},
        "intelligence": intelligence(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(fixture, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
