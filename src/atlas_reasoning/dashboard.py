"""The reasoning-first dashboard's read model (``REV/16``): canonical PostgreSQL state composed into cards, drill-down and history.

``DashboardService`` is the one place that decides what management sees. It reads canonical state only and computes nothing that
belongs upstream:

- **Cards** are the results' *current* versions (``reasoning_results.current_version``). A refused Phase 15 candidate is never a
  version, so it can never be a card; ``reasoning_failed_candidates`` is not read at all.
- **Lifecycle** is the stored status of the shown version (Phase 09 decides it). Grouping and ordering by status are presentation.
- **Notices** (degraded states) come from canonical rows: the case's latest LLM work item and its content-free ``last_error``
  (provider failure, guardrail refusal: the previous valid version stays the card), whether the case's current evidence
  fingerprint differs from the card's (newer evidence not yet reasoned), and the memory status of the latest reasoning call.
  Honcho is never contacted from here.
- **What changed** is the stored ``ReasoningUpdate`` (changed fields, rationale) and ``delta.summary`` of the stored material delta.
- **Evidence** is resolved through ``reasoning_evidence_links`` and the stored case evidence state of the shown version:
  result → evidence reference → ReasoningCase → contributing Intelligence V2 finding → its statements (metrics) and evidence
  blocks → Monday item, cycle and event IDs. Management context (``manager_context`` / ``memory_context`` of a case) is never part
  of it.
- **Human context** (notes, questions, answers, teachings) is read through the Phase 12–14 services; when they are unavailable the
  card still renders, saying so.

The view objects are derived values, never a new source of truth: each carries the canonical IDs and versions it came from and is
rebuilt from PostgreSQL on every request. ``to_dict`` gives the JSON the read API serves; the HTML renders the same objects, so
English and Arabic show the same records.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

from atlas_reasoning import delta as deltas
from atlas_reasoning.atlas_questions import AtlasQuestions, Question
from atlas_reasoning.dashboard_routes import parse_result_id
from atlas_reasoning.enums import LifecycleStatus, ResultChangeKind
from atlas_reasoning.manager_notes import ManagerNotes, Note
from atlas_reasoning.store import dashboard_read as sql
from atlas_reasoning.store.db import DatabaseError
from atlas_reasoning.store.human_context import iso
from atlas_reasoning.store.repository import NotFound, ReasoningStore, citations
from atlas_reasoning.teach_atlas import TeachAtlas, Teaching

LOG = logging.getLogger("atlas_reasoning.dashboard")
T = TypeVar("T")

# Display order on the home page: current cards first (new, updated, active, cooling), then history (resolved, superseded).
CURRENT_STATUSES = (LifecycleStatus.NEW, LifecycleStatus.UPDATED, LifecycleStatus.ACTIVE, LifecycleStatus.COOLING)
HISTORICAL_STATUSES = (LifecycleStatus.RESOLVED, LifecycleStatus.SUPERSEDED)
EVIDENCE_REF = re.compile(r"^ev1_[0-9a-f]{24}$")
MAX_VERSION = 1_000_000

# Notice codes (presentation wording lives in ``dashboard_i18n``).
EVIDENCE_CHANGED = "evidence_changed"        # the case's current evidence differs from what this card reasoned on
UPDATE_PENDING = "update_pending"            # newer evidence is queued for reasoning
PROVIDER_FAILED = "provider_failed"          # the latest reasoning attempt failed at the model provider
VALIDATION_REFUSED = "validation_refused"    # the latest candidate was refused by the Phase 15 guardrails
REFRESH_FAILED = "refresh_failed"            # the latest reasoning attempt failed for another reason
MEMORY_DEGRADED = "memory_degraded"          # contextual memory (Honcho) was unavailable for the latest reasoning call


class DashboardUnavailable(RuntimeError):
    """Canonical state could not be read (database unreachable or failing). Carries no internal detail."""

    code = "READ_FAILED"


def _db_error(error: BaseException) -> bool:
    return isinstance(error, DatabaseError) or type(error).__module__.split(".")[0] == "psycopg"


@dataclass(frozen=True)
class CardSummary:
    """One result at its current version, as listed on the home page."""

    result_id: str
    case_id: str
    version: int
    lifecycle_status: str
    title: str
    reasoning_summary: str
    confidence: str
    subject_type: str
    subject_id: str
    topic_key: str
    case_type: str
    updated_at: str
    superseded_by: Mapping[str, str] | None
    notices: tuple[str, ...] = ()

    @property
    def is_current(self) -> bool:
        return self.lifecycle_status in CURRENT_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {"result_id": self.result_id, "case_id": self.case_id, "version": self.version, "lifecycle_status": self.lifecycle_status,
                "title": self.title, "reasoning_summary": self.reasoning_summary, "confidence": self.confidence, "subject_type": self.subject_type,
                "subject_id": self.subject_id, "topic_key": self.topic_key, "case_type": self.case_type, "updated_at": self.updated_at,
                "superseded_by": dict(self.superseded_by) if self.superseded_by else None, "notices": list(self.notices)}


@dataclass(frozen=True)
class Home:
    current: tuple[CardSummary, ...]
    history: tuple[CardSummary, ...]
    memory_backlog: int

    def to_dict(self) -> dict[str, Any]:
        return {"current": [card.to_dict() for card in self.current], "history": [card.to_dict() for card in self.history],
                "memory_backlog": self.memory_backlog}


@dataclass(frozen=True)
class WhatChanged:
    """The stored account of the shown version's change and of the last content change before it."""

    version: int
    change_kind: str
    lifecycle_reason: str | None              # the transition reason code when the version is a lifecycle change
    content_version: int                      # the latest version (≤ shown) that created or patched the card's content
    content_kind: str                         # ``created`` or ``patched``
    change_rationale: str | None              # the stored ReasoningUpdate rationale of that patch
    changed_fields: tuple[str, ...]
    delta: Mapping[str, Any] | None           # ``delta.summary`` of the stored material delta behind that patch

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "change_kind": self.change_kind, "lifecycle_reason": self.lifecycle_reason,
                "content_version": self.content_version, "content_kind": self.content_kind, "change_rationale": self.change_rationale,
                "changed_fields": list(self.changed_fields), "delta": dict(self.delta) if self.delta is not None else None}


