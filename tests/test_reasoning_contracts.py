"""Reasoning V3 Phase 02: ReasoningCase, ReasoningResult and ReasoningUpdate are explicit, versioned and strict (``REV/02``)."""

import copy
import dataclasses
import json
import unittest
from enum import StrEnum

import reasoning_factory as factory
from jsonschema.validators import validator_for

from atlas_reasoning import contracts, enums
from atlas_reasoning.contracts import (
    IMMUTABLE_RESULT_FIELDS,
    PATCHABLE_FIELDS,
    ContractViolation,
    ReasoningCase,
    ReasoningResult,
    ReasoningUpdate,
    case_errors,
    result_case_errors,
    result_errors,
    update_case_errors,
    update_errors,
    update_result_errors,
)

MODELS = {"ReasoningCase": ReasoningCase, "ReasoningResult": ReasoningResult, "ReasoningUpdate": ReasoningUpdate}


def codes(errors: list[str]) -> set[str]:
    return {error.split(":", 1)[0] for error in errors}


class SchemaFileTests(unittest.TestCase):
    def test_schemas_are_valid_draft_2020_12_with_unique_ids(self):
        ids = set()
        for name in contracts.SCHEMA_FILES:
            schema = contracts.schema(name)
            validator_for(schema).check_schema(schema)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertTrue(schema["$id"].endswith(name))
            ids.add(schema["$id"])
        self.assertEqual(len(ids), len(contracts.SCHEMA_FILES))

    def test_contract_version_is_reasoning_v1(self):
        self.assertEqual(enums.CONTRACT_VERSION, "reasoning-v1")
        self.assertEqual(contracts.schema(contracts.COMMON_SCHEMA)["$defs"]["contract_version"], {"const": "reasoning-v1"})

    def test_schema_enums_equal_the_python_enums(self):
        defs = contracts.schema(contracts.COMMON_SCHEMA)["$defs"]
        pairs = {"subject_type": enums.SubjectType, "case_type": enums.CaseType, "topic_key": enums.TopicKey, "direction": enums.Direction,
                 "confidence_level": enums.ConfidenceLevel, "evidence_level": enums.EvidenceLevel, "statement_kind": enums.StatementKind,
                 "evidence_role": enums.EvidenceRole, "lifecycle_status": enums.LifecycleStatus, "gate_action": enums.GateAction,
                 "update_action": enums.UpdateAction, "note_source": enums.NoteSource, "question_state": enums.QuestionState,
                 "expected_context_type": enums.ExpectedContextType, "memory_status": enums.MemoryStatus}
        for name, enum in pairs.items():
            self.assertEqual(defs[name]["enum"], [member.value for member in enum], name)
        self.assertEqual(defs["patchable_field"]["enum"], list(PATCHABLE_FIELDS))
        case_dims = contracts.schema(contracts.CASE_SCHEMA)["properties"]["identity_dimensions"]["properties"]
        self.assertEqual(sorted(case_dims), sorted(member.value for member in enums.IdentityDimension))

    def test_every_result_field_is_either_patchable_or_immutable(self):
        result_fields = set(contracts.schema(contracts.RESULT_SCHEMA)["properties"])
        self.assertEqual(result_fields, set(PATCHABLE_FIELDS) | set(IMMUTABLE_RESULT_FIELDS))
        self.assertFalse(set(PATCHABLE_FIELDS) & set(IMMUTABLE_RESULT_FIELDS))
        for name in ("case_id", "result_id", "created_at", "lifecycle_status", "version"):
            self.assertIn(name, IMMUTABLE_RESULT_FIELDS)


