"""Contextual memory vocabulary (``REV/10``): session policy, source taxonomy, memory records and the backend protocol.

PostgreSQL is the canonical store of every piece of human context (manager notes, answers, questions, teachings) and of every
reasoning result. Honcho holds *copies* of selected context so it can be retrieved as memory; it is never the database of truth.
This module is backend-neutral: ``honcho_client`` is the only module that knows Honcho's API, ``fake_honcho`` is the offline
backend for tests, and ``memory_sync`` writes copies after the canonical row is committed.

Sessions (logical keys, stored in ``memory_sync_log.session_key``):

==========================  ===================================================================
``global:teachings``        company-wide teachings
``team:editors``            team-level prior reasoning
``editor:<editor_id>``      one Editor (teachings, answers, prior reasoning about that Editor)
``video-type:<key>``        one Video Type
``workflow:<stage>``        one workflow stage (teachings)
``client:<client_id>``      one client (teachings)
``result:<result_id>``      one reasoning result (notes, questions, answers, specific-result teachings)
==========================  ===================================================================

Honcho identifiers must match ``^[a-zA-Z0-9_-]+$``, so a logical key maps to ``atlas-<kind>-<24 hex of its SHA-256>``
(``honcho_session_id``); the logical key travels in the session and message metadata. Honcho identifiers are never Atlas
identifiers: Atlas refers to memory only by ``(source_type, source_id)`` of its canonical row.

What may be written (``check_record``): only the five source types of ``NoteSource``, only into the sessions its policy allows
(``SESSION_POLICY``), only plain text up to 8000 characters (a JSON document or a dump of Monday records is refused), and only
allow-listed scalar metadata. Raw Monday history is never uploaded: nothing in this package reads Monday, and a prior reasoning
summary is built from a result's management summary only (``summary_record``), never from its evidence references.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from atlas_reasoning.enums import NoteSource

MEMORY_VERSION = "atlas-memory-v1"
MAX_BODY = 8000
MAX_ID = 200


class MemoryBackendError(RuntimeError):
    """A memory backend operation failed. ``error_class`` is stable; messages never contain credentials."""

    error_class = "memory_error"
    retryable = False


class MemoryUnavailable(MemoryBackendError):
    """Network failure, timeout, rate limit or server error: try again later."""

    error_class = "memory_unavailable"
    retryable = True


class MemoryRejected(MemoryBackendError):
    """The backend refused the request (authentication, validation). Retrying the same request will not help."""

    error_class = "memory_rejected"


class MemoryNotFound(MemoryRejected):
    """The session or message does not exist (yet). Reading it means "no memory"; it is not an outage."""

    error_class = "memory_not_found"


class MemoryPolicyError(ValueError):
    """A memory record violates the session policy or the leakage rules; it is never sent."""


# --- sessions --------------------------------------------------------------------------------------------------------------

GLOBAL_TEACHINGS = "global:teachings"
TEAM_EDITORS = "team:editors"
FIXED_SESSIONS = (GLOBAL_TEACHINGS, TEAM_EDITORS)
SUBJECT_KINDS = ("editor", "video-type", "workflow", "client", "result")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _subject_id(value: str) -> str:
    if not isinstance(value, str):
        raise MemoryPolicyError("a session subject ID must be a string")
    text = unicodedata.normalize("NFC", value).strip()
    if not text or len(text) > MAX_ID or _CONTROL.search(text):
        raise MemoryPolicyError(f"invalid session subject ID {value!r}")
    return text


def session_key(kind: str, subject_id: str | None = None) -> str:
    """The logical session key for a subject: ``editor:<id>``, ``result:<id>``, … or one of the fixed sessions."""
    if subject_id is None:
        key = f"{kind}"
        if key not in FIXED_SESSIONS:
            raise MemoryPolicyError(f"unknown session {key!r}")
        return key
    if kind not in SUBJECT_KINDS:
        raise MemoryPolicyError(f"unknown session kind {kind!r}")
    return f"{kind}:{_subject_id(subject_id)}"


def editor_session(editor_id: str) -> str:
    return session_key("editor", editor_id)


def video_type_session(video_type_key: str) -> str:
    return session_key("video-type", video_type_key)


def result_session(result_id: str) -> str:
    return session_key("result", result_id)


def parse_session(key: str) -> tuple[str, str | None]:
    """``(kind, subject_id)`` of a valid logical key; ``MemoryPolicyError`` otherwise."""
    if key in FIXED_SESSIONS:
        return key, None
    kind, sep, subject = key.partition(":")
    if not sep or kind not in SUBJECT_KINDS or subject != _subject_id(subject):
        raise MemoryPolicyError(f"invalid session key {key!r}")
    return kind, subject


def session_kind(key: str) -> str:
    return parse_session(key)[0]


def honcho_session_id(key: str) -> str:
    """Honcho-safe session ID for a logical key (Honcho IDs allow only ``[A-Za-z0-9_-]``)."""
    kind = session_kind(key)
    slug = kind.replace(":", "-")
    return f"atlas-{slug}-{hashlib.sha256(key.encode()).hexdigest()[:24]}"


ATLAS_PEER = "atlas"
MANAGEMENT_PEER = "management"


def manager_peer(author: str | None) -> str:
    """A pseudonymous peer per management author: Honcho never receives the author's identity (an email address) itself."""
    if not author or not author.strip():
        return MANAGEMENT_PEER
    return "manager-" + hashlib.sha256(author.strip().casefold().encode()).hexdigest()[:16]


