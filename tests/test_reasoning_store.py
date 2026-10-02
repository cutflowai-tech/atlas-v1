"""Reasoning V3 Phase 03: canonical reasoning state in PostgreSQL is durable, versioned and cannot be partially corrupted (``REV/03``)."""

import copy
import json
import os
import re
import subprocess
import sys
import threading
import unittest
from pathlib import Path

import psycopg
import reasoning_factory as factory
from reasoning_db import TEST_DB_ENV, fresh_database, requires_db, test_database_url

from atlas_reasoning import enums
from atlas_reasoning.contracts import ContractViolation, ReasoningResult, ReasoningUpdate
from atlas_reasoning.enums import GateAction, ResultChangeKind, RunStatus, WorkKind, WorkStatus
from atlas_reasoning.store.db import Database, DatabaseError, redact_url
from atlas_reasoning.store.health import REQUIRED_TABLES, database_health
from atlas_reasoning.store.migrate import MigrationError, apply_migrations, available_migrations
from atlas_reasoning.store.repository import (
    CaseIdentityCollision,
    EvidenceCollision,
    ReasoningStore,
    ResultConflict,
    VersionConflict,
    WorkTransitionError,
    citations,
)

ROOT = Path(__file__).resolve().parents[1]
LATER = "2026-09-29T00:05:00Z"
CANONICAL = {"evidence_schema": "test", "findings": {"a": 1}}


def seed(store: ReasoningStore, case: dict | None = None) -> tuple[str, dict]:
    """A run, a case and its evidence state; returns (run_id, case document)."""
    case = case or factory.case_dict()
    with store.transaction() as tx:
        run_id = tx.create_run(source_snapshot_id=case["source_snapshot_id"], release_id="release-1", upstream_contract_version="1.5.0",
                               intelligence_version="intelligence-v2.0.0", boundary_version="reasoning-input-v1", identity_version="case-identity-v1",
                               fingerprint_version="evidence-fingerprint-v1")
        tx.insert_case(case_id=case["case_id"], identity_version=case["identity_version"], identity_key=case["identity_key"], case_type=case["case_type"],
                       subject_type=case["subject_type"], subject_id=case["subject_id"], topic_key=case["topic_key"], dimensions=case["identity_dimensions"],
                       run_id=run_id, evidence_fingerprint=case["evidence_fingerprint"])
        tx.put_case_evidence(case_id=case["case_id"], evidence_fingerprint=case["evidence_fingerprint"], fingerprint_version="evidence-fingerprint-v1",
                             canonical_evidence=CANONICAL, case_document=case, run_id=run_id)
    return run_id, case


def patched(result: dict, update: dict) -> ReasoningResult:
    document = copy.deepcopy(result)
    for row in update["changed_fields"]:
        document[row["field"]] = row["value"]
    document.update(version=result["version"] + 1, updated_at=LATER)
    return ReasoningResult.from_dict(document)


class ConfigTests(unittest.TestCase):
    def test_password_never_appears_in_display_or_errors(self):
        url = "postgresql://atlas:s3cr3t-pw@127.0.0.1:1/atlas_reasoning_test"
        self.assertNotIn("s3cr3t-pw", redact_url(url))
        self.assertNotIn("s3cr3t-pw", repr(Database(url)))
        with self.assertRaises(DatabaseError) as caught:
            Database(url, connect_timeout=1).connect()
        self.assertNotIn("s3cr3t-pw", str(caught.exception))

    def test_sql_and_the_driver_stay_inside_the_store(self):
        offenders = []
        for path in (ROOT / "src").rglob("*.py"):
            if "atlas_reasoning/store" in path.as_posix():
                continue
            text = path.read_text()
            if re.search(r"^\s*(import psycopg|from psycopg)", text, re.MULTILINE) or re.search(r"\b(INSERT INTO|SELECT \*|UPDATE reasoning_|DELETE FROM)\b", text):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_every_form_of_database_password_is_redacted(self):
        for url in ("postgresql://atlas:s3cr3t-pw@db:5432/x", "postgresql://atlas@db/x?password=s3cr3t-pw&sslmode=require",
                    "postgresql://atlas:p@s3cr3t-pw@db/x", "postgres://:s3cr3t-pw@db/x"):
            with self.subTest(url=url):
                shown = redact_url(url)
                self.assertNotIn("s3cr3t-pw", shown)
                self.assertNotIn("s3cr3t", shown)
        self.assertEqual(redact_url("postgresql://atlas@127.0.0.1:5432/atlas_reasoning"), "postgresql://atlas@127.0.0.1:5432/atlas_reasoning")

    def test_migration_files_are_numbered_and_in_the_foundation_range(self):
        migrations = available_migrations()
        self.assertEqual([m.name for m in migrations][:1], ["0001_reasoning_core.sql"])
        for migration in migrations:
            self.assertRegex(migration.name, r"^\d{4}_[a-z0-9_]+\.sql$")


