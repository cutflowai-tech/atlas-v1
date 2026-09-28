import json
import unittest

from atlas_commander.runtime import CONTRACT_PATHS, load_contract_version, resolve_contract_video_type, video_type_cohort
from atlas_commander.video_type import (
    DUPLICATE_VIDEO_TYPE,
    INVALID_VIDEO_TYPE_VALUE,
    LABEL_ID_MISMATCH,
    MISSING_VIDEO_TYPE,
    UNMAPPED_VIDEO_TYPE,
    VideoTypeMapping,
    partition_by_cohort,
)


class VideoTypeMappingVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v10 = load_contract_version("1.0.0")
        cls.v11 = load_contract_version("1.1.0")

    def test_contract_versions_are_distinct_files(self):
        self.assertEqual(self.v10["contract_version"], "1.0.0")
        self.assertEqual(self.v11["contract_version"], "1.1.0")
        self.assertEqual(self.v10["video_type_cohorts"]["mapping_version"], "monday-video-type-v1.0")
        self.assertEqual(self.v11["video_type_cohorts"]["mapping_version"], "monday-video-type-v1.1")

    def test_v10_mapping_is_preserved_unchanged(self):
        self.assertEqual(self.v10["video_type_cohorts"]["label_to_id"], {"Class B": "5", "Ai": "16"})

    def test_v11_only_adds_class_a_plus(self):
        v10_map = self.v10["video_type_cohorts"]["label_to_id"]
        v11_map = self.v11["video_type_cohorts"]["label_to_id"]
        self.assertEqual({k: v for k, v in v11_map.items() if k in v10_map}, v10_map)
        self.assertEqual({k: v for k, v in v11_map.items() if k not in v10_map}, {"Class A+": "8"})
        strip = lambda config: {k: v for k, v in config.items() if k not in ("$id", "contract_version", "video_type_cohorts")}
        self.assertEqual(strip(self.v10), strip(self.v11))

    def test_label_8_is_quarantined_under_v10_and_resolved_under_v11(self):
        old = resolve_contract_video_type(ids=[8], config=self.v10)
        new = resolve_contract_video_type(ids=[8], config=self.v11)
        self.assertFalse(old.resolved)
        self.assertEqual((old.reason, old.unmapped, old.mapping_version), (UNMAPPED_VIDEO_TYPE, ("id:8",), "monday-video-type-v1.0"))
        self.assertEqual((new.cohort_key, new.canonical_labels, new.mapping_version), ("8", ("Class A+",), "monday-video-type-v1.1"))

    def test_v10_results_remain_reproducible(self):
        self.assertEqual(resolve_contract_video_type(ids=[5, 16], config=self.v10).cohort_key, "16:5")
        self.assertEqual(resolve_contract_video_type(ids=[5, 16], config=self.v11).cohort_key, "16:5")

    def test_every_registered_contract_path_exists(self):
        for version, path in CONTRACT_PATHS.items():
            with self.subTest(version=version):
                self.assertEqual(json.loads(path.read_text())["contract_version"], version)


class VideoTypeCohortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_contract_version("1.1.0")

    def resolve(self, ids=None, labels=None):
        return resolve_contract_video_type(ids=ids, labels=labels, config=self.config)

    def test_singleton_class_a_plus(self):
        result = self.resolve(ids=[8])
        self.assertEqual((result.cohort_key, result.canonical_ids, result.raw_ids), ("8", ("8",), ("8",)))

    def test_mixed_class_b_and_class_a_plus_is_its_own_cohort(self):
        result = self.resolve(ids=[8, 5])
        self.assertEqual(result.cohort_key, "5:8")
        self.assertEqual(result.canonical_labels, ("Class B", "Class A+"))
        self.assertNotEqual(result.cohort_key, self.resolve(ids=[8]).cohort_key)
        self.assertNotEqual(result.cohort_key, self.resolve(ids=[5]).cohort_key)

    def test_order_and_representation_do_not_change_the_key(self):
        keys = {self.resolve(ids=[5, 8]).cohort_key, self.resolve(ids=["8", "5"]).cohort_key, self.resolve(labels=["Class A+", "Class B"]).cohort_key,
                self.resolve(ids=[8, 5], labels=["Class B", "Class A+"]).cohort_key}
        self.assertEqual(keys, {"5:8"})

    def test_unknown_labels_are_quarantined_with_raw_evidence(self):
        for ids, labels, unmapped in (([4], None, ("id:4",)), ([8, 4], None, ("id:4",)), (None, ["Class A"], ("label:Class A",))):
            with self.subTest(ids=ids, labels=labels):
                result = self.resolve(ids=ids, labels=labels)
                self.assertIsNone(result.cohort_key)
                self.assertEqual((result.reason, result.unmapped), (UNMAPPED_VIDEO_TYPE, unmapped))
                self.assertEqual(result.to_dict()["raw_ids"], [str(value) for value in ids or []])

    def test_blank_duplicate_mismatch_and_invalid_values_are_quarantined(self):
        cases = (
            ({"ids": []}, MISSING_VIDEO_TYPE),
            ({"ids": None}, MISSING_VIDEO_TYPE),
            ({"ids": [8, 8]}, DUPLICATE_VIDEO_TYPE),
            ({"ids": [8], "labels": ["Class B"]}, LABEL_ID_MISMATCH),
            ({"ids": [True]}, INVALID_VIDEO_TYPE_VALUE),
            ({"ids": ["eight"]}, INVALID_VIDEO_TYPE_VALUE),
            ({"ids": {"8": 1}}, INVALID_VIDEO_TYPE_VALUE),
        )
        for kwargs, reason in cases:
            with self.subTest(kwargs=kwargs):
                result = self.resolve(**kwargs)
                self.assertFalse(result.resolved)
                self.assertEqual(result.reason, reason)

    def test_label_text_helper_matches_id_resolution(self):
        self.assertEqual(video_type_cohort(["Class A+"], self.config), "8")
        self.assertEqual(video_type_cohort("Class A+", self.config), "8")
        self.assertIsNone(video_type_cohort([], self.config))
        self.assertIsNone(video_type_cohort(["Class A+", "Unknown"], self.config))

    def test_mapping_rejects_collapsing_policies_and_duplicate_ids(self):
        broken = json.loads(json.dumps(self.config))
        broken["video_type_cohorts"]["multi_select_policy"] = "primary-type"
        with self.assertRaises(ValueError):
            VideoTypeMapping.from_contract(broken)
        broken = json.loads(json.dumps(self.config))
        broken["video_type_cohorts"]["label_to_id"]["Alias"] = "8"
        with self.assertRaises(ValueError):
            VideoTypeMapping.from_contract(broken)


class CohortIsolationTests(unittest.TestCase):
    def test_partition_never_mixes_exact_sets(self):
        config = load_contract_version("1.1.0")
        records = [
            {"item": "a", "video_type": resolve_contract_video_type(ids=[8], config=config).cohort_key},
            {"item": "b", "video_type": resolve_contract_video_type(ids=[5, 8], config=config).cohort_key},
            {"item": "c", "video_type": resolve_contract_video_type(ids=[8], config=config).cohort_key},
            {"item": "d", "video_type": resolve_contract_video_type(ids=[5], config=config).cohort_key},
            {"item": "e", "video_type": resolve_contract_video_type(ids=[8, 99], config=config).cohort_key},
            {"item": "f", "video_type": None},
        ]
        cohorts, unresolved = partition_by_cohort(records)
        self.assertEqual({key: [r["item"] for r in group] for key, group in cohorts.items()}, {"8": ["a", "c"], "5:8": ["b"], "5": ["d"]})
        self.assertEqual([r["item"] for r in unresolved], ["e", "f"])


if __name__ == "__main__":
    unittest.main()