class RoundTripTests(unittest.TestCase):
    def test_valid_objects_round_trip_through_models_and_json(self):
        case = factory.case_dict()
        result = factory.result_dict(case)
        update = factory.update_dict(result, case)
        for model, payload in ((ReasoningCase, case), (ReasoningResult, result), (ReasoningUpdate, update)):
            with self.subTest(model=model.__name__):
                obj = model.from_dict(payload)
                self.assertEqual(obj.to_dict(), payload)
                self.assertEqual(model.from_dict(json.loads(json.dumps(obj.to_dict()))), obj)
                self.assertIs(obj.validated(), obj)

    def test_models_are_typed(self):
        case = ReasoningCase.from_dict(factory.case_dict())
        self.assertIs(case.subject_type, enums.SubjectType.EDITOR)
        self.assertIs(case.topic_key, enums.TopicKey.DEADLINE)
        self.assertIs(case.supporting_findings[0].confidence, enums.ConfidenceLevel.MODERATE)
        self.assertIs(case.current_evidence.references[0].role, enums.EvidenceRole.SUPPORTING)
        self.assertIsInstance(case.current_evidence.references[0].event_ids, tuple)
        result = ReasoningResult.from_dict(factory.result_dict())
        self.assertIs(result.lifecycle_status, enums.LifecycleStatus.ACTIVE)
        self.assertIs(result.questions_for_management[0].expected_context_type, enums.ExpectedContextType.ASSIGNMENT_CONTEXT)
        update = ReasoningUpdate.from_dict(factory.update_dict())
        self.assertEqual(update.changed_names, ("confidence", "observation"))

    def test_example_fixtures_match_the_factory_and_validate(self):
        manifest = json.loads((factory.FIXTURES / "manifest.json").read_text())
        case = factory.case_dict()
        result = factory.result_dict(case)
        expected = {"valid/case.json": case, "valid/result.json": result, "valid/update.json": factory.update_dict(result, case)}
        for relative, model in manifest["valid"].items():
            payload = json.loads((factory.FIXTURES / relative).read_text())
            self.assertEqual(payload, expected[relative], f"{relative} drifted: run python3 tests/reasoning_factory.py --write")
            MODELS[model].from_dict(payload)
        examples = factory.invalid_examples()
        self.assertEqual(sorted(manifest["invalid"]), sorted(f"invalid/{name}.json" for name in examples))
        for relative, expectation in manifest["invalid"].items():
            with self.subTest(fixture=relative):
                payload = json.loads((factory.FIXTURES / relative).read_text())
                with self.assertRaises(ContractViolation) as caught:
                    MODELS[expectation["contract"]].from_dict(payload)
                self.assertIn(expectation["code"], caught.exception.codes)


class InvalidPayloadTests(unittest.TestCase):
    def test_unknown_fields_fail_at_every_level(self):
        case = factory.case_dict()
        for path in ((), ("scope",), ("current_evidence",), ("supporting_findings", 0), ("current_evidence", "references", 0), ("memory_context",)):
            bad = copy.deepcopy(case)
            target = bad
            for part in path:
                target = target[part]
            target["unexpected"] = 1
            with self.subTest(path=path):
                self.assertIn("UNKNOWN_FIELD", codes(case_errors(bad)))
        result = factory.result_dict()
        for name in ("observation", "confidence", "model_metadata"):
            bad = copy.deepcopy(result)
            bad[name]["chain_of_thought"] = "hidden"
            self.assertIn("UNKNOWN_FIELD", codes(result_errors(bad)), name)

    def test_structurally_invalid_payloads_fail(self):
        result = factory.result_dict()
        mutations = {
            "missing title": lambda r: r.pop("title"),
            "empty title": lambda r: r.__setitem__("title", ""),
            "version zero": lambda r: r.__setitem__("version", 0),
            "bad result id": lambda r: r.__setitem__("result_id", "result-1"),
            "bad case id": lambda r: r.__setitem__("case_id", "editor:42:deadline"),
            "bad fingerprint": lambda r: r.__setitem__("evidence_fingerprint", "abc"),
            "bad timestamp": lambda r: r.__setitem__("created_at", "yesterday"),
            "refs not a list": lambda r: r["observation"].__setitem__("evidence_refs", "ev1_x"),
            "bad ref id": lambda r: r["observation"].__setitem__("evidence_refs", ["finding-1"]),
            "not an object": lambda r: r.clear(),
        }
        for name, mutate in mutations.items():
            bad = copy.deepcopy(result)
            mutate(bad)
            with self.subTest(mutation=name):
                self.assertTrue(result_errors(bad))
                with self.assertRaises(ContractViolation):
                    ReasoningResult.from_dict(bad)
        self.assertTrue(result_errors([]))
        self.assertTrue(case_errors("case"))

    def test_enums_are_strict(self):
        case = factory.case_dict()
        for path, value in ((("case_type",), "hr_case"), (("topic_key",), "attitude"), (("orientation",), "bad"),
                            (("supporting_findings", 0, "confidence"), "high"), (("current_evidence", "references", 0, "role"), "proof"),
                            (("current_evidence", "statements", 0, "level"), "opinion"), (("manager_context", 0, "source_type"), "gossip"),
                            (("memory_context", "status"), "maybe"), (("contract_version",), "reasoning-v2")):
            bad = copy.deepcopy(case)
            target = bad
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            with self.subTest(path=path):
                self.assertIn("INVALID_ENUM", codes(case_errors(bad)))
        result = factory.result_dict()
        for name, value in (("lifecycle_status", "archived"),):
            bad = copy.deepcopy(result)
            bad[name] = value
            self.assertIn("INVALID_ENUM", codes(result_errors(bad)))
        bad = copy.deepcopy(result)
        bad["confidence"]["level"] = "certain"
        self.assertIn("INVALID_ENUM", codes(result_errors(bad)))
        bad = copy.deepcopy(result)
        bad["questions_for_management"][0]["expected_context_type"] = "salary"
        self.assertIn("INVALID_ENUM", codes(result_errors(bad)))
        update = factory.update_dict()
        update["action"] = "rewrite"
        self.assertIn("INVALID_ENUM", codes(update_errors(update)))
        self.assertEqual(enums.UpdateAction("patch"), "patch")
        with self.assertRaises(ValueError):
            enums.LifecycleStatus("deleted")


