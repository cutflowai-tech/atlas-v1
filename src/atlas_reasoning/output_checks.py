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
# A month name ("May" only capitalized: "may" is a modal verb) with a day or year written right next to it.
_MONTH_NAME = (r"(?:(?i:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
               r"nov(?:ember)?|dec(?:ember)?)|May)")
_DATED = re.compile(r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH_NAME + r"(?:,?\s+\d{4})?\b|\b" + _MONTH_NAME +
                    r"\s+\d{1,4}(?:st|nd|rd|th)?(?:,?\s+\d{4})?\b")


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
    """Where ``text`` writes a date: an ISO date, or a day / year directly next to a month name ("3 September", "September 2026")."""
    return [match.span() for match in _TIMESTAMP.finditer(text)] + [match.span() for match in _DATED.finditer(text)]


# Durations are stored in seconds (``*_seconds`` keys). A text may give one in minutes, hours or days (Phase 15) — only written with
# that unit ("16.5 hours"), at the precision it writes; a converted duration is never a count.
_DURATION_UNITS = {"minute": 60.0, "hour": 3600.0, "day": 86400.0}
_UNIT_AFTER = re.compile(r"\s*(?:-\s*)?(min(?:ute)?s?|h(?:ou)?rs?|hours?|days?)\b", re.IGNORECASE)


def _durations_in(value: Any, key: str = "") -> Iterator[tuple[str, float]]:
    """Every duration value as (unit, value): numbers under keys naming a unit (``*seconds`` in seconds, ``*days`` / ``*hours`` /
    ``*minutes`` in that unit)."""
    if isinstance(value, Mapping):
        for name, item in value.items():
            yield from _durations_in(item, str(name))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _durations_in(item, key)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        lowered = key.lower()
        for unit in ("second", "minute", "hour", "day"):
            if unit in lowered:
                yield unit, abs(float(value))
                break


def case_durations(case: Mapping[str, Any], *, include_delta: bool = True) -> dict[str, frozenset[float]]:
    """The case's durations in each unit a text may use."""
    found = list(_durations_in(_case_sources(case, include_delta)))
    seconds = [value * (1.0 if unit == "second" else _DURATION_UNITS[unit]) for unit, value in found]
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
    base = _case_values(case, include_delta)
    return frozenset(base | _percentages(base))


def _case_values(case: Mapping[str, Any], include_delta: bool) -> frozenset[float]:
    return frozenset({abs(number) for number in _numbers_in(_case_sources(case, include_delta), set())} | set(_ALWAYS))


def _percentages(base: frozenset[float]) -> frozenset[float]:
    # Only a rate (a value between 0 and 1) may be written as a percentage; scaling counts, sample sizes or date parts by 100 would
    # admit almost every small integer (review of PR #34). Accepted only where the text writes a percentage ("69%", "69 percent").
    return frozenset(number * 100 for number in base if number <= 1)


# Numbers written as words (Phase 15): "twelve projects" is held to the same rule as "12 projects". "one" (always allowed) and
# vague quantities ("several", "a few", "most") are not numbers.
_NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
                 "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
                 "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100, "dozen": 12,
                 "thousand": 1000}
# Every number word, "one" included (names of quantities, never of people or entities).
# "zero" is deliberately absent: 0 is always an allowed value, so a "Zero projects were late" claim must not be exempted as a quantity.
NUMBER_WORDS = frozenset({*_NUMBER_WORDS, "one", "none", "first", "second", "third", "fourth", "fifth", "half", "both", "single"})
_TENS = ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_UNITS = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
_WORD = re.compile(r"\b(?:(" + "|".join(_TENS) + r")[-\s](" + "|".join(_UNITS) + r")|(" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) +
                   r"))\b", re.IGNORECASE)
# Digits with a suffix are numbers too: ordinals ("37th"), multiples ("3x"), thousands ("2k").
_SUFFIXED = re.compile(r"(?<![\w.])(\d+)(st|nd|rd|th|x|k)\b", re.IGNORECASE)
_PERCENT_AFTER = re.compile(r"\s*(?:%|per\s?cent\b|(?:percentage\s+)?points?\b|pp\b)", re.IGNORECASE)
_APPROXIMATE_BEFORE = re.compile(r"(?:about|around|roughly|approximately|nearly|almost|over|under|more than|less than|some|~)\s*$", re.IGNORECASE)


