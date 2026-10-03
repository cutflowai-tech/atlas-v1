"""Lossless evidence-input compaction (analyst-input-v2, update-input-v2, review-input-v2).

The case view sent to the model groups evidence references by the fields every record of one evidence block shares (``member_key``,
``role``, ``evidence_code``), written once per group. The canonical case, its fingerprint, every ``ref_id`` and the validator are
unchanged; only the serialization of the model input changes. These tests prove that the v2 input carries exactly the v1 information.
"""

import copy
import json
import random
import unittest

import reasoning_snapshots as snapshots

from atlas_reasoning import analyst, reviewer, updater
from atlas_reasoning.analyst import canonical_json, case_evidence_input, flat_evidence_references
from atlas_reasoning.change_gate import prepare_cases
from atlas_reasoning.contracts import PATCHABLE_FIELDS, ReasoningCase

T0 = "2026-09-28T00:10:00Z"
GROUP_KEYS = ("member_key", "role", "evidence_code")


def documents() -> list[dict]:
    return [dict(case.document) for case in prepare_cases(snapshots.reasoning_input(), T0)[1].values()]


def v1_references(document: dict) -> list[dict]:
    """The analyst-input-v1 reference list, written out independently of the code under test."""
    return sorted(({"ref_id": ref["ref_id"], "member_key": ref["member_key"], "role": ref["role"], "evidence_code": ref["evidence_code"],
                    "monday_item_id": ref["monday_item_id"], "cycle_id": ref["cycle_id"], "editor_id": ref["editor_id"],
                    "video_type_key": ref["video_type_key"], "source_timestamps": sorted(ref["source_timestamps"]), "values": ref["values"]}
                   for ref in document["current_evidence"]["references"]), key=lambda row: row["ref_id"])


def with_many_records(document: dict, count: int = 40) -> dict:
    """A case shaped like production: one block carrying many records (the live site has blocks of 300-800)."""
    document = copy.deepcopy(document)
    references = document["current_evidence"]["references"]
    template = references[0]
    for i in range(count):
        references.append({**copy.deepcopy(template), "ref_id": f"ev1_{i:024x}", "monday_item_id": f"9{i:06d}",
                           "source_timestamps": [f"2026-07-{1 + i % 28:02d}T00:00:00Z"], "values": {"index": i}})
    return document


class LosslessTests(unittest.TestCase):
    def setUp(self):
        self.documents = documents()
        self.assertTrue(self.documents)

    def test_the_versions_record_the_new_input_shape(self):
        self.assertEqual(analyst.ANALYST_INPUT_VERSION, "analyst-input-v2")
        self.assertEqual(updater.UPDATE_INPUT_VERSION, "update-input-v2")
        document = self.documents[0]
        candidate = {name: None for name in PATCHABLE_FIELDS}
        self.assertEqual(reviewer.review_input(document, candidate)["input_version"], "review-input-v2")

    def test_flattening_the_groups_restores_exactly_the_v1_references(self):
        for document in [*self.documents, with_many_records(self.documents[0])]:
            with self.subTest(case=document["identity_key"]):
                self.assertEqual(flat_evidence_references(analyst.analyst_input(document)), v1_references(document))

    def test_every_ref_id_appears_once_and_only_shared_fields_move(self):
        for document in [*self.documents, with_many_records(self.documents[0])]:
            groups = analyst.analyst_input(document)["evidence_references"]
            ref_ids = [record["ref_id"] for group in groups for record in group["records"]]
            self.assertEqual(sorted(ref_ids), sorted(ref["ref_id"] for ref in document["current_evidence"]["references"]))
            self.assertEqual(len(ref_ids), len(set(ref_ids)))
            keys = [tuple(group[key] for key in GROUP_KEYS) for group in groups]
            self.assertEqual(keys, sorted(set(keys)))                                   # one group per shared key, sorted
            for group in groups:
                self.assertEqual(set(group), {*GROUP_KEYS, "records"})
                self.assertTrue(group["records"])
                self.assertEqual([r["ref_id"] for r in group["records"]], sorted(r["ref_id"] for r in group["records"]))
                for record in group["records"]:
                    self.assertEqual(set(record), {"ref_id", "monday_item_id", "cycle_id", "editor_id", "video_type_key", "source_timestamps", "values"})

    def test_everything_but_the_references_is_unchanged(self):
        for document in self.documents:
            view = case_evidence_input(document)
            references = view.pop("evidence_references")
            self.assertEqual(flat_evidence_references({"evidence_references": references}), v1_references(document))
            self.assertEqual(set(view), {"case", "orientation", "supporting_findings", "contradicting_findings", "statements", "evidence_blocks",
                                         "manager_context", "memory_context", "provenance"})
            self.assertEqual(view["provenance"]["evidence_fingerprint"], document["evidence_fingerprint"])

    def test_the_canonical_case_is_not_touched(self):
        for document in self.documents:
            before = copy.deepcopy(document)
            analyst.analyst_input(document)
            self.assertEqual(document, before)
            self.assertEqual(ReasoningCase.from_dict(document).to_dict(), before)          # still a valid canonical case

    def test_same_evidence_gives_byte_identical_input(self):
        document = with_many_records(self.documents[0])
        expected = canonical_json(analyst.analyst_input(document))
        for seed in range(3):
            shuffled = copy.deepcopy(document)
            random.Random(seed).shuffle(shuffled["current_evidence"]["references"])
            self.assertEqual(canonical_json(analyst.analyst_input(shuffled)), expected)

    def test_shared_fields_are_written_once_per_block(self):
        document = with_many_records(self.documents[0])
        v2 = canonical_json(analyst.analyst_input(document))
        v1 = canonical_json({**analyst.analyst_input(document), "evidence_references": v1_references(document)})
        self.assertLess(len(v2), len(v1))
        member_key = document["current_evidence"]["references"][0]["member_key"]
        self.assertEqual(v2.count(json.dumps(member_key)) < v1.count(json.dumps(member_key)), True)

    def test_update_and_review_inputs_share_the_grouped_view(self):
        document = self.documents[0]
        view = case_evidence_input(document)
        candidate = {name: None for name in PATCHABLE_FIELDS}
        self.assertEqual(reviewer.review_input(document, candidate)["case"]["evidence_references"], view["evidence_references"])


if __name__ == "__main__":
    unittest.main()
