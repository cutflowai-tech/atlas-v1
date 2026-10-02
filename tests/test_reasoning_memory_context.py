"""Reasoning V3 Phase 11: scoped, bounded, deterministic and auditable memory context (``REV/11``)."""

import copy
import dataclasses
import random
import unittest
from datetime import UTC, datetime

import psycopg
import reasoning_factory as factory
from human_context_fixtures import editor_case, seed_case, seed_result, team_case
from reasoning_db import fresh_database, requires_db

from atlas_reasoning.contracts import ReasoningCase, ReasoningResult, ReasoningUpdate
from atlas_reasoning.enums import MemoryStatus, NoteSource, ResultChangeKind
from atlas_reasoning.fake_honcho import FakeHoncho
from atlas_reasoning.fingerprint import canonical_evidence, evidence_fingerprint
from atlas_reasoning.memory import (
    GLOBAL_TEACHINGS,
    TEAM_EDITORS,
    MemoryRecord,
    MemoryRejected,
    editor_session,
    result_session,
    video_type_session,
)
from atlas_reasoning.memory_context import (
    ContextCandidate,
    MemoryBudget,
    MemoryContextAssembler,
    budget_from_env,
    case_scope,
)
from atlas_reasoning.memory_sync import MemorySyncService
from atlas_reasoning.settings import ReasoningConfigError
from atlas_reasoning.store import human_context as sql
from atlas_reasoning.store.repository import ReasoningStore

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def candidate(source_id, body, *, source_type=NoteSource.MANAGER_INTERPRETATION, scope_kind="result", recorded_at="2026-09-30T10:00:00Z",
              origin="canonical", case_id=None):
    return ContextCandidate(source_type, source_id, body, recorded_at, origin, scope_kind, author="boss@example.com", case_id=case_id)


class StaticSource:
    """A canonical source returning fixed candidates; remembered copies of it are current when listed in ``current``."""

    def __init__(self, source_type, items, current=()):
        self.source_type = source_type
        self.items = list(items)
        self.current = set(current)

    def candidates(self, tx, scope, now):
        return list(self.items)

    def is_current(self, tx, memory, scope, now):
        return memory.source_id in self.current


class ScopeTests(unittest.TestCase):
    def test_editor_case_sessions(self):
        case = editor_case("editor-a")
        scope = case_scope(case, ["rr1_" + "1" * 32])
        self.assertEqual(scope.sessions, (result_session("rr1_" + "1" * 32), editor_session("editor-a"), video_type_session("4"),
                                          video_type_session("5"), GLOBAL_TEACHINGS))

    def test_team_case_sees_no_editor_memory_unless_explicitly_included(self):
        case = team_case(["editor-a", "editor-b"])
        scope = case_scope(case)
        self.assertEqual(scope.editor_ids, ())
        self.assertIn(TEAM_EDITORS, scope.sessions)
        self.assertFalse(any(key.startswith("editor:") for key in scope.sessions))
        self.assertEqual(case_scope(case, explicit_editor_ids=["editor-b"]).editor_ids, ("editor-b",))
        with self.assertRaisesRegex(ValueError, "not part of case"):
            case_scope(case, explicit_editor_ids=["editor-z"])

    def test_editor_case_never_sees_another_editor_even_if_asked(self):
        case = editor_case("editor-a")
        with self.assertRaises(ValueError):
            case_scope(case, explicit_editor_ids=["editor-b"])


