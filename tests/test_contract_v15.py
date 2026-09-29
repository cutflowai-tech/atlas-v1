"""Contract 1.5 configuration and historical identity-key behavior."""

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import monday_factory as mf

from atlas_commander.contracts import schema_errors
from atlas_commander.cycles import EDITOR_CHANGED_WITHIN_CYCLE
from atlas_commander.dashboard import editor_summary
from atlas_commander.identity import (
    EDITOR_IDENTITY_OUTSIDE_OBSERVED_RANGE,
    INVALID_IDENTITY_VALUE,
    UNMAPPED_EDITOR,
    UNRESOLVED_HISTORICAL_IDENTITY,
    EditorObservation,
    IdentityMapping,
    resolve_editor,
)
from atlas_commander.intelligence import EvidenceScope, quality_rates
from atlas_commander.pipeline import reconstruct_cycles, reconstruct_quality
from atlas_commander.profile import build_editor_profile
from atlas_commander.profile_cli import build_all
from atlas_commander.runtime import (
    ACTIVE_CONTRACT_VERSION,
    ContractConfigError,
    load_contract,
    load_contract_version,
    resolve_contract_editor,
)


def observation(source_label_id: str, logged_name: str, observed_at: str = "2026-09-01T09:00:00Z") -> EditorObservation:
    return EditorObservation(
        monday_board_id="5091110326",
        monday_item_id="item-1",
        column_id="dropdown_mm1emgt8",
        person_ids=(source_label_id,),
        source="editor_column_event",
        event_id="event-1",
        observed_at=observed_at,
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
        self.assertEqual(set(self.contract["authority"]["settled_decisions"]), {f"D{number}" for number in range(20, 52)})
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
        self.assertEqual(self.contract["threshold_governance"]["status"], "identity_gate_satisfied_thresholds_unapproved")
        self.assertEqual(self.contract["threshold_governance"]["governing_decision"], "D44")
        self.assertEqual(self.contract["threshold_governance"]["blocking_identity_keys"], [])
        self.assertEqual(self.contract["threshold_governance"]["completed_steps"],
                         ["approve_identity_mappings", "update_identity_mapping", "record_identity_decision",
                          "rerun_production_distributions", "propose_threshold_values"])
        self.assertEqual(self.contract["threshold_governance"]["threshold_approval_status"], "rule_not_approved")
        self.assertFalse(self.contract["threshold_governance"]["pre_resolution_calibration_approved"])
        self.assertEqual(self.contract["deadline"]["team_wide_lateness"], "process-diagnostic-only-never-an-editor-scoring-input")
        self.assertTrue(self.contract["evidence_requirements"]["raw_identity_evidence_retained_on_quarantine"])
        self.assertFalse(self.contract["coverage_requirements"]["unresolved_identities_enter_calibration"])

    def test_every_unapproved_threshold_is_null_and_marked(self):
        speed = self.contract["speed_benchmark"]
        self.assertEqual((speed["minimum_editor_sample_size"], speed["minimum_comparator_sample_size"]), (None, None))
        self.assertEqual((speed["minimum_editor_sample_size_status"], speed["minimum_comparator_sample_size_status"]),
                         ("rule_not_approved", "rule_not_approved"))
        self.assertEqual((speed["minimum_comparator_editor_count"], speed["minimum_comparator_editor_count_status"]), (None, "rule_not_approved"))
        self.assertEqual({speed["component"][key] for key in ("faster_band", "slower_band")}, {None})
        self.assertNotIn("similar_band", speed["component"])
        deadline = self.contract["deadline"]["component"]
        self.assertEqual({deadline[key] for key in ("better_band", "worse_band", "minimum_editor_sample_size",
                                                    "minimum_comparator_sample_size")}, {None})
        self.assertNotIn("similar_band", deadline)
        interpretation = self.contract["interpretation"]
        self.assertIsNone(interpretation["overall_status"]["lookup_table"])
        self.assertEqual(interpretation["overall_status"]["threshold_status"], "rule_not_approved")
        self.assertEqual({interpretation["quality_component"][key] for key in
                          ("negative_rate_threshold", "positive_rate_threshold", "minimum_project_sample_size")}, {None})
        self.assertIsNone(interpretation["trend"]["minimum_sample_size"])
        self.assertEqual(interpretation["trend"]["material_change_thresholds"],
                         {"positive_quality_rate": None, "negative_quality_rate": None, "late_rate": None, "median_speed_seconds": None})
        self.assertEqual(interpretation["trend"]["directions"]["late_rate"], "lower_is_better")
        self.assertEqual(interpretation["trend"]["directions"]["negative_quality_rate"], "lower_is_better")
        self.assertIsNone(self.contract["active_work"]["capacity_threshold"])

    def test_loader_rejects_schema_invalid_15_config(self):
        invalid = copy.deepcopy(self.contract)
        invalid["speed_benchmark"]["minimum_comparator_sample_size"] = 5
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(invalid))
            with self.assertRaisesRegex(ContractConfigError, "not of type 'null'"):
                load_contract(path)

    def test_loader_rejects_tampered_d49_canonical_identity(self):
        invalid = copy.deepcopy(self.contract)
        michael = next(entry for entry in invalid["editor_attribution"]["entries"]
                       if (entry.get("source_label_id"), entry.get("logged_name")) == ("9", "Michael"))
        michael["editor_id"] = "editor-label-12"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(invalid))
            with self.assertRaisesRegex(ContractConfigError, "D49 identity attestations"):
                load_contract(path)

    def test_loader_rejects_misspelled_or_alias_rule_keys(self):
        # A typo in a threshold key must fail loudly, never silently leave the rule unapproved (SF-1).
        cases = {"quality typo": ("interpretation", "quality_component", "negative_rate_treshold", 0.3),
                 "overall alias": ("interpretation", "overall_status", "lookup", {}),
                 "trend singular": ("interpretation", "trend", "material_change_threshold", None)}
        for name, (section, rule, key, value) in cases.items():
            with self.subTest(case=name):
                invalid = copy.deepcopy(self.contract)
                invalid[section][rule][key] = value
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "contract.json"
                    path.write_text(json.dumps(invalid))
                    with self.assertRaises(ContractConfigError):
                        load_contract(path)

    def test_loader_rejects_a_historical_tuple_made_ongoing_or_an_editor_made_historical(self):
        for key, validity in ((("5", "Ahmed"), "ongoing"), (("4", "Mario"), "historical")):
            with self.subTest(identity=key):
                invalid = copy.deepcopy(self.contract)
                entry = next(e for e in invalid["editor_attribution"]["entries"] if (e["source_label_id"], e["logged_name"]) == key)
                entry["validity"] = validity
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "contract.json"
                    path.write_text(json.dumps(invalid))
                    with self.assertRaisesRegex(ContractConfigError, "D51 validity"):
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
        self.assertEqual((result.identity["editor_id"], result.identity["mapping_version"]), ("editor-label-6", "monday-editor-v1.3"))

    def test_new_name_under_known_source_label_never_inherits_mapping(self):
        self.assertQuarantined("6", "Another Will", UNMAPPED_EDITOR)
        self.assertQuarantined("12", "Anas", UNMAPPED_EDITOR)

    def test_historical_reused_names_merge_only_to_the_attested_canonical_ids(self):
        cases = [
            ("5", "Ahmed", "2026-04-01T10:00:00Z", "editor-label-12"),
            ("7", "Mans", "2026-04-01T10:00:00Z", "editor-label-14"),
            ("9", "Michael", "2026-04-01T10:00:00Z", "editor-label-13"),
        ]
        for source_label_id, logged_name, observed_at, canonical_id in cases:
            with self.subTest(identity=(source_label_id, logged_name)):
                result = resolve_contract_editor(observation(source_label_id, logged_name, observed_at), self.contract)
                self.assertTrue(result.resolved)
                self.assertEqual(result.identity["editor_id"], canonical_id)

    def test_attested_editors_resolve_at_exact_observed_timestamp_bounds(self):
        cases = [
            ("4", "Mario", "2026-03-14T00:44:34.286658Z", "2026-09-28T23:40:30.586199Z", "editor-label-4"),
            ("5", "Anas", "2026-05-18T21:18:49.066589Z", "2026-09-28T23:53:06.778508Z", "editor-label-5"),
            ("7", "Martin", "2026-05-12T16:18:07.005690Z", "2026-09-28T23:46:48.811226Z", "editor-label-7"),
            ("8", "Samra", "2026-03-14T06:03:43.139996Z", "2026-08-11T21:21:19.738906Z", "editor-label-8"),
            ("9", "Ibrahim", "2026-05-03T14:10:25.391996Z", "2026-09-29T11:28:22.791445Z", "editor-label-9"),
            ("10", "Amir", "2026-04-22T16:43:52.478289Z", "2026-09-28T23:50:05.196143Z", "editor-label-10"),
            ("11", "Refaat", "2026-06-29T01:31:10.174360Z", "2026-09-28T23:51:39.316328Z", "editor-label-11"),
            ("5", "Ahmed", "2026-03-14T05:58:12.013277Z", "2026-05-04T10:50:59.999145Z", "editor-label-12"),
            ("7", "Mans", "2026-03-14T06:03:36.639229Z", "2026-05-06T08:13:45.547424Z", "editor-label-14"),
            ("9", "Michael", "2026-03-14T06:03:49.632351Z", "2026-05-02T20:03:48.180209Z", "editor-label-13"),
        ]
        for source_label_id, logged_name, first, last, canonical_id in cases:
            with self.subTest(identity=(source_label_id, logged_name)):
                for observed_at in (first, last):
                    result = resolve_contract_editor(observation(source_label_id, logged_name, observed_at), self.contract)
                    self.assertTrue(result.resolved)
                    self.assertEqual(result.identity["editor_id"], canonical_id)
        before = resolve_contract_editor(observation("8", "Samra", "2026-03-14T06:03:43.139995Z"), self.contract)
        self.assertEqual(before.exception.code, EDITOR_IDENTITY_OUTSIDE_OBSERVED_RANGE, "no mapping applies before its first attested observation")

    def test_confirmed_current_editors_keep_resolving_after_their_observed_range(self):
        # D51: the observed range is evidence, not an expiry date, for the seven confirmed current Editors.
        ongoing = {("4", "Mario"): "editor-label-4", ("5", "Anas"): "editor-label-5", ("7", "Martin"): "editor-label-7",
                   ("8", "Samra"): "editor-label-8", ("9", "Ibrahim"): "editor-label-9", ("10", "Amir"): "editor-label-10",
                   ("11", "Refaat"): "editor-label-11"}
        for (source_label_id, logged_name), canonical_id in ongoing.items():
            for observed_at in ("2026-09-30T08:00:00Z", "2026-10-05T12:00:00Z", "2027-06-01T00:00:00Z"):
                with self.subTest(identity=(source_label_id, logged_name), observed_at=observed_at):
                    result = resolve_contract_editor(observation(source_label_id, logged_name, observed_at), self.contract)
                    self.assertTrue(result.resolved, result.exception)
                    self.assertEqual(result.identity["editor_id"], canonical_id)

    def test_historical_reused_identities_stay_bounded(self):
        # The reused label tuples end at their last attested observation: label 5 is Anas's now, not Ahmed's.
        bounded = {("5", "Ahmed"): "2026-05-04T10:50:59.999146Z", ("7", "Mans"): "2026-05-06T08:13:45.547425Z",
                   ("9", "Michael"): "2026-05-02T20:03:48.180210Z"}
        for (source_label_id, logged_name), just_after in bounded.items():
            for observed_at in (just_after, "2026-10-05T12:00:00Z"):
                with self.subTest(identity=(source_label_id, logged_name), observed_at=observed_at):
                    result = resolve_contract_editor(observation(source_label_id, logged_name, observed_at), self.contract)
                    self.assertEqual(result.exception.code, EDITOR_IDENTITY_OUTSIDE_OBSERVED_RANGE)
        entries = {(e["source_label_id"], e["logged_name"]): e["validity"] for e in self.contract["editor_attribution"]["entries"]}
        self.assertEqual({key for key, validity in entries.items() if validity == "historical"}, set(bounded))
        self.assertEqual(resolve_contract_editor(observation("5", "Anas", "2026-10-05T12:00:00Z"), self.contract).identity["editor_id"], "editor-label-5")

    def test_future_work_by_confirmed_editors_is_attributed_in_a_profile(self):
        logs = [mf.editor("ed", "900", "2026-10-02T08:00:00Z", [4], ["Mario"]), mf.video_type("vt", "900", "2026-10-02T08:01:00Z", [4]),
                mf.status("s1", "900", "2026-10-02T09:00:00Z", "Create File", "In Progress"),
                mf.status("s2", "900", "2026-10-02T15:00:00Z", "In Progress", "Ready For Approval")]
        result = reconstruct_cycles(mf.payload(*logs), self.contract, ingestion={"retrieved_at": "2026-10-03T12:00:00Z"})
        self.assertEqual([(cycle.editor_id, cycle.exclusions) for cycle in result.cycles], [("editor-label-4", [])])

    def test_observed_timestamps_validate_but_do_not_replace_the_tuple_key(self):
        mapping = IdentityMapping.from_dict({
            "mapping_version": "bounded-v1",
            "identity_key": ["source_label_id", "logged_name"],
            "entries": [{
                "source_label_id": "6", "logged_name": "Will", "editor_id": "editor-label-6",
                "canonical_editor_name": "Will", "role": "editor", "validity": "historical", "first_observed_at": "2026-03-14T00:00:00Z",
                "last_observed_at": "2026-09-27T23:59:59Z", "attestation_source": "test evidence", "decision_id": "D16",
            }],
        })
        too_late = replace(observation("6", "Will"), observed_at="2026-09-28T00:00:00Z")
        self.assertEqual(resolve_editor(too_late, mapping).exception.code, EDITOR_IDENTITY_OUTSIDE_OBSERVED_RANGE)
        too_early = replace(observation("6", "Will"), observed_at="2026-03-13T23:59:59Z")
        result = resolve_editor(too_early, mapping)
        self.assertEqual(result.exception.code, EDITOR_IDENTITY_OUTSIDE_OBSERVED_RANGE)
        self.assertEqual(resolve_editor(observation("6", "Other"), mapping).exception.code, UNMAPPED_EDITOR)
        invalid_time = replace(observation("6", "Will"), observed_at="not-a-timestamp")
        self.assertEqual(resolve_editor(invalid_time, mapping).exception.code, "MISSING_EVIDENCE")

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

    def test_same_label_id_with_a_different_logged_name_inside_cycle_is_reassignment(self):
        logs = [
            mf.editor("editor-old", "1", "2026-09-01T09:00:00Z", [6], ["Another Will"]),
            mf.video_type("video", "1", "2026-09-01T09:00:01Z", [4]),
            mf.status("start", "1", "2026-09-01T10:00:00Z", "Create File", "In Progress"),
            mf.editor("editor-new", "1", "2026-09-01T11:00:00Z", [6], ["Will"]),
            mf.status("end", "1", "2026-09-01T12:00:00Z", "In Progress", "Ready For Approval"),
        ]
        cycle = reconstruct_cycles(mf.payload(*logs), self.contract).cycles[0]
        self.assertIsNone(cycle.editor_id)
        self.assertIn(EDITOR_CHANGED_WITHIN_CYCLE, cycle.exclusions)

    def test_no_named_d49_identity_remains_unresolved_and_d50_is_not_mapped(self):
        mapped = {(entry["source_label_id"], entry["logged_name"]) for entry in self.contract["editor_attribution"]["entries"]}
        self.assertEqual(self.contract["editor_attribution"]["named_unresolved_identities"], [])
        attested = {("4", "Mario"), ("5", "Anas"), ("7", "Martin"), ("8", "Samra"), ("9", "Ibrahim"),
                    ("10", "Amir"), ("11", "Refaat"), ("5", "Ahmed"), ("7", "Mans"), ("9", "Michael")}
        quarantined = {(entry["source_label_id"], entry["logged_name"])
                       for entry in self.contract["editor_attribution"]["quarantine_reasons"]}
        self.assertTrue(attested <= mapped)
        self.assertFalse(mapped & quarantined)


