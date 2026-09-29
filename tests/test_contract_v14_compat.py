"""Contract 1.5 code must leave every earlier contract's output and operations exactly as they were.

Production stays on contract 1.4.0 until 1.5 is explicitly activated, and deploying the 1.5 code must not change a 1.4
site, nor break status, publication or rollback of 1.4 builds staged or published before that code shipped. Those builds
never contained ``publication.json`` (a contract 1.5 artifact); the golden hashes pin the exact bytes the pre-1.5 code
(f9e7571) produced, so a 1.4 build made now is indistinguishable from one made then.
"""

import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from test_ingest import FakeMonday, items
from test_profile import NOW, dataset
from test_sync_run import T0, TOKEN, Clock, Monotonic, logs

from atlas_commander import profile_cli, site_layout
from atlas_commander.capabilities import capabilities
from atlas_commander.management import editor_intelligence, team_intelligence
from atlas_commander.pipeline import reconstruct_cycles
from atlas_commander.runtime import ACTIVE_CONTRACT_VERSION, load_contract_version
from atlas_sync import publish as pub
from atlas_sync import run as sync
from atlas_sync import status as st

ROOT = Path(__file__).resolve().parents[1]
HISTORY = "2026-08-15T00:00:00Z"
# Text that exists only under contract 1.5 semantics; a 1.4 page showing any of it would misstate what 1.4 computes.
V15_ONLY_TEXT = (
    "Positive and context labels are shown from Monday as separate factual evidence",
    "Positive Monday labels are shown as factual evidence",
    "Active Work statuses are approved",
    "positive labels are evidence and never an automatic reward recommendation",
    "atlas-release-id", "atlas-snapshot-id", "source snapshot", "Context labels", "Active Work", "Awaiting Approval",
    "data-classification",
)
# The D10-era statements a 1.4 page must keep.
D10_TEXT = ("No approved positive quality signal exists in V1; For Bonus is context only",)


def build_site(version: str, out: Path) -> dict:
    contract = load_contract_version(version)
    activity, items_payload = dataset()
    result = reconstruct_cycles(activity, contract, items_payload=items_payload, ingestion={"retrieved_at": NOW})
    return profile_cli.build_all(result, contract, out, NOW)


class GoldenSiteTests(unittest.TestCase):
    """Byte-for-byte: contracts before 1.5 reproduce the pre-1.5 site."""

    def setUp(self):
        self.out = Path(tempfile.mkdtemp(prefix="atlas-golden-"))

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_contract_1_4_and_1_3_sites_are_byte_identical_to_the_pre_1_5_build(self):
        for version in ("1.3.0", "1.4.0"):
            with self.subTest(version=version):
                out = self.out / version
                build_site(version, out)
                golden = json.loads((ROOT / "fixtures" / "golden" / f"site-v{version[:3]}-sha256.json").read_text())
                actual = {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob("*")) if p.is_file()}
                self.assertEqual(golden["contract_version"], version)
                self.assertEqual(sorted(actual), sorted(golden["files"]), "a 1.4 site has exactly the pre-1.5 files (no publication.json)")
                changed = sorted(name for name in actual if actual[name] != golden["files"][name])
                self.assertEqual(changed, [], f"{version} output changed")

    def test_1_4_pages_do_not_show_contract_1_5_claims(self):
        doc = build_site("1.4.0", self.out)
        pages = [p for p in self.out.rglob("*.html")]
        self.assertTrue(pages)
        for page in pages:
            text = page.read_text(encoding="utf-8")
            for phrase in V15_ONLY_TEXT:
                self.assertNotIn(phrase, text, f"{page.relative_to(self.out)} shows 1.5-only text {phrase!r}")
        english = (self.out / "en" / "profiles" / "editor-label-6.html").read_text(encoding="utf-8")
        for phrase in D10_TEXT:
            self.assertIn(phrase, english)
        self.assertNotIn("publication", doc)
        self.assertNotIn("quality_labels_by_class", doc["team"])
        for summary in doc["editors"]:
            self.assertEqual(summary["quality"]["source"], "quality.negative")
            for event in summary["events"]:
                self.assertNotIn("label_class", event)
                self.assertNotIn("column_id", event)
            self.assertIn("overall_score", summary["intelligence"])
            self.assertEqual(summary["intelligence"]["positive_signals"]["reason"],
                             "No approved positive quality signal exists in V1; For Bonus is context only (D10).")

    def test_management_reasons_follow_the_contract(self):
        legacy, current = editor_intelligence("1.4.0"), editor_intelligence("1.5.0")
        self.assertIn("(D10)", legacy["reward_recommendation"]["reason"])
        self.assertIn("open decision 5", legacy["workload_capacity"]["reason"])
        self.assertNotIn("overall_score", current, "contract 1.5 has no overall score (D37)")
        self.assertNotIn("overall_status", current, "contract 1.5 publishes a real Overall Status instead of a pending slot")
        self.assertNotIn("D10", current["reward_recommendation"]["reason"])
        self.assertIn("(D10)", team_intelligence("1.4.0")["positive_signals"]["reason"])

    def test_capabilities_exist_only_from_contract_1_5(self):
        for version in ("1.0.0", "1.3.0", "1.4.0"):
            flags = capabilities(version)
            self.assertFalse(flags.label_taxonomy or flags.editor_intelligence or flags.publication_identity, version)
        for version in ("1.5.0", "1.5.1", "1.6.0"):
            flags = capabilities(version)
            self.assertTrue(flags.label_taxonomy and flags.editor_intelligence and flags.publication_identity, version)
        self.assertEqual(ACTIVE_CONTRACT_VERSION, "1.4.0")
        self.assertNotIn(site_layout.PUBLICATION_JSON, site_layout.required_files(["editor-label-6"], "1.4.0"))
        self.assertIn(site_layout.PUBLICATION_JSON, site_layout.required_files(["editor-label-6"], "1.5.0"))


