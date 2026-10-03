"""Atlas questions and management answers (``REV/13``): Atlas asks for missing business context instead of inventing it.

**Questions** come only from a committed result version's ``questions_for_management`` (``record_result_questions``), never from
free text: this is not a chat. For each question of the version:

- a question answerable from deterministic evidence (counts, rates, dates, which projects were late, …: ``evidence_answerable``) is
  suppressed: Atlas must read the evidence, not ask management;
- the same question (``dedup_key``: normalized text) already **open** for the case is not duplicated: the open question is kept
  and its ask count, latest result version and run are updated (the database also allows one open question per case and key);
- a question already **answered** or **dismissed** for the case is not asked again (the answer is reused as context; a dismissal
  stands);
- otherwise a new open question is stored, then copied to the result's memory session (``atlas_question``).

Every ask is recorded in ``atlas_question_asks`` with its outcome, so repeated asking stays auditable; processing the same result
version twice is a no-op. Open questions of the case that the latest version no longer asks become ``superseded``.

**Answers** (source ``manager_answer``) are committed first, then copied to the result session and the case subject's session
(Editor / Video Type). Answers are append-only: a new answer that differs from the question's latest answer is stored with
``conflicts_with_answer_id`` pointing at it, so conflicting history stays visible instead of being silently replaced; re-submitting
an identical answer creates nothing. A dismissed or superseded question takes no answers.

Answered questions reach later reasoning through ``AnswerContextSource``: the latest answer of each answered question of the case,
attributed, with any conflicting earlier answer stated alongside it.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from atlas_reasoning.enums import ExpectedContextType, NoteSource, QuestionState
from atlas_reasoning.memory import MemoryRecord, RetrievedMemory, result_session
from atlas_reasoning.memory_context import CaseScope, ContextCandidate
from atlas_reasoning.memory_sync import MemorySyncService, SyncOutcome, subject_session
from atlas_reasoning.store import human_context as sql
from atlas_reasoning.store.repository import NotFound, ReasoningStore, StoreError, StoreTransaction
from atlas_reasoning.user_text import clean_identity, clean_text, normalized_for_comparison

log = logging.getLogger("atlas_reasoning.questions")

MAX_ANSWER = 8000
MAX_REASON = 2000
MAX_CONFLICT_QUOTE = 1500


class QuestionClosed(StoreError):
    """The question was dismissed or superseded and takes no answers (or was answered and cannot be dismissed)."""


def dedup_key(text: str) -> str:
    """The same question, however it is cased, spaced or punctuated at the end, has one key."""
    normalized = normalized_for_comparison(text).rstrip(" ?.!؟")
    return "q1_" + hashlib.sha256(normalized.encode()).hexdigest()[:32]


# Questions whose answer is a number, rate, date or list Atlas already has from Monday and the metric engine.
_EVIDENCE_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r"\bhow many\b",
    r"\bhow (late|early|long|often|much time)\b",
    r"\bwhat (is|was|were|are) the (late|on[- ]?time|deadline|delivery|revision|average|median|mean|current|previous) ",
    r"\b(late|on[- ]?time|lateness) rate\b",
    r"\bsample size\b",
    r"\bnumber of (projects|items|deliveries|videos|revisions)\b",
    r"\bwhich (projects|items|deliveries|videos) (were|was|are) (late|early|on[- ]?time)\b",
    r"\bwhen (was|were) .* (delivered|submitted|ready|approved)\b",
    r"\bwhat (percentage|share|proportion)\b",
))


def evidence_answerable(text: str) -> bool:
    """True when the question asks for a fact the deterministic evidence already holds (``REV/13`` #9)."""
    lowered = normalized_for_comparison(text)
    return any(pattern.search(lowered) for pattern in _EVIDENCE_PATTERNS)


@dataclass(frozen=True)
class Answer:
    answer_id: str
    question_id: str
    body: str
    author: str | None
    created_at: str
    conflicts_with_answer_id: str | None
    source_type: str = NoteSource.MANAGER_ANSWER.value

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Answer:
        return cls(row["answer_id"], row["question_id"], row["body"], row["author"], sql.iso(row["created_at"]) or "", row["conflicts_with_answer_id"])

    def to_dict(self) -> dict[str, Any]:
        return {"answer_id": self.answer_id, "question_id": self.question_id, "body": self.body, "author": self.author,
                "created_at": self.created_at, "conflicts_with_answer_id": self.conflicts_with_answer_id,
                "conflict": self.conflicts_with_answer_id is not None, "source_type": self.source_type}


@dataclass(frozen=True)
class Question:
    question_id: str
    case_id: str
    result_id: str | None
    result_version: int | None
    text: str
    reason: str
    expected_context_type: str
    state: str
    ask_count: int
    created_at: str
    updated_at: str
    resolved_at: str | None
    resolved_by: str | None
    dismiss_reason: str | None
    answers: tuple[Answer, ...] = field(default=())

    @classmethod
    def from_row(cls, row: Mapping[str, Any], answers: Sequence[Answer] = ()) -> Question:
        return cls(row["question_id"], row["case_id"], row["result_id"], row["result_version"], row["question_text"], row["reason"],
                   row["expected_context_type"], row["state"], row["ask_count"], sql.iso(row["created_at"]) or "", sql.iso(row["updated_at"]) or "",
                   sql.iso(row["resolved_at"]), row["resolved_by"], row["dismiss_reason"], tuple(answers))

    @property
    def has_conflict(self) -> bool:
        return any(answer.conflicts_with_answer_id for answer in self.answers)

    def to_dict(self) -> dict[str, Any]:
        return {"question_id": self.question_id, "case_id": self.case_id, "result_id": self.result_id, "result_version": self.result_version,
                "text": self.text, "reason": self.reason, "expected_context_type": self.expected_context_type, "state": self.state,
                "ask_count": self.ask_count, "created_at": self.created_at, "updated_at": self.updated_at, "resolved_at": self.resolved_at,
                "resolved_by": self.resolved_by, "dismiss_reason": self.dismiss_reason, "has_conflicting_answers": self.has_conflict,
                "answers": [answer.to_dict() for answer in self.answers], "source_type": NoteSource.ATLAS_QUESTION.value}


@dataclass(frozen=True)
class AskReport:
    result_id: str
    result_version: int
    outcomes: tuple[tuple[str, str, str | None], ...]     # (dedup_key, outcome, question_id)
    superseded: tuple[str, ...]
    sync: tuple[SyncOutcome, ...]


def _answer_body(question_text: str, answer: Mapping[str, Any], previous: Mapping[str, Any] | None) -> str:
    body = f"Question: {question_text}\nAnswer: {answer['body']}"
    if previous is not None:
        quote = previous["body"] if len(previous["body"]) <= MAX_CONFLICT_QUOTE else previous["body"][: MAX_CONFLICT_QUOTE - 1] + "…"
        body += f"\nConflict: management answered differently earlier ({sql.iso(previous['created_at'])}): {quote}"
    return body[:8000]


def _question_record(row: Mapping[str, Any]) -> MemoryRecord:
    body = f"Atlas asked management: {row['question_text']}\nWhy it matters: {row['reason']}"
    return MemoryRecord(NoteSource.ATLAS_QUESTION, row["question_id"], result_session(row["result_id"]), body[:8000],
                        recorded_at=sql.iso(row["created_at"]),
                        metadata={"case_id": row["case_id"], "result_id": row["result_id"], "expected_context_type": row["expected_context_type"]})


def question_records(tx: StoreTransaction, question_id: str) -> list[MemoryRecord]:
    """Resolver: the memory copy of a question while it is open (a resolved question needs none)."""
    try:
        row = sql.get_question(tx, question_id)
    except NotFound:
        return []
    return [_question_record(row)] if row["state"] == QuestionState.OPEN and row["result_id"] else []


def answer_records(tx: StoreTransaction, answer_id: str) -> list[MemoryRecord]:
    """Resolver: the memory copies of an answer (result session and the case subject's session)."""
    try:
        answer = sql.get_answer(tx, answer_id)
    except NotFound:
        return []
    question = sql.get_question(tx, answer["question_id"])
    previous = sql.get_answer(tx, answer["conflicts_with_answer_id"]) if answer["conflicts_with_answer_id"] else None
    case = tx.get_case(question["case_id"])
    sessions = [result_session(question["result_id"])] if question["result_id"] else []
    subject = subject_session(case.subject_type, case.subject_id)
    if subject is not None and subject.split(":", 1)[0] in ("editor", "video-type"):
        sessions.append(subject)
    body = _answer_body(question["question_text"], answer, previous)
    return [MemoryRecord(NoteSource.MANAGER_ANSWER, answer_id, session, body, author=answer["author"], recorded_at=sql.iso(answer["created_at"]),
                         metadata={"case_id": question["case_id"], "result_id": question["result_id"], "question_id": question["question_id"],
                                   "conflicts_with": answer["conflicts_with_answer_id"]})
            for session in sessions]


class AtlasQuestions:
    def __init__(self, store: ReasoningStore, sync: MemorySyncService) -> None:
        self.store = store
        self.sync = sync

    # --- questions from reasoning results ---------------------------------------------------------------------------------

    def record_result_questions(self, result_id: str, *, version: int | None = None, run_id: str | None = None) -> AskReport:
        """Store the questions of one committed result version (Phases 07-09 call this after committing the version)."""
        created: list[dict[str, Any]] = []
        outcomes: list[tuple[str, str, str | None]] = []
        with self.store.transaction() as tx:
            result = tx.get_result(result_id, version).to_dict()
            case_id, result_version = result["case_id"], result["version"]
            if not self._is_current(tx, result_id, result_version) or sql.version_asked(tx, result_id, result_version):
                # An old version (a newer one already replaced it) or a version already processed: nothing is asked again, so a
                # question a later version superseded is never revived.
                return AskReport(result_id, result_version, (), (), ())
            kept: list[str] = []
            for question in result["questions_for_management"]:
                try:
                    text = clean_text(question["text"], field="question", max_length=400)
                    reason = clean_text(question["reason"], field="reason", max_length=MAX_REASON)
                except ValueError as error:   # one unusable question text never stops the others
                    log.warning("question skipped result_id=%s version=%s: %s", result_id, result_version, type(error).__name__)
                    continue
                context_type = ExpectedContextType(question["expected_context_type"]).value
                key = dedup_key(text)
                if evidence_answerable(text):
                    outcome, question_id = "suppressed_evidence", None
                else:
                    outcome, question_id, row = self._ask(tx, case_id, result_id, result_version, key, text, reason, context_type, run_id)
                    if row is not None:
                        created.append(row)
                    if outcome in ("created", "repeated") and question_id:
                        kept.append(question_id)
                if sql.record_ask(tx, case_id=case_id, result_id=result_id, result_version=result_version, run_id=run_id, dedup_key=key,
                                  question_id=question_id, outcome=outcome, text=text):
                    outcomes.append((key, outcome, question_id))
            superseded = sql.supersede_open_questions(tx, case_id, kept)
        sync = self.sync.sync([_question_record(row) for row in created])
        for question_id in superseded:
            self.sync.retire_source(NoteSource.ATLAS_QUESTION, question_id)
        return AskReport(result_id, result_version, tuple(outcomes), tuple(superseded), tuple(sync))

    @staticmethod
    def _is_current(tx: StoreTransaction, result_id: str, version: int) -> bool:
        return bool(sql.result_case(tx, result_id)["current_version"] == version)

    @staticmethod
    def _ask(tx: StoreTransaction, case_id: str, result_id: str, version: int, key: str, text: str, reason: str, context_type: str,
             run_id: str | None) -> tuple[str, str | None, dict[str, Any] | None]:
        existing = sql.latest_question(tx, case_id, key)
        if existing is not None and existing["state"] == QuestionState.OPEN:
            if (existing["result_id"], existing["result_version"]) != (result_id, version):
                sql.repeat_question(tx, existing["question_id"], result_id=result_id, result_version=version, run_id=run_id)
            return "repeated", existing["question_id"], None
        if existing is not None and existing["state"] == QuestionState.ANSWERED:
            return "suppressed_answered", existing["question_id"], None
        if existing is not None and existing["state"] == QuestionState.DISMISSED:
            return "suppressed_dismissed", existing["question_id"], None
        row = sql.insert_question(tx, case_id=case_id, result_id=result_id, result_version=version, dedup_key=key, text=text, reason=reason,
                                  expected_context_type=context_type, run_id=run_id)
        if row is None:     # a concurrent run created it first: treat as a repeat
            existing = sql.latest_question(tx, case_id, key)
            assert existing is not None
            return "repeated", existing["question_id"], None
        return "created", row["question_id"], row

    # --- answers and dismissal --------------------------------------------------------------------------------------------

    def answer(self, question_id: str, body: str, *, author: str | None) -> tuple[Answer, bool, tuple[SyncOutcome, ...]]:
        """Store an answer; returns ``(answer, created, sync outcomes)``. An identical repeat returns the existing answer."""
        text = clean_text(body, field="answer", max_length=MAX_ANSWER)
        who = clean_identity(author)
        with self.store.transaction() as tx:
            question = sql.get_question(tx, question_id, lock=True)
            if question["state"] not in (QuestionState.OPEN, QuestionState.ANSWERED):
                raise QuestionClosed(f"question {question_id} is {question['state']}")
            history = sql.answers(tx, [question_id])
            latest = history[-1] if history else None
            # Only the latest answer makes a resubmission a repeat: re-asserting an EARLIER answer is management's newest position
            # and is stored (as a conflict with the latest), never silently dropped.
            if latest is not None and normalized_for_comparison(latest["body"]) == normalized_for_comparison(text):
                return Answer.from_row(latest), False, ()
            row = sql.insert_answer(tx, question_id=question_id, body=text, author=who, conflicts_with=latest["answer_id"] if latest else None)
            if question["state"] == QuestionState.OPEN:
                sql.resolve_question(tx, question_id, state=QuestionState.ANSWERED, by=who)
            records = answer_records(tx, row["answer_id"])
        sync = self.sync.sync(records)
        self.sync.retire_source(NoteSource.ATLAS_QUESTION, question_id)
        return Answer.from_row(row), True, tuple(sync)

    def dismiss(self, question_id: str, *, author: str | None, reason: str | None = None) -> Question:
        why = clean_text(reason, field="reason", max_length=MAX_REASON) if reason is not None else None
        who = clean_identity(author)
        with self.store.transaction() as tx:
            question = sql.get_question(tx, question_id, lock=True)
            if question["state"] == QuestionState.DISMISSED:
                return self._load(tx, question_id)
            if question["state"] != QuestionState.OPEN:
                raise QuestionClosed(f"question {question_id} is {question['state']} and cannot be dismissed")
            sql.resolve_question(tx, question_id, state=QuestionState.DISMISSED, by=who, dismiss_reason=why)
            loaded = self._load(tx, question_id)
        self.sync.retire_source(NoteSource.ATLAS_QUESTION, question_id)
        return loaded

    # --- reads ------------------------------------------------------------------------------------------------------------

    @staticmethod
    def _load(tx: StoreTransaction, question_id: str) -> Question:
        row = sql.get_question(tx, question_id)
        return Question.from_row(row, [Answer.from_row(answer) for answer in sql.answers(tx, [question_id])])

    def get(self, question_id: str) -> Question:
        with self.store.transaction() as tx:
            return self._load(tx, question_id)

    def for_result(self, result_id: str, *, include_resolved: bool = True) -> list[Question]:
        """Questions of the result's case (open first is the caller's choice; order is creation order)."""
        with self.store.transaction() as tx:
            case_id = sql.result_case(tx, result_id)["case_id"]
            states = None if include_resolved else [QuestionState.OPEN.value]
            rows = sql.questions(tx, case_ids=[case_id], states=states)
            answers = sql.answers(tx, [row["question_id"] for row in rows])
        by_question: dict[str, list[Answer]] = {}
        for answer in answers:
            by_question.setdefault(answer["question_id"], []).append(Answer.from_row(answer))
        return [Question.from_row(row, by_question.get(row["question_id"], [])) for row in rows]


class AnswerContextSource:
    """The latest answer to each answered question of the case, as attributed management context (``REV/13`` #8)."""

    source_type = NoteSource.MANAGER_ANSWER

    def candidates(self, tx: StoreTransaction, scope: CaseScope, now: datetime) -> Sequence[ContextCandidate]:
        rows = sql.questions(tx, case_ids=[scope.case_id], states=[QuestionState.ANSWERED.value])
        history = sql.answers(tx, [row["question_id"] for row in rows])
        latest: dict[str, Mapping[str, Any]] = {}
        for row in history:
            latest[row["question_id"]] = row
        by_id = {row["answer_id"]: row for row in history}
        found = []
        for row in rows:
            answer = latest.get(row["question_id"])
            if answer is None:
                continue
            previous = by_id.get(answer["conflicts_with_answer_id"]) if answer["conflicts_with_answer_id"] else None
            session = result_session(row["result_id"]) if row["result_id"] else None
            found.append(ContextCandidate(NoteSource.MANAGER_ANSWER, answer["answer_id"], _answer_body(row["question_text"], answer, previous),
                                          sql.iso(answer["created_at"]) or "", "canonical", "result", session_key=session, author=answer["author"],
                                          case_id=row["case_id"], labels={"conflict": previous is not None}))
        return found

    def is_current(self, tx: StoreTransaction, memory: RetrievedMemory, scope: CaseScope, now: datetime) -> bool:
        """A remembered answer (possibly from another case of the same subject) is current while it is its question's latest answer."""
        try:
            answer = sql.get_answer(tx, memory.source_id or "")
        except NotFound:
            return False
        history = sql.answers(tx, [answer["question_id"]])
        return bool(history and history[-1]["answer_id"] == answer["answer_id"])
