"""Reasoning V3 Phase 04: the same management issue keeps the same case_id across runs (``REV/04``).

The golden ``fixtures/reasoning/case-identity-showcase.json`` pins every identity the showcase snapshot produces; regenerate it
only for a deliberate identity-rule change (new ``IDENTITY_VERSION``): ``python3 tests/test_reasoning_case_identity.py --write``.
"""

import copy
import json
import random
import sys
import unittest
from pathlib import Path

import reasoning_factory as factory
import reasoning_snapshots as snapshots

from atlas_commander.investigation.catalog import DETECTORS
from atlas_commander.investigation.engine import build_intelligence
from atlas_reasoning import case_identity
from atlas_reasoning.case_identity import CaseIdentityCollision, CaseIdentityError, assert_no_collisions, build_identity, identity_errors
from atlas_reasoning.case_mapping import TOPIC_RULES, identity_of, map_cases, map_findings, member_key, rule_for
from atlas_reasoning.contracts import ContractViolation, ReasoningCase, case_errors
from atlas_reasoning.enums import CaseType, SubjectType, TopicKey
from atlas_reasoning.reasoning_input_boundary import upstream_finding

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "reasoning" / "case-identity-showcase.json"


def golden_document() -> dict:
    mapping = map_cases(snapshots.reasoning_input())
    return {"description": "Every case identity of the showcase snapshot (atlas_commander.demo, contract 1.5.0, demo.GENERATED_AT). Changing it "
                           "means existing cases would get new identities: only with a new IDENTITY_VERSION.",
            "identity_version": case_identity.IDENTITY_VERSION,
            "cases": {c.identity.identity_key: {"case_id": c.case_id, "case_type": c.identity.case_type.value,
                                                "member_keys": [m.member_key for m in c.contributions]} for c in mapping.candidates}}


def _finding_rows() -> list[dict]:
    return snapshots.intelligence_copy()["findings"]


def _ids(rows: list[dict]) -> dict[str, list[str]]:
    mapping = map_findings([upstream_finding(row) for row in rows])
    return {c.case_id: [m.member_key for m in c.contributions] for c in mapping.candidates}


def _numbers(value, factor: float):
    if isinstance(value, dict):
        return {key: _numbers(item, factor) for key, item in value.items()}
    if isinstance(value, list):
        return [_numbers(item, factor) for item in value]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return value * factor + 1


class IdentityConstructionTests(unittest.TestCase):
    def test_case_id_is_a_hash_of_the_normalized_identity_key(self):
        identity = build_identity("editor", "  Editor-Label-12 ", "deadline", "editor_pattern")
        self.assertEqual(identity.subject_id, "editor-label-12")
        self.assertEqual(identity.identity_key, "case-identity-v1|editor|editor-label-12|deadline")
        self.assertRegex(identity.case_id, r"^rc1_[0-9a-f]{32}$")
        self.assertEqual(identity.case_id, build_identity(SubjectType.EDITOR, "editor-label-12", TopicKey.DEADLINE, CaseType.EDITOR_PATTERN).case_id)

    def test_optional_dimensions_are_part_of_identity_only_when_given(self):
        base = build_identity("team", "team", "open_work_risk", "open_work_risk")
        past_eta = build_identity("team", "team", "open_work_risk", "open_work_risk", {"signal": "past_eta"})
        runway = build_identity("team", "team", "open_work_risk", "open_work_risk", {"signal": "short_remaining_runway"})
        self.assertEqual(len({base.case_id, past_eta.case_id, runway.case_id}), 3)
        self.assertTrue(past_eta.identity_key.endswith("|signal=past_eta"))
        ordered = build_identity("editor", "e1", "deadline", "editor_pattern", {"workflow_stage": "runway", "video_type": "premium-short"})
        self.assertEqual(ordered.identity_key, "case-identity-v1|editor|e1|deadline|video_type=premium-short|workflow_stage=runway")

    def test_invalid_components_are_refused(self):
        for args in (("editor", "", "deadline", "editor_pattern"), ("editor", None, "deadline", "editor_pattern"), ("person", "e1", "deadline", "editor_pattern"),
                     ("editor", "e1", "attitude", "editor_pattern"), ("editor", "e1", "deadline", "hr_case")):
            with self.subTest(args=args), self.assertRaises(CaseIdentityError):
                build_identity(*args)
        with self.assertRaises(CaseIdentityError):
            build_identity("editor", "e1", "deadline", "editor_pattern", {"late_rate": "0.3"})
        with self.assertRaises(CaseIdentityError):
            build_identity("editor", "e1", "deadline", "editor_pattern", {"signal": "  "})

    def test_encoding_is_injective(self):
        tricky = build_identity("editor", "a|deadline", "speed", "editor_pattern")
        plain = build_identity("editor", "a", "deadline", "editor_pattern")
        self.assertNotEqual(tricky.identity_key, plain.identity_key)
        self.assertNotEqual(tricky.case_id, plain.case_id)
        self.assertNotEqual(build_identity("editor", "x=y", "deadline", "editor_pattern").identity_key,
                            build_identity("editor", "x", "deadline", "editor_pattern", {"signal": "y"}).identity_key)

    def test_collisions_are_detected_not_merged(self):
        a = build_identity("editor", "e1", "deadline", "editor_pattern")
        b = build_identity("editor", "e2", "deadline", "editor_pattern")
        self.assertEqual(set(assert_no_collisions([a, b, a])), {a.case_id, b.case_id})

        class Forged(type(a)):
            @property
            def case_id(self) -> str:
                return a.case_id

        forged = Forged(b.subject_type, b.subject_id, b.topic_key, b.case_type, b.dimensions)
        with self.assertRaises(CaseIdentityCollision):
            assert_no_collisions([a, forged])

    def test_the_contract_rejects_a_case_whose_id_does_not_follow_from_its_identity(self):
        case = factory.case_dict()
        self.assertEqual(identity_errors(case), [])
        for name, value in (("case_id", "rc1_" + "f" * 32), ("identity_key", "editor:somebody"), ("subject_id", "editor-label-13"), ("topic_key", "speed")):
            bad = copy.deepcopy(case)
            bad[name] = value
            with self.subTest(field=name):
                self.assertIn("CASE_ID_MISMATCH", {e.split(":")[0] for e in case_errors(bad)})
                with self.assertRaises(ContractViolation):
                    ReasoningCase.from_dict(bad)