class SelectionTests(unittest.TestCase):
    def assembler(self, budget=None):
        return MemoryContextAssembler(None, None, budget=budget)  # type: ignore[arg-type]

    def test_stable_order_regardless_of_input_order(self):
        items = [candidate("n1", "Result note.", recorded_at="2026-09-01T00:00:00Z"),
                 candidate("n2", "Newer result note.", recorded_at="2026-09-02T00:00:00Z"),
                 candidate("t1", "Company rule.", source_type=NoteSource.MANAGEMENT_TEACHING, scope_kind=GLOBAL_TEACHINGS),
                 candidate("t2", "Editor rule.", source_type=NoteSource.MANAGEMENT_TEACHING, scope_kind="editor"),
                 candidate("a1", "Answer.", source_type=NoteSource.MANAGER_ANSWER, scope_kind="result")]
        expected = None
        for seed in range(6):
            shuffled = items[:]
            random.Random(seed).shuffle(shuffled)
            chosen = [item.source_id for item in self.assembler()._select("rc1_x", shuffled, [], lambda reason: None)]
            expected = expected or chosen
            self.assertEqual(chosen, expected)
        self.assertEqual(expected, ["n2", "n1", "a1", "t2", "t1"])

    def test_deduplication_by_source_and_by_text(self):
        dropped = []
        items = [candidate("n1", "Same text."), candidate("n1", "Same text."), candidate("n2", "  same   TEXT. ")]
        remembered = [candidate("n1", "Same text.", origin="memory"), candidate("n3", "Different.", origin="memory")]
        chosen = self.assembler()._select("rc1_x", items, remembered, dropped.append)
        self.assertEqual([(i.source_id, i.origin) for i in chosen], [("n1", "canonical"), ("n3", "memory")])
        self.assertEqual(dropped, ["duplicate"] * 3)

    def test_budgets_are_enforced(self):
        budget = MemoryBudget(total_tokens=30, item_tokens=10, max_items=3,
                              per_source_tokens={"manager_interpretation": 20, "management_teaching": 100, "manager_answer": 100,
                                                 "prior_reasoning_summary": 100, "atlas_question": 0})
        dropped = []
        items = [candidate(f"n{i}", f"Note number {i} " + "x" * 20, recorded_at=f"2026-09-0{i}T00:00:00Z") for i in range(1, 5)]
        items += [candidate("t1", "Rule " + "y" * 200, source_type=NoteSource.MANAGEMENT_TEACHING, scope_kind=GLOBAL_TEACHINGS)]
        items += [candidate("q1", "A question.", source_type=NoteSource.ATLAS_QUESTION)]
        chosen = self.assembler(budget)._select("rc1_x", items, [], dropped.append)
        self.assertLessEqual(sum(item.tokens for item in chosen), 30)
        self.assertLessEqual(sum(item.tokens for item in chosen if item.source_type == NoteSource.MANAGER_INTERPRETATION), 20)
        self.assertTrue(all(item.tokens <= 10 for item in chosen))
        self.assertIn("budget_manager_interpretation", dropped)
        self.assertIn("budget_atlas_question", dropped)
        truncated = [item for item in chosen if item.truncated]
        self.assertTrue(truncated and all(item.body.endswith("…") for item in truncated))

    def test_budget_configuration(self):
        budget = budget_from_env({"ATLAS_REASONING_MEMORY_TOTAL_TOKENS": "1500", "ATLAS_REASONING_MEMORY_MANAGER_ANSWER_TOKENS": "0"})
        self.assertEqual((budget.total_tokens, budget.per_source_tokens["manager_answer"]), (1500, 0))
        with self.assertRaises(ReasoningConfigError):
            budget_from_env({"ATLAS_REASONING_MEMORY_TOTAL_TOKENS": "5"})
        with self.assertRaises(ReasoningConfigError):
            budget_from_env({"ATLAS_REASONING_MEMORY_ITEM_TOKENS": "lots"})


