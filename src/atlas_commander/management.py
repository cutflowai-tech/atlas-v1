"""Management intelligence slots for the CEO Dashboard (none approved in Atlas V1).

Each future management rule (overall status, score, needs-attention, recommendations, ...) has
a named slot here so the dashboard can show where it will appear. No slot computes anything:
every value is ``None`` with the state ``rule_not_approved`` and the reason. Approving a rule
means adding it to a versioned contract and implementing it here, separately from both the
metric engine and the presentation layer.
"""

from __future__ import annotations

from typing import Any

RULE_NOT_APPROVED = "rule_not_approved"

PENDING_RULES: dict[str, dict[str, str]] = {
    "overall_status": {"label": "Overall status",
                       "reason": "No overall performance status rule is approved for Atlas V1."},
    "overall_score": {"label": "Overall score",
                      "reason": "Atlas V1 has no approved scoring; speed, deadline and quality stay separate with their own evidence."},
    "needs_attention": {"label": "Needs attention",
                        "reason": "No rule defines when an Editor needs management attention."},
    "positive_signals": {"label": "Positive signals",
                         "reason": "No approved positive quality signal exists in V1; For Bonus is context only (D10)."},
    "trend_direction": {"label": "Improving / declining",
                        "reason": "No trend rule is approved; monthly figures are shown with their sample sizes only."},
    "workload_capacity": {"label": "Workload / capacity judgement",
                          "reason": "Which current statuses count as active workload is an open decision (DECISIONS.md, open decision 5)."},
    "management_recommendation": {"label": "Management recommendation",
                                  "reason": "Recommendations are outside Atlas V1 scope; AI may explain but is never the source of truth."},
    "reward_recommendation": {"label": "Reward recommendation",
                              "reason": "No reward rule is approved; For Bonus labels are context only (D10)."},
    "team_patterns": {"label": "Team / process patterns",
                      "reason": "No rule defines a team or process pattern; label counts per Editor are shown as facts only."},
}

EDITOR_SLOTS = ("overall_status", "overall_score", "needs_attention", "positive_signals", "trend_direction", "workload_capacity",
                "management_recommendation", "reward_recommendation")
TEAM_SLOTS = ("needs_attention", "positive_signals", "team_patterns", "trend_direction", "workload_capacity")


def pending(slot: str) -> dict[str, Any]:
    rule = PENDING_RULES[slot]
    return {"slot": slot, "label": rule["label"], "value": None, "state": RULE_NOT_APPROVED, "reason": rule["reason"]}


def editor_intelligence() -> dict[str, dict[str, Any]]:
    return {slot: pending(slot) for slot in EDITOR_SLOTS}


def team_intelligence() -> dict[str, dict[str, Any]]:
    return {slot: pending(slot) for slot in TEAM_SLOTS}