class MappingRuleTests(unittest.TestCase):
    def test_every_registered_detector_has_a_topic_rule(self):
        for detector in DETECTORS:
            with self.subTest(detector=detector.detector_id):
                self.assertIsNotNone(rule_for(detector.detector_id) if detector.detector_id != "data.quality" else rule_for("data.any_code"))

    def test_rules_name_only_known_finding_types(self):
        known = {detector.detector_id for detector in DETECTORS}
        self.assertEqual(set(TOPIC_RULES) - known, set())

    def test_unknown_types_and_values_are_reported_never_guessed(self):
        rows = _finding_rows()
        unknown = copy.deepcopy(rows[0])
        unknown["finding_type"] = "novel.detector"
        changed = next(copy.deepcopy(r) for r in rows if r["finding_type"] == "change.editor")
        for statement in changed["statements"]:
            statement["params"]["measure"] = "revision_count"
        mapping = map_findings([upstream_finding(unknown), upstream_finding(changed)])
        self.assertEqual(mapping.candidates, ())
        self.assertEqual(sorted(row["finding_type"] for row in mapping.unmapped), ["change.editor", "novel.detector"])
        self.assertTrue(all(row["reason"] for row in mapping.unmapped))

    def test_findings_of_one_issue_share_a_case(self):
        mapping = map_cases(snapshots.reasoning_input())
        cases = {c.identity.identity_key: c for c in mapping.candidates}
        deadline = cases["case-identity-v1|editor|editor-label-12|deadline"]
        types = sorted({m.finding.finding_type for m in deadline.contributions})
        self.assertEqual(types, ["change.editor", "concentration.positive", "contradiction.bad_headline", "person.mix_adjusted_deadline"])
        self.assertEqual(len([m for m in deadline.contributions if m.finding.finding_type == "change.editor"]), 2, "history and comparison window")
        self.assertIn("case-identity-v1|editor|editor-label-12|speed", cases)
        self.assertEqual(mapping.unmapped, ())
        self.assertEqual(mapping.warnings, ())

    def test_member_keys_are_unique_within_every_case(self):
        for at in (snapshots.GENERATED_AT, snapshots.shifted(3)):
            review = build_intelligence(snapshots._reconstruction(), snapshots.CONTRACT, at, mode="review")
            for mode, mapping in (("approved_only", map_cases(snapshots.reasoning_input(at))),
                                  ("review", map_findings([upstream_finding(row) for row in review["findings"]]))):
                with self.subTest(at=at, mode=mode):
                    self.assertEqual((mapping.warnings, mapping.unmapped), ((), ()))
                    for candidate in mapping.candidates:
                        keys = [m.member_key for m in candidate.contributions]
                        self.assertEqual(len(keys), len(set(keys)))


