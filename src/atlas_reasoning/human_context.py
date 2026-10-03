"""Wiring of the human-context layer: canonical context sources for the assembler and the memory-sync resolvers.

Phases 12-14 each add one canonical source of management context (manager notes, management answers, teachings). This module is
the one place that lists them, so the context assembler (``REV/11``) and the sync retry (``REV/10``) always know every source.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from atlas_reasoning import atlas_questions, manager_notes, teach_atlas
from atlas_reasoning.enums import NoteSource
from atlas_reasoning.memory import MemoryBackend
from atlas_reasoning.memory_context import ContextSource, MemoryContextAssembler, budget_from_env
from atlas_reasoning.memory_sync import MemorySyncService
from atlas_reasoning.store.repository import ReasoningStore


def context_sources() -> list[ContextSource]:
    """Every canonical source of management context, in registration order."""
    return [manager_notes.NoteContextSource(), atlas_questions.AnswerContextSource(), teach_atlas.TeachingContextSource()]


def sync_service(store: ReasoningStore, backend: MemoryBackend | None, *, clock: Callable[[], datetime] | None = None) -> MemorySyncService:
    """A sync service able to rebuild every kind of memory copy from PostgreSQL. ``clock`` decides which teachings are in effect."""
    now = clock or (lambda: datetime.now(UTC))
    return MemorySyncService(store, backend, resolvers={NoteSource.MANAGER_INTERPRETATION: manager_notes.note_records,
                                                       NoteSource.ATLAS_QUESTION: atlas_questions.question_records,
                                                       NoteSource.MANAGER_ANSWER: atlas_questions.answer_records,
                                                       NoteSource.MANAGEMENT_TEACHING: lambda tx, source_id: teach_atlas.teaching_records(tx, source_id, now())})


def assembler(store: ReasoningStore, backend: MemoryBackend | None, env: Mapping[str, str] | None = None, **kwargs: Any) -> MemoryContextAssembler:
    return MemoryContextAssembler(store, backend, sources=context_sources(), budget=budget_from_env(env), **kwargs)