class ContractV15IntegratedRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract_version("1.5.0")

    def test_real_contract_parses_for_bonus_registry_and_scores_only_quality_labels(self):
        logs = [
            mf.editor("editor", "1", "2026-09-28T08:00:00Z", [6], ["Will"]),
            mf.video_type("video", "1", "2026-09-28T08:01:00Z", [4]),
            mf.status("start", "1", "2026-09-28T09:00:00Z", "Create File", "In Progress"),
            mf.status("end", "1", "2026-09-28T11:00:00Z", "In Progress", "Ready For Approval"),
            mf.dropdown("bonus", "1", "dropdown_mm3tyvvc", "2026-09-28T11:01:00Z", [1, 5, 6],
                        ["1- Exceptional Quality", "On Time Delivery", "High Workload"]),
        ]
        reconstruction = reconstruct_cycles(mf.payload(*logs), self.contract, ingestion={"retrieved_at": "2026-09-29T12:00:00Z"})
        quality = reconstruct_quality(reconstruction, self.contract, "2026-09-29T12:00:00Z")
        observed = {(row["performance_label"], row["evidence"]["source_values"]["label_class"])
                    for row in quality.occurrences}
        self.assertEqual(observed, {("1- Exceptional Quality", "Positive"), ("On Time Delivery", "Positive"),
                                    ("High Workload", "Context")})
        facts = quality_rates("editor-label-6", quality.occurrences, reconstruction.cycles,
                              EvidenceScope.from_contract(self.contract, "2026-09-29T12:00:00Z"), None, None)
        self.assertEqual((facts["positive_count"], facts["negative_count"]), (1, 0))
        self.assertEqual({row["label"] for row in facts["scoring_exclusions"]}, {"On Time Delivery", "High Workload"})

        profile = build_editor_profile(reconstruction, self.contract, "editor-label-6", "2026-09-29T12:00:00Z")
        summary = editor_summary(profile)
        self.assertEqual(summary["quality"]["positive"]["total_occurrences"], 2)
        self.assertEqual(summary["quality"]["context"]["total_occurrences"], 1)
        self.assertEqual({event["kind"] for event in summary["events"] if event["kind"].endswith("_label")},
                         {"positive_label", "context_label"})
        self.assertNotIn("D10", summary["intelligence"]["positive_signals"]["reason"])

    def test_actual_v15_contract_builds_one_shared_bilingual_publication(self):
        from test_profile import NOW, dataset

        activity, items = dataset()
        reconstruction = reconstruct_cycles(activity, self.contract, items_payload=items, ingestion={"retrieved_at": NOW})
        profile = build_editor_profile(reconstruction, self.contract, "editor-label-6", NOW)
        self.assertIsNone(profile["overall"]["status"])
        self.assertEqual(profile["overall"]["status_label"], "Not enough approved logic to classify")
        self.assertTrue(profile["speed"]["leave_one_out"])
        self.assertEqual(profile["trend"]["window"]["timezone"], "Africa/Cairo")
        self.assertEqual(profile["quality"]["component"]["state"], "not_classifiable")
        with tempfile.TemporaryDirectory() as directory:
            dashboard = build_all(reconstruction, self.contract, Path(directory), NOW)
            publication = dashboard["publication"]
            self.assertEqual({(row["release_id"], row["snapshot_id"]) for row in publication["routes"].values()},
                             {(publication["release_id"], publication["snapshot_id"])})
            self.assertTrue((Path(directory) / "en" / "dashboard.html").is_file())
            self.assertTrue((Path(directory) / "ar" / "dashboard.html").is_file())


if __name__ == "__main__":
    unittest.main()
