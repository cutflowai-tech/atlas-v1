"""An in-memory ``MemoryBackend`` for tests and offline development (``REV/10``): no network, no credentials.

It applies the same write policy as the real client (``memory.check_record``), can be switched into an outage (every call raises
``MemoryUnavailable``) or a rejection, and counts calls so tests can prove what was and was not sent.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from atlas_reasoning.memory import MemoryBackendError, MemoryRecord, MemoryUnavailable, RetrievedMemory, check_record


@dataclass
class StoredMessage:
    memory_ref: str
    record: MemoryRecord
    metadata: dict[str, Any]
    retired: bool = False


@dataclass
class FakeHoncho:
    name: str = "fake-honcho"
    failure: MemoryBackendError | None = None
    sessions: dict[str, list[StoredMessage]] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    _ids: Any = field(default_factory=lambda: itertools.count(1))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def outage(self, error: MemoryBackendError | None = None) -> None:
        self.failure = error or MemoryUnavailable("simulated Honcho outage")

    def restore(self) -> None:
        self.failure = None

    def _check(self, operation: str, session_key: str) -> None:
        with self._lock:
            self.calls.append((operation, session_key))
        if self.failure is not None:
            raise self.failure

    def write(self, record: MemoryRecord) -> str:
        record = check_record(record)
        self._check("write", record.session_key)
        with self._lock:
            ref = f"msg_{next(self._ids):06d}"
            self.sessions.setdefault(record.session_key, []).append(StoredMessage(ref, record, record.provenance()))
        return ref

    def retire(self, session_key: str, memory_ref: str) -> None:
        self._check("retire", session_key)
        with self._lock:
            for message in self.sessions.get(session_key, []):
                if message.memory_ref == memory_ref:
                    message.retired = True

    def read(self, session_key: str, *, limit: int) -> Sequence[RetrievedMemory]:
        self._check("read", session_key)
        with self._lock:
            live = [message for message in self.sessions.get(session_key, []) if not message.retired]
        return [RetrievedMemory(m.memory_ref, session_key, m.record.body, dict(m.metadata), m.record.recorded_at) for m in reversed(live)][:limit]

    def messages(self, session_key: str | None = None) -> list[StoredMessage]:
        with self._lock:
            if session_key is not None:
                return list(self.sessions.get(session_key, []))
            return [message for rows in self.sessions.values() for message in rows]