# Which sessions each source may be written to. Anything else is a wrong-session write and is refused.
SESSION_POLICY: Mapping[NoteSource, frozenset[str]] = {
    NoteSource.MANAGER_INTERPRETATION: frozenset({"result"}),
    NoteSource.ATLAS_QUESTION: frozenset({"result"}),
    NoteSource.MANAGER_ANSWER: frozenset({"result", "editor", "video-type"}),
    NoteSource.MANAGEMENT_TEACHING: frozenset({GLOBAL_TEACHINGS, "editor", "video-type", "workflow", "client", "result"}),
    NoteSource.PRIOR_REASONING_SUMMARY: frozenset({"result", "editor", "video-type", TEAM_EDITORS}),
}

# Sources written by Atlas itself; every other source is written by (a pseudonymous peer for) its management author.
ATLAS_SOURCES = frozenset({NoteSource.ATLAS_QUESTION, NoteSource.PRIOR_REASONING_SUMMARY})

# Metadata a record may carry besides its provenance. Values are short scalars; nothing else reaches the backend.
METADATA_KEYS = frozenset({"case_id", "result_id", "result_version", "question_id", "revision", "scope_type", "scope_id", "teaching_type",
                           "validity_mode", "valid_from", "valid_until", "expected_context_type", "conflicts_with"})


def _clean_body(body: str) -> str:
    if not isinstance(body, str):
        raise MemoryPolicyError("a memory body must be text")
    text = unicodedata.normalize("NFC", body).strip()
    if not text:
        raise MemoryPolicyError("a memory body must not be empty")
    if len(text) > MAX_BODY:
        raise MemoryPolicyError(f"a memory body is limited to {MAX_BODY} characters")
    if "\x00" in text:
        raise MemoryPolicyError("a memory body must not contain NUL characters")
    if text[0] in "[{":
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, (dict, list)):
            raise MemoryPolicyError("a memory body must be prose, not a JSON document (raw data is never uploaded)")
    return text


@dataclass(frozen=True)
class MemoryRecord:
    """One copy of canonical context to be written to one memory session."""

    source_type: NoteSource
    source_id: str
    session_key: str
    body: str
    author: str | None = None
    recorded_at: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def peer_id(self) -> str:
        return ATLAS_PEER if self.source_type in ATLAS_SOURCES else manager_peer(self.author)

    def provenance(self) -> dict[str, Any]:
        """Metadata stored with the copy: enough to trace it back to its canonical row, never the author's identity."""
        return {"atlas": MEMORY_VERSION, "source_type": self.source_type.value, "source_id": self.source_id, "session_key": self.session_key,
                "recorded_at": self.recorded_at, "content_sha256": self.content_sha256, **dict(sorted(self.metadata.items()))}

    @property
    def content_sha256(self) -> str:
        payload = {"source_type": self.source_type.value, "source_id": self.source_id, "session_key": self.session_key, "body": self.body,
                   "metadata": dict(self.metadata)}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def check_record(record: MemoryRecord) -> MemoryRecord:
    """The record, normalized, when it may be written; ``MemoryPolicyError`` otherwise (wrong session, raw data, bad metadata)."""
    try:
        source = NoteSource(record.source_type)
    except ValueError:
        raise MemoryPolicyError(f"unknown memory source type {record.source_type!r}") from None
    if not isinstance(record.source_id, str) or not record.source_id.strip() or len(record.source_id) > MAX_ID:
        raise MemoryPolicyError("a memory record needs the ID of its canonical source row")
    kind = session_kind(record.session_key)
    if kind not in SESSION_POLICY[source] and record.session_key not in SESSION_POLICY[source]:
        raise MemoryPolicyError(f"{source.value} may not be written to session {record.session_key!r}")
    unknown = set(record.metadata) - METADATA_KEYS
    if unknown:
        raise MemoryPolicyError(f"metadata keys not allowed in memory: {sorted(unknown)}")
    for key, value in record.metadata.items():
        if value is not None and not isinstance(value, (str, int, bool)):
            raise MemoryPolicyError(f"memory metadata {key} must be a scalar")
        if isinstance(value, str) and len(value) > MAX_ID:
            raise MemoryPolicyError(f"memory metadata {key} is too long")
    return MemoryRecord(source, record.source_id, record.session_key, _clean_body(record.body), record.author, record.recorded_at,
                        {key: value for key, value in record.metadata.items() if value is not None})


def summary_record(result: Mapping[str, Any], session: str) -> MemoryRecord:
    """A prior-reasoning memory built only from a result's management-facing summary (title, summary, confidence level).

    Evidence references, Monday IDs, metrics and claims are deliberately left out: the canonical result in PostgreSQL holds them."""
    body = f"{result['title']}\n{result['reasoning_summary']}\nConfidence: {result['confidence']['level']}."
    return MemoryRecord(NoteSource.PRIOR_REASONING_SUMMARY, result["result_id"], session, body,
                        recorded_at=result.get("updated_at"),
                        metadata={"case_id": result["case_id"], "result_id": result["result_id"], "result_version": result["version"]})


# --- backends --------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrievedMemory:
    """One memory item as a backend returned it. ``metadata`` is untrusted until checked against the canonical store."""

    memory_ref: str
    session_key: str
    body: str
    metadata: Mapping[str, Any]
    created_at: str | None = None

    @property
    def source_type(self) -> str | None:
        value = self.metadata.get("source_type")
        return value if isinstance(value, str) else None

    @property
    def source_id(self) -> str | None:
        value = self.metadata.get("source_id")
        return value if isinstance(value, str) else None


class MemoryBackend(Protocol):
    """What Atlas needs from a memory service. ``write`` returns the backend's reference for the stored copy."""

    name: str

    def write(self, record: MemoryRecord) -> str: ...

    def retire(self, session_key: str, memory_ref: str) -> None: ...

    def read(self, session_key: str, *, limit: int) -> Sequence[RetrievedMemory]: ...