@requires_db
class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.db = fresh_database()

    def test_every_required_table_exists_and_health_is_ok(self):
        report = database_health(self.db)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["missing_tables"], [])
        for name in ("reasoning_runs", "reasoning_cases", "reasoning_results", "reasoning_result_versions", "reasoning_evidence_links", "manager_notes",
                     "atlas_questions", "atlas_answers", "teachings", "llm_calls", "memory_sync_log"):
            self.assertIn(name, REQUIRED_TABLES)

    def test_migrations_are_repeatable(self):
        self.assertEqual(apply_migrations(self.db), [])
        self.assertEqual(apply_migrations(self.db), [])
        self.assertTrue(database_health(self.db)["ok"])

    def test_a_changed_applied_migration_is_refused(self):
        with self.db.transaction() as conn:
            conn.execute("UPDATE schema_migrations SET checksum = %s", ("0" * 64,))
        with self.assertRaises(MigrationError):
            apply_migrations(self.db)
        report = database_health(self.db)
        self.assertFalse(report["ok"])
        self.assertTrue(report["problems"])

    def test_concurrent_bootstraps_apply_each_migration_once(self):
        with self.db.transaction() as conn:
            conn.execute("DROP SCHEMA atlas_reasoning CASCADE")
        results, errors = [], []

        def run():
            try:
                results.append(apply_migrations(self.db))
            except Exception as error:  # noqa: BLE001
                errors.append(error)

        threads = [threading.Thread(target=run) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        applied = [name for r in results for name in r]   # the complete set (every branch's migrations), each exactly once
        self.assertEqual(sorted(applied), [migration.name for migration in available_migrations()])
        self.assertEqual(sorted(len(r) for r in results), [0, 0, 0, len(available_migrations())])   # by one bootstrap
        self.assertTrue(database_health(self.db)["ok"])

    def test_status_constraints_mirror_the_enums(self):
        expected = {("reasoning_runs", "status"): enums.RunStatus, ("reasoning_cases", "case_type"): enums.CaseType,
                    ("reasoning_cases", "subject_type"): enums.SubjectType, ("reasoning_cases", "topic_key"): enums.TopicKey,
                    ("reasoning_results", "lifecycle_status"): enums.LifecycleStatus, ("reasoning_result_versions", "lifecycle_status"): enums.LifecycleStatus,
                    ("reasoning_result_versions", "change_kind"): enums.ResultChangeKind, ("reasoning_case_observations", "action"): enums.GateAction,
                    ("reasoning_work_items", "kind"): enums.WorkKind, ("reasoning_work_items", "status"): enums.WorkStatus,
                    ("reasoning_evidence_links", "role"): enums.EvidenceRole, ("atlas_questions", "state"): enums.QuestionState,
                    ("atlas_questions", "expected_context_type"): enums.ExpectedContextType, ("teachings", "scope_type"): enums.TeachingScope,
                    ("teachings", "teaching_type"): enums.TeachingType, ("teachings", "validity_mode"): enums.TeachingValidity,
                    ("teachings", "status"): enums.TeachingStatus, ("llm_calls", "status"): enums.LLMCallStatus,
                    ("memory_sync_log", "status"): enums.MemorySyncStatus, ("memory_sync_log", "source_type"): enums.NoteSource}
        with self.db.transaction() as conn:
            rows = conn.execute("""SELECT t.relname AS table_name, pg_get_constraintdef(c.oid) AS definition FROM pg_constraint c
                                   JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace
                                   WHERE n.nspname = 'atlas_reasoning' AND c.contype = 'c'""").fetchall()
        for (table, column), enum in expected.items():
            with self.subTest(table=table, column=column):
                definitions = [row["definition"] for row in rows if row["table_name"] == table and re.match(rf"CHECK \(\({column} = ANY", row["definition"])]
                self.assertEqual(len(definitions), 1, definitions)
                self.assertEqual(set(re.findall(r"'([a-z_]+)'::text", definitions[0])), {member.value for member in enum})


@requires_db
class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.run_id, self.case = seed(self.store)
        self.result = ReasoningResult.from_dict(factory.result_dict(self.case))
        with self.store.transaction() as tx:
            tx.create_result(self.result, run_id=self.run_id)

    def _fails(self, sql: str, params: tuple = ()) -> None:
        with self.assertRaises(Exception) as caught, self.store.db.transaction() as conn:
            conn.execute(sql, params)
        self.assertIn(type(caught.exception).__module__.split(".")[0], ("psycopg",))

    def test_foreign_keys(self):
        self._fails("INSERT INTO reasoning_case_observations (run_id, case_id, action, reason_code, evidence_fingerprint) VALUES ('run_' || repeat('0', 32), %s, 'new', 'x', %s)",
                    (self.case["case_id"], self.case["evidence_fingerprint"]))
        self._fails("INSERT INTO reasoning_case_observations (run_id, case_id, action, reason_code, evidence_fingerprint) VALUES (%s, %s, 'new', 'x', %s)",
                    (self.run_id, self.case["case_id"], "ef1_" + "9" * 64))
        self._fails("INSERT INTO reasoning_results (result_id, case_id, current_version, lifecycle_status) VALUES ('rr1_' || repeat('b', 32), 'rc1_' || repeat('9', 32), 1, 'new')")
        self._fails("INSERT INTO atlas_answers (answer_id, question_id, body) VALUES ('a1', 'missing', 'x')")
        self._fails("INSERT INTO manager_notes (note_id, result_id, case_id, body) VALUES ('n1', %s, 'rc1_' || repeat('9', 32), 'x')", (self.result.result_id,))
        self._fails("""INSERT INTO reasoning_work_items (work_item_id, run_id, case_id, kind, gate_action, status, requires_llm, fingerprint_after)
                       VALUES ('wi_' || repeat('1', 32), %s, %s, 'new_result', 'new', 'pending', true, 'ef1_' || repeat('7', 64))""",
                    (self.run_id, self.case["case_id"]))

    def test_a_result_without_its_current_version_cannot_be_committed(self):
        self._fails("INSERT INTO reasoning_results (result_id, case_id, current_version, lifecycle_status) VALUES ('rr1_' || repeat('c', 32), %s, 1, 'resolved')",
                    (self.case["case_id"],))

    def test_a_note_belongs_to_its_results_case(self):
        with self.store.db.transaction() as conn:
            conn.execute("INSERT INTO manager_notes (note_id, result_id, case_id, body, author) VALUES ('n1', %s, %s, 'Context.', 'manager')",
                         (self.result.result_id, self.case["case_id"]))
        self._fails("INSERT INTO manager_notes (note_id, result_id, case_id, body, source_type) VALUES ('n2', %s, %s, 'x', 'manager_answer')",
                    (self.result.result_id, self.case["case_id"]))

    def test_uniqueness(self):
        with self.assertRaises(ResultConflict), self.store.transaction() as tx:
            tx.create_result(ReasoningResult.from_dict({**factory.result_dict(self.case), "result_id": "rr1_" + "d" * 32}))
        self._fails("INSERT INTO reasoning_results (result_id, case_id, current_version, lifecycle_status) VALUES ('rr1_' || repeat('e', 32), %s, 1, 'active')",
                    (self.case["case_id"],))
        with self.store.db.transaction() as conn:
            conn.execute("""INSERT INTO atlas_questions (question_id, case_id, dedup_key, question_text, reason, expected_context_type, state)
                            VALUES ('q1', %s, 'runway', 'Why?', 'Missing context.', 'workflow_context', 'open')""", (self.case["case_id"],))
            conn.execute("""INSERT INTO atlas_questions (question_id, case_id, dedup_key, question_text, reason, expected_context_type, state, resolved_at)
                            VALUES ('q0', %s, 'runway', 'Why?', 'Missing context.', 'workflow_context', 'answered', now())""", (self.case["case_id"],))
        self._fails("""INSERT INTO atlas_questions (question_id, case_id, dedup_key, question_text, reason, expected_context_type, state)
                       VALUES ('q2', %s, 'runway', 'Why again?', 'Missing context.', 'workflow_context', 'open')""", (self.case["case_id"],))
        with self.store.transaction() as tx:
            tx.record_llm_call(request_id="req-1", provider="fake", model="m", purpose="test", status="succeeded", attempts=1, latency_ms=5,
                               started_at="2026-09-28T00:00:00Z", finished_at="2026-09-28T00:00:01Z")
        with self.assertRaises(psycopg.errors.UniqueViolation), self.store.transaction() as tx:
            tx.record_llm_call(request_id="req-1", provider="fake", model="m", purpose="test", status="succeeded", attempts=1, latency_ms=5,
                               started_at="2026-09-28T00:00:00Z", finished_at="2026-09-28T00:00:01Z")
        row = ("manager_interpretation", "n1", "result:x", "write", "a" * 64, "pending")
        with self.store.db.transaction() as conn:
            conn.execute("INSERT INTO memory_sync_log (sync_id, source_type, source_id, session_key, operation, content_sha256, status) VALUES ('s1', %s, %s, %s, %s, %s, %s)", row)
        self._fails("INSERT INTO memory_sync_log (sync_id, source_type, source_id, session_key, operation, content_sha256, status) VALUES ('s2', %s, %s, %s, %s, %s, %s)", row)

    def test_case_identity_collisions_are_refused(self):
        other = copy.deepcopy(self.case)
        other["case_id"] = "rc1_" + "1" * 32
        with self.assertRaises(CaseIdentityCollision):
            seed(self.store, other)
        other = copy.deepcopy(self.case)
        other["identity_key"] = "editor:other:deadline"
        with self.assertRaises(CaseIdentityCollision):
            seed(self.store, other)

    def test_the_same_fingerprint_cannot_hold_different_evidence(self):
        with self.store.transaction() as tx:
            self.assertFalse(tx.put_case_evidence(case_id=self.case["case_id"], evidence_fingerprint=self.case["evidence_fingerprint"],
                                                  fingerprint_version="evidence-fingerprint-v1", canonical_evidence=CANONICAL, case_document=self.case,
                                                  run_id=self.run_id))
        with self.assertRaises(EvidenceCollision), self.store.transaction() as tx:
            tx.put_case_evidence(case_id=self.case["case_id"], evidence_fingerprint=self.case["evidence_fingerprint"], fingerprint_version="evidence-fingerprint-v1",
                                 canonical_evidence={"other": True}, case_document=self.case, run_id=self.run_id)

    def test_identity_and_history_are_immutable(self):
        self._fails("UPDATE reasoning_cases SET case_id = 'rc1_' || repeat('f', 32)")
        self._fails("UPDATE reasoning_cases SET identity_key = 'x'")
        self._fails("UPDATE reasoning_cases SET topic_key = 'speed'")
        self._fails("UPDATE reasoning_results SET case_id = 'rc1_' || repeat('f', 32)")
        self._fails("UPDATE reasoning_results SET created_at = created_at - interval '1 day'")
        self._fails("UPDATE reasoning_results SET result_id = 'rr1_' || repeat('f', 32)")
        for table in ("reasoning_result_versions", "reasoning_evidence_links", "reasoning_case_evidence"):
            with self.subTest(table=table):
                self._fails(f"UPDATE {table} SET result_id = result_id" if table != "reasoning_case_evidence" else f"UPDATE {table} SET case_id = case_id")
                self._fails(f"DELETE FROM {table}")
        with self.store.db.transaction() as conn:
            conn.execute("UPDATE reasoning_cases SET consecutive_absent_runs = 0 WHERE case_id = %s", (self.case["case_id"],))

    def test_a_result_must_satisfy_its_contract_and_case(self):
        bad = factory.result_dict(self.case)
        bad["result_id"] = "rr1_" + "4" * 32
        bad["interpretation"]["evidence_refs"] = ["ev1_" + "0" * 24]
        with self.store.db.transaction() as conn:
            conn.execute("UPDATE reasoning_results SET lifecycle_status = 'resolved'")
        with self.assertRaises(ContractViolation) as caught, self.store.transaction() as tx:
            tx.create_result(ReasoningResult.from_dict(bad))
        self.assertIn("UNKNOWN_EVIDENCE_REF", caught.exception.codes)


@requires_db
class VersionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.run_id, self.case = seed(self.store)
        self.v1 = factory.result_dict(self.case)
        with self.store.transaction() as tx:
            tx.create_result(ReasoningResult.from_dict(self.v1), run_id=self.run_id)
        self.update = factory.update_dict(self.v1, self.case)

    def test_versions_are_kept_and_retrievable(self):
        v2 = patched(self.v1, self.update)
        with self.store.transaction() as tx:
            tx.append_result_version(v2, expected_version=1, change_kind=ResultChangeKind.PATCHED, update=ReasoningUpdate.from_dict(self.update),
                                     run_id=self.run_id, reason="evidence changed")
        lifecycle = {**v2.to_dict(), "version": 3, "lifecycle_status": "cooling", "updated_at": "2026-09-30T00:00:00Z"}
        with self.store.transaction() as tx:
            tx.append_result_version(ReasoningResult.from_dict(lifecycle), expected_version=2, change_kind=ResultChangeKind.LIFECYCLE, reason="disappeared")
        history = self.store.result_history(self.v1["result_id"])
        self.assertEqual([(row["version"], row["change_kind"]) for row in history], [(1, "created"), (2, "patched"), (3, "lifecycle")])
        self.assertEqual(self.store.get_result(self.v1["result_id"], 1).to_dict(), self.v1)
        self.assertEqual(self.store.get_result(self.v1["result_id"]).to_dict(), lifecycle)
        self.assertEqual(history[1]["update_document"], self.update)
        with self.store.transaction() as tx:
            links = tx.evidence_links(self.v1["result_id"], 1)
            open_result = tx.open_result(self.case["case_id"])
        refs = {ref["ref_id"]: ref for ref in self.case["current_evidence"]["references"]}
        self.assertEqual({row["ref_id"]: row["cited_in"] for row in links}, citations(self.v1))
        self.assertTrue(set(citations(self.v1)) <= set(refs))
        for row in links:
            self.assertEqual(row["event_ids"], refs[row["ref_id"]]["event_ids"])
            self.assertEqual(row["monday_item_id"], refs[row["ref_id"]]["monday_item_id"])
        assert open_result is not None
        self.assertEqual((open_result.version, open_result.lifecycle_status), (3, enums.LifecycleStatus.COOLING))

    def test_a_patch_changes_exactly_its_listed_fields(self):
        sneaky = patched(self.v1, self.update).to_dict()
        sneaky["title"] = "Rewritten title"
        with self.assertRaises(ContractViolation) as caught, self.store.transaction() as tx:
            tx.append_result_version(ReasoningResult.from_dict(sneaky), expected_version=1, change_kind=ResultChangeKind.PATCHED,
                                     update=ReasoningUpdate.from_dict(self.update))
        self.assertIn("UNPATCHED_FIELD_CHANGED", caught.exception.codes)
        unapplied = patched(self.v1, self.update).to_dict()
        unapplied["confidence"] = self.v1["confidence"]
        with self.assertRaises(ContractViolation) as caught, self.store.transaction() as tx:
            tx.append_result_version(ReasoningResult.from_dict(unapplied), expected_version=1, change_kind=ResultChangeKind.PATCHED,
                                     update=ReasoningUpdate.from_dict(self.update))
        self.assertIn("PATCH_NOT_APPLIED", caught.exception.codes)
        moved_identity = patched(self.v1, self.update).to_dict()
        moved_identity["created_at"] = "2026-09-27T00:00:00Z"
        with self.assertRaises(ContractViolation) as caught, self.store.transaction() as tx:
            tx.append_result_version(ReasoningResult.from_dict(moved_identity), expected_version=1, change_kind=ResultChangeKind.PATCHED,
                                     update=ReasoningUpdate.from_dict(self.update))
        self.assertIn("IMMUTABLE_FIELD", caught.exception.codes)
        self.assertEqual(len(self.store.result_history(self.v1["result_id"])), 1)

    def test_a_lifecycle_version_records_no_update(self):
        lifecycle = {**self.v1, "version": 2, "lifecycle_status": "cooling", "updated_at": LATER}
        with self.assertRaises(ContractViolation), self.store.transaction() as tx:
            tx.append_result_version(ReasoningResult.from_dict(lifecycle), expected_version=1, change_kind=ResultChangeKind.LIFECYCLE,
                                     update=ReasoningUpdate.from_dict(self.update))

    def test_stale_writer_gets_a_version_conflict(self):
        v2 = patched(self.v1, self.update)
        with self.store.transaction() as tx:
            tx.append_result_version(v2, expected_version=1, change_kind=ResultChangeKind.PATCHED, update=ReasoningUpdate.from_dict(self.update))
        with self.assertRaises((VersionConflict, ContractViolation)), self.store.transaction() as tx:
            tx.append_result_version(v2, expected_version=1, change_kind=ResultChangeKind.PATCHED, update=ReasoningUpdate.from_dict(self.update))
        self.assertEqual(len(self.store.result_history(self.v1["result_id"])), 2)


@requires_db
class AtomicityTests(unittest.TestCase):
    def setUp(self):
        self.store = ReasoningStore(fresh_database())

    def _counts(self) -> dict[str, int]:
        with self.store.db.transaction() as conn:
            return {table: conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
                    for table in ("reasoning_runs", "reasoning_cases", "reasoning_case_evidence", "reasoning_results", "reasoning_result_versions",
                                  "reasoning_evidence_links")}

    def test_a_failed_transaction_leaves_nothing_behind(self):
        case = factory.case_dict()
        with self.assertRaises(RuntimeError), self.store.transaction() as tx:
            run_id = tx.create_run(source_snapshot_id="s", release_id=None, upstream_contract_version="1.5.0", intelligence_version="i",
                                   boundary_version="b", identity_version="case-identity-v1", fingerprint_version="f")
            tx.insert_case(case_id=case["case_id"], identity_version="case-identity-v1", identity_key=case["identity_key"], case_type="editor_pattern",
                           subject_type="editor", subject_id="editor-label-12", topic_key="deadline", dimensions={}, run_id=run_id,
                           evidence_fingerprint=case["evidence_fingerprint"])
            tx.put_case_evidence(case_id=case["case_id"], evidence_fingerprint=case["evidence_fingerprint"], fingerprint_version="f",
                                 canonical_evidence=CANONICAL, case_document=case, run_id=run_id)
            tx.create_result(ReasoningResult.from_dict(factory.result_dict(case)), run_id=run_id)
            raise RuntimeError("crash after every write")
        self.assertEqual(set(self._counts().values()), {0})

    def test_a_failure_inside_result_creation_rolls_back_the_result(self):
        run_id, case = seed(self.store)
        before = self._counts()
        original = self.store.transaction

        from atlas_reasoning.store import repository

        real = repository.StoreTransaction._insert_version

        def failing(self, *args, **kwargs):
            real(self, *args, **kwargs)
            raise RuntimeError("disk full while writing evidence links")

        repository.StoreTransaction._insert_version = failing
        try:
            with self.assertRaises(RuntimeError), original() as tx:
                tx.create_result(ReasoningResult.from_dict(factory.result_dict(case)), run_id=run_id)
        finally:
            repository.StoreTransaction._insert_version = real
        self.assertEqual(self._counts(), before)


@requires_db
class ConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.run_id, self.case = seed(self.store)
        self.v1 = factory.result_dict(self.case)
        with self.store.transaction() as tx:
            tx.create_result(ReasoningResult.from_dict(self.v1))

    def test_concurrent_writers_cannot_corrupt_versions(self):
        update = factory.update_dict(self.v1, self.case)
        barrier = threading.Barrier(6)
        outcomes: list[str] = []

        def write(i: int) -> None:
            document = patched(self.v1, update).to_dict()
            document["reasoning_summary"] = self.v1["reasoning_summary"]
            barrier.wait()
            try:
                with self.store.transaction() as tx:
                    tx.append_result_version(ReasoningResult.from_dict(document), expected_version=1, change_kind=ResultChangeKind.PATCHED,
                                             update=ReasoningUpdate.from_dict(update), reason=f"writer {i}")
                outcomes.append("ok")
            except VersionConflict:
                outcomes.append("conflict")
            except Exception as error:  # noqa: BLE001
                outcomes.append(f"error {type(error).__name__}: {error}")

        threads = [threading.Thread(target=write, args=(i,)) for i in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(outcomes), ["conflict"] * 5 + ["ok"], outcomes)
        history = self.store.result_history(self.v1["result_id"])
        self.assertEqual([row["version"] for row in history], [1, 2])
        self.assertEqual(self.store.get_result(self.v1["result_id"]).version, 2)

    def test_concurrent_creation_of_two_open_results_for_one_case_fails_for_one(self):
        with self.store.db.transaction() as conn:
            conn.execute("UPDATE reasoning_results SET lifecycle_status = 'resolved'")
        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def create(i: int) -> None:
            document = {**factory.result_dict(self.case), "result_id": f"rr1_{i:032x}"}
            barrier.wait()
            try:
                with self.store.transaction() as tx:
                    tx.create_result(ReasoningResult.from_dict(document))
                outcomes.append("ok")
            except Exception as error:  # noqa: BLE001
                outcomes.append(type(error).__name__)

        threads = [threading.Thread(target=create, args=(i,)) for i in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(outcomes), ["ResultConflict", "ok"], outcomes)


@requires_db
class WorkItemTests(unittest.TestCase):
    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.run_id, self.case = seed(self.store)

    def test_status_transitions_are_guarded(self):
        fp = self.case["evidence_fingerprint"]
        with self.store.transaction() as tx:
            item = tx.create_work_item(run_id=self.run_id, case_id=self.case["case_id"], kind=WorkKind.NEW_RESULT, gate_action=GateAction.NEW,
                                       result_id=None, base_result_version=None, fingerprint_before=None, fingerprint_after=fp, material_delta=None,
                                       case_document=self.case)
            tx.set_work_item_status(item, WorkStatus.IN_PROGRESS)
        with self.assertRaises(WorkTransitionError), self.store.transaction() as tx:
            tx.create_work_item(run_id=self.run_id, case_id=self.case["case_id"], kind=WorkKind.NEW_RESULT, gate_action=GateAction.UPDATED,
                                result_id=None, base_result_version=None, fingerprint_before=None, fingerprint_after=fp, material_delta=None,
                                supersedes=item, case_document=self.case)
        for status in (WorkStatus.CANCELLED, WorkStatus.SUPERSEDED):
            with self.subTest(status=status), self.assertRaises(WorkTransitionError), self.store.transaction() as tx:
                tx.set_work_item_status(item, status)
        with self.store.transaction() as tx:
            tx.set_work_item_status(item, WorkStatus.DONE)
        with self.assertRaises(WorkTransitionError), self.store.transaction() as tx:
            tx.set_work_item_status(item, WorkStatus.FAILED)

    def test_llm_work_requires_its_case_document(self):
        with self.assertRaises(psycopg.errors.CheckViolation), self.store.transaction() as tx:
            tx.create_work_item(run_id=self.run_id, case_id=self.case["case_id"], kind=WorkKind.NEW_RESULT, gate_action=GateAction.NEW, result_id=None,
                                base_result_version=None, fingerprint_before=None, fingerprint_after=self.case["evidence_fingerprint"], material_delta=None)

    def test_one_open_llm_item_per_case_and_superseding(self):
        fp = self.case["evidence_fingerprint"]
        with self.store.transaction() as tx:
            first = tx.create_work_item(run_id=self.run_id, case_id=self.case["case_id"], kind=WorkKind.NEW_RESULT, gate_action=GateAction.NEW, result_id=None,
                                        base_result_version=None, fingerprint_before=None, fingerprint_after=fp, material_delta=None,
                                        case_document=self.case)
        with self.assertRaises(psycopg.errors.UniqueViolation), self.store.transaction() as tx:
            tx.create_work_item(run_id=self.run_id, case_id=self.case["case_id"], kind=WorkKind.NEW_RESULT, gate_action=GateAction.NEW, result_id=None,
                                base_result_version=None, fingerprint_before=None, fingerprint_after=fp, material_delta=None,
                                        case_document=self.case)
        with self.store.transaction() as tx:
            second = tx.create_work_item(run_id=self.run_id, case_id=self.case["case_id"], kind=WorkKind.NEW_RESULT, gate_action=GateAction.UPDATED,
                                         result_id=None, base_result_version=None, fingerprint_before=None, fingerprint_after=fp, material_delta=None,
                                         supersedes=first, case_document=self.case)
        items = {item.work_item_id: item for item in self.store.work_items(case_id=self.case["case_id"])}
        self.assertEqual(items[first].status, WorkStatus.SUPERSEDED)
        self.assertEqual(items[second].status, WorkStatus.PENDING)
        self.assertEqual([item.work_item_id for item in self.store.work_items(open_only=True)], [second])
        with self.store.transaction() as tx:
            tx.set_work_item_status(second, WorkStatus.DONE)
            tx.set_run_status(self.run_id, RunStatus.GATED, counts={"new": 1})
        self.assertEqual(self.store.work_items(open_only=True), [])
        self.assertEqual(self.store.get_run(self.run_id)["status"], "gated")


@requires_db
class RestartPersistenceTests(unittest.TestCase):
    def test_state_written_by_one_process_is_read_by_a_fresh_one(self):
        store = ReasoningStore(fresh_database())
        _, case = seed(store)
        result = factory.result_dict(case)
        with store.transaction() as tx:
            tx.create_result(ReasoningResult.from_dict(result))
        script = ("import json, sys\n"
                  "from atlas_reasoning.store.db import Database\n"
                  "from atlas_reasoning.store.repository import ReasoningStore\n"
                  "store = ReasoningStore(Database(sys.argv[1]))\n"
                  "print(json.dumps({'result': store.get_result(sys.argv[2]).to_dict(), 'case': store.get_case(sys.argv[3]).case_id,"
                  " 'versions': [r['version'] for r in store.result_history(sys.argv[2])]}))\n")
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        output = subprocess.run([sys.executable, "-c", script, test_database_url(), result["result_id"], case["case_id"]], env=env,
                                capture_output=True, text=True, check=True).stdout
        read = json.loads(output)
        self.assertEqual(read["result"], result)
        self.assertEqual(read["case"], case["case_id"])
        self.assertEqual(read["versions"], [1])


class SkipPolicyTests(unittest.TestCase):
    def test_database_url_must_name_a_test_database(self):
        from unittest import mock

        with mock.patch.dict(os.environ, {TEST_DB_ENV: "postgresql://atlas@localhost/atlas_production"}), self.assertRaises(RuntimeError):
            test_database_url()


if __name__ == "__main__":
    unittest.main()


@requires_db
class CommandTests(unittest.TestCase):
    def _run(self, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        base = {key: value for key, value in os.environ.items() if not key.startswith("ATLAS_REASONING")}
        base.update({"PYTHONPATH": str(ROOT / "src"), "ATLAS_REASONING_DATABASE_URL": test_database_url() or ""}, **(env or {}))
        return subprocess.run([sys.executable, "-m", "atlas_reasoning", *args], env=base, capture_output=True, text=True, check=False)

    def test_migrate_health_and_debug_lookups(self):
        db = fresh_database()
        with db.transaction() as conn:
            conn.execute("DROP SCHEMA atlas_reasoning CASCADE")
        self.assertEqual(self._run("db-health").returncode, 1)
        migrated = self._run("migrate")
        self.assertEqual(migrated.returncode, 0, migrated.stderr)
        self.assertEqual(json.loads(migrated.stdout)["applied"], [m.name for m in available_migrations()])
        self.assertEqual(json.loads(migrated.stdout)["applied"][:1], ["0001_reasoning_core.sql"])
        self.assertEqual(json.loads(self._run("migrate").stdout)["applied"], [])
        health = self._run("db-health")
        self.assertEqual(health.returncode, 0)
        self.assertTrue(json.loads(health.stdout)["ok"])
        store = ReasoningStore(db)
        run_id, case = seed(store)
        with store.transaction() as tx:
            tx.create_result(ReasoningResult.from_dict(factory.result_dict(case)))
        shown = json.loads(self._run("case", case["case_id"]).stdout)
        self.assertEqual(shown["case"]["case_id"], case["case_id"])
        self.assertEqual(len(shown["results"]), 1)
        self.assertEqual([row["version"] for row in json.loads(self._run("result", factory.RESULT_ID).stdout)], [1])
        self.assertEqual(json.loads(self._run("run", run_id).stdout)["run"]["run_id"], run_id)
        missing = self._run("case", "rc1_" + "f" * 32)
        self.assertEqual(missing.returncode, 2)
        self.assertIn("NotFound", missing.stderr)

    def test_missing_configuration_is_reported_without_secrets(self):
        result = self._run("db-health", env={"ATLAS_REASONING_DATABASE_URL": ""})
        self.assertEqual(result.returncode, 2)
        self.assertIn("ATLAS_REASONING_DATABASE_URL", result.stderr)
        secret = "postgresql://atlas:t0p-s3cret@127.0.0.1:1/atlas_reasoning_test"
        result = self._run("db-health", env={"ATLAS_REASONING_DATABASE_URL": secret})
        self.assertNotIn("t0p-s3cret", result.stdout + result.stderr)
