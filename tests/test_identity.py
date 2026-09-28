import json
import unittest
from dataclasses import replace
from itertools import permutations

from atlas_commander.contracts import ROOT, schema_errors
from atlas_commander.identity import EditorEvidence, IdentityResolutionError, resolve_editor


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.row = json.loads((ROOT / "fixtures/good/editor-identity.json").read_text())
        self.evidence = EditorEvidence("board-1", "item-1", "editor", "event-100", ("person-42",))

    def resolve(self, evidence=None, rows=None, version="identity-v1"):
        return resolve_editor(evidence or self.evidence, [self.row] if rows is None else rows, version)

    def assert_quarantined(self, code, **kwargs):
        with self.assertRaises(IdentityResolutionError) as caught:
            self.resolve(**kwargs)
        error = caught.exception
        self.assertEqual(error.code, code)
        self.assertEqual(error.exception_output["code"], code)
        self.assertNotIn("editor_id", error.exception_output)
        json.dumps(error.exception_output)
        return error.exception_output

    def test_fixture_resolves_to_contract_with_provenance(self):
        result = self.resolve()
        self.assertEqual(result, self.row)
        self.assertEqual(schema_errors(result, "editor-identity.schema.json"), [])
        self.assertEqual(result["monday_person_id"], self.evidence.monday_person_ids[0])

    def test_missing_editor_fixture_is_quarantined(self):
        fixture = json.loads((ROOT / "fixtures/bad/missing-editor.json").read_text())
        self.assertNotIn("editor_id", fixture)
        evidence = replace(self.evidence, monday_board_id=fixture["monday_board_id"],
                           monday_item_id=fixture["monday_item_id"], monday_person_ids=())
        output = self.assert_quarantined("MISSING_EDITOR", evidence=evidence)
        self.assertEqual(output["evidence"]["monday_item_id"], fixture["monday_item_id"])

    def test_multiple_editor_values_are_ambiguous(self):
        self.assert_quarantined("AMBIGUOUS_EDITOR", evidence=replace(self.evidence, monday_person_ids=("person-42", "person-43")))

    def test_conflicting_mappings_are_deterministic(self):
        rows = [self.row, dict(self.row, editor_id="editor-other")]
        outputs = [self.assert_quarantined("AMBIGUOUS_EDITOR", rows=order) for order in permutations(rows)]
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0]["candidate_editor_ids"], ["editor-42", "editor-other"])

    def test_duplicate_identical_evidence_and_rows_are_harmless(self):
        self.assertEqual(self.resolve(evidence=replace(self.evidence, monday_person_ids=("person-42", "person-42")),
                                      rows=[self.row, self.row]), self.row)

    def test_version_is_explicit_and_never_falls_forward(self):
        newer = dict(self.row, mapping_version="identity-v2", editor_id="editor-new")
        self.assertEqual(self.resolve(rows=[newer, self.row]), self.row)
        self.assertEqual(self.resolve(rows=[self.row, newer], version="identity-v2"), newer)
        self.assert_quarantined("UNMAPPED_EDITOR", rows=[newer])
        self.assert_quarantined("MISSING_MAPPING_VERSION", version="")

    def test_display_names_cannot_resolve_identity(self):
        for value in ("Fixture Editor", "fixture editor", "person-42 ", "PERSON-42"):
            with self.subTest(value=value):
                self.assert_quarantined("UNMAPPED_EDITOR", evidence=replace(self.evidence, monday_person_ids=(value,)))
        self.assertEqual(self.resolve(rows=[dict(self.row, display_name="Renamed Editor")])["editor_id"], "editor-42")

    def test_no_current_assignee_without_event_evidence(self):
        self.assert_quarantined("MISSING_EDITOR_EVIDENCE", evidence=replace(self.evidence, event_id=""))
        self.assert_quarantined("MISSING_EDITOR", evidence=replace(self.evidence, monday_person_ids=()))

    def test_evidence_must_be_monday_and_traceable(self):
        for field in ("monday_board_id", "monday_item_id", "column_id", "event_id", "source"):
            with self.subTest(field=field):
                self.assert_quarantined("MISSING_EDITOR_EVIDENCE", evidence=replace(self.evidence, **{field: ""}))
        self.assert_quarantined("MISSING_EDITOR_EVIDENCE", evidence=replace(self.evidence, source="ai"))

    def test_invalid_editor_values_are_not_coerced(self):
        for ids in (("",), ("   ",), (42,), "person-42"):
            with self.subTest(ids=ids):
                self.assert_quarantined("INVALID_EDITOR", evidence=replace(self.evidence, monday_person_ids=ids))

    def test_invalid_matching_mapping_is_quarantined(self):
        for updates in ({"editor_id": ""}, {"display_name": " "}, {"resolution": "fuzzy"},
                        {"contract_version": "2.0.0"}, {"extra": "value"}):
            with self.subTest(updates=updates):
                self.assert_quarantined("INVALID_IDENTITY_MAPPING", rows=[dict(self.row, **updates)])

    def test_conflicting_display_metadata_is_not_order_dependent(self):
        self.assert_quarantined("AMBIGUOUS_EDITOR", rows=[self.row, dict(self.row, display_name="Different")])

    def test_output_is_detached_from_input(self):
        result = self.resolve()
        result["editor_id"] = "changed"
        self.assertEqual(self.resolve(), self.row)


if __name__ == "__main__":
    unittest.main()