class StabilityTests(unittest.TestCase):
    def test_changed_evidence_values_keep_the_case_id(self):
        rows = _finding_rows()
        changed = copy.deepcopy(rows)
        for row in changed:
            for statement in row["statements"]:
                statement["params"] = _numbers(statement["params"], 1.7)
            for block in row["supporting_evidence"]:
                block["sample"] = _numbers(block["sample"], 2.0)
                block["comparison"] = _numbers(block["comparison"], 0.5)
                for record in block["records"]:
                    record["values"] = _numbers(record["values"], 3.0)
            row["sample_size"] += 7
            row["affected_projects"] = row["affected_projects"][:1]
        self.assertEqual(_ids(changed), _ids(rows))

    def test_late_rate_20_31_45_percent_is_one_case(self):
        row = next(r for r in _finding_rows() if r["finding_type"] == "change.editor" and r["scope"]["editor_id"] == "editor-label-12")
        ids = set()
        for rate in (0.20, 0.31, 0.45):
            variant = copy.deepcopy(row)
            for statement in variant["statements"]:
                statement["params"]["current"] = rate
                statement["params"]["difference"] = rate - statement["params"]["baseline"]
            ids.add(identity_of(upstream_finding(variant)).case_id)
        self.assertEqual(len(ids), 1)

    def test_changed_confidence_keeps_the_case_id(self):
        rows = _finding_rows()
        changed = copy.deepcopy(rows)
        for row in changed:
            row["confidence"]["level"] = {"weak": "strong", "moderate": "weak", "strong": "moderate"}[row["confidence"]["level"]]
            row["confidence"]["factors"] = []
            row["importance"]["rank"] = 99
            row["severity"] = "low"
        self.assertEqual(_ids(changed), _ids(rows))

    def test_volatile_metadata_never_enters_identity(self):
        rows = _finding_rows()
        changed = copy.deepcopy(rows)
        for i, row in enumerate(changed):
            row["finding_id"] = f"{row['finding_type']}:{i:016x}"
            row["time_window"] = {"window": "current", "start_date": "2027-01-01", "end_date_exclusive": "2027-01-31", "completed_days": 30}
            row["text"] = {"en": "different wording"}
            row["limitations"] = ["other"]
        self.assertEqual(_ids(changed), _ids(rows))

    def test_input_order_does_not_matter(self):
        rows = _finding_rows()
        expected = _ids(rows)
        for seed in range(5):
            shuffled = copy.deepcopy(rows)
            random.Random(seed).shuffle(shuffled)
            for row in shuffled:
                random.Random(seed).shuffle(row["supporting_evidence"])
            self.assertEqual(_ids(shuffled), expected)
            self.assertEqual(list(_ids(shuffled)), list(expected), "candidates come out in case_id order")

    def test_different_topic_and_different_editor_separate(self):
        mapping = map_cases(snapshots.reasoning_input())
        keys = {c.identity.identity_key: c.case_id for c in mapping.candidates}
        self.assertNotEqual(keys["case-identity-v1|editor|editor-label-12|deadline"], keys["case-identity-v1|editor|editor-label-12|speed"])
        self.assertNotEqual(keys["case-identity-v1|editor|editor-label-12|deadline"], keys["case-identity-v1|editor|editor-label-15|deadline"])
        self.assertEqual(len(set(keys.values())), len(keys))
        row = next(r for r in _finding_rows() if r["finding_type"] == "editor.speed_pattern")
        moved = copy.deepcopy(row)
        moved["scope"]["editor_id"] = "editor-label-99"
        self.assertNotEqual(identity_of(upstream_finding(row)).case_id, identity_of(upstream_finding(moved)).case_id)

    def test_historical_replay_keeps_identities(self):
        """Rebuild the snapshot with the analysis windows moved forward: finding IDs change, persisting issues keep their case."""
        base = map_cases(snapshots.reasoning_input())
        base_ids = {c.identity.identity_key: c.case_id for c in base.candidates}
        base_findings = {f.finding_id for f in snapshots.reasoning_input().findings}
        for days in (1, 7):
            at = snapshots.shifted(days)
            with self.subTest(days=days):
                replay = map_cases(snapshots.reasoning_input(at))
                self.assertEqual(replay.unmapped, ())
                replay_ids = {c.identity.identity_key: c.case_id for c in replay.candidates}
                shared = set(base_ids) & set(replay_ids)
                self.assertGreaterEqual(len(shared), len(base_ids) // 2, "most issues persist one week later")
                for key in shared:
                    self.assertEqual(replay_ids[key], base_ids[key])
                moved = base_findings - {f.finding_id for f in snapshots.reasoning_input(at).findings}
                self.assertTrue(moved, "the analysis window moved, so window-scoped finding IDs changed")
        self.assertEqual(map_cases(snapshots.reasoning_input()).by_case_id().keys(), base.by_case_id().keys())

    def test_identity_golden(self):
        self.assertEqual(golden_document(), json.loads(GOLDEN.read_text()),
                         "case identities changed: that orphans existing cases; bump IDENTITY_VERSION and regenerate deliberately")

    def test_member_keys_survive_value_changes(self):
        row = next(r for r in _finding_rows() if r["finding_type"] == "person.mix_adjusted_deadline")
        variant = copy.deepcopy(row)
        for statement in variant["statements"]:
            statement["params"] = _numbers(statement["params"], 1.3)
        self.assertEqual(member_key(upstream_finding(row)), member_key(upstream_finding(variant)))


if __name__ == "__main__":
    if sys.argv[1:] == ["--write"]:
        GOLDEN.write_text(json.dumps(golden_document(), indent=1) + "\n")
    else:
        unittest.main()
