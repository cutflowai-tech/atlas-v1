from __future__ import annotations

import copy
import importlib.util
import unittest
from datetime import datetime
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "round4_distribution_analysis.py"
SPEC = importlib.util.spec_from_file_location("round4_distribution_analysis", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


class Round4DistributionAnalysisTests(unittest.TestCase):
    def tuple_ranges(self):
        result = {}
        for index, row in enumerate(analysis.ATTESTED_TUPLES):
            first = datetime.fromisoformat(f"{row['first_day']}T12:00:00+00:00")
            last = datetime.fromisoformat(f"{row['last_day']}T12:00:00+00:00")
            result[(row["source_label_id"], row["logged_name"])] = {
                "first_observed_at": first,
                "last_observed_at": last,
                "item_ids": {f"item-{index}"},
                "observations": 1,
            }
        return result

    def test_attestation_overlay_is_non_mutating_and_idempotent(self):
        unresolved = [
            {"source_label_id": row["source_label_id"], "logged_name": row["logged_name"]}
            for row in analysis.ATTESTED_TUPLES
        ]
        contract = {
            "editor_attribution": {
                "mapping_version": "test-v1",
                "entries": [],
                "named_unresolved_identities": unresolved,
            }
        }
        original = copy.deepcopy(contract)
        once = analysis.contract_with_attestations(contract, self.tuple_ranges())
        twice = analysis.contract_with_attestations(once, self.tuple_ranges())

        self.assertEqual(original, contract)
        self.assertEqual(10, len(once["editor_attribution"]["entries"]))
        self.assertEqual(10, len(twice["editor_attribution"]["entries"]))
        self.assertEqual("test-v1-round4-analysis", twice["editor_attribution"]["mapping_version"])
        self.assertEqual([], twice["editor_attribution"]["named_unresolved_identities"])

    def test_attestation_overlay_rejects_inexact_contract_bounds(self):
        row = analysis.ATTESTED_TUPLES[0]
        ranges = self.tuple_ranges()
        observed = ranges[(row["source_label_id"], row["logged_name"])]
        contract = {
            "editor_attribution": {
                "mapping_version": "test-v1",
                "entries": [{
                    "source_label_id": row["source_label_id"],
                    "logged_name": row["logged_name"],
                    "editor_id": row["editor_id"],
                    "canonical_editor_name": row["display_name"],
                    "role": "editor",
                    "decision_id": "D49",
                    "attestation_source": analysis.ATTESTATION_SOURCE,
                    "first_observed_at": observed["first_observed_at"].isoformat(),
                    "last_observed_at": "2026-09-27T12:00:00+00:00",
                }],
                "named_unresolved_identities": [],
            }
        }
        with self.assertRaisesRegex(RuntimeError, "conflicts with management attestation"):
            analysis.contract_with_attestations(contract, ranges)

    def test_prior_baseline_removes_only_attested_entries(self):
        attested = analysis.ATTESTED_TUPLES[0]
        contract = {"editor_attribution": {"mapping_version": "v1.3", "entries": [
            {"source_label_id": attested["source_label_id"], "logged_name": attested["logged_name"]},
            {"source_label_id": "6", "logged_name": "Will"},
        ], "named_unresolved_identities": []}}
        baseline = analysis.contract_before_attestations(contract)
        self.assertEqual([{"source_label_id": "6", "logged_name": "Will"}], baseline["editor_attribution"]["entries"])
        self.assertEqual(10, len(baseline["editor_attribution"]["named_unresolved_identities"]))

    def test_attestation_overlay_rejects_a_conflicting_contract_mapping(self):
        row = analysis.ATTESTED_TUPLES[0]
        contract = {
            "editor_attribution": {
                "mapping_version": "test-v1",
                "entries": [{
                    "source_label_id": row["source_label_id"],
                    "logged_name": row["logged_name"],
                    "editor_id": "wrong-editor",
                    "canonical_editor_name": row["display_name"],
                }],
                "named_unresolved_identities": [],
            }
        }
        with self.assertRaisesRegex(RuntimeError, "conflicts with management attestation"):
            analysis.contract_with_attestations(contract, self.tuple_ranges())

    def test_overall_lookup_covers_exactly_combinations_with_two_components(self):
        lookup = analysis._proposed_overall_lookup()
        self.assertEqual(54, len(lookup))
        self.assertEqual("Strong", lookup["Positive|Positive|Not classifiable"])
        self.assertEqual("Good", lookup["Neutral|Neutral|Not classifiable"])
        self.assertEqual("Mixed", lookup["Positive|Negative|Not classifiable"])
        self.assertEqual("Below Expectations", lookup["Negative|Negative|Not classifiable"])
        self.assertNotIn("Positive|Not classifiable|Not classifiable", lookup)

    def test_deadline_sensitivity_is_deterministic(self):
        rows = []
        for editor_id, late_count in (("a", 4), ("b", 16), ("c", 10)):
            rows.extend(
                {"editor_id": editor_id, "classification": "late" if index < late_count else "early"}
                for index in range(20)
            )
        first = analysis._deadline_sensitivity(rows)
        second = analysis._deadline_sensitivity(list(reversed(rows)))
        self.assertEqual(first, second)
        candidate = analysis._matching_grid(
            first,
            minimum_editor_projects=5,
            minimum_comparator_projects=30,
            symmetric_band_rate_points=0.15,
        )
        self.assertEqual(3, candidate["classifiable_editors"])
        self.assertGreater(candidate["perturbations"], 0)

    def test_distribution_has_stable_linear_quartiles(self):
        self.assertEqual(
            {"n": 4, "min": 1.0, "q1": 1.75, "median": 2.5, "q3": 3.25, "max": 4.0, "mean": 2.5},
            analysis.distribution([4, 1, 3, 2]),
        )


if __name__ == "__main__":
    unittest.main()