@dataclass(frozen=True)
class HumanContext:
    """Management context attached to a card (Phases 12-13). ``available`` is false when it could not be read."""

    available: bool
    notes: tuple[Note, ...] = ()
    note_history: Mapping[str, Sequence[Mapping[str, Any]]] = field(default_factory=dict)
    questions: tuple[Question, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"available": self.available, "label": "management_context", "notes": [note.to_dict() for note in self.notes],
                "note_history": {key: list(value) for key, value in self.note_history.items()},
                "questions": [question.to_dict() for question in self.questions]}


@dataclass(frozen=True)
class ResultCard:
    """A full card: the canonical document of the shown version plus what changed, supersession links and notices."""

    summary: CardSummary                       # the result at its current version
    document: Mapping[str, Any]                # the shown version's canonical ReasoningResult document
    shown_version: int
    what_changed: WhatChanged
    replaces: tuple[str, ...]                  # results this one superseded

    @property
    def is_current_version(self) -> bool:
        return self.shown_version == self.summary.version

    @property
    def lifecycle_status(self) -> str:
        return str(self.document["lifecycle_status"])

    def to_dict(self) -> dict[str, Any]:
        return {"result_id": self.summary.result_id, "case_id": self.summary.case_id, "current_version": self.summary.version,
                "shown_version": self.shown_version, "is_current_version": self.is_current_version, "lifecycle_status": self.lifecycle_status,
                "current_lifecycle_status": self.summary.lifecycle_status, "notices": list(self.summary.notices) if self.is_current_version else [],
                "subject_type": self.summary.subject_type, "subject_id": self.summary.subject_id, "topic_key": self.summary.topic_key,
                "result": dict(self.document), "what_changed": self.what_changed.to_dict(), "replaces": list(self.replaces)}


