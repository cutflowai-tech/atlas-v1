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
# An ISO date or timestamp inside a case string. Its parts (year, month, day, hour, ...) are *date parts*: a text may write them only
# as a date ("since 15 September", "2026-09-15"), never as a count or a duration (Phase 15: otherwise every number up to 59 passes).
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?")
_MONTH = re.compile(r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
                    r"nov(?:ember)?|dec(?:ember)?)\b", re.IGNORECASE)


def _numbers_in(value: Any, dates: set[float] | None = None) -> Iterator[float]:
    """The numbers of a case value; date parts of timestamps go to ``dates`` instead."""
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, str):
        stamps = _TIMESTAMP.findall(value)
        if dates is not None:
            dates.update(float(part) for stamp in stamps for part in re.findall(r"\d+", stamp))
        for _, number, _ in text_numbers(_TIMESTAMP.sub(" ", value)):   # free-standing numbers only: never digits inside hex IDs
            yield number
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _numbers_in(item, dates)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _numbers_in(item, dates)


def _case_sources(case: Mapping[str, Any], include_delta: bool) -> list[Any]:
    return [case["scope"], case["supporting_findings"], case["contradicting_findings"], case["current_evidence"], case.get("identity_dimensions"),
            case["subject_id"], case.get("material_delta") if include_delta else None]


def case_date_parts(case: Mapping[str, Any], *, include_delta: bool = True) -> frozenset[float]:
    """The parts of every date and timestamp the case carries."""
    dates: set[float] = set()
    for _ in _numbers_in(_case_sources(case, include_delta), dates):
        pass
    return frozenset(dates)


def _date_spans(text: str) -> list[tuple[int, int]]:
    """Where ``text`` writes a date: an ISO date, or a day / year next to a month name."""
    spans = [match.span() for match in _TIMESTAMP.finditer(text)]
    for match in _MONTH.finditer(text):
        spans.append((max(0, match.start() - 6), min(len(text), match.end() + 7)))
    return spans


# Durations are stored in seconds (``*_seconds`` keys). A text may give one in minutes, hours or days (Phase 15) — only written with
# that unit ("16.5 hours"), at the precision it writes; a converted duration is never a count.
_DURATION_UNITS = {"minute": 60.0, "hour": 3600.0, "day": 86400.0}
_UNIT_AFTER = re.compile(r"\s*(?:-\s*)?(min(?:ute)?s?|h(?:ou)?rs?|hours?|days?)\b", re.IGNORECASE)


def _durations_in(value: Any, key: str = "") -> Iterator[float]:
    """Every duration value (a number under a key ending in ``seconds``), in seconds."""
    if isinstance(value, Mapping):
        for name, item in value.items():
            yield from _durations_in(item, str(name))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _durations_in(item, key)
    elif isinstance(value, (int, float)) and not isinstance(value, bool) and key.endswith("seconds"):
        yield abs(float(value))


def case_durations(case: Mapping[str, Any], *, include_delta: bool = True) -> dict[str, frozenset[float]]:
    """The case's durations in each unit a text may use."""
    seconds = list(_durations_in(_case_sources(case, include_delta)))
    return {unit: frozenset(value / size for value in seconds) for unit, size in _DURATION_UNITS.items()}


def _unit(text: str, end: int) -> str | None:
    match = _UNIT_AFTER.match(text, end)
    if match is None:
        return None
    word = match.group(1).lower()
    return "minute" if word.startswith("min") else "day" if word.startswith("day") else "hour"


def case_numbers(case: Mapping[str, Any], *, include_delta: bool = True) -> frozenset[float]:
    """Every number a text about ``case`` may use anywhere: the case's values and rates as percentages (durations in other units and
    date parts are accepted only where the text writes a duration or a date: ``unsupported_number_errors``).
    With ``include_delta`` the before-values of the material delta count too (an update may say "up from 11 to 12"); without it only
    the current evidence. Human context (``manager_context``, ``memory_context``) is never a source: context is not evidence."""
    sources = _case_sources(case, include_delta)
    base = {abs(number) for number in _numbers_in(sources, set())} | set(_ALWAYS)
    # Only a rate (a value between 0 and 1) may be written as a percentage; scaling counts, sample sizes or date parts by 100 would
    # admit almost every small integer (review of PR #34).
    return frozenset(base | {number * 100 for number in base if number <= 1})


# Numbers written as words (Phase 15): "twelve projects" is held to the same rule as "12 projects". "one" (always allowed) and
# vague quantities ("several", "a few", "most") are not numbers.
_NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
                 "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
                 "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100, "dozen": 12,
                 "thousand": 1000}
_WORD = re.compile(r"\b(" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")\b", re.IGNORECASE)


def text_numbers(text: str) -> list[tuple[str, float, int]]:
    """(token, value, decimals) of every free-standing number in ``text``, digits or number words."""
    return [(token, value, decimals) for token, value, decimals, _, _ in _numbers_with_positions(text)]


def _numbers_with_positions(text: str) -> list[tuple[str, float, int, int, int]]:
    found = []
    for match in _NUMBER.finditer(text):
        whole, fraction = match.group(1).replace(",", ""), match.group(2) or ""
        found.append((match.group(0), float(f"{whole}.{fraction}" if fraction else whole), len(fraction), match.start(), match.end()))
    for match in _WORD.finditer(text):
        found.append((match.group(0), float(_NUMBER_WORDS[match.group(1).lower()]), 0, match.start(), match.end()))
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
    dates = case_date_parts(case, include_delta=include_delta)
    durations = case_durations(case, include_delta=include_delta)
    errors = []
    for path, text in visible_texts(output):
        spans = _date_spans(text)
        for token, value, decimals, start, end in _numbers_with_positions(text):
            if supported(value, decimals, allowed):
                continue
            if decimals == 0 and value in dates and any(low <= start < high for low, high in spans):
                continue     # a date the case carries, written as a date
            unit = _unit(text, end)
            if unit is not None and supported(value, decimals, durations[unit]):
                continue     # a duration the case carries, written in another unit
            errors.append(f"UNSUPPORTED_NUMBER: {path}: {token!r} is not a value of the case")
    return errors
