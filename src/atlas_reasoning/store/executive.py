"""Data access for the executive brief (``REV/17`` #2, #7, #8; migration ``0500_executive_briefs.sql``). All executive SQL lives here.

    store = ExecutiveStore(reasoning_store)
    with store.transaction() as tx:
        rows = tx.canonical_results(run_id)            # the only executive input source: canonical current result versions
        current = tx.current_brief("company")
        tx.append_brief(brief, expected_version=current.version if current else None)   # VersionConflict on a race
        tx.record_run(run_id=..., decision=..., ...)
    store.current_brief(); store.brief_history(); store.synthesis_runs(run_id)

Guarantees, enforced here and again by the database:

- the input is read from ``reasoning_results`` joined to their **current** version only, with lifecycle ``new`` / ``active`` /
  ``updated``, or ``resolved`` by a lifecycle transition in one of the run's ``resolved_lookback_runs`` most recent runs. A refused
  Phase 15 candidate (``reasoning_failed_candidates``) is never a result, so it can never be selected;
- a new brief version is appended only on top of the version the writer read (optimistic concurrency: ``VersionConflict``), so a
  concurrent writer can never lose or duplicate a version and a failed synthesis never touches the current one;
- every version stores its input rows and every statement's result references; foreign keys tie a reference to its version's input
  and an input row to an existing canonical result version;
- versions, inputs, references and run records are append-only.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from typing import Any

from atlas_reasoning.contracts import ReasoningResult
from atlas_reasoning.enums import LifecycleStatus
from atlas_reasoning.executive import POLICY_VERSION, RESOLVED_LOOKBACK_RUNS, CanonicalResult, Decision
from atlas_reasoning.executive_contracts import COMPANY_SCOPE, SECTIONS, ExecutiveBrief
from atlas_reasoning.executive_validator import ReferenceIndex
from atlas_reasoning.store.repository import NotFound, ReasoningStore, VersionConflict

MAX_STORED_CANDIDATE = 256 * 1024
_OPEN_ELIGIBLE = (LifecycleStatus.NEW.value, LifecycleStatus.ACTIVE.value, LifecycleStatus.UPDATED.value)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _unique_violation() -> type[Exception]:
    import psycopg

    error: type[Exception] = psycopg.errors.UniqueViolation
    return error


class ExecutiveTransaction:
    """Executive reads and writes inside one database transaction."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def _all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return list(self.conn.execute(sql, list(params) if params else None).fetchall())

    def _one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        row: dict[str, Any] | None = self.conn.execute(sql, list(params) if params else None).fetchone()
        return row

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self._one("SELECT * FROM reasoning_runs WHERE run_id = %s", (run_id,))
        if row is None:
            raise NotFound(f"run {run_id} does not exist")
        return row

    # --- input ----------------------------------------------------------------------------------------------------------------

    def recent_runs(self, run_id: str, count: int) -> list[str]:
        """``run_id`` and the runs started before it, newest first, ``count`` in all."""
        rows = self._all("""SELECT run_id FROM reasoning_runs
                            WHERE (started_at, run_id) <= (SELECT started_at, run_id FROM reasoning_runs WHERE run_id = %s)
                            ORDER BY started_at DESC, run_id DESC LIMIT %s""", (run_id, max(1, count)))
        return [row["run_id"] for row in rows]

    def canonical_results(self, run_id: str, *, resolved_lookback_runs: int = RESOLVED_LOOKBACK_RUNS) -> list[CanonicalResult]:
        """Every eligible canonical result (current version) for a brief synthesized for ``run_id``. Unordered: the input builder
        orders it."""
        recent = self.recent_runs(run_id, resolved_lookback_runs)
        rows = self._all("""
            SELECT r.result_id, r.current_version, r.lifecycle_status, v.document, c.case_type, c.subject_type, c.subject_id, c.topic_key,
                   c.video_type, c.workflow_stage, c.detector_family, c.signal, e.case_document -> 'orientation' AS orientation,
                   e.case_document -> 'scope' -> 'affected_editor_ids' AS affected_editor_ids
            FROM reasoning_results r
            JOIN reasoning_result_versions v ON v.result_id = r.result_id AND v.version = r.current_version
            JOIN reasoning_cases c ON c.case_id = r.case_id
            JOIN reasoning_case_evidence e ON e.case_id = r.case_id AND e.evidence_fingerprint = v.evidence_fingerprint
            WHERE r.lifecycle_status = ANY(%s)
               OR (r.lifecycle_status = 'resolved' AND EXISTS (
                       SELECT 1 FROM reasoning_lifecycle_transitions t
                       WHERE t.result_id = r.result_id AND t.result_version = r.current_version AND t.to_status = 'resolved' AND t.run_id = ANY(%s)))
            """, (list(_OPEN_ELIGIBLE), recent))
        if not rows:
            return []
        ids = [row["result_id"] for row in rows]
        reasons = {row["result_id"]: row["reason_code"] for row in self._all("""
            SELECT DISTINCT ON (t.result_id) t.result_id, t.reason_code
            FROM reasoning_lifecycle_transitions t JOIN reasoning_results r ON r.result_id = t.result_id
            WHERE t.result_id = ANY(%s) AND t.to_status = r.lifecycle_status
            ORDER BY t.result_id, t.result_version DESC, t.created_at DESC""", (ids,))}
        patched = {row["result_id"]: tuple(change["field"] for change in (row["update_document"] or {}).get("changed_fields") or [])
                   for row in self._all("""SELECT DISTINCT ON (result_id) result_id, update_document FROM reasoning_result_versions
                                           WHERE result_id = ANY(%s) AND change_kind = 'patched' ORDER BY result_id, version DESC""", (ids,))}
        questions: dict[str, list[tuple[str, str]]] = {}
        for row in self._all("""SELECT result_id, question_text, expected_context_type FROM atlas_questions
                                WHERE result_id = ANY(%s) AND state = 'open'""", (ids,)):
            questions.setdefault(row["result_id"], []).append((row["question_text"], row["expected_context_type"]))
        found = []
        for row in rows:
            dimensions = {name: row[name] for name in ("video_type", "workflow_stage", "detector_family", "signal") if row[name] is not None}
            found.append(CanonicalResult(
                result=ReasoningResult.from_dict(row["document"]), lifecycle_status=LifecycleStatus(row["lifecycle_status"]),
                current_version=row["current_version"], case_type=row["case_type"], subject_type=row["subject_type"], subject_id=row["subject_id"],
                topic_key=row["topic_key"], dimensions=dimensions,
                orientation=str(row["orientation"]) if row["orientation"] is not None else "neutral",
                affected_editor_ids=tuple(str(editor) for editor in row["affected_editor_ids"] or ()), lifecycle_reason=reasons.get(row["result_id"]),
                patched_fields=patched.get(row["result_id"], ()), open_questions=tuple(questions.get(row["result_id"], ()))))
        return found

    def classify_references(self, references: Iterable[str]) -> ReferenceIndex:
        """Which of ``references`` (outside the synthesis input) are canonical results and which are refused Phase 15 candidates."""
        ids = sorted({ref for ref in references if isinstance(ref, str)})
        if not ids:
            return ReferenceIndex()
        canonical = {row["result_id"] for row in self._all("SELECT result_id FROM reasoning_results WHERE result_id = ANY(%s)", (ids,))}
        failed = {value for row in self._all("""SELECT candidate_id, result_id FROM reasoning_failed_candidates
                                                 WHERE candidate_id = ANY(%s) OR result_id = ANY(%s)""", (ids, ids))
                  for value in (row["candidate_id"], row["result_id"]) if value in ids}
        return ReferenceIndex(frozenset(canonical), frozenset(failed - canonical))

    # --- briefs ---------------------------------------------------------------------------------------------------------------

    def current_brief(self, scope: str = COMPANY_SCOPE) -> ExecutiveBrief | None:
        row = self._one("""SELECT v.document FROM executive_briefs b JOIN executive_brief_versions v
                           ON v.brief_id = b.brief_id AND v.version = b.current_version WHERE b.scope = %s""", (scope,))
        return ExecutiveBrief.from_dict(row["document"]) if row else None

    def get_brief(self, brief_id: str, version: int) -> ExecutiveBrief:
        row = self._one("SELECT document FROM executive_brief_versions WHERE brief_id = %s AND version = %s", (brief_id, version))
        if row is None:
            raise NotFound(f"executive brief {brief_id} has no version {version}")
        return ExecutiveBrief.from_dict(row["document"])

    def brief_history(self, scope: str = COMPANY_SCOPE) -> list[ExecutiveBrief]:
        rows = self._all("""SELECT v.document FROM executive_brief_versions v JOIN executive_briefs b ON b.brief_id = v.brief_id
                            WHERE b.scope = %s ORDER BY v.version""", (scope,))
        return [ExecutiveBrief.from_dict(row["document"]) for row in rows]

    def statement_refs(self, brief_id: str, version: int) -> list[dict[str, Any]]:
        return self._all("""SELECT section, statement_id, result_id FROM executive_statement_refs WHERE brief_id = %s AND version = %s
                            ORDER BY statement_id, result_id""", (brief_id, version))

    def brief_inputs(self, brief_id: str, version: int) -> list[dict[str, Any]]:
        return self._all("""SELECT result_id, result_version, lifecycle_status, position FROM executive_brief_inputs
                            WHERE brief_id = %s AND version = %s ORDER BY position""", (brief_id, version))

    def append_brief(self, brief: ExecutiveBrief, *, expected_version: int | None) -> None:
        """Make ``brief`` the current version on top of ``expected_version`` (``None``: the scope has no brief yet). ``VersionConflict``
        when another writer moved the brief first; the caller's transaction then rolls back completely."""
        document = ExecutiveBrief.from_dict(brief.to_dict()).to_dict()    # validated again: never persist an invalid document
        if (expected_version is None) != (brief.version == 1) or (expected_version is not None and brief.version != expected_version + 1):
            raise VersionConflict(f"brief version {brief.version} does not follow {expected_version}")
        try:
            if expected_version is None:
                self.conn.execute("""INSERT INTO executive_briefs (brief_id, scope, current_version) VALUES (%s, %s, 1)""", (brief.brief_id, brief.scope))
            else:
                moved = self.conn.execute("""UPDATE executive_briefs SET current_version = %s, updated_at = now()
                                             WHERE brief_id = %s AND scope = %s AND current_version = %s""",
                                          (brief.version, brief.brief_id, brief.scope, expected_version))
                if moved.rowcount != 1:
                    raise VersionConflict(f"executive brief {brief.brief_id} is no longer at version {expected_version}")
            generator = brief.generator
            self.conn.execute("""INSERT INTO executive_brief_versions (brief_id, version, run_id, input_version, input_fingerprint, generator, provider,
                                                                       model, prompt_version, validator_version, document, created_at)
                                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)""",
                              (brief.brief_id, brief.version, brief.run_id, brief.input_version, brief.input_fingerprint, generator.kind, generator.provider,
                               generator.model, brief.prompt_version, brief.validator_version, _json(document), brief.created_at))
            for position, row in enumerate(brief.input_results, start=1):
                self.conn.execute("""INSERT INTO executive_brief_inputs (brief_id, version, result_id, result_version, lifecycle_status, position)
                                     VALUES (%s, %s, %s, %s, %s, %s)""",
                                  (brief.brief_id, brief.version, row.result_id, row.result_version, row.lifecycle_status.value, position))
            for section in SECTIONS:
                for statement in getattr(brief.sections, section):
                    for result_id in statement.result_ids:
                        self.conn.execute("""INSERT INTO executive_statement_refs (brief_id, version, section, statement_id, result_id)
                                             VALUES (%s, %s, %s, %s, %s)""", (brief.brief_id, brief.version, section, statement.statement_id, result_id))
        except _unique_violation() as error:
            raise VersionConflict(f"executive brief {brief.brief_id} version {brief.version} already exists or its scope has another brief") from error

    # --- runs -----------------------------------------------------------------------------------------------------------------

    def record_run(self, *, run_id: str, decision: Decision, input_fingerprint: str | None, brief_id: str | None, brief_version: int | None,
                   llm_calls: int = 0, failure: str | None = None, error_codes: Sequence[str] = (), violations: Sequence[Mapping[str, Any]] = (),
                   rejected_candidate: Mapping[str, Any] | None = None, candidate_omitted: str | None = None, model: str | None = None,
                   prompt_version: str | None = None, request_ids: Sequence[str] = (), scope: str = COMPANY_SCOPE) -> str:
        """Audit one synthesis run. A refused candidate is stored for debugging only (never as a version); larger than
        ``MAX_STORED_CANDIDATE`` bytes it is omitted and only its violations are kept."""
        synthesis_id = f"xs_{uuid.uuid4().hex}"
        stored, omitted = None, candidate_omitted
        if rejected_candidate is not None:
            text = _json(rejected_candidate).replace("\\u0000", "\\ufffd")     # jsonb refuses NUL; the debugging copy keeps a marker
            if len(text.encode()) > MAX_STORED_CANDIDATE:
                omitted = f"candidate larger than {MAX_STORED_CANDIDATE} bytes"
            else:
                stored = text
        self.conn.execute("""INSERT INTO executive_brief_runs (synthesis_id, run_id, scope, decision, policy_version, input_fingerprint, brief_id,
                                                               brief_version, llm_calls, failure, error_codes, violations, rejected_candidate,
                                                               candidate_omitted, model, prompt_version, request_ids)
                             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)""",
                          (synthesis_id, run_id, scope, decision.value, POLICY_VERSION, input_fingerprint, brief_id, brief_version, llm_calls, failure,
                           list(error_codes), _json([dict(row) for row in violations]), stored, omitted, model, prompt_version, list(request_ids)))
        return synthesis_id

    def synthesis_runs(self, run_id: str | None = None) -> list[dict[str, Any]]:
        if run_id is None:
            return self._all("SELECT * FROM executive_brief_runs ORDER BY created_at, synthesis_id")
        return self._all("SELECT * FROM executive_brief_runs WHERE run_id = %s ORDER BY created_at, synthesis_id", (run_id,))