def text_numbers(text: str) -> list[tuple[str, float, int]]:
    """(token, value, decimals) of every free-standing number in ``text``, digits or number words."""
    return [(token, value, decimals) for token, value, decimals, _, _ in _numbers_with_positions(text)]


def _numbers_with_positions(text: str) -> list[tuple[str, float, int, int, int]]:
    found = []
    for match in _NUMBER.finditer(text):
        whole, fraction = match.group(1).replace(",", ""), match.group(2) or ""
        found.append((match.group(0), float(f"{whole}.{fraction}" if fraction else whole), len(fraction), match.start(), match.end()))
    for match in _WORD.finditer(text):
        if match.group(1):
            value = _NUMBER_WORDS[match.group(1).lower()] + _NUMBER_WORDS.get(match.group(2).lower(), 1 if match.group(2).lower() == "one" else 0)
        else:
            value = _NUMBER_WORDS[match.group(3).lower()]
        found.append((match.group(0), float(value), 0, match.start(), match.end()))
    for match in _SUFFIXED.finditer(text):
        number = float(match.group(1)) * (1000 if match.group(2).lower() == "k" else 1)
        found.append((match.group(0), number, 0, match.start(), match.end()))
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


def _matches_value(value: float, decimals: int, values: frozenset[float], *, approximate: bool) -> bool:
    """A whole number must equal a whole case value, unless the text marks it as approximate ("about 12"); a number written with
    decimals may round a case value to that precision."""
    if decimals > 0 or approximate:
        return supported(value, decimals, values)
    return value in values


def number_supported(text: str, value: float, decimals: int, start: int, end: int, *, base: frozenset[float], percents: frozenset[float],
                     dates: frozenset[float], durations: Mapping[str, frozenset[float]]) -> bool:
    """Whether one number of ``text`` is grounded in the case, judged by how the text writes it (Phase 15):

    - with a duration unit ("16.5 hours"): only a case duration in that unit;
    - with a percent sign or word ("69%"): a case rate as a percentage, or a case value;
    - inside a written date ("3 September", "2026-09-03"): a part of a case date;
    - otherwise: a case value (exactly, for a whole number not marked approximate)."""
    approximate = bool(_APPROXIMATE_BEFORE.search(text[max(0, start - 20): start]))
    unit = _unit(text, end)
    if unit is not None:
        return _matches_value(value, decimals, durations[unit], approximate=True) or value in _ALWAYS
    if _PERCENT_AFTER.match(text, end):
        return _matches_value(value, decimals, percents | base, approximate=True)
    if decimals == 0 and value in dates and any(low <= start < high for low, high in _date_spans(text)):
        return True
    return _matches_value(value, decimals, base, approximate=approximate)


def unsupported_number_errors(output: Mapping[str, Any], case: Mapping[str, Any], *, include_delta: bool = True) -> list[str]:
    base = _case_values(case, include_delta)
    percents, dates = _percentages(base), case_date_parts(case, include_delta=include_delta)
    durations = case_durations(case, include_delta=include_delta)
    errors = []
    for path, text in visible_texts(output):
        for token, value, decimals, start, end in _numbers_with_positions(text):
            if not number_supported(text, value, decimals, start, end, base=base, percents=percents, dates=dates, durations=durations):
                errors.append(f"UNSUPPORTED_NUMBER: {path}: {token!r} is not a value of the case")
    return errors


def written_numbers(text: str) -> list[tuple[str, float, int, str, bool]]:
    """(token, value, decimals, form, approximate) of every number in ``text``, by how it is written: ``percent``, ``date`` (a part of
    a written date), ``minute`` / ``hour`` / ``day`` (a duration with that unit) or ``plain``. Additive (Phase 17): lets a downstream
    text be held to the numbers another text writes, in the same form, with the rules ``number_supported`` applies to a case."""
    spans = _date_spans(text)
    found = []
    for token, value, decimals, start, end in _numbers_with_positions(text):
        unit = _unit(text, end)
        if unit is not None:
            form = unit
        elif _PERCENT_AFTER.match(text, end):
            form = "percent"
        elif decimals == 0 and any(low <= start < high for low, high in spans):
            form = "date"
        else:
            form = "plain"
        found.append((token, value, decimals, form, bool(_APPROXIMATE_BEFORE.search(text[max(0, start - 20): start]))))
    return found
