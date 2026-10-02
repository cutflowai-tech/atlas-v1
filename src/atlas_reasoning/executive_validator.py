"""The deterministic ExecutiveBrief validator (``REV/17`` #5, #6, #9): the final gate before an executive candidate becomes canonical.

    report = validate_brief(candidate, executive_input, expected, references)
    if not report.ok: ...   # never committed; the previous valid brief stays current

It is separate from the prompt and runs on the **complete** candidate (the model's sections with Python's identity and provenance,
``executive.assemble_brief``). It is an additional downstream boundary: it never weakens or replaces the Phase 15 guardrails, which
already accepted every result in the input. No LLM judges anything here.

Grounding model: an executive statement is explainable only as *statement → one or more canonical ReasoningResult IDs of the synthesis
input*. A statement is held to what those cited results say (their wording as it appears in the input), never to raw detectors, Monday
events or evidence records.

Rules (stable codes, ``ExecutiveCode``):

1. **Hidden reasoning** — no field for it (``RAW_REASONING_FIELD``: any reasoning-like key, anywhere) and no reasoning dump in a
   statement (``HIDDEN_REASONING_TEXT``).
2. **References** — every statement cites ≥ 1 result (``MISSING_RESULT_REFERENCE``); each reference is a well-formed result ID
   (``INVALID_REFERENCE``), once per statement (``DUPLICATE_REFERENCE``), and one of the input results. A reference outside the input
   is named precisely: a canonical result that was not supplied (``RESULT_NOT_IN_INPUT``), a refused Phase 15 candidate
   (``FAILED_CANDIDATE_REFERENCE``), a raw source identifier — Intelligence V2 finding, evidence record, case, fingerprint, work
   item or Monday item (``RAW_SOURCE_REFERENCE``) — or an ID that does not exist (``UNKNOWN_RESULT``).
3. **Numbers** — every number in a statement is written by one of its cited results (``UNSUPPORTED_NUMBER``); the only derived numbers
   allowed are the count of cited results and of their distinct subjects.
4. **Metrics** — no metric term (score, index, rating, ranking, productivity, efficiency, ratio, "<x> rate" …) that the cited
   results do not use (``UNSUPPORTED_METRIC``).
5. **Entities** — every Editor ID is one the cited results concern (``UNKNOWN_ENTITY``); ``editor_context`` statements cite only
   results about their ``editor_id`` (``EDITOR_MISMATCH``).
6. **Lifecycle** — a resolved result is never a top concern and is described as resolved, never as current; an open result is never
   described as resolved; ``what_changed`` cites at least one result whose lifecycle shows a change (``LIFECYCLE_CONTRADICTION``).
7. **Questions** — ``unresolved_questions`` are questions ("?") taken from cited results that have open Atlas questions
   (``QUESTION_AS_FACT``, ``UNSUPPORTED_QUESTION``).
8. **Safety** — Phase 15's causality, people and certainty rules on every statement (``guardrails.statement_safety_violations``:
   ``CAUSAL_OVERCLAIM``, ``HR_JUDGMENT``, ``UNSUPPORTED_BLAME``, ``CONFIDENCE_EXCEEDED``); no high-confidence wording over weak results.
9. **Identity and provenance** — brief ID, version, run, input fingerprint, input results, prompt version, request ID and the
   answering model (``settings.model_identity_matches``) are what Python expected (``IDENTITY_MISMATCH``, ``PROVENANCE_MISMATCH``,
   ``MODEL_SUBSTITUTED``); the document satisfies ``executive-brief-v1`` (``CONTRACT_INVALID``); no statement is repeated
   (``DUPLICATE_STATEMENT``).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from atlas_reasoning import guardrails
from atlas_reasoning.enums import ConfidenceLevel, LifecycleStatus
from atlas_reasoning.executive_contracts import EDITOR_SECTION, SECTIONS, brief_errors
from atlas_reasoning.output_checks import NUMBER_WORDS, supported, written_numbers
from atlas_reasoning.settings import model_identity_matches

if TYPE_CHECKING:
    from atlas_reasoning.executive import ExecutiveInput

VALIDATOR_VERSION = "executive-validator-v1"


class ExecutiveCode(StrEnum):
    """Stable reasons an executive candidate is refused. Never renamed; new codes are only added."""

    CONTRACT_INVALID = "CONTRACT_INVALID"
    RAW_REASONING_FIELD = "RAW_REASONING_FIELD"
    HIDDEN_REASONING_TEXT = "HIDDEN_REASONING_TEXT"
    MISSING_RESULT_REFERENCE = "MISSING_RESULT_REFERENCE"
    INVALID_REFERENCE = "INVALID_REFERENCE"
    DUPLICATE_REFERENCE = "DUPLICATE_REFERENCE"
    RESULT_NOT_IN_INPUT = "RESULT_NOT_IN_INPUT"
    FAILED_CANDIDATE_REFERENCE = "FAILED_CANDIDATE_REFERENCE"
    RAW_SOURCE_REFERENCE = "RAW_SOURCE_REFERENCE"
    UNKNOWN_RESULT = "UNKNOWN_RESULT"
    UNSUPPORTED_NUMBER = "UNSUPPORTED_NUMBER"
    UNSUPPORTED_METRIC = "UNSUPPORTED_METRIC"
    UNKNOWN_ENTITY = "UNKNOWN_ENTITY"
    SECTION_MISMATCH = "SECTION_MISMATCH"
    INVALID_TEXT = "INVALID_TEXT"
    EDITOR_MISMATCH = "EDITOR_MISMATCH"
    LIFECYCLE_CONTRADICTION = "LIFECYCLE_CONTRADICTION"
    QUESTION_AS_FACT = "QUESTION_AS_FACT"
    UNSUPPORTED_QUESTION = "UNSUPPORTED_QUESTION"
    DUPLICATE_STATEMENT = "DUPLICATE_STATEMENT"
    CAUSAL_OVERCLAIM = "CAUSAL_OVERCLAIM"
    HR_JUDGMENT = "HR_JUDGMENT"
    UNSUPPORTED_BLAME = "UNSUPPORTED_BLAME"
    CONFIDENCE_EXCEEDED = "CONFIDENCE_EXCEEDED"
    PROJECTION = "PROJECTION"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    PROVENANCE_MISMATCH = "PROVENANCE_MISMATCH"
    MODEL_SUBSTITUTED = "MODEL_SUBSTITUTED"


# Python's or the provider's failures: re-asking the model cannot fix them.
NOT_RETRYABLE = frozenset({ExecutiveCode.IDENTITY_MISMATCH, ExecutiveCode.PROVENANCE_MISMATCH, ExecutiveCode.MODEL_SUBSTITUTED})


@dataclass(frozen=True)
class ExecutiveViolation:
    code: ExecutiveCode
    path: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "path": self.path, "detail": self.detail}


@dataclass(frozen=True)
class ExecutiveReport:
    violations: tuple[ExecutiveViolation, ...]
    validator_version: str = VALIDATOR_VERSION

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(sorted({violation.code.value for violation in self.violations}))

    @property
    def retryable(self) -> bool:
        return bool(self.violations) and not any(violation.code in NOT_RETRYABLE for violation in self.violations)

    def to_dict(self) -> dict[str, Any]:
        return {"validator_version": self.validator_version, "ok": self.ok, "codes": list(self.codes),
                "violations": [violation.to_dict() for violation in self.violations]}


@dataclass(frozen=True)
class ExpectedBrief:
    """What Python decided for the candidate (never the model)."""

    brief_id: str
    version: int
    run_id: str
    model: str                       # the configured (pinned) model
    prompt_version: str
    request_id: str | None = None


@dataclass(frozen=True)
class ReferenceIndex:
    """What the canonical store knows about references that are **not** in the synthesis input (``ExecutiveTransaction.classify_references``):
    which are canonical result IDs and which are refused Phase 15 candidates (their ``fc_`` IDs, or the result IDs they would have had)."""

    canonical: frozenset[str] = frozenset()
    failed_candidates: frozenset[str] = frozenset()


# --- identifiers -----------------------------------------------------------------------------------------------------------------------

_RESULT_ID = re.compile(r"^rr1_[0-9a-f]{32}$")
_FAILED_CANDIDATE_ID = re.compile(r"^fc_[0-9a-f]{32}$")
# Upstream or internal identifiers that are never an executive source: Intelligence V2 finding IDs, evidence references, case IDs,
# evidence fingerprints, work items, runs, calls, questions, and bare Monday item numbers.
_RAW_SOURCE_ID = re.compile(r"^(?:[a-z_.]+:[0-9a-f]{16}|ev1_[0-9a-f]{24}|rc1_[0-9a-f]{32}|ef1_[0-9a-f]{64}|wi_[0-9a-f]{32}|run_[0-9a-f]{32}|"
                            r"req_[0-9a-f]{32}|call_[0-9a-f]{32}|q[a-z]?_[0-9a-f]{32}|\d{4,})$")


def _references(row: Any) -> list[Any]:
    refs = row.get("result_ids") if isinstance(row, Mapping) else None
    return list(refs) if isinstance(refs, (list, tuple)) else []


def _statement_rows(candidate: Mapping[str, Any]) -> Iterator[tuple[str, str, int, Any]]:
    """(path, section, position, row) of every statement slot of a candidate, tolerant of malformed answers."""
    sections = candidate.get("sections")
    if not isinstance(sections, Mapping):
        return
    for section in SECTIONS:
        rows = sections.get(section)
        if isinstance(rows, (list, tuple)):
            for i, row in enumerate(rows):
                yield f"sections/{section}/{i}", section, i, row


def out_of_input_references(candidate: Mapping[str, Any], inp: ExecutiveInput) -> frozenset[str]:
    """The string references of a candidate that are not input results (to be classified by the store)."""
    known = inp.result_ids
    return frozenset(ref for _, _, _, row in _statement_rows(candidate) for ref in _references(row) if isinstance(ref, str) and ref not in known)


# --- text helpers --------------------------------------------------------------------------------------------------------------------


# Unicode hyphens and minus signs read as "-" (an Editor ID written with U+2011 is still that Editor ID).
_HYPHENS = str.maketrans({c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe63\uff0d"})


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).translate(_HYPHENS).replace("’", "'").casefold()


def _words(*phrases: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(phrases) + r")\b")


_NEGATORS = frozenset({"not", "no", "never", "without", "nor", "none", "neither", "isn't", "aren't", "wasn't", "weren't", "hasn't", "haven't",
                       "doesn't", "don't", "didn't", "cannot", "can't", "yet"})
_CLAUSE = re.compile(r"[,;:()—]|\s-\s|\bbut\b|\bwhile\b|\bwhereas\b|\bwhich\b")


def _negated(lowered: str, start: int) -> bool:
    head = lowered[:start]
    breaks = [match.end() for match in _CLAUSE.finditer(head)]
    clause = head[breaks[-1]:] if breaks else head
    return any(word in _NEGATORS or word.endswith("n't") for word in re.findall(r"[a-z']+", clause)[-4:])


def _negated_after(lowered: str, end: int) -> bool:
    """"needs no attention", "deserves no concern": the negation follows the phrase."""
    return re.match(r"\s+(?:no|not|none|nothing)\b", lowered[end:]) is not None


def _found(pattern: re.Pattern[str], text: str) -> bool:
    lowered = _norm(text)
    return any(not _negated(lowered, match.start()) and not _negated_after(lowered, match.end()) for match in pattern.finditer(lowered))


_REASONING_KEY = re.compile(r"chain|thought|think|reasoning|scratch|analysis|deliberat|internal|hidden|rationale", re.IGNORECASE)
_HIDDEN_TEXT = _words(r"chain[- ]of[- ]thought", r"step[- ]by[- ]step", r"my reasoning", r"internal reasoning", r"hidden reasoning", r"scratch ?pad",
                      r"let me", r"i (?:think|thought|reasoned|considered|need to|will now|first)")
_HIDDEN_MARKUP = re.compile(r"</?\s*(?:think|thinking|reasoning|analysis)\b")
# Wording that presents something as current, pressing or getting worse (never true of a resolved result).
_CURRENT = _words(r"still", r"remains? (?:a |an )?(?:concern|risk|issue|problem|open|active|unresolved|late|slow|high|elevated)", r"ongoing",
                  r"continues? to", r"continuing", r"persists?", r"persisting", r"currently", r"(?:is|are) active", r"(?:is|are) open",
                  r"current (?:concern|risk|issue|problem)", r"worsen(?:s|ed|ing)?", r"(?:getting|got|grows?|growing) worse", r"growing",
                  r"needs?", r"deserves?", r"attention", r"urgent(?:ly)?", r"pressing", r"(?:has|have|had) returned", r"(?:is|are) back(?! to normal)",
                  r"came back", r"comes back", r"recurr(?:s|ed|ing|ence|ent)", r"keeps? (?:recurring|returning|coming back|happening|growing|rising)",
                  r"rising", r"increasing", r"escalat(?:es|ed|ing)", r"re-?opened", r"re-?opening",
                  r"(?:is|are|remains?) (?:still )?(?:a |an )?(?:serious |major |key |real |big |growing )?(?:risk|concern|problem|issue)s?")
# A resolved-only statement that turns against its own resolution ("was resolved, yet …") describes something current.
_CONTRAST = _words(r"but", r"yet", r"however", r"although", r"though", r"even so", r"nevertheless", r"still")
# One vocabulary of "it is over", used in both directions: required for resolved-only statements, refused for open results.
_RESOLUTION = _words(r"resolved", r"no longer", r"stopped", r"(?:has|have|had) ended", r"ended", r"went away", r"gone away", r"disappeared",
                     r"(?:is|are|was|were|been|got|now) (?:closed|fixed|gone|over|cleared|settled|solved|finished|done)", r"(?:has|have) cleared",
                     r"cleared up", r"back to normal", r"normali[sz]ed", r"not (?:observed|seen|reported) (?:any more|anymore|again)", r"addressed",
                     r"recovered", r"(?:any|no) longer (?:a |an )?(?:problem|issue|concern|risk)",
                     r"not (?:a |an )?(?:problem|issue|concern|risk) any ?(?:more|longer)", r"back on track", r"eliminated",
                     r"behind (?:us|them|the team)", r"dealt with", r"under control", r"remedied", r"(?:is|are|was|were) corrected")


def _claims_resolved(text: str) -> bool:
    """A non-negated statement that something is over ("to be resolved" and "unresolved" are not claims)."""
    lowered = _norm(text)
    return any(not _negated(lowered, match.start()) and not re.search(r"\bbe\s+$", lowered[: match.start()])
               for match in _RESOLUTION.finditer(lowered))
_HIGH_CONFIDENCE = _words(r"high(?:ly)? confiden(?:t|ce)", r"strong(?:ly)? confiden(?:t|ce)", r"very confident", r"strong evidence",
                          r"(?:is|are|am|feels?|remains?) confident", r"confidently", r"with confidence",
                          r"clear(?:ly)? (?:shows?|established|pattern)", r"well[- ]established", r"strong pattern")
_METRIC_TERMS = _words(r"scores?", r"scoring", r"index(?:es)?", r"indices", r"ratings?", r"rankings?", r"ranked", r"kpis?", r"productivity",
                       r"efficiency", r"percentiles?", r"grades?", r"composite", r"utili[sz]ation", r"ratios?", r"throughput", r"velocity",
                       r"turnaround", r"slas?", r"percentages?", r"averages?", r"medians?",
                       # rankings and superlatives no result computes
                       r"slowest", r"fastest", r"worst", r"best", r"highest", r"lowest", r"biggest", r"largest", r"smallest", r"greatest",
                       r"quickest", r"poorest", r"weakest", r"strongest", r"of all (?:the )?editors", r"on the (?:whole )?team", r"in the team",
                       r"(?:most|least) \w+ of all", r"top performers?", r"bottom")
_RATE = re.compile(r"\b([a-z][a-z-]*)\s+rates?\b")
_RATE_MODIFIERS = frozenset({"the", "a", "an", "its", "their", "his", "her", "same", "similar", "higher", "lower", "high", "low", "overall", "current",
                             "previous", "baseline", "team", "team's", "editor's", "cohort", "peer", "average", "median", "typical", "rising", "falling",
                             "steady", "stable", "increased", "decreased", "this", "that", "whose", "which"})
_EDITOR_ID = re.compile(r"\beditor[-_][a-z0-9][a-z0-9_-]*[a-z0-9]\b")
# An Editor label written loosely ("editor label-7", "label 7"): read as the Editor ID it names.
_EDITOR_LABEL = re.compile(r"\b(?:editor[-_ ])?label[-_ ]?(\d+)\b")
_PROPER = re.compile(r"\b[^\W\d_]{2,}(?:'s)?\b")
_PERSON_AFTER = _words(r"is", r"was", r"has", r"had", r"shows?", r"showed", r"delivered", r"missed", r"works?", r"worked", r"took", r"seems",
                       r"appears", r"tends", r"needs", r"did", r"does", r"handled", r"edited", r"submitted", r"failed")
# Words an executive brief uses that need not appear in its cited results (never names).
_BRIEF_VOCABULARY = frozenset(["result", "results", "card", "cards", "case", "cases", "concern", "concerns", "improvement", "improvements", "pattern", "patterns", "brief", "question", "questions", "open", "new", "updated", "active", "resolved", "reappeared", "review", "reviews", "inspect", "check", "compare", "look", "consider", "start", "ask", "discuss", "deliveries", "delivery", "late", "lateness", "editors", "team", "teams", "both", "together", "across", "several"])
# Multipliers and ordinals are numbers too ("doubled", "half", "the second slowest").
_MULTIPLIERS = _words(r"doubl(?:e|ed|es|ing)", r"tripl(?:e|ed|es|ing)", r"quadrupl(?:e|ed|es|ing)", r"halv(?:e|ed|es|ing)", r"twice", r"thrice",
                      r"half", r"quarters?", r"thirds", r"\w+fold")
_RESULT_NOUNS = frozenset({"result", "results", "card", "cards", "case", "cases", "pattern", "patterns", "concern", "concerns", "issue", "issues",
                           "improvement", "improvements", "question", "questions"})
_EDITOR_NOUNS = frozenset({"editor", "editors"})
# Forecasts: no result projects anything forward.
_PROJECTION = _words(r"will (?:likely |probably |almost certainly |soon )?(?:continue|keep|rise|fall|grow|increase|decrease|worsen|improve|"
                     r"get worse|get better|reach|exceed|drop|recover|persist|repeat)", r"next (?:week|month|quarter|year|run|cycle)",
                     r"going forward", r"in the coming (?:weeks|months)", r"is (?:likely|expected|projected|forecast) to", r"forecasts?", r"projected")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Sections whose statements may cite resolved and open results together (they describe what results share, not their state).
_MIXED_SECTIONS = frozenset({"system_patterns", "uncertainty"})
_CHANGED_REASONS = frozenset({"reappeared", "reappeared_after_resolution"})


# --- per-result grounding ------------------------------------------------------------------------------------------------------------


def _result_texts(row: Mapping[str, Any]) -> list[str]:
    texts = [str(row.get(name) or "") for name in ("title", "summary", "observation", "interpretation", "management_significance")]
    confidence = row.get("confidence") or {}
    texts.append(str(confidence.get("rationale") or ""))
    texts += [str(text) for text in row.get("limitations") or []]
    texts += [str(q.get("text") or "") for q in row.get("open_questions") or []]
    texts += [str(text) for text in row.get("suggested_investigations") or []]
    return texts


def _editors(row: Mapping[str, Any]) -> set[str]:
    subject = row.get("subject") or {}
    editors = {str(editor) for editor in subject.get("affected_editor_ids") or []}
    if subject.get("subject_type") == "editor":
        editors.add(str(subject.get("subject_id")))
    return editors


@dataclass(frozen=True)
class _Grounding:
    """What a statement may draw on: the input rows of the results it cites."""

    rows: tuple[Mapping[str, Any], ...]

    @property
    def text(self) -> str:
        return _norm(" \n ".join(text for row in self.rows for text in _result_texts(row)))

    def numbers(self) -> dict[str, set[float]]:
        """The numbers the cited results write, by written form (plain, percent, date, minute / hour / day / week / month / year, and
        ``by`` for a written difference)."""
        forms: dict[str, set[float]] = {}
        for row in self.rows:
            for text in _result_texts(row):
                for token, value, _, form, _ in _forms(text):
                    forms.setdefault(form, set()).add(value)
        return forms

    def words(self) -> set[str]:
        found = {token for row in self.rows for text in _result_texts(row) for token in _tokens(text)}
        for row in self.rows:
            subject = row.get("subject") or {}
            values = [subject.get("subject_id"), subject.get("topic_key"), subject.get("case_type"), *(subject.get("dimensions") or {}).values()]
            found |= {token for value in values if value for token in _tokens(str(value))}
        return found

    def editor_subjects(self) -> int:
        return len({row["subject"]["subject_id"] for row in self.rows if row["subject"]["subject_type"] == "editor"})

    def editors(self) -> set[str]:
        return set().union(*(_editors(row) for row in self.rows)) if self.rows else set()

    def statuses(self) -> set[str]:
        return {str(row["lifecycle_status"]) for row in self.rows}


# --- rules ------------------------------------------------------------------------------------------------------------------------------


def _raw_reasoning_fields(value: Any, path: str = "") -> Iterator[ExecutiveViolation]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            here = f"{path}/{key}" if path else str(key)
            if _REASONING_KEY.search(str(key)) and str(key) not in ("prompt_version", "validator_version"):
                yield ExecutiveViolation(ExecutiveCode.RAW_REASONING_FIELD, here, "hidden reasoning has no place in an executive brief")
            yield from _raw_reasoning_fields(item, here)
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            yield from _raw_reasoning_fields(item, f"{path}/{i}")


def _control_characters(value: Any, path: str = "") -> Iterator[ExecutiveViolation]:
    if isinstance(value, str):
        if _CONTROL.search(value):
            yield ExecutiveViolation(ExecutiveCode.INVALID_TEXT, path or "<brief>", "control characters are not text")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _control_characters(str(key), f"{path}/{key}" if path else str(key))
            yield from _control_characters(item, f"{path}/{key}" if path else str(key))
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            yield from _control_characters(item, f"{path}/{i}")


def _classify(ref: Any, known: frozenset[str], references: ReferenceIndex) -> ExecutiveCode | None:
    if not isinstance(ref, str):
        return ExecutiveCode.INVALID_REFERENCE
    if ref in known:
        return None
    if _RESULT_ID.match(ref):
        if ref in references.canonical:
            return ExecutiveCode.RESULT_NOT_IN_INPUT
        if ref in references.failed_candidates:
            return ExecutiveCode.FAILED_CANDIDATE_REFERENCE
        return ExecutiveCode.UNKNOWN_RESULT
    if _FAILED_CANDIDATE_ID.match(ref):
        return ExecutiveCode.FAILED_CANDIDATE_REFERENCE
    if _RAW_SOURCE_ID.match(ref):
        return ExecutiveCode.RAW_SOURCE_REFERENCE
    return ExecutiveCode.INVALID_REFERENCE


def _reference_rules(path: str, row: Any, known: frozenset[str], references: ReferenceIndex) -> list[ExecutiveViolation]:
    found: list[ExecutiveViolation] = []
    refs = _references(row)
    if not refs:
        return [ExecutiveViolation(ExecutiveCode.MISSING_RESULT_REFERENCE, f"{path}/result_ids", "a statement must cite at least one canonical result")]
    seen: set[str] = set()
    for i, ref in enumerate(refs):
        if isinstance(ref, str) and ref in seen:
            found.append(ExecutiveViolation(ExecutiveCode.DUPLICATE_REFERENCE, f"{path}/result_ids/{i}", f"{ref!r} is cited twice"))
            continue
        if isinstance(ref, str):
            seen.add(ref)
        code = _classify(ref, known, references)
        if code is not None:
            found.append(ExecutiveViolation(code, f"{path}/result_ids/{i}", f"{ref!r} is not a canonical result of the synthesis input"))
    return found


def _tokens(text: str) -> set[str]:
    return {token for token in re.split(r"[^0-9a-z\u0600-\u06ff']+", _norm(text).replace("_", " ")) if token} | \
        {token.removesuffix("'s") for token in re.split(r"[^0-9a-z\u0600-\u06ff']+", _norm(text).replace("_", " ")) if token}


_LONG_UNIT_AFTER = re.compile(r"\s*(?:-\s*)?(weeks?|wks?|months?|years?|yrs?)\b")
_DIFFERENCE_BEFORE = re.compile(r"\bby\s*$")


def _forms(text: str) -> list[tuple[str, float, int, str, bool]]:
    """``output_checks.written_numbers`` plus the forms it does not know: longer duration units and written differences ("by 5")."""
    text = unicodedata.normalize("NFKC", text).translate(_HYPHENS)    # "editor‑label‑12" (U+2011) is an identifier, not "12"
    found = []
    cursor = 0
    for token, value, decimals, form, approximate in written_numbers(text):
        start = text.find(token, cursor)
        if start < 0:
            start = text.find(token)
        end = start + len(token)
        cursor = max(cursor, end)
        unit = _LONG_UNIT_AFTER.match(text, end) if form == "plain" else None
        if unit is not None:
            form = unit.group(1)[0]   # w / m / y
            form = {"w": "week", "m": "month", "y": "year"}[form]
        elif _DIFFERENCE_BEFORE.search(text[max(0, start - 8): start]):
            form = f"by-{form}"
        found.append((token, value, decimals, form, approximate))
    return found


def _numbers(path: str, text: str, grounding: _Grounding) -> list[ExecutiveViolation]:
    """Every number is one the cited results write, **in the same form** (a count stays a count, a percentage a percentage, a date part a
    date, a duration a duration with its unit). Derived: only the number of cited results ("two results") and of cited Editors."""
    forms = grounding.numbers()
    found = []
    for token, value, decimals, form, approximate in _forms(text):
        allowed = set(forms.get(form, set())) | ({0.0, 1.0} if form == "plain" else set())
        if decimals or approximate:
            ok = supported(value, decimals, frozenset(allowed))
        else:
            ok = value in allowed
        if not ok and form == "plain" and not decimals:
            following = re.search(r"\b" + re.escape(_norm(token)) + r"\s+([a-z']+)(?:\s+([a-z']+))?", _norm(text))
            nouns = {word for word in (following.groups() if following else ()) if word}       # "two results", "two open results"
            ok = (bool(nouns & _RESULT_NOUNS) and value == len(grounding.rows)) or \
                (bool(nouns & _EDITOR_NOUNS) and value == grounding.editor_subjects() > 0)
        if not ok:
            found.append(ExecutiveViolation(ExecutiveCode.UNSUPPORTED_NUMBER, path, f"{token!r} ({form}) is not written by any cited result"))
    source = grounding.text
    for match in _MULTIPLIERS.finditer(_norm(text)):
        if not re.search(r"\b" + re.escape(match.group(0)) + r"\b", source):
            found.append(ExecutiveViolation(ExecutiveCode.UNSUPPORTED_NUMBER, path, f"{match.group(0)!r} is not written by any cited result"))
    return found


def _metrics(path: str, text: str, grounding: _Grounding) -> list[ExecutiveViolation]:
    lowered, source = _norm(text), grounding.text
    found = []
    for match in _METRIC_TERMS.finditer(lowered):
        if not re.search(r"\b" + re.escape(match.group(0)) + r"\b", source):
            found.append(ExecutiveViolation(ExecutiveCode.UNSUPPORTED_METRIC, path, f"{match.group(0)!r} is not a measure the cited results use"))
    for match in _RATE.finditer(lowered):
        word = match.group(1)
        if word in _RATE_MODIFIERS or f"{word} rate" in source:
            continue
        found.append(ExecutiveViolation(ExecutiveCode.UNSUPPORTED_METRIC, path, f"'{word} rate' is not a rate the cited results use"))
    return found


def _entities(path: str, text: str, grounding: _Grounding) -> list[ExecutiveViolation]:
    """Editor IDs (also written loosely, or with Unicode hyphens) the cited results concern; no other name the cited results do not use."""
    known = {_norm(editor) for editor in grounding.editors()}
    source = grounding.text

    def written(editor: str) -> bool:
        return editor in known or re.search(r"(?<![\w-])" + re.escape(editor) + r"(?![\w-])", source) is not None

    lowered = _norm(text)
    found = [ExecutiveViolation(ExecutiveCode.UNKNOWN_ENTITY, path, f"{match.group(0)!r} is not an Editor the cited results concern")
             for match in _EDITOR_ID.finditer(lowered) if not written(match.group(0))]
    for match in _EDITOR_LABEL.finditer(lowered):
        editor = f"editor-label-{match.group(1)}"
        if not written(editor):
            found.append(ExecutiveViolation(ExecutiveCode.UNKNOWN_ENTITY, path, f"{match.group(0)!r} is not an Editor the cited results concern"))
    words = grounding.words() | _BRIEF_VOCABULARY | guardrails.ATLAS_VOCABULARY | guardrails.STOPWORDS | NUMBER_WORDS
    for sentence in guardrails.sentences(unicodedata.normalize("NFKC", text)):
        for match in _PROPER.finditer(sentence):
            word = match.group(0)
            if not word[0].isupper() or _norm(word.removesuffix("'s")) in words:
                continue
            initial = not sentence[: match.start()].strip(" \"'(-")
            person_like = word.endswith("'s") or bool(_PERSON_AFTER.match(_norm(sentence[match.end():].strip())))
            if initial and not person_like:
                continue
            found.append(ExecutiveViolation(ExecutiveCode.UNKNOWN_ENTITY, path, f"{word.removesuffix(chr(39) + 's')!r} is not named by the cited results"))
    return found


def _lifecycle(path: str, section: str, text: str, grounding: _Grounding) -> list[ExecutiveViolation]:
    found: list[ExecutiveViolation] = []
    statuses = grounding.statuses()
    resolved = LifecycleStatus.RESOLVED.value
    if section == "top_concerns" and resolved in statuses:
        found.append(ExecutiveViolation(ExecutiveCode.LIFECYCLE_CONTRADICTION, path, "a resolved result is never a current top concern"))
    if section == "what_changed" and not any(row["lifecycle_status"] in ("new", "updated", "resolved") or (row.get("change") or {}).get("lifecycle_reason")
                                             in _CHANGED_REASONS for row in grounding.rows):
        found.append(ExecutiveViolation(ExecutiveCode.LIFECYCLE_CONTRADICTION, path, "no cited result is new, updated, resolved or reappeared"))
    if statuses == {resolved}:
        if _found(_CURRENT, text) or _found(_CONTRAST, text):
            found.append(ExecutiveViolation(ExecutiveCode.LIFECYCLE_CONTRADICTION, path, "resolved results are described as current"))
        elif not _claims_resolved(text):
            found.append(ExecutiveViolation(ExecutiveCode.LIFECYCLE_CONTRADICTION, path, "resolved results must be described as resolved"))
    elif resolved not in statuses:
        if _claims_resolved(text):
            found.append(ExecutiveViolation(ExecutiveCode.LIFECYCLE_CONTRADICTION, path, "an open result is described as resolved"))
    elif section not in _MIXED_SECTIONS:
        # Resolved and open results in one statement: whatever it says about their state is true of only some of them.
        found.append(ExecutiveViolation(ExecutiveCode.LIFECYCLE_CONTRADICTION, path, "cite resolved and open results in separate statements"))
    elif _found(_CURRENT, text) or _claims_resolved(text):
        found.append(ExecutiveViolation(ExecutiveCode.LIFECYCLE_CONTRADICTION, path, "a statement about resolved and open results describes their state"))
    return found


def _section(path: str, section: str, grounding: _Grounding) -> list[ExecutiveViolation]:
    """Improvements cite favourable or resolved results; top concerns never cite a favourable one."""
    found = []
    if section == "important_improvements":
        strays = [str(row["result_id"]) for row in grounding.rows
                  if row["lifecycle_status"] != LifecycleStatus.RESOLVED.value and (row.get("subject") or {}).get("orientation") != "favourable"]
        if strays:
            found.append(ExecutiveViolation(ExecutiveCode.SECTION_MISMATCH, path, f"neither favourable nor resolved: {strays}"))
    if section == "top_concerns":
        strays = [str(row["result_id"]) for row in grounding.rows if (row.get("subject") or {}).get("orientation") == "favourable"]
        if strays:
            found.append(ExecutiveViolation(ExecutiveCode.SECTION_MISMATCH, path, f"a favourable result is not a concern: {strays}"))
    return found


def _questions(path: str, text: str, grounding: _Grounding) -> list[ExecutiveViolation]:
    found = []
    if not text.strip().endswith("?"):
        found.append(ExecutiveViolation(ExecutiveCode.QUESTION_AS_FACT, path, "a management question must stay a question"))
    asked = {" ".join(_norm(str(q.get("text") or "")).split()) for row in grounding.rows for q in row.get("open_questions") or []}
    if " ".join(_norm(text).split()) not in asked:
        found.append(ExecutiveViolation(ExecutiveCode.UNSUPPORTED_QUESTION, path, "not one of the cited results' open Atlas questions"))
    return found


def _editor(path: str, row: Mapping[str, Any], grounding: _Grounding) -> list[ExecutiveViolation]:
    editor = str(row.get("editor_id") or "")
    strays = [str(result["result_id"]) for result in grounding.rows if editor not in _editors(result)]
    if strays:
        return [ExecutiveViolation(ExecutiveCode.EDITOR_MISMATCH, f"{path}/editor_id", f"cited results not about {editor!r}: {strays}")]
    return []


def _safety(path: str, text: str, grounding: _Grounding) -> list[ExecutiveViolation]:
    found = [ExecutiveViolation(ExecutiveCode(violation.code.value), violation.path, violation.detail)
             for violation in guardrails.statement_safety_violations(path, text, names=grounding.editors())]
    if _found(_PROJECTION, text) and not re.search(_PROJECTION.pattern, grounding.text):
        found.append(ExecutiveViolation(ExecutiveCode.PROJECTION, path, "a forecast no cited result makes"))
    levels = {str((row.get("confidence") or {}).get("level")) for row in grounding.rows}
    if levels and ConfidenceLevel.STRONG.value not in levels and _found(_HIGH_CONFIDENCE, text):
        found.append(ExecutiveViolation(ExecutiveCode.CONFIDENCE_EXCEEDED, path, "claims high confidence; no cited result is strong"))
    return found


def _identity(candidate: Mapping[str, Any], inp: ExecutiveInput, expected: ExpectedBrief) -> list[ExecutiveViolation]:
    found: list[ExecutiveViolation] = []

    def check(path: str, actual: Any, wanted: Any, code: ExecutiveCode = ExecutiveCode.IDENTITY_MISMATCH) -> None:
        if actual != wanted:
            found.append(ExecutiveViolation(code, path, f"{actual!r} is not the expected {wanted!r}"))

    check("brief_id", candidate.get("brief_id"), expected.brief_id)
    check("version", candidate.get("version"), expected.version)
    check("run_id", candidate.get("run_id"), expected.run_id)
    check("input_fingerprint", candidate.get("input_fingerprint"), inp.fingerprint)
    check("input_results", candidate.get("input_results"), inp.input_results())
    check("omitted_result_count", candidate.get("omitted_result_count"), inp.omitted)
    check("prompt_version", candidate.get("prompt_version"), expected.prompt_version, ExecutiveCode.PROVENANCE_MISMATCH)
    generator: Mapping[str, Any] = candidate["generator"] if isinstance(candidate.get("generator"), Mapping) else {}
    check("generator/kind", generator.get("kind"), "model", ExecutiveCode.PROVENANCE_MISMATCH)
    model = str(generator.get("model") or "")
    if not model_identity_matches(expected.model, model):
        found.append(ExecutiveViolation(ExecutiveCode.MODEL_SUBSTITUTED, "generator/model", f"answered by {model!r}, configured {expected.model!r}"))
    if expected.request_id is not None and expected.request_id not in (generator.get("request_ids") or []):
        found.append(ExecutiveViolation(ExecutiveCode.PROVENANCE_MISMATCH, "generator/request_ids", "the call's request ID is not recorded"))
    return found


# --- entry point ------------------------------------------------------------------------------------------------------------------------


def validate_brief(candidate: Mapping[str, Any], inp: ExecutiveInput, expected: ExpectedBrief, references: ReferenceIndex | None = None) -> ExecutiveReport:
    """Every executive rule on one complete candidate. ``references`` classifies references outside the input (from the store)."""
    references = references or ReferenceIndex()
    if not isinstance(candidate, Mapping):
        return ExecutiveReport((ExecutiveViolation(ExecutiveCode.CONTRACT_INVALID, "<brief>", "not an object"),))
    violations: list[ExecutiveViolation] = list(_raw_reasoning_fields(candidate))
    violations += _control_characters(candidate)
    known = inp.result_ids
    by_id = inp.by_id()
    seen_texts: dict[str, str] = {}
    for path, section, _, row in _statement_rows(candidate):
        violations += _reference_rules(path, row, known, references)
        if not isinstance(row, Mapping) or not isinstance(row.get("text"), str):
            continue
        text = row["text"]
        key = " ".join(_norm(text).split())
        if key in seen_texts:
            violations.append(ExecutiveViolation(ExecutiveCode.DUPLICATE_STATEMENT, f"{path}/text", f"repeats {seen_texts[key]}"))
        seen_texts.setdefault(key, path)
        if _found(_HIDDEN_TEXT, text) or _HIDDEN_MARKUP.search(_norm(text)):
            violations.append(ExecutiveViolation(ExecutiveCode.HIDDEN_REASONING_TEXT, f"{path}/text", "a statement exposes reasoning steps"))
        cited = tuple(by_id[ref] for ref in dict.fromkeys(ref for ref in _references(row) if isinstance(ref, str) and ref in known))
        if not cited:
            continue
        grounding = _Grounding(cited)
        text_path = f"{path}/text"
        violations += _numbers(text_path, text, grounding)
        violations += _metrics(text_path, text, grounding)
        violations += _entities(text_path, text, grounding)
        violations += _lifecycle(text_path, section, text, grounding)
        violations += _section(text_path, section, grounding)
        violations += _safety(text_path, text, grounding)
        if section == "unresolved_questions":
            violations += _questions(text_path, text, grounding)
        if section == EDITOR_SECTION:
            violations += _editor(path, row, grounding)
    contract = brief_errors(candidate)
    # A reference the rules above already named precisely is not reported again as a contract error.
    named = {violation.path.split("/result_ids")[0] for violation in violations if "/result_ids" in violation.path}
    violations += [ExecutiveViolation(ExecutiveCode.CONTRACT_INVALID, "<brief>", error) for error in contract
                   if not ("/result_ids" in error and error.split(": ", 2)[1].split("/result_ids")[0] in named)]
    if not contract:
        violations += _identity(candidate, inp, expected)
    return ExecutiveReport(tuple(dict.fromkeys(violations)))


def correction_message(report: ExecutiveReport) -> str:
    """What the model is told after a refused answer: codes and paths only (never free text echoed back)."""
    lines = [f"- {violation.code.value} at {violation.path}" for violation in report.violations[:40]]
    return ("Atlas validation refused your previous answer. Problems (code at path):\n" + "\n".join(lines) +
            "\nReturn a complete corrected answer in the same JSON format that follows every rule of the system prompt. Cite only result_ids from "
            "the input; use only numbers, measures and names the cited results write, in the same form; keep every result's lifecycle (resolved "
            "is never current, open is never over) and cite resolved and open results in separate statements; improvements cite favourable or "
            "resolved results, concerns never favourable ones; copy open questions word for word; rank nothing; state causes only as "
            "possibilities; make no judgement about people and do not claim more confidence than the results.")
