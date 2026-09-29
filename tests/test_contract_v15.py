"""Contract 1.5 configuration and historical identity-key behavior."""

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import monday_factory as mf

from atlas_commander.contracts import schema_errors
from atlas_commander.identity import (
    EDITOR_IDENTITY_OUTSIDE_OBSERVED_RANGE,
    INVALID_IDENTITY_VALUE,
    UNMAPPED_EDITOR,
    UNRESOLVED_HISTORICAL_IDENTITY,
    EditorObservation,
    IdentityMapping,
    resolve_editor,
)
from atlas_commander.pipeline import reconstruct_cycles
from atlas_commander.runtime import (
    ACTIVE_CONTRACT_VERSION,
    ContractConfigError,
    load_contract,
    load_contract_version,
    resolve_contract_editor,
)


def observation(source_label_id: str, logged_name: str) -> EditorObservation:
    return EditorObservation(
        monday_board_id="5091110326",
        monday_item_id="item-1",
        column_id="dropdown_mm1emgt8",
        person_ids=(source_label_id,),
        source="editor_column_event",
        event_id="event-1",
        observed_at="2026-09-01T09:00:00Z",
        label_names=(logged_name,),
    )


class ContractV15ConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract_version("1.5.0")

    def test_contract_is_loadable_validated_and_not_activated_by_this_atomic_change(self):
        self.assertEqual(self.contract["contract_version"], "1.5.0")
        self.assertEqual(schema_errors(self.contract, "monday-contract-v1.5.schema.json"), [])
        self.assertEqual(ACTIVE_CONTRACT_VERSION, "1.4.0")
        self.assertEqual(load_contract_version("1.4.0")["contract_version"], "1.4.0")

    def test_settled_decisions_and_rule_versions_are_complete(self):
        self.assertEqual(set(self.contract["authority"]["settled_decisions"]), {f"D{number}" for number in range(20, 51)})
        self.assertEqual(
            set(self.contract["rule_versions"]),
            {
                "windowing", "identity", "quality_labels", "quality_component", "speed_benchmark", "speed_component",
                "deadline_fact", "deadline_component", "overall_status", "recent_change", "trend", "revision_context",
                "active_work", "evidence", "coverage",
            },
        )

    def test_quality_registries_separate_visible_and_scored_labels(self):
        registries = self.contract["quality_labels"]["registries"]
        self.assertEqual([entry["label"] for entry in registries["positive"]],
                         ["1- Exceptional Quality", "Saved Rush Project", "Client Praise", "On Time Delivery"])
        self.assertEqual([entry["label"] for entry in registries["context"]], ["High Workload", "Additional Revisions"])
        self.assertEqual(len(registries["negative"]), 7)
        self.assertFalse(next(entry for entry in registries["negative"] if entry["label"] == "Late Delivery")["scored_quality"])
        self.assertFalse(next(entry for entry in registries["positive"] if entry["label"] == "On Time Delivery")["scored_quality"])
        self.assertTrue(next(entry for entry in registries["positive"] if entry["label"] == "Saved Rush Project")["scored_quality"])
        self.assertTrue(all(not entry["scored_quality"] for entry in registries["context"]))

    def test_windows_work_revisions_benchmarks_and_coverage_are_explicit(self):
        self.assertEqual(self.contract["time_windows"]["timezone"], "Africa/Cairo")
        self.assertEqual(self.contract["time_windows"]["current_window"], {"completed_days": 30, "exclude_current_local_day": True})
        self.assertTrue(self.contract["speed_benchmark"]["leave_one_out"])
        self.assertEqual(self.contract["deadline"]["component"]["team_population"], "other-eligible-editors-only-same-window")
        self.assertEqual(self.contract["active_work"]["active_statuses"], ["In Progress", "Revisions", "Internal Revisions"])
        self.assertEqual(self.contract["active_work"]["awaiting_approval_statuses"], ["Ready For Approval"])
        self.assertFalse(self.contract["revision_context"]["scored"])
        self.assertEqual(self.contract["threshold_governance"]["status"], "blocked_unresolved_identities")
        self.assertFalse(self.contract["threshold_governance"]["pre_resolution_calibration_approved"])
        self.assertEqual(self.contract["deadline"]["team_wide_lateness"], "process-diagnostic-only-never-an-editor-scoring-input")
        self.assertTrue(self.contract["evidence_requirements"]["raw_identity_evidence_retained_on_quarantine"])
        self.assertFalse(self.contract["coverage_requirements"]["unresolved_identities_enter_calibration"])

    def test_every_unapproved_threshold_is_null_and_marked(self):
        speed = self.contract["speed_benchmark"]
        self.assertEqual((speed["minimum_editor_sample_size"], speed["minimum_comparator_sample_size"]), (None, None))
        self.assertEqual((speed["minimum_editor_sample_size_status"], speed["minimum_comparator_sample_size_status"]),
                         ("rule_not_approved", "rule_not_approved"))
        self.assertEqual({speed["component"][key] for key in ("faster_band", "similar_band", "slower_band")}, {None})
        deadline = self.contract["deadline"]["component"]
        self.assertEqual({deadline[key] for key in ("better_band", "similar_band", "worse_band", "minimum_editor_sample_size",
                                                    "minimum_comparator_sample_size")}, {None})
        interpretation = self.contract["interpretation"]
        self.assertIsNone(interpretation["overall_status"]["lookup_table"])
        self.assertEqual(interpretation["overall_status"]["threshold_status"], "rule_not_approved")
        self.assertEqual({interpretation["quality_component"][key] for key in
                          ("negative_rate_threshold", "positive_rate_threshold", "minimum_project_sample_size")}, {None})
        self.assertEqual((interpretation["trend"]["minimum_sample_size"], interpretation["trend"]["material_change_threshold"]),
                         (None, None))
        self.assertIsNone(self.contract["active_work"]["capacity_threshold"])

    def test_loader_rejects_schema_invalid_15_config(self):
        invalid = copy.deepcopy(self.contract)
        invalid["speed_benchmark"]["minimum_comparator_sample_size"] = 5
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(invalid))
            with self.assertRaisesRegex(ContractConfigError, "not of type 'null'"):
                load_contract(path)


