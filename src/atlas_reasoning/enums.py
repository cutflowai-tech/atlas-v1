"""Strict enumerations shared by the Reasoning V3 contracts (``reasoning-v1``), the PostgreSQL schema and later phases.

Every value here is also an ``enum`` in ``contracts/reasoning-common-v1.schema.json`` and a ``CHECK`` constraint in
``store/migrations/0001_reasoning_core.sql``; ``tests/test_reasoning_contracts.py`` and ``tests/test_reasoning_store.py`` fail when
the three drift apart. Adding a value is a contract change (a new contract version or an approved compatible addition).
"""

from __future__ import annotations

from enum import StrEnum

CONTRACT_VERSION = "reasoning-v1"


class SubjectType(StrEnum):
    """What a case is about: one stable subject."""

    EDITOR = "editor"
    TEAM = "team"
    VIDEO_TYPE = "video_type"
    WORKFLOW_STAGE = "workflow_stage"
    PROJECT = "project"
    DATA_SOURCE = "data_source"


class CaseType(StrEnum):
    """The family of management issue; later phases key memory scope (Phase 11) and lifecycle policy (Phase 09) on it."""

    EDITOR_PATTERN = "editor_pattern"
    TEAM_PATTERN = "team_pattern"
    VIDEO_TYPE_PATTERN = "video_type_pattern"
    WORKFLOW_PATTERN = "workflow_pattern"
    OPEN_WORK_RISK = "open_work_risk"
    PROJECT_RISK = "project_risk"
    DATA_QUALITY = "data_quality"


class TopicKey(StrEnum):
    """The management topic of a case (``case_topics`` maps every Intelligence V2 finding type to one)."""

    DEADLINE = "deadline"
    SPEED = "speed"
    QUALITY = "quality"
    WORKLOAD = "workload"
    RUNWAY = "runway"
    POST_EDITOR_DELAY = "post_editor_delay"
    WORKFLOW_TIME = "workflow_time"
    COMPONENT_CONFLICT = "component_conflict"
    HIDDEN_SIGNAL = "hidden_signal"
    OPEN_WORK_RISK = "open_work_risk"
    DATA_QUALITY = "data_quality"


class IdentityDimension(StrEnum):
    """Optional case-identity dimensions, used only when a topic rule says they are part of the topic itself."""

    VIDEO_TYPE = "video_type"
    WORKFLOW_STAGE = "workflow_stage"
    DETECTOR_FAMILY = "detector_family"
    SIGNAL = "signal"


class Direction(StrEnum):
    """Intelligence V2 finding direction, and a case's orientation (never a score)."""

    ADVERSE = "adverse"
    FAVOURABLE = "favourable"
    MIXED = "mixed"
    NEUTRAL = "neutral"


class ConfidenceLevel(StrEnum):
    """Evidence strength, the Intelligence V2 scale (D53.11). A reasoning result's confidence uses the same scale and may never
    exceed the strongest upstream finding of its case."""

    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


CONFIDENCE_ORDER = (ConfidenceLevel.WEAK, ConfidenceLevel.MODERATE, ConfidenceLevel.STRONG)


class EvidenceLevel(StrEnum):
    """Intelligence V2 statement levels (``atlas_commander.investigation.models``)."""

    FACT = "fact"
    METRIC = "metric"
    PATTERN = "pattern"
    ASSOCIATION = "association"
    INTERPRETATION = "interpretation"
    HYPOTHESIS = "hypothesis"


class StatementKind(StrEnum):
    """The kind of value a statement carries (``reasoning_input_boundary.STATEMENT_KINDS``)."""

    SOURCE_FACT = "source_fact"
    DERIVED_VALUE = "deterministic_derived_value"
    UPSTREAM_INTERPRETATION = "upstream_interpretation"


class EvidenceRole(StrEnum):
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    CONTEXT = "context"


