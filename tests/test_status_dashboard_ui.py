"""Task 7 presentation: one language-neutral operational snapshot, two locales."""

import re
import unittest
from collections import Counter

from atlas_commander.dashboard_html import operational_status
from atlas_commander.i18n import AR, EN, catalog

SNAPSHOT = {
    "generated_at": "2026-09-29T12:00:00Z",
    "snapshot_scope": "build_time",
    "system_state": "healthy",
    "freshness_state": "stale",
    "current_publication": {
        "attempt_id": "attempt-published",
        "publication_id": "publication-7",
        "published_at": "2026-09-29T11:00:00Z",
        "source_run_id": "run-42",
        "monday_retrieved_at": "2026-09-29T08:00:00Z",
        "coverage": {
            "history_start": "2026-08-15T00:00:00Z",
            "history_end": "2026-09-29T08:00:00Z",
        },
        "contract_version": "1.4.0",
        "board_id": "123456",
    },
    "last_attempt": {
        "attempt_id": "attempt-failed",
        "started_at": "2026-09-29T11:50:00Z",
        "finished_at": "2026-09-29T11:51:00Z",
        "status": "failed",
        "error_category": "monday_transport",
        "source_run_id": None,
        "raw_exception": "SECRET traceback must never be displayed",
    },
    "last_successful_attempt": {
        "attempt_id": "attempt-published",
        "started_at": "2026-09-29T07:55:00Z",
        "finished_at": "2026-09-29T08:05:00Z",
        "status": "success",
        "source_run_id": "run-42",
    },
    "freshness": {
        "age_seconds": 14400,
        "expected_interval_seconds": 3600,
        "stale_after_seconds": 7200,
    },
}


def status_values(html: str) -> Counter:
    return Counter(re.findall(r'data-status-value="([^"]*)"', html))


class OperationalStatusPresentationTests(unittest.TestCase):
    def test_both_locales_render_identical_underlying_snapshot_values(self):
        english = operational_status(SNAPSHOT, EN)
        arabic = operational_status(SNAPSHOT, AR)
        self.assertEqual(status_values(english), status_values(arabic))
        for value in ("build_time", "healthy", "stale", "run-42", "publication-7", "14400", "3600", "7200"):
            self.assertIn(value, status_values(english))

    def test_status_and_freshness_are_separate_localized_dimensions(self):
        english = operational_status(SNAPSHOT, EN)
        arabic = operational_status(SNAPSHOT, AR)
        self.assertIn("System status", english)
        self.assertIn("Data freshness", english)
        self.assertIn("Healthy", english)
        self.assertIn("Stale", english)
        self.assertIn("حالة النظام", arabic)
        self.assertIn("حداثة البيانات", arabic)
        self.assertIn("سليمة", arabic)
        self.assertIn("قديمة وغير محدثة", arabic)

    def test_publication_retrieval_attempts_and_coverage_are_visible(self):
        html = operational_status(SNAPSHOT, EN)
        for label in ("Last sync attempt", "Last successful sync", "Monday data retrieved", "Published at",
                      "Evidence coverage", "Source run", "Executable contract", "Monday board ID"):
            self.assertIn(label, html)
        self.assertIn("attempt-failed", html)
        self.assertIn("attempt-published", html)
        self.assertIn("monday_transport", html)
        self.assertIn('data-status-value="2026-08-15T00:00:00Z/2026-09-29T08:00:00Z"', html)
        self.assertIn('data-status-value="2026-09-29T11:51:00Z"', html)

    def test_snapshot_scope_is_explicit_and_static_build_points_to_authoritative_cli(self):
        english = operational_status(SNAPSHOT, EN)
        arabic = operational_status(SNAPSHOT, AR)
        self.assertIn('data-status-value="build_time"', english)
        self.assertIn("Build-time snapshot", english)
        self.assertIn("Atlas status CLI is authoritative for current runtime status", english)
        self.assertIn("لقطة وقت الإنشاء", arabic)
        self.assertIn("أمر حالة Atlas هو المرجع المعتمد للحالة التشغيلية الحالية", arabic)

        runtime = {**SNAPSHOT, "snapshot_scope": "runtime"}
        runtime_html = operational_status(runtime, EN)
        self.assertIn('data-status-value="runtime"', runtime_html)
        self.assertIn("Runtime snapshot", runtime_html)
        self.assertNotIn("captured when this dashboard build was generated", runtime_html)

    def test_renderer_whitelists_safe_fields_and_never_displays_raw_exception(self):
        html = operational_status(SNAPSHOT, EN)
        self.assertNotIn("SECRET traceback", html)
        self.assertNotIn("raw_exception", html)

    def test_absent_snapshot_is_explicitly_unknown_not_healthy(self):
        english = operational_status(None, EN)
        arabic = operational_status(None, AR)
        self.assertIn("No operational status snapshot was injected", english)
        self.assertIn("لم يتم تضمين ملخص للحالة التشغيلية", arabic)
        self.assertNotIn("Healthy", english)

    def test_every_operational_key_has_english_and_arabic(self):
        entries = catalog()
        keys = {key for key in entries if key.startswith("ops.")}
        self.assertTrue(keys)
        for key in keys:
            self.assertTrue(entries[key]["en"], key)
            self.assertTrue(entries[key]["ar"], key)


if __name__ == "__main__":
    unittest.main()
