"""Management intelligence slots for the CEO Dashboard (none approved in Atlas V1).

Each future management rule (overall status, score, needs-attention, recommendations, ...) has
a named slot here so the dashboard can show where it will appear. No slot computes anything:
every value is ``None`` with the state ``rule_not_approved`` and the reason. Approving a rule
means adding it to a versioned contract and implementing it here, separately from both the
metric engine and the presentation layer.
"""

from __future__ import annotations

from typing import Any

from atlas_commander.capabilities import capabilities

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

# Contract 1.5 (D20--D50) changes what is factual, so the reasons for the still-unapproved judgements change with it. The
# Overall Status becomes a real deterministic result (the profile's ``overall``), and there is no Overall score at all (D37).
V15_REASONS: dict[str, str] = {
    "positive_signals": "Positive Monday labels are shown as factual evidence; no Strength or Recognition threshold is approved.",
    "workload_capacity": "Active Work statuses are approved; no capacity threshold or capacity judgement is approved.",
    "reward_recommendation": "No reward rule is approved; positive labels are evidence and never an automatic reward recommendation.",
    "trend_direction": "Recent Change is shown as a fact with both windows and samples; no Trend materiality threshold is approved.",
}

EDITOR_SLOTS = ("overall_status", "overall_score", "needs_attention", "positive_signals", "trend_direction", "workload_capacity",
                "management_recommendation", "reward_recommendation")
TEAM_SLOTS = ("needs_attention", "positive_signals", "team_patterns", "trend_direction", "workload_capacity")
V15_EDITOR_SLOTS = tuple(slot for slot in EDITOR_SLOTS if slot not in {"overall_status", "overall_score"})
V15_PENDING_SLOTS = tuple(slot for slot in PENDING_RULES if slot not in {"overall_status", "overall_score"})


def pending(slot: str, *, v15: bool = False) -> dict[str, Any]:
    rule = PENDING_RULES[slot]
    reason = V15_REASONS.get(slot, rule["reason"]) if v15 else rule["reason"]
    return {"slot": slot, "label": rule["label"], "value": None, "state": RULE_NOT_APPROVED, "reason": reason}


def editor_intelligence(contract_version: str | None = None) -> dict[str, dict[str, Any]]:
    """Pending management judgements for one Editor under ``contract_version``."""
    v15 = capabilities(contract_version).editor_intelligence
    return {slot: pending(slot, v15=v15) for slot in (V15_EDITOR_SLOTS if v15 else EDITOR_SLOTS)}


def team_intelligence(contract_version: str | None = None) -> dict[str, dict[str, Any]]:
    v15 = capabilities(contract_version).editor_intelligence
    return {slot: pending(slot, v15=v15) for slot in TEAM_SLOTS}