class LifecycleStatus(StrEnum):
    """Result lifecycle (Phase 09 owns the transitions; the LLM never decides them)."""

    NEW = "new"
    ACTIVE = "active"
    UPDATED = "updated"
    COOLING = "cooling"
    RESOLVED = "resolved"
    SUPERSEDED = "superseded"


OPEN_LIFECYCLE = (LifecycleStatus.NEW, LifecycleStatus.ACTIVE, LifecycleStatus.UPDATED, LifecycleStatus.COOLING)


class GateAction(StrEnum):
    """Change Gate decision for one case in one run (Phase 05)."""

    UNCHANGED = "unchanged"
    NEW = "new"
    UPDATED = "updated"
    DISAPPEARED = "disappeared"


class UpdateAction(StrEnum):
    """What a ReasoningUpdate does to the result it targets."""

    PATCH = "patch"
    NO_CHANGE = "no_change"


class NoteSource(StrEnum):
    """Provenance of management context and memory items. Never deterministic evidence."""

    MANAGER_INTERPRETATION = "manager_interpretation"
    MANAGER_ANSWER = "manager_answer"
    MANAGEMENT_TEACHING = "management_teaching"
    ATLAS_QUESTION = "atlas_question"
    PRIOR_REASONING_SUMMARY = "prior_reasoning_summary"


class QuestionState(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    DISMISSED = "dismissed"
    SUPERSEDED = "superseded"


class ExpectedContextType(StrEnum):
    """What kind of management context a question asks for (Phase 13)."""

    BUSINESS_RULE = "business_rule"
    WORKFLOW_CONTEXT = "workflow_context"
    ASSIGNMENT_CONTEXT = "assignment_context"
    CLIENT_CONTEXT = "client_context"
    TEMPORARY_SITUATION = "temporary_situation"
    DATA_CORRECTION = "data_correction"
    OTHER = "other"


class MemoryStatus(StrEnum):
    """Whether contextual memory was supplied to a case (Phase 11 marks degraded calls)."""

    NOT_REQUESTED = "not_requested"
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class TeachingScope(StrEnum):
    COMPANY = "company"
    EDITOR = "editor"
    VIDEO_TYPE = "video_type"
    WORKFLOW = "workflow"
    CLIENT = "client"
    SPECIFIC_RESULT = "specific_result"


class TeachingType(StrEnum):
    BUSINESS_RULE = "business_rule"
    CONTEXT = "context"
    CORRECTION = "correction"
    INTERPRETATION = "interpretation"
    TEMPORARY_SITUATION = "temporary_situation"


class TeachingValidity(StrEnum):
    UNTIL_CHANGED = "until_changed"
    DATE_RANGE = "date_range"
    CURRENT_PERIOD = "current_period"


class TeachingStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class RunStatus(StrEnum):
    """A reasoning run: ``started`` → ``gated`` (Change Gate persisted) → a final status (Phase 18 adds partial / degraded)."""

    STARTED = "started"
    GATED = "gated"
    COMPLETE = "complete"
    PARTIAL = "partial"
    DEGRADED = "degraded"
    FAILED = "failed"


class WorkKind(StrEnum):
    """Work the Change Gate hands to later phases. Only ``new_result`` and ``update_result`` may involve an LLM call."""

    NEW_RESULT = "new_result"
    UPDATE_RESULT = "update_result"
    LIFECYCLE = "lifecycle"


LLM_WORK = (WorkKind.NEW_RESULT, WorkKind.UPDATE_RESULT)


class WorkStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    SUPERSEDED = "superseded"


OPEN_WORK = (WorkStatus.PENDING, WorkStatus.IN_PROGRESS)


class ResultChangeKind(StrEnum):
    """Why a result version exists."""

    CREATED = "created"
    PATCHED = "patched"
    NO_CHANGE_REVIEW = "no_change_review"
    LIFECYCLE = "lifecycle"


class LLMCallStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class MemorySyncStatus(StrEnum):
    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"
    SKIPPED = "skipped"