class EvidenceRequirementTests(unittest.TestCase):
    def test_result_without_evidence_is_rejected(self):
        result = factory.result_dict()
        for field_path in (("observation",), ("interpretation",), ("management_significance",), ("supporting_evidence", 0), ("counter_evidence", 0)):
            bad = copy.deepcopy(result)
            target = bad
            for part in field_path:
                target = target[part]
            target["evidence_refs"] = []
            with self.subTest(field=field_path):
                self.assertIn("MISSING_EVIDENCE", codes(result_errors(bad)))
            del target["evidence_refs"]
            self.assertIn("MISSING_EVIDENCE", codes(result_errors(bad)))
        bad = copy.deepcopy(result)
        bad["supporting_evidence"] = []
        self.assertIn("MISSING_EVIDENCE", codes(result_errors(bad)))

    def test_case_needs_evidence_for_every_finding(self):
        case = factory.case_dict()
        bad = copy.deepcopy(case)
        bad["current_evidence"]["references"] = [r for r in bad["current_evidence"]["references"] if r["member_key"] != factory.MEMBER_MIX]
        self.assertIn("FINDING_WITHOUT_EVIDENCE", codes(case_errors(bad)))
        bad = copy.deepcopy(case)
        bad["current_evidence"]["references"] = []
        self.assertIn("SCHEMA_INVALID", codes(case_errors(bad)))
        bad = copy.deepcopy(case)
        bad["current_evidence"]["references"][0]["event_ids"] = []
        self.assertTrue(case_errors(bad))

    def test_result_may_cite_only_its_case_evidence(self):
        case = factory.case_dict()
        result = factory.result_dict(case)
        self.assertEqual(result_case_errors(result, case), [])
        result["interpretation"]["evidence_refs"] = ["ev1_" + "f" * 24]
        self.assertIn("UNKNOWN_EVIDENCE_REF", codes(result_case_errors(result, case)))

    def test_contradicted_case_requires_counter_evidence(self):
        case = factory.case_dict()
        result = factory.result_dict(case)
        result["counter_evidence"] = []
        self.assertEqual(result_errors(result), [])
        self.assertIn("COUNTER_EVIDENCE_MISSING", codes(result_case_errors(result, case)))

    def test_confidence_cannot_exceed_the_strongest_upstream_finding(self):
        case = factory.case_dict()
        result = factory.result_dict(case)
        result["confidence"]["level"] = "strong"
        self.assertIn("CONFIDENCE_EXCEEDS_UPSTREAM", codes(result_case_errors(result, case)))


