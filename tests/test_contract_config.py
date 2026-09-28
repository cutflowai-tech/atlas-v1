import unittest

from atlas_commander.contracts import schema_errors
from atlas_commander.identity import EditorObservation
from atlas_commander.runtime import load_contract, load_contract_version, normalize_contract_events, resolve_contract_editor, video_type_cohort


class MondayContractRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_contract()

    def test_runtime_normalizes_raw_statuses_and_preserves_mapping_evidence(self):
        raw = {
            "id": "event-1", "board_id": "board-1", "created_at": "2026-09-01T09:00:00Z", "user_id": "99154021",
            "data": {"pulse_id": "item-1", "column_id": "status", "previous_value": {"label": {"text": "Create File"}}, "value": {"label": {"text": "In Progress"}}},
        }
        result = normalize_contract_events([raw], self.config)
        self.assertEqual(result.quarantined, [])
        event = result.accepted[0]
        self.assertEqual(event["raw_from_status"], "Create File")
        self.assertEqual(event["raw_to_status"], "In Progress")
        self.assertEqual(event["status_phase_from"], "pre-cycle")
        self.assertEqual(event["status_phase_to"], "active-production")
        self.assertEqual(event["mapping_version"], "monday-status-v1.0")
        self.assertEqual(schema_errors(event, "normalized-status-event.schema.json"), [])

    def test_runtime_quarantines_a_label_not_in_project_mapping(self):
        raw = {"id": "event-2", "board_id": "board-1", "created_at": "2026-09-01T09:00:00Z", "data": {"pulse_id": "item-1", "column_id": "status", "value": "Brand New Label"}}
        result = normalize_contract_events([raw], self.config)
        self.assertEqual(result.accepted, [])
        self.assertEqual(result.quarantined[0]["reason"], "UNKNOWN_STATUS")

    def test_editor_mapping_uses_editor_field_and_mapping_version(self):
        observation = EditorObservation("board-1", "item-1", "Editor Name", ("12",), "editor_column_event", "event-1", "2026-09-01T09:00:00Z")
        result = resolve_contract_editor(observation, self.config)
        self.assertTrue(result.resolved)
        assert result.identity is not None
        self.assertEqual(result.identity["editor_id"], "editor-label-12")
        self.assertEqual(result.identity["mapping_version"], "monday-editor-v1.0")

    def test_shared_account_is_not_an_editor_mapping(self):
        observation = EditorObservation("board-1", "item-1", "Editor Name", ("99154021",), "editor_column_event", "event-1", "2026-09-01T09:00:00Z")
        result = resolve_contract_editor(observation, self.config)
        self.assertFalse(result.resolved)

    def test_video_type_runtime_requires_exact_resolved_full_set(self):
        # Pinned to the approved contract 1.1.0 so its results stay reproducible after later versions.
        v11 = load_contract_version("1.1.0")
        self.assertEqual(v11["video_type_cohorts"]["mapping_version"], "monday-video-type-v1.1")
        self.assertEqual(video_type_cohort(["Class A+"], v11), "8")
        self.assertEqual(video_type_cohort(["Class B", "Class A+"], v11), "5:8")
        self.assertEqual(video_type_cohort(["Class B", "Ai"], v11), "16:5")
        self.assertIsNone(video_type_cohort(["Class B", "Unknown"], v11))
        self.assertIsNone(video_type_cohort(["Class A+", "Unknown"], v11))
        self.assertIsNone(video_type_cohort(["Class A"], v11))
        self.assertIsNone(video_type_cohort([], v11))
        # The active contract applies the same exact-full-set rules with its own mapping version.
        self.assertEqual(video_type_cohort(["Class B", "Class A+"], self.config), "5:8")
        self.assertIsNone(video_type_cohort(["Class A+", "Unknown"], self.config))


if __name__ == "__main__":
    unittest.main()