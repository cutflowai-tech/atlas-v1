"""Reasoning validation and safety guardrails (``REV/15``): the final deterministic gate before an LLM answer becomes canonical.

    report = validate_candidate(candidate, case, expected)
    if not report.ok: ...   # never committed; the previous valid result stays current

``candidate`` is the complete ``ReasoningResult`` document Python built from the model's answer — for a new result the assembled
version 1, for an update the **merged** next version (``updater.merge``), never just the raw patch. ``case`` is the exact case the
model saw (evidence plus its attributed human context). ``expected`` is what Python, not the model, decided: identity, version,
snapshot, fingerprint, model, prompt version and, for an update, the previous version.

Every rule below is deterministic (no LLM judges another LLM here). A candidate may fail several rules at once; each failure is a
``Violation(code, path, detail)`` with a stable ``ValidationCode``. JSON-Schema conformity is necessary but never sufficient: the
contract checks run first, then grounding and safety policy.

Policy (the exact boundary is documented in ``docs/REASONING-V3-GUARDRAILS.md``):

1. **Identity and provenance** — case, result, version, snapshot, fingerprint, previous version, prompt version, request ID and the
   answering model (``settings.model_identity_matches``) match what Python expected (``IDENTITY_MISMATCH``, ``PROVENANCE_MISMATCH``,
   ``MODEL_SUBSTITUTED``).
2. **Evidence references** — every cited ``ref_id`` is one of the case's references (``UNKNOWN_EVIDENCE``); supporting claims never
   cite contradicting evidence, and a contradicted case's counter-evidence cites its contradicting evidence (``WRONG_EVIDENCE_ROLE``,
   ``COUNTER_EVIDENCE_MISSING``); every visible conclusion cites at least one supporting deterministic reference
   (``NO_SUPPORTING_EVIDENCE``).
3. **Numbers** — ``output_checks``: every number (digits or words) is a case value, a rate as a percentage, or a duration in other
   units (``UNSUPPORTED_NUMBER``). Human context is never a source of numbers.
4. **Entities** — Editor identifiers, project / Monday item numbers and proper names must belong to the case (or, inside an
   attributed sentence, to its management context) (``UNKNOWN_PERSON``, ``UNKNOWN_PROJECT``, ``UNKNOWN_ENTITY``).
5. **Metrics** — no invented Atlas metric (scores, indices, ratings, rankings, productivity, efficiency, composite or risk
   percentages, unknown "<x> rate"s) (``UNSUPPORTED_METRIC``).
6. **Causality** — upstream evidence levels never establish causation, so causal language is allowed only hedged (may / might /
   could …) in interpretive fields or negated; never as an observation, evidence statement or title (``CAUSAL_OVERCLAIM``).
7. **People** — no personality, psychological, motivation, character, competence-as-trait, pay or employment-action judgement
   (``HR_JUDGMENT``) and no personal blame (``UNSUPPORTED_BLAME``); observable work patterns are allowed.
8. **Confidence** — never above the upstream ceiling, never ``strong`` for a contradicted case, and no text that claims more
   certainty than the level (``CONFIDENCE_EXCEEDED``).
9. **Human context stays attributed** — a sentence that draws on management context (notes, answers, teachings, memory) must say
   so; it may never be an observation, evidence statement or title (``MEMORY_ATTRIBUTION_LOST``, ``CONTEXT_AS_EVIDENCE``).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from atlas_reasoning import contracts
from atlas_reasoning.enums import CONFIDENCE_ORDER, ConfidenceLevel, EvidenceRole
from atlas_reasoning.output_checks import unsupported_number_errors
from atlas_reasoning.settings import model_identity_matches

VALIDATOR_VERSION = "reasoning-guardrails-v1"


class ValidationCode(StrEnum):
    """Stable, machine-readable reasons a candidate is refused. Never renamed; new codes are only added."""

    CONTRACT_INVALID = "CONTRACT_INVALID"                    # not a valid reasoning-v1 document (or update)
    PATCH_INVALID = "PATCH_INVALID"                          # an update that is not a valid patch of the previous version
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"                  # case / result / version / snapshot / fingerprint / previous version
    PROVENANCE_MISMATCH = "PROVENANCE_MISMATCH"              # prompt version, request ID, provider metadata
    MODEL_SUBSTITUTED = "MODEL_SUBSTITUTED"                  # answered by another model than the pinned one
    UNKNOWN_EVIDENCE = "UNKNOWN_EVIDENCE"                    # a ref_id that is not evidence of this case
    WRONG_EVIDENCE_ROLE = "WRONG_EVIDENCE_ROLE"              # contradicting evidence presented as support (or vice versa)
    COUNTER_EVIDENCE_MISSING = "COUNTER_EVIDENCE_MISSING"    # a contradicted case without its counter-evidence
    NO_SUPPORTING_EVIDENCE = "NO_SUPPORTING_EVIDENCE"        # a visible conclusion without supporting deterministic evidence
    UNSUPPORTED_NUMBER = "UNSUPPORTED_NUMBER"                # a number that is not a value of the case
    UNKNOWN_PERSON = "UNKNOWN_PERSON"                        # a person / Editor the case does not contain
    UNKNOWN_PROJECT = "UNKNOWN_PROJECT"                      # a project / Monday item the case does not contain
    UNKNOWN_ENTITY = "UNKNOWN_ENTITY"                        # another proper name the case does not contain
    UNSUPPORTED_METRIC = "UNSUPPORTED_METRIC"                # a metric Atlas does not calculate
    CAUSAL_OVERCLAIM = "CAUSAL_OVERCLAIM"                    # causation where the evidence shows association at most
    HR_JUDGMENT = "HR_JUDGMENT"                              # personality, psychology, motivation, pay, employment action ...
    UNSUPPORTED_BLAME = "UNSUPPORTED_BLAME"                  # a person blamed for an outcome
    CONFIDENCE_EXCEEDED = "CONFIDENCE_EXCEEDED"              # level above the ceiling, or text claiming more certainty
    MEMORY_ATTRIBUTION_LOST = "MEMORY_ATTRIBUTION_LOST"      # management context used without saying so
    CONTEXT_AS_EVIDENCE = "CONTEXT_AS_EVIDENCE"              # management context presented as observation / evidence
    REVIEWER_REJECTED = "REVIEWER_REJECTED"                  # the optional second reviewer refused a deterministically valid candidate
    REVIEWER_FAILED = "REVIEWER_FAILED"                      # the optional reviewer could not give a verdict (fails safe)


# A failure the model can plausibly correct when told the codes; identity, provenance and model failures are Python's or the
# provider's, and a reviewer verdict is final for this attempt.
NOT_RETRYABLE = frozenset({ValidationCode.IDENTITY_MISMATCH, ValidationCode.PROVENANCE_MISMATCH, ValidationCode.MODEL_SUBSTITUTED,
                           ValidationCode.REVIEWER_REJECTED, ValidationCode.REVIEWER_FAILED})


@dataclass(frozen=True)
class Violation:
    code: ValidationCode
    path: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "path": self.path, "detail": self.detail}


@dataclass(frozen=True)
class ValidationReport:
    violations: tuple[Violation, ...]
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
class Expected:
    """What Python decided for the candidate (never the model)."""

    case_id: str
    result_id: str
    version: int
    source_snapshot_id: str
    evidence_fingerprint: str
    prompt_version: str
    model: str                                      # the configured (pinned) model
    request_id: str | None = None
    previous: Mapping[str, Any] | None = None       # the previous version (update path)


class GuardrailError(ValueError):
    """A candidate failed Phase 15 validation. ``report`` holds every violation."""

    def __init__(self, report: ValidationReport) -> None:
        super().__init__(f"candidate refused: {', '.join(report.codes)}")
        self.report = report


# --- text helpers -------------------------------------------------------------------------------------------------------------

_SENTENCE = re.compile(r"(?<=[.!?;])\s+|\n+")


def sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE.split(text) if part.strip()]


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).replace("’", "'").casefold()


def _has(pattern: re.Pattern[str], text: str) -> bool:
    return pattern.search(_norm(text)) is not None


def _words(*phrases: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(phrases) + r")\b")


_NEGATORS = frozenset({"not", "no", "never", "cannot", "can't", "without", "neither", "nor", "unknown", "unclear", "isn't", "doesn't",
                       "don't", "didn't", "wasn't", "aren't", "weren't", "none", "nothing", "n't"})
_HEDGES = re.compile(r"\b(?:may|might|could|possibly|perhaps|potentially|whether|if|one possible|a possible|hypothes[ie]s|to check|"
                     r"worth checking|it is possible|can)\b")
_CLAUSE_BREAK = re.compile(r"[,;:()\u2014]|\s-\s|\bbut\b|\bwhile\b|\bwhereas\b|\bwhich\b")
# Attribution names its source: management (or a manager, a management teaching). Generic verbs ("said", "noted") alone are not enough.
_ATTRIBUTION = _words(r"management", r"manager", r"managers", r"management's", r"manager's", r"according to management",
                      r"management teaching", r"teaching", r"taught")


def _clause_before(lowered: str, start: int) -> str:
    """The text of the clause that leads up to ``start`` (from the last clause break)."""
    head = lowered[:start]
    breaks = [match.end() for match in _CLAUSE_BREAK.finditer(head)]
    return head[breaks[-1]:] if breaks else head


def _negated_before(lowered: str, start: int) -> bool:
    """A negation governs the phrase at ``start``: a negator among the four words before it, in the same clause ("does not show what
    caused", "is not effort"). A negation elsewhere in the sentence ("Ahmed caused the delays, not the brief") does not count."""
    words = re.findall(r"[a-z']+", _clause_before(lowered, start))[-4:]
    return any(word in _NEGATORS or word.endswith("n't") for word in words)


def _hedged_before(lowered: str, start: int) -> bool:
    """A possibility marker before the phrase, in the same clause ("may have caused", "could be due to")."""
    return _HEDGES.search(_clause_before(lowered, start)) is not None


def _visible(candidate: Mapping[str, Any]) -> Iterator[tuple[str, str, str]]:
    """(path, field, text) of every user-visible text of a result."""
    for name in ("title", "reasoning_summary"):
        yield name, name, str(candidate.get(name) or "")
    for name in ("observation", "interpretation", "management_significance"):
        claim = candidate.get(name)
        if isinstance(claim, Mapping):
            yield f"{name}/statement", name, str(claim.get("statement", ""))
    for name in ("supporting_evidence", "counter_evidence"):
        for i, claim in enumerate(candidate.get(name) or []):
            yield f"{name}/{i}/statement", name, str(claim.get("statement", ""))
    for i, row in enumerate(candidate.get("alternative_explanations") or []):
        yield f"alternative_explanations/{i}/explanation", "alternative_explanations", str(row.get("explanation", ""))
    confidence = candidate.get("confidence")
    if isinstance(confidence, Mapping):
        yield "confidence/rationale", "confidence", str(confidence.get("rationale", ""))
    for i, text in enumerate(candidate.get("limitations") or []):
        yield f"limitations/{i}", "limitations", str(text)
    for i, row in enumerate(candidate.get("questions_for_management") or []):
        yield f"questions_for_management/{i}/text", "questions_for_management", str(row.get("text", ""))
        yield f"questions_for_management/{i}/reason", "questions_for_management", str(row.get("reason", ""))
    for i, row in enumerate(candidate.get("suggested_investigations") or []):
        yield f"suggested_investigations/{i}/text", "suggested_investigations", str(row.get("text", ""))


# Fields that state deterministic facts: they may never carry causal claims (even hedged) or management context.
FACTUAL_FIELDS = frozenset({"title", "observation", "supporting_evidence", "counter_evidence"})
# Fields about the quality of Atlas's own evidence ("weak because the sample is small"): exempt from the causality rule.
EPISTEMIC_FIELDS = frozenset({"limitations", "confidence"})


# --- case vocabulary ----------------------------------------------------------------------------------------------------------


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _management_statement(body: str) -> str:
    """What management itself said: an answer's context body quotes Atlas's question first ("Question: ..."); that line is Atlas's."""
    return "\n".join(line for line in body.splitlines() if not line.startswith("Question:"))


def _named_values(value: Any, key: str = "") -> Iterator[str]:
    if isinstance(value, Mapping):
        for name, item in value.items():
            yield from _named_values(item, str(name))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _named_values(item, key)
    elif isinstance(value, str) and key.endswith("name") and key not in ("finding_type",):
        yield value


def _tokens(text: str) -> set[str]:
    return {token for token in re.split(r"[^0-9a-z؀-ۿ]+", _norm(text).replace("_", " ")) if token}


@dataclass(frozen=True)
class CaseVocabulary:
    """What a candidate may name: the case's own words and identifiers, and (separately) its management context's."""

    words: frozenset[str]                  # every token of every case string (keys and values), snake_case split
    phrases: str                           # every case string, normalized and joined (for multi-word lookups)
    names: frozenset[str]                  # people named by the case (values of ``*_name`` keys, e.g. ``editor_name``), normalized
    editor_ids: frozenset[str]
    item_ids: frozenset[str]
    context_words: frozenset[str]          # tokens of manager_context / memory_context bodies
    context_items: tuple[tuple[str, frozenset[str]], ...]   # (source, distinctive tokens) per context item

    @classmethod
    def of(cls, case: Mapping[str, Any]) -> CaseVocabulary:
        evidence = {key: value for key, value in case.items() if key not in ("manager_context", "memory_context")}
        strings = list(_strings(evidence))
        words = set().union(*(_tokens(text) for text in strings)) if strings else set()
        references = case["current_evidence"]["references"]
        editors = {case["subject_id"]} if case["subject_type"] == "editor" else set()
        editors |= set(case["scope"]["affected_editor_ids"]) | {ref["editor_id"] for ref in references if ref.get("editor_id")}
        items = {str(ref["monday_item_id"]) for ref in references if ref.get("monday_item_id")}
        # Management sources only: Atlas's own remembered reasoning and questions are not management statements to attribute.
        bodies = [(f"manager_context:{row.get('source_type')}:{row.get('source_id', '')}", str(row.get("body", ""))) for row in case.get("manager_context") or []
                  if row.get("source_type") in MANAGEMENT_SOURCES]
        memory = case.get("memory_context") or {}
        bodies += [(f"memory_context:{row.get('source_type')}:{row.get('memory_ref', '')}", str(row.get("body", ""))) for row in memory.get("items") or []
                   if row.get("source_type") in MANAGEMENT_SOURCES]
        context_words = set().union(*(_tokens(body) for _, body in bodies)) if bodies else set()
        names = {token for value in _named_values(evidence) for token in _tokens(value) if token.isalpha() and len(token) > 1}
        generic = words | ATLAS_VOCABULARY | STOPWORDS
        distinct = tuple((source, frozenset(token for token in _tokens(_management_statement(body)) if len(token) >= 4 and token not in generic
                                            and not token.isdigit()))
                         for source, body in bodies)
        return cls(frozenset(words), " | ".join(_norm(text).replace("_", " ") for text in strings), frozenset(names), frozenset(editors), frozenset(items),
                   frozenset(context_words), distinct)


def _wordset(text: str) -> frozenset[str]:
    return frozenset(text.split())


# Human context that is management's own statement and must stay attributed as such.
MANAGEMENT_SOURCES = frozenset({"manager_interpretation", "manager_answer", "management_teaching"})


# Words Atlas itself uses for its metrics, workflow and evidence (allowed even when a given case does not contain them).
ATLAS_VOCABULARY = _wordset("""
atlas monday editor editors team teams video type types class cohort cohorts project projects item items delivery deliveries deadline deadlines
late lateness early on time ontime rate rates late-rate share median medians mean average sample samples window windows current previous
baseline comparison trend trends recent change changes status overall benchmark benchmarks speed work time duration durations runway
quality revision revisions label labels workload workflow stage stages post pre ready approval eta etas cycle cycles finding findings
evidence pattern patterns association concentration contradiction contradictions signal signals management manager managers question
questions answer answers teaching teachings context interpretation observation limitation limitations confidence weak moderate strong
week weeks month months day days hour hours minute minutes year years percent percentage peer peers group groups intelligence interpretation
january february march april may june july august september october november december monday tuesday wednesday thursday friday saturday sunday
""")
STOPWORDS = _wordset("""
the a an and or but of to in on at for from by with without within into over under than then this that these those it its is are was were be been
being has have had do does did not no nor so as if may might could would should can will shall each every all any some most more less few several
which who whom whose what when where why how there here they them their he she his her we our you your i me my one also only just very much many
about after before during between against across per while because since until both either neither other another such same own up down out off
""")

_MONTHS_DAYS = _wordset("january february march april may june july august september october november december monday tuesday wednesday "
                         "thursday friday saturday sunday")


# --- rules ----------------------------------------------------------------------------------------------------------------------


def _identity(candidate: Mapping[str, Any], case: Mapping[str, Any], expected: Expected) -> list[Violation]:
    found: list[Violation] = []

    def check(path: str, actual: Any, wanted: Any, code: ValidationCode = ValidationCode.IDENTITY_MISMATCH) -> None:
        if actual != wanted:
            found.append(Violation(code, path, f"{actual!r} is not the expected {wanted!r}"))

    check("case_id", candidate.get("case_id"), expected.case_id)
    check("case_id", case.get("case_id"), expected.case_id)
    check("result_id", candidate.get("result_id"), expected.result_id)
    check("version", candidate.get("version"), expected.version)
    check("source_snapshot_id", candidate.get("source_snapshot_id"), expected.source_snapshot_id)
    check("source_snapshot_id", case.get("source_snapshot_id"), expected.source_snapshot_id)
    check("evidence_fingerprint", candidate.get("evidence_fingerprint"), expected.evidence_fingerprint)
    check("evidence_fingerprint", case.get("evidence_fingerprint"), expected.evidence_fingerprint)
    previous = expected.previous
    if previous is None:
        check("version", candidate.get("version"), 1)
        check("superseded_by", candidate.get("superseded_by"), None)
        check("previous_result_id", case.get("previous_result_id"), None)
    else:
        check("result_id", candidate.get("result_id"), previous["result_id"])
        check("case_id", previous["case_id"], expected.case_id)
        check("version", candidate.get("version"), previous["version"] + 1)
        check("created_at", candidate.get("created_at"), previous["created_at"])
        check("lifecycle_status", candidate.get("lifecycle_status"), previous["lifecycle_status"])
        check("superseded_by", candidate.get("superseded_by"), previous["superseded_by"])
        check("previous_result_id", case.get("previous_result_id"), previous["result_id"])
        check("previous_result_version", case.get("previous_result_version"), previous["version"])
    check("prompt_version", candidate.get("prompt_version"), expected.prompt_version, ValidationCode.PROVENANCE_MISMATCH)
    metadata: Mapping[str, Any] = candidate["model_metadata"] if isinstance(candidate.get("model_metadata"), Mapping) else {}
    model = str(metadata.get("model") or "")
    if not model_identity_matches(expected.model, model):
        found.append(Violation(ValidationCode.MODEL_SUBSTITUTED, "model_metadata/model", f"answered by {model!r}, configured {expected.model!r}"))
    if expected.request_id is not None and expected.request_id not in (metadata.get("request_ids") or []):
        found.append(Violation(ValidationCode.PROVENANCE_MISMATCH, "model_metadata/request_ids", "the call's request ID is not recorded"))
    return found


def _role_sets(case: Mapping[str, Any]) -> tuple[set[str], set[str], set[str]]:
    """(all, supporting, contradicting) ref IDs of the case. A reference counts as contradicting when its role says so or it belongs
    to a contradicting finding; as supporting when its role is supporting and it belongs to no contradicting finding."""
    references = case["current_evidence"]["references"]
    contradicting_members = {row["member_key"] for row in case["contradicting_findings"]}
    counter = {ref["ref_id"] for ref in references if ref["role"] == EvidenceRole.CONTRADICTING or ref["member_key"] in contradicting_members}
    support = {ref["ref_id"] for ref in references if ref["ref_id"] not in counter and ref["role"] == EvidenceRole.SUPPORTING}
    return {ref["ref_id"] for ref in references}, support, counter


def _evidence(candidate: Mapping[str, Any], case: Mapping[str, Any]) -> list[Violation]:
    found: list[Violation] = []
    known, support, counter = _role_sets(case)
    usable_support = known - counter     # supporting or context records: deterministic evidence that does not point the other way

    def claims() -> Iterator[tuple[str, str, Mapping[str, Any]]]:
        for name in ("observation", "interpretation", "management_significance"):
            if isinstance(candidate.get(name), Mapping):
                yield name, name, candidate[name]
        for name in ("supporting_evidence", "counter_evidence"):
            for i, claim in enumerate(candidate.get(name) or []):
                yield f"{name}/{i}", name, claim
        for i, row in enumerate(candidate.get("alternative_explanations") or []):
            yield f"alternative_explanations/{i}", "alternative_explanations", row
        for i, row in enumerate(candidate.get("suggested_investigations") or []):
            yield f"suggested_investigations/{i}", "suggested_investigations", row

    for path, name, claim in claims():
        refs = [ref for ref in claim.get("evidence_refs") or [] if isinstance(ref, str)]
        unknown = sorted(set(refs) - known)
        if unknown:
            found.append(Violation(ValidationCode.UNKNOWN_EVIDENCE, f"{path}/evidence_refs", f"not evidence of this case: {unknown}"))
        valid = set(refs) & known
        if name == "supporting_evidence" and valid & counter:
            found.append(Violation(ValidationCode.WRONG_EVIDENCE_ROLE, f"{path}/evidence_refs",
                                   f"contradicting evidence presented as support: {sorted(valid & counter)}"))
        if name in ("observation", "interpretation", "management_significance", "supporting_evidence") and not valid & usable_support:
            found.append(Violation(ValidationCode.NO_SUPPORTING_EVIDENCE, f"{path}/evidence_refs", "cites no supporting deterministic evidence"))
        if name == "counter_evidence" and counter and valid and not valid & counter and valid <= support:
            found.append(Violation(ValidationCode.WRONG_EVIDENCE_ROLE, f"{path}/evidence_refs",
                                   "supporting evidence presented as counter-evidence"))
        if name == "alternative_explanations" and not claim.get("requires_context") and not valid:
            found.append(Violation(ValidationCode.NO_SUPPORTING_EVIDENCE, f"{path}/evidence_refs",
                                   "an explanation that does not need context must cite evidence"))
    contradicted = bool(case["contradicting_findings"]) or bool(counter)
    cited_counter = {ref for claim in candidate.get("counter_evidence") or [] for ref in claim.get("evidence_refs") or []}
    if contradicted and not candidate.get("counter_evidence"):
        found.append(Violation(ValidationCode.COUNTER_EVIDENCE_MISSING, "counter_evidence", "the case has contradicting evidence the result does not address"))
    elif contradicted and counter and not cited_counter & counter:
        found.append(Violation(ValidationCode.COUNTER_EVIDENCE_MISSING, "counter_evidence", "cites none of the case's contradicting evidence"))
    return found


def _numbers(candidate: Mapping[str, Any], case: Mapping[str, Any], *, include_delta: bool) -> list[Violation]:
    found = []
    for error in unsupported_number_errors(candidate, case, include_delta=include_delta):
        _, _, rest = error.partition(": ")
        path, _, detail = rest.partition(": ")
        found.append(Violation(ValidationCode.UNSUPPORTED_NUMBER, path, detail))
    return found


_EDITOR_ID = re.compile(r"\beditor[-_][a-z0-9][a-z0-9_-]*\b")
_PROJECT_ID = re.compile(r"\b(?:items?|projects?|tasks?|jobs?|videos?|cards?|deliver(?:y|ies))\s*(?:#|no\.?\s*|number\s*)?(\d{2,})\b|#\s?(\d{2,})\b")
_PROPER = re.compile(r"\b[^\W\d_]{2,}(?:'s)?\b")
_ENTITY_NOUN = _words(r"projects?", r"work", r"jobs?", r"videos?", r"deliveries", r"delivery", r"clients?", r"accounts?", r"campaigns?",
                      r"briefs?", r"orders?")
_PERSON_VERB = _words(r"is", r"was", r"has", r"had", r"did", r"missed", r"caused", r"worked", r"took", r"delivered", r"edited", r"failed",
                      r"handled", r"submitted", r"seems", r"appears", r"tends")
# Sentence starters that are never names.
_STARTERS = _wordset("the this that these those it its there atlas most some all each every several many few one no both management overall "
                      "late early work projects deliveries deadlines quality speed workload editor editors team video class however while "
                      "although because since if when where why how what which only based compared relative given during after before across "
                      "among over under in on at for from by with without a an and but or as also then thus still yet")


def _attributed(text: str) -> bool:
    return _has(_ATTRIBUTION, text)


def _known_word(word: str, vocab: CaseVocabulary, attributed: bool) -> bool:
    key = _norm(word.removesuffix("'s"))
    known = key in vocab.words or key in ATLAS_VOCABULARY or key in STOPWORDS or key in _MONTHS_DAYS
    return known or (attributed and key in vocab.context_words)


def _entities(candidate: Mapping[str, Any], vocab: CaseVocabulary) -> list[Violation]:
    found: list[Violation] = []
    for path, name, text in _visible(candidate):
        title_case = name == "title" and sum(word[:1].isupper() for word in text.split()) * 2 > len(text.split())
        for sentence in sentences(text):
            lowered = _norm(sentence)
            attributed = _attributed(sentence)
            for match in _EDITOR_ID.finditer(lowered):
                if match.group(0) not in vocab.editor_ids:
                    found.append(Violation(ValidationCode.UNKNOWN_PERSON, path, f"{match.group(0)!r} is not an Editor of this case"))
            for match in _PROJECT_ID.finditer(lowered):
                number = match.group(1) or match.group(2)
                if number not in vocab.item_ids:
                    found.append(Violation(ValidationCode.UNKNOWN_PROJECT, path, f"project / item {number!r} is not in this case's evidence"))
            proper = [match for match in _PROPER.finditer(sentence) if match.group(0)[0].isupper()]
            unknown = {match.start() for match in proper if not _known_word(match.group(0), vocab, attributed)}
            for match in proper:
                word = match.group(0)
                base = word.removesuffix("'s")
                key = _norm(base)
                if match.start() not in unknown:
                    continue
                after = sentence[match.end(): match.end() + 30]
                person_like = bool(_PERSON_VERB.match(_norm(after.strip()))) or word.endswith("'s")
                if title_case and not person_like:
                    # A Title Case headline capitalizes ordinary words: only a run of unknown capitalized words (a full name such as
                    # "Sara Lee") is a name there; identifiers above are still checked.
                    neighbours = [other.start() for other in proper if other.start() != match.start()
                                  and abs(other.start() - match.start()) <= len(word) + 20]
                    if not any(start in unknown for start in neighbours):
                        continue
                initial = match.start() == 0 or sentence[: match.start()].strip() in ('"', "'", "(", "-")
                entity_like = bool(_ENTITY_NOUN.match(_norm(after.strip())))
                if initial and (key in _STARTERS or not (person_like or entity_like)):
                    continue
                code = ValidationCode.UNKNOWN_PERSON if person_like else ValidationCode.UNKNOWN_ENTITY
                found.append(Violation(code, path, f"{base!r} is not named in this case"))
    return found


# Metric nouns Atlas never calculates (unless the case itself carries the term).
_METRIC_NOUNS = _words(r"scores?", r"scoring", r"index(?:es)?", r"indices", r"ratings?", r"rankings?", r"ranked", r"kpis?", r"productivity",
                       r"efficiency", r"percentiles?", r"grades?", r"composite", r"risk (?:percentage|score|level|rating|index)",
                       r"performance (?:level|score|index|rating)", r"utili[sz]ation", r"ratios?")
_RATE = re.compile(r"\b([a-z-]+(?:\s[a-z-]+)?)\s+(?:rates?|percentages?|ratios?)\b")
_ALLOWED_RATES = ("late", "on-time", "on time", "ontime", "lateness", "revision", "return", "approval", "delivery", "early", "deadline")
# Modifiers that describe a rate rather than name a new metric ("a higher rate", "the team's rate").
_RATE_MODIFIERS = _wordset("higher lower same similar overall current previous baseline team cohort peer peers editor editor's team's their "
                            "its average median typical comparable rising falling steady stable increased decreased")


def _metrics(candidate: Mapping[str, Any], vocab: CaseVocabulary) -> list[Violation]:
    found: list[Violation] = []
    for path, _, text in _visible(candidate):
        lowered = _norm(text)
        for match in _METRIC_NOUNS.finditer(lowered):
            term = match.group(0)
            if not all(token in vocab.words for token in _tokens(term)):
                found.append(Violation(ValidationCode.UNSUPPORTED_METRIC, path, f"{term!r} is not a metric Atlas calculates"))
        for match in _RATE.finditer(lowered):
            words = match.group(1).split()
            name = words[-1]
            phrase = " ".join(words)
            if (any(phrase.endswith(allowed) for allowed in _ALLOWED_RATES) or f"{name} rate" in vocab.phrases or name in STOPWORDS
                    or name in _RATE_MODIFIERS or name in ATLAS_VOCABULARY or name in vocab.words):
                continue
            found.append(Violation(ValidationCode.UNSUPPORTED_METRIC, path, f"'{name} rate' is not a rate Atlas calculates"))
    return found


_CAUSAL = _words(r"caus(?:e|es|ed|ing) (?:the|this|these|a|an|his|her|their|it)", r"caused", r"causing", r"cause of", r"the cause",
                 r"because of", r"due to", r"result(?:ed|s|ing)? in", r"as a result of", r"result of", r"led to", r"leads? to", r"leading to",
                 r"responsible for", r"the reason (?:for|why|that)", r"attributable to", r"drove", r"driven by", r"is why", r"explains? why",
                 r"explains? (?:the|this|these|that|his|her|their)", r"explained (?:the|this|these|that)", r"triggered", r"stems? from",
                 r"owing to", r"driv(?:es|ing) (?:the|this|these|his|her|their)", r"produc(?:ed|es|ing) (?:the|this|these)",
                 r"made (?:the |these |this |his |her |their )?\w+ (?:late|slip|slower|worse)", r"hurts?|hurting|hurt (?:the|this)")
# Non-causal uses of the same words: a team lead, results in a window, work due to a client, evidence that leads to a reading.
_NOT_CAUSAL_BEFORE = re.compile(r"(?:team|a|the|project|our|their)\s+$|(?:the|these|those|recent|current)\s+$")
_DUE_DATE_AFTER = re.compile(r"\s*(?:the\s+)?(?:clients?|customers?)\s+(?:on|by|in|at|before|within|for)\b")   # "due to the client by Friday"
_NOT_CAUSAL_AFTER = re.compile(r"\s*(?:the\s+|a\s+)?(?:clients?|customers?|delivery|interpretation|conclusion|reading|view|observation|"
                               r"current window|previous window|this window)\b")


def _causal_matches(lowered: str) -> Iterator[re.Match[str]]:
    for match in _CAUSAL.finditer(lowered):
        phrase = match.group(0)
        before = lowered[max(0, match.start() - 12): match.start()]
        if phrase.startswith(("lead", "result")) and _NOT_CAUSAL_BEFORE.search(before):
            continue
        if phrase in ("leads to", "lead to", "leading to", "results in", "result in") and _NOT_CAUSAL_AFTER.match(lowered, match.end()):
            continue
        if phrase == "due to" and _DUE_DATE_AFTER.match(lowered, match.end()):
            continue
        yield match


def _causality(candidate: Mapping[str, Any]) -> list[Violation]:
    found: list[Violation] = []
    for path, name, text in _visible(candidate):
        if name in EPISTEMIC_FIELDS:
            continue
        for sentence in sentences(text):
            lowered = _norm(sentence)
            for match in _causal_matches(lowered):
                if _negated_before(lowered, match.start()):
                    continue
                if name in FACTUAL_FIELDS or not _hedged_before(lowered, match.start()):
                    found.append(Violation(ValidationCode.CAUSAL_OVERCLAIM, path,
                                           "causal claim: Atlas evidence shows patterns and associations, not causes" +
                                           (" (factual fields never carry causal claims)" if name in FACTUAL_FIELDS else " (state it as a possibility)")))
                    break
    return found


_HR = _words(r"lazy", r"laziness", r"careless(?:ness)?", r"incompeten(?:t|ce|cy)", r"competen(?:t|ce|cy)", r"unskilled", r"untalented", r"talented",
             r"(?:un)?motivated", r"motivation", r"unmotivated", r"attitudes?", r"personality", r"personalit(?:y|ies)",
             r"(?:his|her|their|personal|the editor's) character", r"character flaws?",
             r"sick(?:ness)?", r"ill", r"illness(?:es)?", r"medical", r"health", r"pregnan(?:t|cy)", r"maternity", r"diagnos(?:is|ed)",
             r"hospitali[sz]ed", r"hospital", r"family (?:emergency|problems?|issues?)", r"personal (?:life|problems?|issues?|reasons)",
             r"disengag(?:ed|ement)", r"checked out", r"commitment", r"team player", r"struggl(?:es|ed|ing)", r"overwhelm(?:ed|ing)?",
             r"(?:does not |doesn't |did not |didn't |never )?cares? about", r"underperform(?:s|ed|ing|er|ers|ance)?",
             r"(?:weak|poor|bad|low) performers?", r"(?:be )?let (?:\w+ )?go", r"remov(?:e|ed|ing) \w+ from (?:the )?(?:project|team|work|account)",
             r"lacks? (?:\w+ )?(?:skills?|discipline|focus|drive|commitment|ability)",
             r"(?:dis)?honest(?:y)?", r"(?:dis)?loyal(?:ty)?", r"intelligen(?:t|ce)", r"stupid", r"smart", r"psycholog(?:y|ical|ically)",
             r"mental(?:ly)?", r"depress(?:ed|ion)", r"anxious", r"anxiety", r"emotional(?:ly)?", r"burn(?:ed|t)?[ -]?out", r"stressed",
             r"salary", r"salaries", r"pay (?:raise|rise|cut)", r"bonus(?:es)?", r"compensation", r"fir(?:e|ed|ing) (?:him|her|them|the editor)",
             r"fired", r"firing", r"terminat(?:e|ed|ion|ing)", r"dismiss(?:al|ed)? (?:him|her|them|the editor)", r"let (?:him|her|them) go",
             r"promot(?:e|ed|ion|ing)", r"demot(?:e|ed|ion|ing)", r"disciplin(?:e|ary|ed)", r"warning letter", r"performance improvement plan",
             r"\bpip\b", r"hir(?:e|ing) (?:a|an|another|new|more|replacement|someone)", r"should (?:be )?hired?", r"punish(?:ed|ment|ing)?",
             r"reprimand(?:ed)?", r"replace (?:him|her|them|the editor)",
             r"(?:good|bad|poor|weak|strong|great|terrible) (?:editor|employee|worker|person)", r"underperformer", r"slacker", r"effort",
             r"work ethic", r"dedication", r"reliable person", r"unreliable (?:editor|person|employee)")


def _people(candidate: Mapping[str, Any], vocab: CaseVocabulary) -> list[Violation]:
    found: list[Violation] = []
    names = sorted(vocab.editor_ids | vocab.names, key=len, reverse=True)
    person = r"\b(?:the editor|this editor|that editor|editor|he|she|his|her|" + "".join(re.escape(_norm(name)) + "|" for name in names) + r"they)"
    blame_agent = re.compile(person + r"\W+(?:\w+\W+){0,3}?(?:caused|causes|is responsible|was responsible|are responsible|is to blame|"
                             r"was to blame|is the reason|was the reason|is at fault|was at fault|failed to|neglected|ignored|did not care)")
    blame_object = re.compile(r"(?:because of|due to|caused by|driven by|attributable to|the fault of|blame on)\s+(?:the\s+)?" + person + r"\b")
    blame_words = re.compile(r"\b(?:blame[sd]?|blaming|at fault|fault of|culprit|to blame)\b|'s fault\b|\b(?:his|her|their) fault\b")
    for path, name, text in _visible(candidate):
        for sentence in sentences(text):
            lowered = _norm(sentence)
            for match in _HR.finditer(lowered):
                # Only Atlas's own statements about what its evidence cannot show may name these, negated ("clock time is not effort").
                if name in EPISTEMIC_FIELDS and _negated_before(lowered, match.start()):
                    continue
                found.append(Violation(ValidationCode.HR_JUDGMENT, path, "a judgement about a person (personality, psychology, health, "
                                                                      "motivation, competence, pay or employment action) that work evidence cannot support"))
                break
            for pattern in (blame_words, blame_agent, blame_object):
                hit = next((match for match in pattern.finditer(lowered) if not _negated_before(lowered, match.start())), None)
                if hit is not None:
                    found.append(Violation(ValidationCode.UNSUPPORTED_BLAME, path, "a person is blamed; Atlas evidence describes work patterns only"))
                    break
    return found


_CERTAINTY = _words(r"proves?", r"proven", r"conclusive(?:ly)?", r"undoubtedly", r"definitely", r"certainly", r"without doubt",
                    r"beyond doubt", r"irrefutabl[ey]", r"guaranteed?", r"confirms?", r"confirmed", r"obvious(?:ly)?")
_HIGH_CONFIDENCE = _words(r"high(?:ly)? confiden(?:t|ce)", r"strong(?:ly)? confiden(?:t|ce)", r"very confident", r"confidence is strong",
                          r"result is strong", r"strong evidence", r"conclusively", r"clear(?:ly)?", r"evident(?:ly)?", r"strong pattern",
                          r"it is certain")


def _confidence(candidate: Mapping[str, Any], case: Mapping[str, Any]) -> list[Violation]:
    found: list[Violation] = []
    confidence: Mapping[str, Any] = candidate["confidence"] if isinstance(candidate.get("confidence"), Mapping) else {}
    try:
        level = ConfidenceLevel(str(confidence.get("level")))
    except ValueError:
        return [Violation(ValidationCode.CONTRACT_INVALID, "confidence/level", "not a confidence level")]
    ceiling = max((CONFIDENCE_ORDER.index(ConfidenceLevel(row["confidence"])) for row in case["supporting_findings"]), default=0)
    if CONFIDENCE_ORDER.index(level) > ceiling:
        found.append(Violation(ValidationCode.CONFIDENCE_EXCEEDED, "confidence/level",
                               f"{level.value} exceeds the strongest supporting finding ({CONFIDENCE_ORDER[ceiling].value})"))
    _, _, counter = _role_sets(case)
    if level == ConfidenceLevel.STRONG and (case["contradicting_findings"] or counter):
        found.append(Violation(ValidationCode.CONFIDENCE_EXCEEDED, "confidence/level", "strong confidence while the case has contradicting evidence"))
    for path, _, text in _visible(candidate):
        for sentence in sentences(text):
            lowered = _norm(sentence)
            if any(not _negated_before(lowered, match.start()) for match in _CERTAINTY.finditer(lowered)):
                found.append(Violation(ValidationCode.CONFIDENCE_EXCEEDED, path, "claims proof or certainty; Atlas evidence never proves"))
            elif level != ConfidenceLevel.STRONG and any(not _negated_before(lowered, match.start()) for match in _HIGH_CONFIDENCE.finditer(lowered)):
                found.append(Violation(ValidationCode.CONFIDENCE_EXCEEDED, path, f"claims high confidence while the level is {level.value}"))
    return found


def _attribution(candidate: Mapping[str, Any], vocab: CaseVocabulary) -> list[Violation]:
    found: list[Violation] = []
    if not vocab.context_items:
        return found
    for path, name, text in _visible(candidate):
        if name == "questions_for_management":
            continue    # a question asserts nothing
        for sentence in sentences(text):
            tokens = _tokens(sentence)
            for source, distinctive in vocab.context_items:
                overlap = tokens & distinctive
                # A short statement is matched on fewer words: one of up to two distinctive words, two of up to four, else three.
                needed = 1 if len(distinctive) <= 2 else 2 if len(distinctive) <= 4 else 3
                if not distinctive or len(overlap) < needed:
                    continue
                if name in FACTUAL_FIELDS:
                    found.append(Violation(ValidationCode.CONTEXT_AS_EVIDENCE, path,
                                           f"management context ({source.split(':')[1]}) presented as deterministic evidence"))
                elif not _attributed(sentence):
                    found.append(Violation(ValidationCode.MEMORY_ATTRIBUTION_LOST, path,
                                           f"uses management context ({source.split(':')[1]}) without attributing it to management"))
                break
    return found


def _contract(candidate: Mapping[str, Any], case: Mapping[str, Any]) -> list[Violation]:
    errors = contracts.result_errors(candidate)
    return [Violation(ValidationCode.CONTRACT_INVALID, "<result>", error) for error in errors]


# --- entry point ---------------------------------------------------------------------------------------------------------------


def validate_candidate(candidate: Mapping[str, Any], case: Mapping[str, Any], expected: Expected, *,
                       extra: Iterable[Violation] = ()) -> ValidationReport:
    """Every Phase 15 rule on one complete candidate. ``extra`` carries violations found earlier (e.g. an invalid patch)."""
    violations: list[Violation] = list(extra)
    contract = _contract(candidate, case) if isinstance(candidate, Mapping) else [Violation(ValidationCode.CONTRACT_INVALID, "<result>", "not an object")]
    violations += contract
    if not contract:
        vocab = CaseVocabulary.of(case)
        violations += _identity(candidate, case, expected)
        violations += _evidence(candidate, case)
        violations += _numbers(candidate, case, include_delta=expected.previous is not None)
        violations += _entities(candidate, vocab)
        violations += _metrics(candidate, vocab)
        violations += _causality(candidate)
        violations += _people(candidate, vocab)
        violations += _confidence(candidate, case)
        violations += _attribution(candidate, vocab)
    unique = list(dict.fromkeys(violations))
    return ValidationReport(tuple(unique))


def patch_violations(errors: Sequence[str]) -> list[Violation]:
    """Update-level errors (``updater.update_consistency_errors``) as violations."""
    found = []
    for error in errors:
        code, _, detail = error.partition(": ")
        mapped = {"STALE_BASE_VERSION": ValidationCode.IDENTITY_MISMATCH, "CASE_MISMATCH": ValidationCode.IDENTITY_MISMATCH,
                  "EVIDENCE_FINGERPRINT_MISMATCH": ValidationCode.IDENTITY_MISMATCH,
                  "UNKNOWN_EVIDENCE_REF": ValidationCode.UNKNOWN_EVIDENCE}.get(code, ValidationCode.PATCH_INVALID)
        field_name = (detail or "").split(" ", 1)[0].rstrip(":")
        path = field_name if field_name in contracts.PATCHABLE_FIELDS else code
        found.append(Violation(mapped, path, f"{code}: {detail}" if detail else error))
    return found


def correction_message(report: ValidationReport) -> str:
    """What the model is told after a refused answer: codes and paths only (never free text echoed back), so the retry is bounded and
    cannot be steered by content."""
    lines = [f"- {violation.code.value} at {violation.path}" for violation in report.violations[:40]]
    return ("Atlas validation refused your previous answer. Problems (code at path):\n" + "\n".join(lines) +
            "\nReturn a complete corrected answer in the same JSON format that follows every rule of the system prompt. Fix exactly these "
            "problems: cite only the case's references in their roles, use only the case's numbers and names, state causes only as "
            "possibilities, make no judgement about people, keep management context attributed and never present it as evidence, and do "
            "not claim more confidence than the evidence supports.")