@dataclass(frozen=True)
class EvidenceItem:
    """One Monday evidence record of the case, resolved from the stored case evidence state."""

    ref_id: str
    cited_in: tuple[str, ...]                  # the card fields citing it (empty: part of the case, not cited by this card)
    linked: bool                               # present in ``reasoning_evidence_links`` for this version
    role: str
    evidence_code: str
    member_key: str
    finding_id: str
    monday_item_id: str
    cycle_id: str | None
    event_ids: tuple[str, ...]
    source_timestamps: tuple[str, ...]
    editor_id: str | None
    video_type_key: str | None
    values: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"ref_id": self.ref_id, "cited_in": list(self.cited_in), "linked": self.linked, "role": self.role, "evidence_code": self.evidence_code,
                "member_key": self.member_key, "finding_id": self.finding_id, "monday_item_id": self.monday_item_id, "cycle_id": self.cycle_id,
                "event_ids": list(self.event_ids), "source_timestamps": list(self.source_timestamps), "editor_id": self.editor_id,
                "video_type_key": self.video_type_key, "values": dict(self.values)}


@dataclass(frozen=True)
class FindingTrace:
    """One contributing Intelligence V2 finding with its deterministic statements, evidence blocks and Monday records."""

    side: str                                  # ``supporting`` or ``contradicting`` (relative to the case orientation)
    finding: Mapping[str, Any]                 # the case's FindingRef: V2 finding_id, member key, type, direction, confidence, ...
    statements: tuple[Mapping[str, Any], ...]
    blocks: tuple[Mapping[str, Any], ...]
    evidence: tuple[EvidenceItem, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"side": self.side, "finding": dict(self.finding), "statements": [dict(row) for row in self.statements],
                "blocks": [dict(row) for row in self.blocks], "evidence": [item.to_dict() for item in self.evidence]}


@dataclass(frozen=True)
class Claim:
    field: str
    index: int | None
    text: str
    evidence_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "index": self.index, "text": self.text, "evidence_refs": list(self.evidence_refs)}


@dataclass(frozen=True)
class EvidenceTrace:
    result_id: str
    version: int
    case: Mapping[str, Any]                    # case identity, snapshot, fingerprint, orientation, scope, upstream versions
    claims: tuple[Claim, ...]
    findings: tuple[FindingTrace, ...]
    unresolved: tuple[str, ...]                # cited references that do not resolve (never expected; shown when they occur)

    @property
    def resolves(self) -> bool:
        return not self.unresolved

    def to_dict(self) -> dict[str, Any]:
        return {"result_id": self.result_id, "version": self.version, "case": dict(self.case), "claims": [claim.to_dict() for claim in self.claims],
                "findings": [finding.to_dict() for finding in self.findings], "unresolved": list(self.unresolved), "resolves": self.resolves}


@dataclass(frozen=True)
class VersionRow:
    version: int
    change_kind: str
    lifecycle_status: str
    created_at: str
    evidence_fingerprint: str
    source_snapshot_id: str
    model: str
    prompt_version: str
    reason: str | None
    change_rationale: str | None
    changed_fields: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "change_kind": self.change_kind, "lifecycle_status": self.lifecycle_status, "created_at": self.created_at,
                "evidence_fingerprint": self.evidence_fingerprint, "source_snapshot_id": self.source_snapshot_id, "model": self.model,
                "prompt_version": self.prompt_version, "reason": self.reason, "change_rationale": self.change_rationale,
                "changed_fields": list(self.changed_fields)}


@dataclass(frozen=True)
class History:
    summary: CardSummary
    versions: tuple[VersionRow, ...]
    transitions: tuple[Mapping[str, Any], ...]
    replaces: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"result_id": self.summary.result_id, "current_version": self.summary.version, "lifecycle_status": self.summary.lifecycle_status,
                "notices": list(self.summary.notices),
                "superseded_by": dict(self.summary.superseded_by) if self.summary.superseded_by else None, "replaces": list(self.replaces),
                "versions": [row.to_dict() for row in self.versions], "transitions": [dict(row) for row in self.transitions]}


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _notices(row: Mapping[str, Any], work: Mapping[str, Any] | None, memory: Mapping[str, Any] | None) -> tuple[str, ...]:
    notices = []
    status = row["lifecycle_status"]
    if status in CURRENT_STATUSES and row["presence"] == "present" and row["last_evidence_fingerprint"] != row["evidence_fingerprint"]:
        notices.append(EVIDENCE_CHANGED)
    if work is not None and status not in HISTORICAL_STATUSES:
        error = _text(work.get("last_error"))
        if work["status"] in ("pending", "in_progress"):
            notices.append(UPDATE_PENDING)
        elif work["status"] == "failed":
            notices.append(PROVIDER_FAILED if error.startswith("provider:") else VALIDATION_REFUSED if error.startswith("validation:")
                           else REFRESH_FAILED)
    if memory is not None and memory["memory_status"] in ("degraded", "unavailable"):
        notices.append(MEMORY_DEGRADED)
    return tuple(notices)


