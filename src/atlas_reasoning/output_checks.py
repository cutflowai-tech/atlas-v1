"""Deterministic checks of model-written reasoning against its case (``REV/07`` #3, ``REV/08``), beyond the reasoning-v1 contract.

The contract already guarantees that every claim cites evidence of its case and that confidence never exceeds the upstream
ceiling (``contracts.result_case_errors``). This module adds the check the contract cannot express: **no invented numbers**. Every
number written in a user-visible text field must be one of the case's own deterministic values (statement parameters, record
values, block samples and comparisons, sample sizes, scope counts, digits inside case strings such as dates), a rate optionally
written as a percentage (0.6875 → 69% / 68.75%; only values between 0 and 1 are scaled), rounded to the precision the text uses.
Numbers in management context or memory are never admitted: context is not evidence. A derived figure the case does not carry (a new
difference, average or projection) is refused with ``UNSUPPORTED_NUMBER``.

Errors are ``"<CODE>: <detail>"`` like the contracts, so callers can treat both alike.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import Any

# Values every text may use without the case carrying them: zero, one and a whole (100%).
_ALWAYS = (0.0, 1.0, 100.0)
# A number token not glued to an identifier on either side ("editor-label-12", "rc1_…", "Q3" are not numbers); after a hyphen only
# when a digit precedes it (the end of a range such as "12-16", or the parts of a date "2026-09-15").
_NUMBER = re.compile(r"(?<![\w.])(?<![^\W\d]-)(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\w]|\.\d)")
# An ISO date or timestamp inside a case string: every part (year, month, day, hour, ...) may be written ("since 15 September").
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?")


def _numbers_in(value: Any) -> Iterator[float]:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, str):
        for _, number, _ in text_numbers(value):   # free-standing numbers only: never digits inside hex IDs
            yield number
        for stamp in _TIMESTAMP.findall(value):
            yield from (float(part) for part in re.findall(r"\d+", stamp))
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _numbers_in(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _numbers_in(item)


def case_numbers(case: Mapping[str, Any], *, include_delta: bool = True) -> frozenset[float]:
    """Every number a text about ``case`` may use: the case's values and those values as percentages. With ``include_delta`` the
    before-values of the material delta count too (an update may say "up from 11 to 12"); without it only the current evidence."""
    sources = [case["scope"], case["supporting_findings"], case["contradicting_findings"], case["current_evidence"], case.get("identity_dimensions"),
               case["subject_id"], case.get("material_delta") if include_delta else None]
    base = {abs(number) for number in _numbers_in(sources)} | set(_ALWAYS)
    # Only a rate (a value between 0 and 1) may be written as a percentage; scaling counts, sample sizes or date parts by 100 would
    # admit almost every small integer (review of PR #34).
    return frozenset(base | {number * 100 for number in base if number <= 1})


def text_numbers(text: str) -> list[tuple[str, float, int]]:
    """(token, value, decimals) of every free-standing number in ``text``."""
    found = []
    for match in _NUMBER.finditer(text):
        whole, fraction = match.group(1).replace(",", ""), match.group(2) or ""
        found.append((match.group(0), float(f"{whole}.{fraction}" if fraction else whole), len(fraction)))
    return found


def supported(value: float, decimals: int, allowed: frozenset[float]) -> bool:
    tolerance = 0.5 * 10 ** -decimals + 1e-9
    return any(abs(candidate - value) <= tolerance for candidate in allowed)


def visible_texts(output: Mapping[str, Any]) -> Iterator[tuple[str, str]]:
    """(field path, text) of every user-visible text in a result (or the patchable part of one)."""
    for name in ("title", "reasoning_summary"):
        if isinstance(output.get(name), str):
            yield name, output[name]
    for name in ("observation", "interpretation", "management_significance"):
        claim = output.get(name)
        if isinstance(claim, Mapping):
            yield f"{name}/statement", str(claim.get("statement", ""))
    for name in ("supporting_evidence", "counter_evidence"):
        for i, claim in enumerate(output.get(name) or []):
            yield f"{name}/{i}/statement", str(claim.get("statement", ""))
    for i, row in enumerate(output.get("alternative_explanations") or []):
        yield f"alternative_explanations/{i}/explanation", str(row.get("explanation", ""))
    if isinstance(output.get("confidence"), Mapping):
        yield "confidence/rationale", str(output["confidence"].get("rationale", ""))
    for i, text in enumerate(output.get("limitations") or []):
        yield f"limitations/{i}", str(text)
    for i, row in enumerate(output.get("questions_for_management") or []):
        yield f"questions_for_management/{i}/text", str(row.get("text", ""))
        yield f"questions_for_management/{i}/reason", str(row.get("reason", ""))
    for i, row in enumerate(output.get("suggested_investigations") or []):
        yield f"suggested_investigations/{i}/text", str(row.get("text", ""))


def unsupported_number_errors(output: Mapping[str, Any], case: Mapping[str, Any], *, include_delta: bool = True) -> list[str]:
    allowed = case_numbers(case, include_delta=include_delta)
    errors = []
    for path, text in visible_texts(output):
        for token, value, decimals in text_numbers(text):
            if not supported(value, decimals, allowed):
                errors.append(f"UNSUPPORTED_NUMBER: {path}: {token!r} is not a value of the case")
    return errors
