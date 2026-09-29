"""Guard for an optional AI rewrite of a finding (Task 48, HANDOFF §30-31).

Atlas does not call any language model. When one is used later to shorten, combine or re-word findings, its output passes
through ``rewrite_problems`` first. A rewrite is rejected (and the deterministic text kept) when it:

- introduces a number that is not in the finding's structured fields or deterministic text: no invented metrics;
- uses causal, blame, psychological, disciplinary or HR language (``FORBIDDEN``);
- names a person who is not an affected Editor of the finding;
- sounds more certain than the finding's evidence ("proves", "definitely", "will be late") when evidence is not strong.

The deterministic finding payload always remains the source of truth. ``accept_rewrite`` never edits a rewrite: it returns
either the rewrite, unchanged, or the deterministic text.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

FORBIDDEN = (
    r"\bcaus(?:e|ed|es|ing)\b", r"\bbecause of\b", r"\bdue to\b", r"\bleads? to\b", r"\bresult(?:s|ed)? in\b", r"\bfault\b", r"\bblame\w*\b",
    r"\bnegligen\w*\b", r"\blazy\b", r"\bcareless\w*\b", r"\bunmotivated\b", r"\bdisciplin\w*\b", r"\battitude\b", r"\bpersonality\b",
    r"\btalent\w*\b", r"\bfire[ds]?\b", r"\bterminat\w*\b", r"\bdismiss\w*\b", r"\bpromot\w*\b", r"\bdemot\w*\b", r"\bsalary\b", r"\bpay cut\b",
    r"\bpunish\w*\b", r"\bwarning letter\b", r"\bperformance improvement plan\b", r"\bunderperform\w*\b", r"\bincompeten\w*\b",
)
OVERCERTAIN = (r"\bprove[sd]?\b", r"\bdefinitely\b", r"\bcertainly\b", r"\bwill be late\b", r"\bguarantee\w*\b", r"\bclearly shows\b")
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)?")


def _numbers(text: str) -> set[str]:
    return {match.replace(",", ".").lstrip("-").rstrip("0").rstrip(".") or "0" for match in NUMBER.findall(text)}


def _flatten(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _flatten(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _flatten(item)
    elif value is not None:
        yield str(value)


def rewrite_problems(finding: Mapping[str, Any], rewrite: str, editor_names: Mapping[str, str], all_names: Iterable[str] = ()) -> list[str]:
    """Why ``rewrite`` may not replace the deterministic text of ``finding`` (a serialized finding); empty when acceptable."""
    problems: list[str] = []
    lowered = rewrite.lower()
    for pattern in FORBIDDEN:
        if re.search(pattern, lowered):
            problems.append(f"forbidden language: {pattern}")
    if (finding.get("confidence") or {}).get("level") != "strong":
        problems += [f"over-certain language for {finding.get('confidence', {}).get('level')} evidence: {pattern}" for pattern in OVERCERTAIN
                     if re.search(pattern, lowered)]
    allowed = set()
    for source in (finding.get("text") or {}, [statement.get("params") for statement in finding.get("statements", [])], finding.get("sample_size")):
        for item in _flatten(source):
            allowed |= _numbers(item)
            try:
                number = float(item)
            except ValueError:
                continue
            allowed |= _numbers(f"{number * 100:.0f}") | _numbers(f"{number * 100:.1f}") | _numbers(f"{number:.1f}")
    invented = sorted(_numbers(rewrite) - allowed)
    if invented:
        problems.append(f"numbers not in the finding: {invented}")
    affected = {editor_names.get(editor, editor) for editor in finding.get("affected_editors", [])}
    for name in all_names:
        if name and name not in affected and re.search(rf"\b{re.escape(name)}\b", rewrite):
            problems.append(f"names a person outside the finding: {name}")
    return problems


def accept_rewrite(finding: Mapping[str, Any], rewrite: str, editor_names: Mapping[str, str], all_names: Iterable[str] = ()) -> tuple[str, list[str]]:
    """The rewrite when it passes the guard, else the deterministic summary; with the problems found."""
    problems = rewrite_problems(finding, rewrite, editor_names, all_names)
    return (rewrite if not problems else str((finding.get("text") or {}).get("summary", ""))), problems