class LegacyBuildOperationsTests(unittest.TestCase):
    """Status, staged publication and rollback of 1.4 builds that have no publication.json."""

    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="atlas-v14-ops-"))
        self.env = {"MONDAY_API_TOKEN": TOKEN, "ATLAS_DATA_DIR": str(self.data), "ATLAS_HISTORY_START": HISTORY}
        self.days = 0

    def tearDown(self):
        shutil.rmtree(self.data, ignore_errors=True)

    def stage(self):
        self.days += 1
        result = sync.run_once(self.env, transport=FakeMonday(logs(), items()), clock=Clock(start=T0 + timedelta(days=self.days)),
                               monotonic=Monotonic(), sleep=lambda s: None)
        self.assertEqual(result.status, "success", result.as_dict())
        site = Path(result.staged_build_dir) / "site"
        self.assertFalse((site / site_layout.PUBLICATION_JSON).exists(), "a 1.4 build has no publication.json")
        self.assertNotIn("atlas-release-id", (site / "index.html").read_text(encoding="utf-8"))
        return result

    BUILD_CHECKS = ("current_pointer", "build_completion", "build_metadata", "artifact_hashes", "locales", "raw_source", "raw_verification",
                    "provenance", "current_metadata", "publication_history")

    def assert_live(self, attempt):
        self.assertEqual(pub.live_attempt(load(self.env)), attempt.attempt_id)
        snapshot = st.evaluate_status(self.env, clock=lambda: T0 + timedelta(days=self.days + 1))
        self.assertTrue(snapshot.live_usable, snapshot.as_dict())
        checks = {check.name: check.status for check in snapshot.checks}
        self.assertEqual({name: checks.get(name) for name in self.BUILD_CHECKS}, dict.fromkeys(self.BUILD_CHECKS, "passed"), snapshot.as_dict())
        self.assertNotIn("build_tampered", snapshot.failure_categories)

    def test_status_publish_and_rollback_of_builds_without_publication_json(self):
        first = self.stage()
        published = pub.publish(first.attempt_id, self.env, clock=Clock(start=T0 + timedelta(days=self.days, minutes=5)))
        self.assertEqual(published.status, pub.PUBLISHED, published.as_dict())
        self.assert_live(first)

        second = self.stage()          # staged, not yet published: publishing it later must still work
        third = self.stage()
        for attempt in (second, third):
            result = pub.publish(attempt.attempt_id, self.env, clock=Clock(start=T0 + timedelta(days=self.days, minutes=5)))
            self.assertEqual(result.status, pub.PUBLISHED, result.as_dict())
            self.assert_live(attempt)

        back = pub.rollback(None, self.env, clock=Clock(start=T0 + timedelta(days=self.days, minutes=10)))
        self.assertEqual((back.status, back.attempt_id), (pub.PUBLISHED, second.attempt_id), back.as_dict())
        self.assert_live(second)
        explicit = pub.rollback(first.attempt_id, self.env, clock=Clock(start=T0 + timedelta(days=self.days, minutes=15)))
        self.assertEqual((explicit.status, explicit.attempt_id), (pub.PUBLISHED, first.attempt_id), explicit.as_dict())
        self.assert_live(first)


def load(env):
    from atlas_sync.config import load_sync_config
    return load_sync_config(env, now=T0)


if __name__ == "__main__":
    unittest.main()