def _summary(row: Mapping[str, Any], work: Mapping[str, Any] | None = None, memory: Mapping[str, Any] | None = None) -> CardSummary:
    document = row["document"]
    superseded = ({"result_id": row["superseded_by_result_id"], "case_id": row["superseded_by_case_id"]}
                  if row["superseded_by_result_id"] else None)
    return CardSummary(row["result_id"], row["case_id"], row["current_version"], row["lifecycle_status"], _text(document.get("title")),
                       _text(document.get("reasoning_summary")), _text((document.get("confidence") or {}).get("level")), row["subject_type"],
                       row["subject_id"], row["topic_key"], row["case_type"], _text(document.get("updated_at")), superseded,
                       _notices(row, work, memory))


def _order(cards: Sequence[CardSummary], statuses: Sequence[str]) -> tuple[CardSummary, ...]:
    """Presentation order only: by lifecycle group, then most recently updated, then result ID."""
    rank = {status: index for index, status in enumerate(statuses)}
    newest_first = sorted(cards, key=lambda card: (card.updated_at, card.result_id), reverse=True)
    return tuple(sorted(newest_first, key=lambda card: rank[card.lifecycle_status]))


def _claims(document: Mapping[str, Any]) -> tuple[Claim, ...]:
    claims = []
    for name in ("observation", "interpretation", "management_significance"):
        claims.append(Claim(name, None, _text(document[name]["statement"]), tuple(document[name]["evidence_refs"])))
    for name in ("supporting_evidence", "counter_evidence"):
        claims += [Claim(name, index, _text(row["statement"]), tuple(row["evidence_refs"])) for index, row in enumerate(document[name])]
    claims += [Claim("alternative_explanations", index, _text(row["explanation"]), tuple(row["evidence_refs"]))
               for index, row in enumerate(document["alternative_explanations"])]
    claims += [Claim("suggested_investigations", index, _text(row["text"]), tuple(row["evidence_refs"]))
               for index, row in enumerate(document["suggested_investigations"])]
    return tuple(claims)