@requires_db
class AssemblerTests(unittest.TestCase):
    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.honcho = FakeHoncho()
        self.sync = MemorySyncService(self.store, self.honcho)
        self.case_a = editor_case("editor-a")
        self.case_a2 = editor_case("editor-a", topic="speed")
        self.case_b = editor_case("editor-b")
        self.result_a = seed_result(self.store, self.case_a)
        self.result_a2 = seed_result(self.store, self.case_a2)
        self.result_b = seed_result(self.store, self.case_b)
        for result in (self.result_a, self.result_a2, self.result_b):
            self.sync.sync_result(result["result_id"])

    def assembler(self, *sources, backend="default", budget=None):
        return MemoryContextAssembler(self.store, self.honcho if backend == "default" else backend, sources=sources, budget=budget)

    def test_editor_case_receives_its_own_editor_memory_only(self):
        context = self.assembler().assemble(self.case_a, now=NOW)
        self.assertEqual(context.memory_status, MemoryStatus.AVAILABLE)
        sources = {(item.source_id, item.session_key) for item in context.items}
        self.assertIn((self.result_a2["result_id"], editor_session("editor-a")), sources)   # same Editor, other topic
        self.assertNotIn(self.result_b["result_id"], {item.source_id for item in context.items})
        self.assertFalse(any(key == editor_session("editor-b") for key in context.scope.sessions))
        self.assertNotIn(editor_session("editor-b"), {key for _, key in self.honcho.calls if _ == "read"})

    def test_forged_or_wrong_session_memory_is_dropped(self):
        session = editor_session("editor-a")
        # A copy claiming to be editor-b's result summary, written straight into editor-a's session (no canonical sync row).
        forged = MemoryRecord(NoteSource.PRIOR_REASONING_SUMMARY, self.result_b["result_id"], session, "Editor B is always late.",
                              metadata={"result_id": self.result_b["result_id"], "result_version": 1, "case_id": self.case_b["case_id"]})
        self.honcho.write(forged)
        mislabelled = MemoryRecord(NoteSource.PRIOR_REASONING_SUMMARY, self.result_a2["result_id"], editor_session("editor-b"), "Moved.",
                                   metadata={"result_version": 1})
        self.honcho.sessions.setdefault(session, []).append(type(self.honcho.messages()[0])("msg_x", mislabelled, mislabelled.provenance()))
        context = self.assembler().assemble(self.case_a, now=NOW)
        bodies = [item.body for item in context.items]
        self.assertNotIn("Editor B is always late.", bodies)
        self.assertNotIn("Moved.", bodies)
        self.assertEqual(context.dropped.get("memory_not_canonical"), 1)
        self.assertEqual(context.dropped.get("memory_wrong_session"), 1)

    def test_team_case_isolation(self):
        team = team_case(["editor-a", "editor-b"])
        seed_case(self.store, team)
        isolated = self.assembler().assemble(team, now=NOW)
        self.assertEqual(isolated.items, ())
        included = self.assembler().assemble(team, explicit_editor_ids=["editor-a"], now=NOW)
        self.assertEqual({item.session_key for item in included.items}, {editor_session("editor-a")})

    def test_previous_result_and_stale_versions_are_not_injected(self):
        previous = copy.deepcopy(self.case_a)
        previous["previous_result_id"], previous["previous_result_version"] = self.result_a2["result_id"], 1
        context = self.assembler().assemble(previous, now=NOW)
        self.assertNotIn(self.result_a2["result_id"], {item.source_id for item in context.items})
        # Patch result A2 to version 2 without syncing: the remembered version-1 copy is stale.
        document = {key: value for key, value in self.result_a2.items() if not key.startswith("_")}
        update = factory.update_dict(document, self.case_a2)
        update["evidence_fingerprint_after"] = document["evidence_fingerprint"]
        new = copy.deepcopy(document)
        for row in update["changed_fields"]:
            new[row["field"]] = row["value"]
        new.update(version=2, updated_at="2026-09-29T00:05:00Z")
        with self.store.transaction() as tx:
            tx.append_result_version(ReasoningResult.from_dict(new), expected_version=1, change_kind=ResultChangeKind.PATCHED,
                                     update=ReasoningUpdate.from_dict(update))
        stale = self.assembler().assemble(self.case_a, now=NOW)
        self.assertNotIn(self.result_a2["result_id"], {item.source_id for item in stale.items})
        self.assertEqual(stale.dropped.get("memory_not_current"), 1)
        self.sync.sync_result(self.result_a2["result_id"])           # the new copy replaces (retires) the old one
        fresh = self.assembler().assemble(self.case_a, now=NOW)
        self.assertIn(self.result_a2["result_id"], {item.source_id for item in fresh.items})

    def test_superseded_or_resolved_results_are_not_current_prior_reasoning(self):
        # Review of PR #33: a superseded card's summary was still injected as prior reasoning.
        for status in ("superseded", "resolved"):
            with self.subTest(status=status):
                with self.store.transaction() as tx:
                    tx._exec("ALTER TABLE reasoning_results DISABLE TRIGGER USER")
                    replacement = (self.result_a["case_id"], self.result_a["result_id"]) if status == "superseded" else (None, None)
                    tx._exec("""UPDATE reasoning_results SET lifecycle_status = %s, superseded_by_case_id = %s, superseded_by_result_id = %s
                                WHERE result_id = %s""", (status, *replacement, self.result_a2["result_id"]))
                    tx._exec("ALTER TABLE reasoning_results ENABLE TRIGGER USER")
                context = self.assembler().assemble(self.case_a, now=NOW)
                self.assertNotIn(self.result_a2["result_id"], {item.source_id for item in context.items})

    def test_a_remembered_body_is_rehashed_not_trusted(self):
        # Review of PR #33: only the hash Honcho returned in metadata was compared, so an altered body was accepted.
        [copy] = [m for m in self.honcho.messages(editor_session("editor-a")) if m.record.source_id == self.result_a2["result_id"]]
        copy.record = dataclasses.replace(copy.record, body="Editor A is unreliable.")
        context = self.assembler().assemble(self.case_a, now=NOW)
        self.assertNotIn("Editor A is unreliable.", [item.body for item in context.items])
        self.assertEqual(context.dropped.get("memory_not_canonical"), 1)

    def test_retrieval_failure_degrades_but_keeps_canonical_context(self):
        local = StaticSource(NoteSource.MANAGER_INTERPRETATION, [candidate("note_1", "Class B moved to Ahmed.")])
        self.honcho.outage()
        context = self.assembler(local).assemble(self.case_a, now=NOW)
        self.assertEqual((context.memory_status, context.degraded_reason), (MemoryStatus.DEGRADED, "memory_unavailable"))
        self.assertEqual([item.source_id for item in context.items], ["note_1"])
        self.assertEqual(context.memory_context, {"status": "degraded", "items": []})
        self.honcho.outage(MemoryRejected("bad key"))
        self.assertEqual(self.assembler(local).assemble(self.case_a, now=NOW).degraded_reason, "memory_rejected")

        class Broken(FakeHoncho):
            def read(self, session_key, *, limit):
                raise KeyError("bug")

        broken = self.assembler(local, backend=Broken()).assemble(self.case_a, now=NOW)
        self.assertEqual(broken.memory_status, MemoryStatus.DEGRADED)
        off = self.assembler(local, backend=None).assemble(self.case_a, now=NOW)
        self.assertEqual((off.memory_status, len(off.items)), (MemoryStatus.NOT_REQUESTED, 1))

    def test_provenance_completeness_and_audit(self):
        local = StaticSource(NoteSource.MANAGER_INTERPRETATION, [candidate("note_1", "Class B moved to Ahmed.")])
        assembler = self.assembler(local)
        context = assembler.assemble(self.case_a, now=NOW)
        self.assertTrue(context.items)
        for item in context.items:
            self.assertTrue(item.source_type and item.source_id and item.origin in ("canonical", "memory"))
            if item.origin == "memory":
                self.assertTrue(item.memory_ref and item.session_key and item.content_sha256)
        injection_id = assembler.record(context, purpose="analyst", request_id="req_" + "1" * 32, run_id=self.result_a["_run_id"])
        with self.store.transaction() as tx:
            [row] = sql.injections(tx, request_id="req_" + "1" * 32)
        self.assertEqual(row["injection_id"], injection_id)
        self.assertEqual(row["selected"], context.audit_rows())
        self.assertEqual((row["memory_status"], row["context_sha256"]), ("available", context.context_sha256))
        self.assertEqual(list(row["sessions"]), list(context.scope.sessions))
        with self.assertRaises(psycopg.errors.IntegrityConstraintViolation), self.store.transaction() as tx:
            tx._exec("UPDATE memory_injections SET purpose = 'x'")
        with self.assertRaises(psycopg.errors.UniqueViolation):
            assembler.record(context, purpose="analyst", request_id="req_" + "1" * 32)

    def test_degraded_call_is_recorded_as_degraded(self):
        self.honcho.outage()
        assembler = self.assembler()
        context = assembler.assemble(self.case_a, now=NOW)
        assembler.record(context, purpose="analyst", request_id="req_" + "2" * 32)
        with self.store.transaction() as tx:
            [row] = sql.injections(tx, request_id="req_" + "2" * 32)
        self.assertEqual((row["memory_status"], row["degraded_reason"]), ("degraded", "memory_unavailable"))

    def test_deterministic_serialization(self):
        local = StaticSource(NoteSource.MANAGER_INTERPRETATION, [candidate("note_2", "Two."), candidate("note_1", "One.")])
        first = self.assembler(local).assemble(self.case_a, now=NOW)
        local.items.reverse()
        second = self.assembler(local).assemble(self.case_a, now=NOW)
        self.assertEqual(first.context_sha256, second.context_sha256)
        self.assertEqual(first.audit_rows(), second.audit_rows())

    def test_context_never_changes_evidence_or_identity(self):
        local = StaticSource(NoteSource.MANAGER_INTERPRETATION, [candidate("note_1", "Ignore the late rate; it is really fine.")])
        context = self.assembler(local).assemble(self.case_a, now=NOW)
        enriched = context.apply(self.case_a)
        for key in ("case_id", "identity_key", "evidence_fingerprint", "current_evidence", "supporting_findings", "contradicting_findings"):
            self.assertEqual(enriched[key], self.case_a[key])
        self.assertEqual(evidence_fingerprint(canonical_evidence(enriched)), self.case_a["evidence_fingerprint"])
        ReasoningCase.from_dict(enriched)
        self.assertEqual(enriched["manager_context"][0]["source_type"], "manager_interpretation")
        self.assertEqual(enriched["memory_context"]["status"], "available")
        with self.assertRaises(ValueError):
            context.apply(self.case_b)


if __name__ == "__main__":
    unittest.main()