class ExecutiveStore:
    """The executive brief in the canonical Reasoning V3 database (built on ``ReasoningStore``'s database and session lock)."""

    def __init__(self, store: ReasoningStore) -> None:
        self.reasoning = store

    @contextmanager
    def transaction(self) -> Iterator[ExecutiveTransaction]:
        with self.reasoning.db.transaction() as conn:
            yield ExecutiveTransaction(conn)

    @contextmanager
    def snapshot(self) -> Iterator[ExecutiveTransaction]:
        """A read-only REPEATABLE READ transaction: every query sees the same committed state (the synthesis input never mixes a
        result row with lifecycle reasons, patches or questions from a later commit of a concurrent engine)."""
        with self.reasoning.db.transaction() as conn:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            yield ExecutiveTransaction(conn)

    def session_lock(self, key: int) -> AbstractContextManager[bool]:
        return self.reasoning.session_lock(key)

    def current_brief(self, scope: str = COMPANY_SCOPE) -> ExecutiveBrief | None:
        with self.transaction() as tx:
            return tx.current_brief(scope)

    def brief_history(self, scope: str = COMPANY_SCOPE) -> list[ExecutiveBrief]:
        with self.transaction() as tx:
            return tx.brief_history(scope)

    def synthesis_runs(self, run_id: str | None = None) -> list[dict[str, Any]]:
        with self.transaction() as tx:
            return tx.synthesis_runs(run_id)