class ImmutableIdentityTests(unittest.TestCase):
    def test_case_and_result_identity_cannot_be_reassigned(self):
        case = ReasoningCase.from_dict(factory.case_dict())
        result = ReasoningResult.from_dict(factory.result_dict())
        for obj, name in ((case, "case_id"), (result, "case_id"), (result, "result_id"), (result, "created_at")):
            with self.subTest(field=name), self.assertRaises(dataclasses.FrozenInstanceError):
                setattr(obj, name, "rc1_" + "f" * 32)

    def test_an_update_cannot_patch_any_immutable_field(self):
        update = factory.update_dict()
        for name in IMMUTABLE_RESULT_FIELDS:
            bad = copy.deepcopy(update)
            bad["changed_fields"].append({"field": name, "value": "x"})
            with self.subTest(field=name):
                self.assertIn("IMMUTABLE_FIELD", codes(update_errors(bad)))
                with self.assertRaises(ContractViolation):
                    ReasoningUpdate.from_dict(bad)
        bad = copy.deepcopy(update)
        bad["preserved_fields"].append("result_id")
        self.assertIn("IMMUTABLE_FIELD", codes(update_errors(bad)))
        bad = copy.deepcopy(update)
        bad["changed_fields"].append({"field": "salary_note", "value": "x"})
        self.assertIn("UNKNOWN_FIELD", codes(update_errors(bad)))

    def test_an_update_cannot_retarget_another_case_or_result(self):
        result = factory.result_dict()
        update = factory.update_dict(result)
        self.assertEqual(update_result_errors(update, result), [])
        for name in ("case_id", "result_id"):
            bad = copy.deepcopy(update)
            bad[name] = ("rc1_" if name == "case_id" else "rr1_") + "f" * 32
            self.assertEqual(update_errors(bad), [])
            self.assertIn("IMMUTABLE_FIELD", codes(update_result_errors(bad, result)))


