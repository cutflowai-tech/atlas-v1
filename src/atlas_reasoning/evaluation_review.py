"""The human management-quality review of a Reasoning V3 evaluation (Phase 19-B, ``REV/19`` #7).

The automated evaluation (Phase 19-A metrics) measures what can be measured structurally. Whether the cards are useful, proportionate and
fair to people is a human judgement. This module is the fixed checklist that judgement is recorded against, and nothing more:

    template(run)            a blank review record bound to one evaluation run (its canonical report sha256)
    validate(record)         the problems of a completed record (empty = valid)
    summarize(record)        counts per rating and the items rated ``concern`` / ``fails``

A review is **release input only**: it never changes a metric, a threshold, the report or the runner's result code, and the runner never
reads it. The release owner weighs it next to the evaluation report.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

REVIEW_SCHEMA = "reasoning-management-review-v1"
RATINGS = ("meets", "concern", "fails", "not_applicable")
NEEDS_NOTES = frozenset({"concern", "fails", "not_applicable"})


@dataclass(frozen=True)
class ReviewItem:
    item_id: str
    question: str
    look_for: str
    automated_signal: tuple[str, ...] = ()       # the Phase 19-A metrics that measure part of it (the human judges the rest)


CHECKLIST: tuple[ReviewItem, ...] = (
    ReviewItem("factual_grounding", "Is every statement on the card supported by the cited findings and records?",
               "Claims, numbers and names that do not appear in the cited evidence; evidence cited for something it does not show.",
               ("grounding_failure_rate",)),
    ReviewItem("proportionality", "Is the card's weight proportionate to the evidence (sample size, effect size, duration)?",
               "Small samples presented as patterns; routine variation presented as a problem; urgency without a reason."),
    ReviewItem("management_usefulness", "Would a manager know what to look at or ask next after reading it?",
               "Restated data without interpretation; vague significance; suggested investigations that are not actionable."),
    ReviewItem("uncertainty_calibration", "Does the stated confidence match the evidence, and is uncertainty stated plainly?",
               "Strong confidence on thin or contradicted evidence; hedging that hides a clear finding; confidence above the case ceiling.",
               ("validation_rejection_rate",)),
    ReviewItem("unnecessary_churn", "Did cards stay stable when the evidence did not materially change?",
               "Rewritten wording, new cards for the same topic, or status flips across runs without a material change.",
               ("unnecessary_new_card_rate", "unnecessary_field_rewrite_rate", "case_identity_stability")),
    ReviewItem("lifecycle_correctness", "Are the lifecycle states right (active, monitoring, stale, resolved) and their transitions justified?",
               "Cards kept active after their evidence disappeared; resolution without a reason; flip-flopping states.",
               ("lifecycle_churn_rate",)),
    ReviewItem("atlas_questions_quality", "Are the Atlas Questions specific, answerable by a manager, and about context Monday cannot show?",
               "Questions the data already answers; leading or loaded questions; questions about a person's character."),
    ReviewItem("duplicate_questions", "Is each question asked once, and never re-asked after the manager answered it?",
               "The same question in two wordings; an answered question asked again.", ("duplicate_question_rate",)),
    ReviewItem("hr_blame_personality_language", "Is the language free of HR judgements, blame and personality claims about people?",
               "Words about attitude, effort, competence or character; blame for outcomes the data cannot attribute; ranking people."),
    ReviewItem("evidence_traceability", "Can every claim be traced from the card to its findings and Monday records?",
               "Statements without references; references that do not resolve; evidence the reader cannot open."),
    ReviewItem("executive_brief_usefulness", "Does the ExecutiveBrief prioritise what matters and stay faithful to the underlying cards?",
               "Claims not on any card; important cards missing; tone stronger than the cards support."),
    ReviewItem("limitations_counter_evidence", "Are limitations and counter-evidence visible, not buried or omitted?",
               "Contradicting findings missing from the card; limitations that are boilerplate rather than specific."),
)
ITEM_IDS = tuple(item.item_id for item in CHECKLIST)


def template(run: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """A blank review record. ``run`` is the evaluation runner's JSON (``RunnerResult.to_dict``); the record is bound to its report."""
    return {"schema": REVIEW_SCHEMA, "report_sha256": (run or {}).get("report_sha256"), "evaluation_mode": (run or {}).get("mode"),
            "reviewer": "", "reviewed_at": "", "release_input_only": True, "ratings": list(RATINGS),
            "items": [{"item_id": item.item_id, "question": item.question, "look_for": item.look_for,
                       "automated_signal": list(item.automated_signal), "rating": None, "notes": "", "examples": []} for item in CHECKLIST],
            "overall_notes": ""}


def validate(record: Mapping[str, Any], *, run: Mapping[str, Any] | None = None) -> list[str]:
    """Problems of a completed review record (empty when it is complete and well formed). With ``run``, the record must be bound to it."""
    if not isinstance(record, Mapping):
        return ["the review record must be a JSON object"]
    problems = []
    if record.get("schema") != REVIEW_SCHEMA:
        problems.append(f"schema must be {REVIEW_SCHEMA}")
    for name in ("reviewer", "reviewed_at"):
        if not isinstance(record.get(name), str) or not record[name].strip():
            problems.append(f"{name} is required")
    sha = record.get("report_sha256")
    if not isinstance(sha, str) or len(sha) != 64:
        problems.append("report_sha256 must name the reviewed evaluation report")
    elif run is not None and sha != run.get("report_sha256"):
        problems.append("report_sha256 does not match the evaluation run")
    items = record.get("items")
    if not isinstance(items, list):
        return problems + ["items must be a list"]
    seen: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            problems.append(f"items[{index}] must be an object")
            continue
        item_id = item.get("item_id")
        if item_id not in ITEM_IDS:
            problems.append(f"items[{index}]: unknown item {item_id!r}")
            continue
        if item_id in seen:
            problems.append(f"{item_id}: rated twice")
        seen.append(str(item_id))
        rating = item.get("rating")
        if rating not in RATINGS:
            problems.append(f"{item_id}: rating must be one of {', '.join(RATINGS)}")
        elif rating in NEEDS_NOTES and not (isinstance(item.get("notes"), str) and item["notes"].strip()):
            problems.append(f"{item_id}: a {rating} rating needs notes")
    problems.extend(f"{item_id}: not rated" for item_id in ITEM_IDS if item_id not in seen)
    return problems


def summarize(record: Mapping[str, Any]) -> dict[str, Any]:
    """Counts per rating and the items needing attention. Release input only; it decides nothing."""
    items = [item for item in record.get("items", []) if isinstance(item, Mapping)]
    counts = {rating: sum(1 for item in items if item.get("rating") == rating) for rating in RATINGS}
    return {"schema": REVIEW_SCHEMA, "report_sha256": record.get("report_sha256"), "reviewer": record.get("reviewer"), "counts": counts,
            "concerns": sorted(str(item["item_id"]) for item in items if item.get("rating") == "concern"),
            "fails": sorted(str(item["item_id"]) for item in items if item.get("rating") == "fails"),
            "release_input_only": True}
