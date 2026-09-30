"""Build the verdict document of one snapshot (redesign Phase 2)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from atlas_commander.verdict.confidence import confidence
from atlas_commander.verdict.config import VerdictConfig, load_config
from atlas_commander.verdict.inputs import EditorInputs, TeamInputs, median, metrics, msg, normalize
from atlas_commander.verdict.tiers import Scored, Standing, assign_tier, dimension_points, points_above, rank, score, speed_for_verdict

DOCUMENT_VERSION = "1.0.0"
VERDICT_VERSION = "verdict-v1.0"
SCHEMA = "verdict-v1.schema.json"
NOTE = ("Judgment layer of the Atlas redesign (D54). Computed at build time from this snapshot's dashboard and Intelligence V2 "
        "documents; it never changes a metric, component state, Overall Status, Trend or finding. Low data lowers confidence and "
        "never silences a verdict.")


def build_verdicts(dashboard: Mapping[str, Any], intelligence: Mapping[str, Any] | None, generated_at: str,
                   config: VerdictConfig | None = None) -> dict[str, Any]:
    """The verdict document for ``dashboard`` (and its Intelligence V2 document, when one was published)."""
    config = config or load_config()
    source = dashboard["source"]
    editors = dashboard["editors"]
    window = editors[0]["interpretation"]["window"] if editors else None
    return {
        "document_version": DOCUMENT_VERSION,
        "verdict_version": VERDICT_VERSION,
        "generated_at": generated_at,
        "executable_contract_version": source["executable_contract_version"],
        "source": {"retrieved_at": source.get("retrieved_at"), "dashboard_version": dashboard["dashboard_version"],
                   "intelligence_version": intelligence.get("intelligence_version") if intelligence else None},
        "windows": {"timezone": "Africa/Cairo",
                    "current": _window(window["current"]) if window else {"start_date": "1970-01-01", "end_date_exclusive": "1970-01-01"},
                    "comparison": _window(window["comparison"]) if window else {"start_date": "1970-01-01", "end_date_exclusive": "1970-01-01"}},
        "config": config.as_document(),
        "team": None,
        "editors": editor_verdicts(*normalize(dashboard, intelligence), config),
        "decisions": [],
        "decision_candidates": [],
        "findings": {"hide_from_overview": [], "duplicates": []},
        "note": NOTE,
    }


def _worse_dimensions(m: Mapping[str, Any], median_completed: float | None, config: VerdictConfig) -> tuple[str, ...]:
    """Dimensions on which the Editor is worse than the team (a Best Editor has none)."""
    above = points_above(m["late_rate"], m["team_late_rate"], config)
    speed = speed_for_verdict(m)
    worse = []
    if above is not None and above > 0:
        worse.append("deadlines")
    if speed is not None and speed > 0:
        worse.append("speed")
    if median_completed is not None and m["completed"] < median_completed:
        worse.append("volume")
    return tuple(worse)


def editor_verdicts(editors: list[EditorInputs], team: TeamInputs, config: VerdictConfig) -> list[dict[str, Any]]:
    """One verdict per Editor: metrics (T2.4), score and rank (T2.6), tier (T2.5)."""
    rows = {e.editor_id: metrics(e, team, config) for e in editors}
    ranked = [e for e in editors if e.completed >= config["score.minimum_completed"]]
    median_completed = median([e.completed for e in ranked])
    scored: dict[str, tuple[float | None, dict[str, float | None], list[str]]] = {}
    for e in ranked:
        points = dimension_points(rows[e.editor_id], median_completed, config)
        value, missing = score(points, config, e.quality_approved)
        scored[e.editor_id] = (value, points, missing)
    ranks = rank([Scored(e.editor_id, value, e.late_rate, e.completed) for e in ranked if (value := scored[e.editor_id][0]) is not None])
    out = []
    for e in editors:
        m = rows[e.editor_id]
        position = ranks.get(e.editor_id)
        standing = Standing(in_top_share=position is not None and position <= len(ranks) * config["tier.best_top_share"],
                            worse_dimensions=_worse_dimensions(m, median_completed, config))
        tier = assign_tier(m, len(e.overdue), config, standing)
        value, points, missing = scored.get(e.editor_id, (None, {}, []))
        if e.editor_id not in scored:   # not scored: the key dimensions it lacks still lower its confidence
            unscored = dimension_points(m, median_completed, config)
            missing = [name for name in ("deadlines", "speed") if unscored[name] is None]
            used = [name for name in ("deadlines", "speed") if unscored[name] is not None]
        else:
            used = [name for name, p in points.items() if p is not None]
        level, reasons = confidence(m, [name for name in missing if name != "quality" or e.quality_approved], used, e.headline_contradictions, config)
        out.append({
            "editor_id": e.editor_id, "display_name": e.display_name, "tier": tier, "rank": position, "ranked_of": len(ranks), "score": value,
            "score_parts": {name: round(p, int(config["precision.pct_digits"])) for name, p in points.items() if p is not None},
            "confidence": level, "confidence_reasons": reasons,
            "headline": msg("verdict.headline." + tier), "reasons": [],
            "based_on": used,
            "metrics": m, "overdue": [], "photo_url": None, "finding_ids": list(e.finding_ids), "hidden_finding_ids": [],
        })
    return out


def _window(window: Mapping[str, Any]) -> dict[str, str]:
    return {"start_date": window["start_date"], "end_date_exclusive": window["end_date_exclusive"]}