class ContractV15IdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract_version("1.5.0")

    def assertQuarantined(self, source_label_id: str, logged_name: str, code: str):
        result = resolve_contract_editor(observation(source_label_id, logged_name), self.contract)
        self.assertFalse(result.resolved)
        self.assertIsNotNone(result.exception)
        assert result.exception is not None
        self.assertEqual(result.exception.code, code)
        self.assertEqual(result.exception.person_ids, (source_label_id,))
        self.assertEqual(result.exception.logged_names, (logged_name,))
        self.assertEqual((result.exception.event_id, result.exception.observed_at), ("event-1", "2026-09-01T09:00:00Z"))
        return result

    def test_exact_source_label_and_logged_name_resolves(self):
        result = resolve_contract_editor(observation("6", "Will"), self.contract)
        self.assertTrue(result.resolved)
        assert result.identity is not None
        self.assertEqual((result.identity["editor_id"], result.identity["mapping_version"]), ("editor-label-6", "monday-editor-v1.2"))

    def test_new_name_under_known_source_label_never_inherits_mapping(self):
        self.assertQuarantined("6", "Another Will", UNMAPPED_EDITOR)
        self.assertQuarantined("12", "Anas", UNMAPPED_EDITOR)

    def test_same_name_under_another_source_label_does_not_merge(self):
        self.assertQuarantined("9", "Michael", UNMAPPED_EDITOR)
        self.assertTrue(resolve_contract_editor(observation("13", "Michael"), self.contract).resolved)

    def test_observed_dates_validate_but_do_not_replace_the_tuple_key(self):
        mapping = IdentityMapping.from_dict({
            "mapping_version": "bounded-v1",
            "identity_key": ["source_label_id", "logged_name"],
            "entries": [{
                "source_label_id": "6", "logged_name": "Will", "editor_id": "editor-label-6",
                "canonical_editor_name": "Will", "role": "editor", "first_observed_at": "2026-03-14T00:00:00Z",
                "last_observed_at": "2026-09-27T23:59:59Z", "attestation_source": "test evidence", "decision_id": "D16",
            }],
        })
        too_early = replace(observation("6", "Will"), observed_at="2026-03-13T23:59:59Z")
        result = resolve_editor(too_early, mapping)
        self.assertEqual(result.exception.code, EDITOR_IDENTITY_OUTSIDE_OBSERVED_RANGE)
        self.assertEqual(resolve_editor(observation("6", "Other"), mapping).exception.code, UNMAPPED_EDITOR)
        invalid_time = replace(observation("6", "Will"), observed_at="not-a-timestamp")
        self.assertEqual(resolve_editor(invalid_time, mapping).exception.code, "MISSING_EVIDENCE")

    def test_named_unresolved_identities_remain_unresolved(self):
        pairs = [("4", "Mario"), ("5", "Anas"), ("7", "Martin"), ("8", "Samra"), ("9", "Ibrahim"),
                 ("10", "Amir"), ("11", "Refaat"), ("5", "Ahmed"), ("7", "Mans"), ("9", "Michael")]
        for source_label_id, logged_name in pairs:
            with self.subTest(identity=(source_label_id, logged_name)):
                self.assertQuarantined(source_label_id, logged_name, UNMAPPED_EDITOR)

    def test_d50_reasons_are_exact_and_retain_raw_evidence(self):
        self.assertQuarantined("11", "New", INVALID_IDENTITY_VALUE)
        self.assertQuarantined("2", "Done", INVALID_IDENTITY_VALUE)
        self.assertQuarantined("1", "El Baz", UNRESOLVED_HISTORICAL_IDENTITY)

    def test_pipeline_uses_the_strict_historical_key_and_keeps_d50_evidence(self):
        logs = [
            mf.editor("editor", "1", "2026-09-01T09:00:00Z", [11], ["New"]),
            mf.video_type("video", "1", "2026-09-01T09:00:01Z", [4]),
            mf.status("start", "1", "2026-09-01T10:00:00Z", "Create File", "In Progress"),
            mf.status("end", "1", "2026-09-01T12:00:00Z", "In Progress", "Ready For Approval"),
        ]
        cycle = reconstruct_cycles(mf.payload(*logs), self.contract).cycles[0]
        self.assertIsNone(cycle.editor_id)
        self.assertIn(INVALID_IDENTITY_VALUE, cycle.exclusions)
        assert cycle.editor_exception is not None
        self.assertEqual(cycle.editor_exception["source_label_ids"], ["11"])
        self.assertEqual(cycle.editor_exception["logged_names"], ["New"])
        self.assertEqual(cycle.editor_exception["event_id"], "editor")

    def test_no_unresolved_or_d50_identity_was_attested(self):
        mapped = {(entry["source_label_id"], entry["logged_name"]) for entry in self.contract["editor_attribution"]["entries"]}
        unresolved = {(entry["source_label_id"], entry["logged_name"])
                      for entry in self.contract["editor_attribution"]["named_unresolved_identities"]}
        quarantined = {(entry["source_label_id"], entry["logged_name"])
                       for entry in self.contract["editor_attribution"]["quarantine_reasons"]}
        self.assertFalse(mapped & unresolved)
        self.assertFalse(mapped & quarantined)


if __name__ == "__main__":
    unittest.main()