class SemanticInvariantTests(unittest.TestCase):
    def test_case_invariants(self):
        case = factory.case_dict()
        cases = {
            "PREVIOUS_RESULT_PAIRING": lambda c: c.__setitem__("previous_result_version", None),
            "ORIENTATION_CONFLICT": lambda c: c["contradicting_findings"][0].__setitem__("direction", "adverse"),
            "UNKNOWN_MEMBER": lambda c: c["current_evidence"]["statements"][0].__setitem__("member_key", "other|finding"),
            "STATEMENT_KIND_MISMATCH": lambda c: c["current_evidence"]["statements"][0].__setitem__("kind", "source_fact"),
            "REF_ID_MISMATCH": lambda c: c["current_evidence"]["references"][0].__setitem__("monday_item_id", "9999"),
            "DUPLICATE_FINDING": lambda c: c["supporting_findings"].append(copy.deepcopy(c["supporting_findings"][0])),
        }
        for code, mutate in cases.items():
            bad = copy.deepcopy(case)
            mutate(bad)
            with self.subTest(code=code):
                self.assertIn(code, codes(case_errors(bad)))
        mixed = copy.deepcopy(case)
        mixed["orientation"] = "mixed"
        self.assertIn("ORIENTATION_CONFLICT", codes(case_errors(mixed)), "only an adverse or favourable case can be contradicted")

    def test_material_delta_must_end_at_the_case_fingerprint(self):
        case = factory.case_dict()
        delta = {"delta_version": "material-delta-v1", "fingerprint_before": factory.FP_BEFORE, "fingerprint_after": case["evidence_fingerprint"],
                 "orientation_change": None, "added_findings": [], "removed_findings": [], "added_evidence": [], "removed_evidence": [],
                 "changed_values": [{"member_key": factory.MEMBER_CHANGE, "path": "statements/metric:late_rate_changed/current", "before": 0.6, "after": 0.6875}],
                 "changed_confidence": [], "added_contradictions": [], "removed_contradictions": []}
        good = copy.deepcopy(case)
        good["material_delta"] = delta
        self.assertEqual(case_errors(good), [])
        self.assertEqual(ReasoningCase.from_dict(good).to_dict(), good)
        bad = copy.deepcopy(good)
        bad["material_delta"]["fingerprint_after"] = factory.FP_BEFORE
        self.assertIn("DELTA_FINGERPRINT_MISMATCH", codes(case_errors(bad)))
        self.assertIn("DELTA_NOT_A_CHANGE", codes(case_errors(bad)))

    def test_result_invariants(self):
        result = factory.result_dict()
        bad = copy.deepcopy(result)
        bad["lifecycle_status"] = "superseded"
        self.assertIn("SUPERSEDED_LINK", codes(result_errors(bad)))
        bad["superseded_by"] = {"case_id": result["case_id"], "result_id": "rr1_" + "b" * 32}
        self.assertEqual(result_errors(bad), [])
        bad["superseded_by"]["result_id"] = result["result_id"]
        self.assertIn("SUPERSEDED_LINK", codes(result_errors(bad)))
        bad = copy.deepcopy(result)
        bad["superseded_by"] = {"case_id": result["case_id"], "result_id": "rr1_" + "b" * 32}
        self.assertIn("SUPERSEDED_LINK", codes(result_errors(bad)))
        bad = copy.deepcopy(result)
        bad["updated_at"] = "2026-09-27T00:00:00Z"
        self.assertIn("TIMESTAMP_ORDER", codes(result_errors(bad)))

    def test_update_invariants(self):
        update = factory.update_dict()
        cases = {
            "ACTION_MISMATCH": lambda u: u.__setitem__("action", "no_change"),
            "DUPLICATE_CHANGE": lambda u: u["changed_fields"].append(copy.deepcopy(u["changed_fields"][0])),
            "INVALID_FIELD_VALUE": lambda u: u["changed_fields"][0].__setitem__("value", {"level": "weak"}),
        }
        for code, mutate in cases.items():
            bad = copy.deepcopy(update)
            mutate(bad)
            with self.subTest(code=code):
                self.assertIn(code, codes(update_errors(bad)))
        overlap = copy.deepcopy(update)
        overlap["preserved_fields"].append("confidence")
        self.assertIn("FIELD_ACCOUNTING", codes(update_errors(overlap)))
        no_change = copy.deepcopy(update)
        no_change.update(action="no_change", changed_fields=[], preserved_fields=list(PATCHABLE_FIELDS))
        self.assertEqual(update_errors(no_change), [])
        no_refs = copy.deepcopy(update)
        no_refs["changed_fields"][1]["value"]["evidence_refs"] = []
        self.assertIn("INVALID_FIELD_VALUE", codes(update_errors(no_refs)), "a patched claim still needs evidence")

    def test_update_against_its_result_and_case(self):
        case = factory.case_dict()
        result = factory.result_dict(case)
        update = factory.update_dict(result, case)
        self.assertEqual(update_case_errors(update, case), [])
        stale = copy.deepcopy(update)
        stale["base_version"] = 2
        self.assertIn("STALE_BASE_VERSION", codes(update_result_errors(stale, result)))
        foreign = copy.deepcopy(update)
        foreign["changed_fields"][1]["value"]["evidence_refs"] = ["ev1_" + "e" * 24]
        self.assertIn("UNKNOWN_EVIDENCE_REF", codes(update_case_errors(foreign, case)))
        moved = copy.deepcopy(update)
        moved["evidence_fingerprint_after"] = factory.FP_BEFORE
        self.assertIn("EVIDENCE_FINGERPRINT_MISMATCH", codes(update_case_errors(moved, case)))


class EnumModuleTests(unittest.TestCase):
    def test_every_enum_is_a_str_enum_with_lowercase_values(self):
        for name in dir(enums):
            value = getattr(enums, name)
            if isinstance(value, type) and issubclass(value, StrEnum) and value is not StrEnum:
                for member in value:
                    self.assertRegex(member.value, r"^[a-z][a-z0-9_]*$", f"{name}.{member.name}")


if __name__ == "__main__":
    unittest.main()


class MalformedPatchTests(unittest.TestCase):
    """Review finding: LLM-shaped malformed patches are rejected with ContractViolation, never crash validation."""

    def test_malformed_field_lists_are_violations(self):
        update = factory.update_dict()
        for mutate in (lambda u: u.__setitem__("preserved_fields", 5), lambda u: u.__setitem__("preserved_fields", [["a"]]),
                       lambda u: u["changed_fields"].append({"field": ["title"], "value": 1}), lambda u: u.__setitem__("changed_fields", "title"),
                       lambda u: u["changed_fields"].append("title")):
            bad = copy.deepcopy(update)
            mutate(bad)
            with self.subTest(update=bad.get("changed_fields")), self.assertRaises(ContractViolation):
                ReasoningUpdate.from_dict(bad)