class DashboardService:
    """Canonical reads for the dashboard. Writes stay with the Phase 12-14 services behind ``management_api``."""

    def __init__(self, store: ReasoningStore, *, notes: ManagerNotes | None = None, questions: AtlasQuestions | None = None,
                 teachings: TeachAtlas | None = None) -> None:
        self.store = store
        self.notes = notes
        self.questions = questions
        self.teachings = teachings

    def _read(self, read: Callable[[], T]) -> T:
        try:
            return read()
        except NotFound:
            raise
        except Exception as error:
            if _db_error(error):
                LOG.error("dashboard read failed error=%s", type(error).__name__)
                raise DashboardUnavailable("canonical reasoning state is unavailable") from None
            raise

    # --- home -------------------------------------------------------------------------------------------------------------

    def home(self) -> Home:
        def read() -> Home:
            with self.store.transaction() as tx:
                rows = sql.results(tx)
                case_ids = sorted({row["case_id"] for row in rows})
                work = sql.latest_llm_work(tx, case_ids)
                memory = sql.latest_memory_status(tx, case_ids)
                backlog = sql.memory_backlog(tx)
            cards = [_summary(row, work.get(row["case_id"]), memory.get(row["case_id"])) for row in rows]
            return Home(_order([c for c in cards if c.is_current], CURRENT_STATUSES),
                        _order([c for c in cards if not c.is_current], HISTORICAL_STATUSES), backlog)
        return self._read(read)

    # --- one card ---------------------------------------------------------------------------------------------------------

    @staticmethod
    def _version(version: int | None, current: int) -> int:
        if version is None:
            return current
        if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= MAX_VERSION:
            raise NotFound("not a version")
        return version

    def card(self, result_id: str, version: int | None = None) -> ResultCard:
        parse_result_id(result_id)

        def read() -> ResultCard:
            with self.store.transaction() as tx:
                row = sql.result(tx, result_id)
                shown = self._version(version, row["current_version"])
                work = sql.latest_llm_work(tx, [row["case_id"]]).get(row["case_id"])
                memory = sql.latest_memory_status(tx, [row["case_id"]]).get(row["case_id"])
                versions = [v for v in sql.versions(tx, result_id) if v["version"] <= shown]
                if not versions or versions[-1]["version"] != shown:
                    raise NotFound(f"result {result_id} has no version {shown}")
                document = row["document"] if shown == row["current_version"] else sql.version_document(tx, result_id, shown)["document"]
                transitions = tx.lifecycle_transitions(result_id=result_id)
                content = next(v for v in reversed(versions) if v["change_kind"] in (ResultChangeKind.CREATED, ResultChangeKind.PATCHED))
                material = sql.work_item_delta(tx, content["work_item_id"]) if content["change_kind"] == ResultChangeKind.PATCHED else None
                replaces = sql.replaced_results(tx, result_id)
            latest = versions[-1]
            reason = next((t["reason_code"] for t in reversed(transitions) if t["result_version"] == shown), None)
            changed = tuple(content["changed_fields"] or ()) if content["change_kind"] == ResultChangeKind.PATCHED else ()
            what = WhatChanged(shown, latest["change_kind"], reason if latest["change_kind"] == ResultChangeKind.LIFECYCLE else None,
                               content["version"], content["change_kind"], content["change_rationale"], changed,
                               deltas.summary(material) if material else None)
            return ResultCard(_summary(row, work, memory), document, shown, what, tuple(replaces))
        return self._read(read)

    def human_context(self, result_id: str) -> HumanContext:
        """Notes (with revision history) and questions (with answers and conflicts) of one card, from the Phase 12-13 services. Any
        failure leaves the card readable: the panel says management context is unavailable."""
        parse_result_id(result_id)
        if self.notes is None or self.questions is None:
            return HumanContext(available=False)
        try:
            notes = tuple(self.notes.for_result(result_id))
            history = {note.note_id: self.notes.history(note.note_id) for note in notes if note.revision > 1}
            questions = tuple(self.questions.for_result(result_id))
        except NotFound:
            raise
        except Exception as error:  # noqa: BLE001 - human context is optional on a card; the reasoning stays readable
            LOG.error("human context unavailable result_id=%s error=%s", result_id, type(error).__name__)
            return HumanContext(available=False)
        return HumanContext(True, notes, history, questions)

    def teachings_list(self) -> list[Teaching] | None:
        """Every teaching (Teach Atlas), or ``None`` when the service is unavailable."""
        if self.teachings is None:
            return None
        try:
            return self.teachings.list_teachings()
        except Exception as error:  # noqa: BLE001 - the page says Teach Atlas is unavailable
            LOG.error("teachings unavailable error=%s", type(error).__name__)
            return None

    # --- evidence drill-down ----------------------------------------------------------------------------------------------

    def evidence(self, result_id: str, version: int | None = None) -> EvidenceTrace:
        parse_result_id(result_id)

        def read() -> EvidenceTrace:
            with self.store.transaction() as tx:
                row = sql.result(tx, result_id)
                shown = self._version(version, row["current_version"])
                stored = row if shown == row["current_version"] else sql.version_document(tx, result_id, shown)
                document = stored["document"]
                links = {link["ref_id"]: link for link in tx.evidence_links(result_id, shown)}
                case_document = tx.get_case_evidence(row["case_id"], document["evidence_fingerprint"])["case_document"]
            return self._trace(result_id, shown, document, case_document, links, row)
        return self._read(read)

    @staticmethod
    def _trace(result_id: str, version: int, document: Mapping[str, Any], case_document: Mapping[str, Any], links: Mapping[str, Any],
               row: Mapping[str, Any]) -> EvidenceTrace:
        cited = citations(document)
        references = {ref["ref_id"]: ref for ref in case_document["current_evidence"]["references"]}
        members = {finding["member_key"] for key in ("supporting_findings", "contradicting_findings") for finding in case_document.get(key) or []}
        # A cited reference resolves only when it is linked for this version, exists in the case evidence and belongs to a finding
        # of the case (so the drill-down can show it under that finding).
        unresolved = tuple(sorted(ref for ref in cited if ref not in references or ref not in links or not EVIDENCE_REF.match(ref)
                                  or references[ref]["member_key"] not in members))

        def item(ref: Mapping[str, Any]) -> EvidenceItem:
            return EvidenceItem(ref["ref_id"], tuple(cited.get(ref["ref_id"], ())), ref["ref_id"] in links, ref["role"], ref["evidence_code"],
                                ref["member_key"], ref["finding_id"], _text(ref["monday_item_id"]), ref.get("cycle_id"), tuple(ref.get("event_ids") or ()),
                                tuple(ref.get("source_timestamps") or ()), ref.get("editor_id"), ref.get("video_type_key"), ref.get("values") or {})

        statements = case_document["current_evidence"].get("statements") or []
        blocks = case_document["current_evidence"].get("blocks") or []
        findings = []
        for side, key in (("supporting", "supporting_findings"), ("contradicting", "contradicting_findings")):
            for finding in case_document.get(key) or []:
                member = finding["member_key"]
                findings.append(FindingTrace(side, finding, tuple(s for s in statements if s["member_key"] == member),
                                             tuple(b for b in blocks if b["member_key"] == member),
                                             tuple(item(ref) for ref in references.values() if ref["member_key"] == member)))
        case = {name: case_document.get(name) for name in ("case_id", "case_type", "subject_type", "subject_id", "topic_key", "identity_key",
                                                           "identity_dimensions", "orientation", "scope", "source_snapshot_id", "evidence_fingerprint",
                                                           "upstream_contract_version", "upstream")}
        case["current_evidence_fingerprint"] = row["last_evidence_fingerprint"]
        case["current_version"] = row["current_version"]
        return EvidenceTrace(result_id, version, case, _claims(document), tuple(findings), unresolved)

    def existing(self, result_ids: Sequence[str]) -> set[str]:
        """Which of ``result_ids`` are canonical results (for linking statements to cards)."""
        for result_id in result_ids:
            parse_result_id(result_id)

        def read() -> set[str]:
            with self.store.transaction() as tx:
                return sql.existing_results(tx, result_ids)
        return self._read(read)

    # --- history ----------------------------------------------------------------------------------------------------------

    def history(self, result_id: str) -> History:
        parse_result_id(result_id)

        def read() -> History:
            with self.store.transaction() as tx:
                row = sql.result(tx, result_id)
                work = sql.latest_llm_work(tx, [row["case_id"]]).get(row["case_id"])
                memory = sql.latest_memory_status(tx, [row["case_id"]]).get(row["case_id"])
                versions = sql.versions(tx, result_id)
                transitions = tx.lifecycle_transitions(result_id=result_id)
                replaces = sql.replaced_results(tx, result_id)
            rows = tuple(VersionRow(v["version"], v["change_kind"], v["lifecycle_status"], iso(v["created_at"]) or "", v["evidence_fingerprint"],
                                    v["source_snapshot_id"], v["model"], v["prompt_version"], v["reason"], v["change_rationale"],
                                    tuple(v["changed_fields"] or ()) if v["change_kind"] == ResultChangeKind.PATCHED else ()) for v in versions)
            moves = tuple({"from_status": t["from_status"], "to_status": t["to_status"], "reason_code": t["reason_code"],
                           "result_version": t["result_version"], "created_at": iso(t["created_at"]),
                           "superseded_by_result_id": t["superseded_by_result_id"]} for t in transitions)
            return History(_summary(row, work, memory), rows, moves, tuple(replaces))
        return self._read(read)
