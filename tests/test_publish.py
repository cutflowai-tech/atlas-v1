"""Atomic publication and rollback of completed staged builds (Task 5): temporary directories, fake Monday only."""

import functools
import io
import json
import os
import shutil
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest import mock

from test_ingest import FakeMonday, items
from test_sync_run import T0, TOKEN, Clock, Monotonic, logs

from atlas_sync import __main__ as sync_cli
from atlas_sync import publish as pub
from atlas_sync import run as sync
from atlas_sync.config import load_sync_config

HISTORY = "2026-08-15T00:00:00Z"


def snapshot(root: Path) -> dict[str, tuple]:
    """Bytes, mode and mtime of every file and directory: any modification shows up."""
    entries = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        entries[path.relative_to(root).as_posix()] = (path.read_bytes() if path.is_file() else None, stat.S_IMODE(info.st_mode), info.st_mtime_ns)
    return entries


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="atlas-publish-"))
        assert not any((parent / ".git").exists() for parent in [self.data, *self.data.parents])
        self.env = {"MONDAY_API_TOKEN": TOKEN, "ATLAS_DATA_DIR": str(self.data), "ATLAS_HISTORY_START": HISTORY}
        self.config = load_sync_config(self.env, now=T0)
        self.publish_root = self.data / "published"
        self.pointer = self.publish_root / "current"
        self.days = 0

    def tearDown(self):
        shutil.rmtree(self.data, ignore_errors=True)

    def stage(self):
        """A completed staged build from a fresh run-once attempt."""
        self.days += 1
        result = sync.run_once(self.env, transport=FakeMonday(logs(), items()), clock=Clock(start=T0 + timedelta(days=self.days)),
                               monotonic=Monotonic(), sleep=lambda s: None)
        self.assertEqual(result.status, "success", result.as_dict())
        return result

    def publish(self, attempt_id, **kwargs):
        return pub.publish(attempt_id, self.env, clock=Clock(start=T0 + timedelta(days=30)), **kwargs)

    def rollback(self, attempt_id=None, **kwargs):
        return pub.rollback(attempt_id, self.env, clock=Clock(start=T0 + timedelta(days=31)), **kwargs)

    def site(self, attempt):
        return Path(attempt.staged_build_dir) / "site"

    def live(self):
        """Where ``current`` points (resolved from the publish directory without following further links), or None."""
        return os.path.normpath(self.publish_root / os.readlink(self.pointer)) if self.pointer.is_symlink() else None

    def assert_published(self, result, attempt, previous=None):
        self.assertEqual(result.status, pub.PUBLISHED, result.as_dict())
        self.assertEqual(pub.exit_code(result), 0)
        self.assertTrue(result.switched)
        self.assertEqual((result.attempt_id, result.previous_attempt_id, result.source_run_id), (attempt.attempt_id, previous, attempt.source_run_id))
        self.assertEqual(os.readlink(self.pointer), f"../builds/{attempt.attempt_id}/site")     # relative link text
        self.assertEqual(result.current_link, os.readlink(self.pointer))
        self.assertEqual(self.pointer.resolve(), self.site(attempt).resolve())
        self.assertEqual(result.current_target, str(self.site(attempt)))
        self.assertTrue(pub.current_consistency(self.config)["consistent"])

    def assert_rejected(self, result, category, live_before):
        self.assertEqual((result.status, result.failure_category, result.switched), (pub.REJECTED, category, False), result.as_dict())
        self.assertEqual(pub.exit_code(result), pub.EXIT_REJECTED)
        self.assertEqual(self.live(), live_before)
        self.assertFalse(list(self.publish_root.glob(".current.*")) if self.publish_root.exists() else [])

    # 1, 3, 23 — first publication, exact target, no previous current required
    def test_1_3_23_first_publication(self):
        attempt = self.stage()
        self.assertFalse(self.publish_root.exists() and any(self.publish_root.iterdir()))
        result = self.publish(attempt.attempt_id)
        self.assert_published(result, attempt, previous=None)
        for page in ("en/dashboard.html", "ar/dashboard.html"):              # both languages are live through the one pointer
            self.assertEqual((self.pointer / page).read_bytes(), (self.site(attempt) / page).read_bytes())
        self.assertTrue(self.pointer.is_symlink())
        self.assertFalse((self.site(attempt) / "current").exists())
        self.assertEqual(sorted(p.name for p in self.publish_root.iterdir()), ["CURRENT.json", "current", "history"])

    # 2, 4, 18 — second publication replaces the first; first build untouched; previous recorded
    def test_2_4_18_second_publication_replaces_the_first(self):
        first, second = self.stage(), self.stage()
        self.publish(first.attempt_id)
        before = snapshot(Path(first.staged_build_dir))
        result = self.publish(second.attempt_id)
        self.assert_published(result, second, previous=first.attempt_id)
        self.assertEqual(snapshot(Path(first.staged_build_dir)), before)
        current = json.loads((self.publish_root / "CURRENT.json").read_text())
        self.assertEqual((current["attempt_id"], current["previous_attempt_id"]), (second.attempt_id, first.attempt_id))

    # 5 — failed and incomplete builds
    def test_5_failed_or_incomplete_builds_cannot_publish(self):
        good = self.stage()
        self.publish(good.attempt_id)
        live = self.live()
        with mock.patch.object(sync, "build_dashboard_files", side_effect=RuntimeError("boom")):
            failed = sync.run_once(self.env, transport=FakeMonday(logs(), items()), clock=Clock(start=T0 + timedelta(days=9)), monotonic=Monotonic())
        self.assert_rejected(self.publish(failed.attempt_id), "build_not_complete", live)
        incomplete = self.stage()
        marker = Path(incomplete.staged_build_dir) / "COMPLETE.json"
        marker.chmod(0o644)
        marker.unlink()
        self.assert_rejected(self.publish(incomplete.attempt_id), "build_not_complete", live)
        both = self.stage()
        (Path(both.staged_build_dir) / "FAILED.json").write_text("{}")
        self.assert_rejected(self.publish(both.attempt_id), "build_not_complete", live)

    # 6 — tampered artifacts (changed, deleted, added, symlinked)
    def test_6_tampered_artifacts_cannot_publish(self):
        attempt = self.stage()
        site = self.site(attempt)
        cases = [lambda: (site / "en/dashboard.html").write_text("<html>changed</html>"),
                 lambda: (site / "ar/profiles/editor-label-12.html").unlink(),
                 lambda: (site / "extra.html").write_text("x"),
                 lambda: os.symlink("/etc/hostname", site / "ar/profiles/link.html")]
        for tamper in cases:
            original = snapshot(site)
            tamper()
            self.assert_rejected(self.publish(attempt.attempt_id), "build_tampered", None)
            shutil.rmtree(site)
            site.mkdir()
            for name, (data, _mode, _mtime) in original.items():
                if data is None:
                    (site / name).mkdir(parents=True, exist_ok=True)
                else:
                    (site / name).parent.mkdir(parents=True, exist_ok=True)
                    (site / name).write_bytes(data)
        self.assert_published(self.publish(attempt.attempt_id), attempt)   # restored bytes publish again

    # 7 — tampered build.json / COMPLETE.json
    def test_7_tampered_build_metadata_cannot_publish(self):
        attempt = self.stage()
        metadata_path = Path(attempt.staged_build_dir) / "build.json"
        original = metadata_path.read_bytes()
        metadata_path.chmod(0o644)
        metadata = json.loads(original)
        metadata["artifacts"]["files"]["en/dashboard.html"]["sha256"] = "0" * 64
        metadata_path.write_text(json.dumps(metadata, indent=1, sort_keys=True) + "\n")
        self.assert_rejected(self.publish(attempt.attempt_id), "build_tampered", None)
        metadata_path.write_text("not json")
        self.assert_rejected(self.publish(attempt.attempt_id), "build_metadata_invalid", None)
        metadata_path.write_bytes(original)
        marker = Path(attempt.staged_build_dir) / "COMPLETE.json"
        marker.chmod(0o644)
        marker.write_text(json.dumps({**json.loads(marker.read_text()), "build_metadata_sha256": "f" * 64}))
        self.assert_rejected(self.publish(attempt.attempt_id), "build_tampered", None)

    # 8, 9 — raw evidence
    def test_8_missing_raw_evidence_cannot_publish(self):
        attempt = self.stage()
        shutil.rmtree(attempt.raw_run_dir)
        self.assert_rejected(self.publish(attempt.attempt_id), "missing_raw_evidence", None)

    def test_9_raw_evidence_failing_verification_cannot_publish(self):
        attempt = self.stage()
        raw = Path(attempt.raw_run_dir)
        victim = next(p for p in sorted(raw.iterdir()) if p.name.startswith("column_logs"))
        victim.chmod(0o644)
        victim.write_bytes(victim.read_bytes().replace(b"Ready For Approval", b"Ready For Approvaz"))
        result = self.publish(attempt.attempt_id)
        self.assert_rejected(result, "raw_evidence_invalid", None)
        self.assertTrue(any("SHA-256 mismatch" in problem for problem in result.problems))

    def test_9b_unreadable_raw_manifest_is_rejected_not_raised(self):
        attempt = self.stage()
        manifest = Path(attempt.raw_run_dir) / "manifest.json"
        manifest.chmod(0o644)
        manifest.write_bytes(b"{not json")
        result = self.publish(attempt.attempt_id)
        self.assert_rejected(result, "raw_evidence_invalid", None)
        self.assertEqual(pub.exit_code(result), pub.EXIT_REJECTED)

    def test_9c_status_reports_a_live_build_whose_raw_manifest_became_unreadable(self):
        from atlas_sync import status as st

        attempt = self.stage()
        self.assert_published(self.publish(attempt.attempt_id), attempt)
        manifest = Path(attempt.raw_run_dir) / "manifest.json"
        manifest.chmod(0o644)
        manifest.write_bytes(b"{not json")
        snapshot = st.evaluate_status(self.env, clock=lambda: T0 + timedelta(days=30))
        self.assertEqual((snapshot.system_state, snapshot.live_usable, snapshot.failure_categories), ("failed", False, ["raw_evidence_invalid"]))

    # 10, 11 — contract and board
    def test_10_wrong_contract_cannot_publish(self):
        attempt = self.stage()
        self._rewrite_metadata(attempt, lambda m: m.update(contract_version="1.3.0"))
        self.assert_rejected(self.publish(attempt.attempt_id), "wrong_contract", None)

    def test_11_wrong_board_or_source_run_cannot_publish(self):
        attempt = self.stage()
        self._rewrite_metadata(attempt, lambda m: m["monday"].update(board_id="123"))
        self.assert_rejected(self.publish(attempt.attempt_id), "wrong_board", None)
        other = self.stage()
        self._rewrite_metadata(other, lambda m: m["source"].update(run_id=attempt.source_run_id,
                                                                    raw_run_dir=str(Path(attempt.raw_run_dir))))
        self.assert_rejected(self.publish(other.attempt_id), "wrong_source_run", None)

    def _rewrite_metadata(self, attempt, change):
        """Change build.json and re-seal COMPLETE.json, so only the semantic check can catch it."""
        build = Path(attempt.staged_build_dir)
        metadata = json.loads((build / "build.json").read_text())
        change(metadata)
        data = json.dumps(metadata, indent=1, sort_keys=True).encode() + b"\n"
        for name in ("build.json", "COMPLETE.json"):
            (build / name).chmod(0o644)
        (build / "build.json").write_bytes(data)
        marker = json.loads((build / "COMPLETE.json").read_text())
        (build / "COMPLETE.json").write_text(json.dumps({**marker, "build_metadata_sha256": sync._sha256(data)}))

    # 12, 13 — unknown and malicious attempt IDs
    def test_12_13_unknown_and_traversal_attempt_ids_are_rejected(self):
        attempt = self.stage()
        self.publish(attempt.attempt_id)
        live = self.live()
        self.assert_rejected(self.publish("20260101T000000Z-000000000000"), "unknown_attempt", live)
        for bad in ("../builds/" + attempt.attempt_id, attempt.attempt_id + "/..", "/etc", "..", "", attempt.attempt_id + "/site",
                    attempt.attempt_id.upper()):
            self.assert_rejected(self.publish(bad), "invalid_attempt_id", live)
        outside = self.data / "elsewhere" / "20260101T000000Z-111111111111"
        shutil.copytree(Path(attempt.staged_build_dir), outside)
        os.symlink(outside, self.data / "builds" / outside.name)            # a build dir that is a symlink out of the build root
        self.assert_rejected(self.publish(outside.name), "unknown_attempt", live)

    # 14, 15 and the other switch-point failures
    def test_14_failure_before_the_replace_leaves_current_unchanged(self):
        first, second = self.stage(), self.stage()
        self.publish(first.attempt_id)
        live, before = self.live(), snapshot(self.publish_root)
        with mock.patch.object(pub, "_create_temporary_pointer", side_effect=OSError("disk full")):
            result = self.publish(second.attempt_id)
        self.assertEqual((result.status, result.failure_category, result.switched), (pub.SWITCH_FAILED, "switch_failed", False))
        self.assertEqual(pub.exit_code(result), pub.EXIT_SWITCH_FAILED)
        self.assertEqual(self.live(), live)
        self.assertEqual(snapshot(self.publish_root), before)                # no history, no CURRENT.json change, no temp link

    def test_15_replace_failure_leaves_current_unchanged(self):
        first, second = self.stage(), self.stage()
        self.publish(first.attempt_id)
        live, before = self.live(), snapshot(self.publish_root)
        with mock.patch.object(pub.os, "replace", side_effect=OSError("EXDEV")):
            result = self.publish(second.attempt_id)
        self.assertEqual((result.status, result.switched), (pub.SWITCH_FAILED, False))
        self.assertEqual(self.live(), live)
        self.assertEqual(snapshot(self.publish_root), before)                # the temporary symlink was removed
        self.assertNotIn("EXDEV", json.dumps(result.as_dict()))

    def test_post_switch_verification_failure_is_reported_as_inconsistent(self):
        attempt = self.stage()
        with mock.patch.object(pub, "_verify_pointer", return_value=False):
            result = self.publish(attempt.attempt_id)
        self.assertEqual((result.status, result.switched, result.failure_category), (pub.INCONSISTENT, True, "post_switch_verification_failed"))
        self.assertEqual(pub.exit_code(result), pub.EXIT_INCONSISTENT)
        self.assertFalse((self.publish_root / "CURRENT.json").exists())      # never claims a build it could not verify
        self.assertTrue(result.history_record)

    def test_history_write_failure_is_reported_as_inconsistent(self):
        attempt = self.stage()
        with mock.patch.object(pub, "_write_history", side_effect=OSError("read-only fs")):
            result = self.publish(attempt.attempt_id)
        self.assertEqual((result.status, result.switched, result.failure_category), (pub.INCONSISTENT, True, "history_write_failed"))
        self.assertEqual(Path(self.live()), self.site(attempt))
        self.assertTrue(any("run 'publish" in problem for problem in result.problems))
        repaired = self.publish(attempt.attempt_id)                           # the documented recovery
        self.assert_published(repaired, attempt, previous=attempt.attempt_id)

    def test_current_metadata_write_failure_is_reported_as_inconsistent(self):
        first, second = self.stage(), self.stage()
        self.publish(first.attempt_id)
        with mock.patch.object(pub, "_write_current_metadata", side_effect=OSError("quota")):
            result = self.publish(second.attempt_id)
        self.assertEqual((result.status, result.failure_category), (pub.INCONSISTENT, "current_metadata_write_failed"))
        self.assertEqual(pub.current_consistency(self.config),
                         {"live_attempt_id": second.attempt_id, "recorded_attempt_id": first.attempt_id, "consistent": False})
        self.assertNotIn("quota", json.dumps(result.as_dict()))

    def test_replace_happens_only_inside_the_publish_directory(self):
        """Cross-filesystem invariant: only a symlink is renamed, within one directory; no build is ever moved."""
        attempt = self.stage()
        calls, real = [], os.replace
        with mock.patch.object(pub.os, "replace", side_effect=lambda a, b: (calls.append((Path(a), Path(b))), real(a, b))[1]):
            self.assert_published(self.publish(attempt.attempt_id), attempt)
        root = self.publish_root.resolve()
        self.assertEqual([(a.parent, b.parent) for a, b in calls], [(root, root)] * len(calls))
        self.assertIn((root / ".current.{}.tmp".format(json.loads((root / "CURRENT.json").read_text())["publication_id"]), root / "current"), calls)

    def test_unsafe_current_is_never_overwritten(self):
        attempt = self.stage()
        self.publish_root.mkdir(parents=True)
        self.pointer.mkdir()
        (self.pointer / "index.html").write_text("hand-made")
        self.assert_rejected(self.publish(attempt.attempt_id), "unsafe_current", None)
        self.assertEqual((self.pointer / "index.html").read_text(), "hand-made")
        shutil.rmtree(self.pointer)
        os.symlink("/tmp", self.pointer)
        self.assert_rejected(self.publish(attempt.attempt_id), "unsafe_current", "/tmp")

    # 16, 17 — history and CURRENT.json
    def test_16_17_history_and_current_metadata(self):
        first, second = self.stage(), self.stage()
        one, two = self.publish(first.attempt_id), self.publish(second.attempt_id)
        self.publish("20260101T000000Z-000000000000")                         # a rejection is recorded too
        names = sorted(p.name for p in (self.publish_root / "history").iterdir())
        self.assertEqual([n[:7] for n in names], ["000001-", "000002-", "000003-"])
        records = [json.loads((self.publish_root / "history" / n).read_text()) for n in names]
        self.assertEqual([(r["action"], r["status"], r["switched"], r["attempt_id"]) for r in records],
                         [("publish", "published", True, first.attempt_id), ("publish", "published", True, second.attempt_id),
                          ("publish", "rejected", False, "20260101T000000Z-000000000000")])
        self.assertEqual(records[1]["previous_attempt_id"], first.attempt_id)
        self.assertEqual(records[1]["build_metadata_sha256"], sync._sha256((Path(second.staged_build_dir) / "build.json").read_bytes()))
        self.assertEqual((records[1]["contract_version"], records[1]["board_id"], records[1]["source_run_id"]),
                         ("1.4.0", self.config.board_id, second.source_run_id))
        for name in names:                                                    # history records are read-only once written
            self.assertEqual(stat.S_IMODE((self.publish_root / "history" / name).stat().st_mode), 0o444)
        current = json.loads((self.publish_root / "CURRENT.json").read_text())
        self.assertEqual(current["publication_id"], two.publication_id)
        self.assertEqual(Path(current["current_target"]), self.pointer.resolve())
        self.assertEqual(current["current_link"], os.readlink(self.pointer))
        self.assertEqual(current["attempt_id"], self.pointer.resolve().parent.name)
        self.assertEqual(current["history_record"], two.history_record)
        self.assertNotEqual(one.publication_id, two.publication_id)

    # 19, 20, 21, 22 — rollback
    def test_19_rollback_returns_to_the_previous_published_build(self):
        first, second = self.stage(), self.stage()
        self.publish(first.attempt_id)
        self.publish(second.attempt_id)
        result = self.rollback()
        self.assertEqual(result.action, "rollback")
        self.assert_published(result, first, previous=second.attempt_id)
        record = json.loads(Path(result.history_record).read_text())
        self.assertEqual((record["action"], record["attempt_id"], record["previous_attempt_id"]), ("rollback", first.attempt_id, second.attempt_id))
        self.assertEqual(json.loads((self.publish_root / "CURRENT.json").read_text())["action"], "rollback")

    def test_20_explicit_rollback_only_to_a_previously_published_build(self):
        first, second, never = self.stage(), self.stage(), self.stage()
        self.publish(first.attempt_id)
        self.publish(second.attempt_id)
        live = self.live()
        self.assert_rejected(self.rollback(never.attempt_id), "not_previously_published", live)
        self.assert_rejected(self.rollback(second.attempt_id), "already_current", live)
        self.assert_rejected(self.rollback("../x"), "invalid_attempt_id", live)
        self.assert_published(self.rollback(first.attempt_id), first, previous=second.attempt_id)

    def test_21_22_rollback_to_a_tampered_build_is_rejected_and_current_unchanged(self):
        first, second = self.stage(), self.stage()
        self.publish(first.attempt_id)
        self.publish(second.attempt_id)
        live, before = self.live(), (self.publish_root / "CURRENT.json").read_bytes()
        (self.site(first) / "ar/dashboard.html").write_text("<html>tampered</html>")
        result = self.rollback()
        self.assert_rejected(result, "build_tampered", live)
        self.assertEqual((self.publish_root / "CURRENT.json").read_bytes(), before)
        empty = pub.rollback(None, {**self.env, "ATLAS_DATA_DIR": str(self.data / "empty")})
        self.assertEqual((empty.status, empty.failure_category), (pub.REJECTED, "nothing_published"))

    def test_rollback_without_an_earlier_publication(self):
        attempt = self.stage()
        self.publish(attempt.attempt_id)
        self.assert_rejected(self.rollback(), "no_previous_publication", self.live())

    # 24 — build files are never modified
    def test_24_publish_and_rollback_never_modify_build_files(self):
        first, second = self.stage(), self.stage()
        builds = self.data / "builds"
        before = {name: value for name, value in snapshot(builds).items() if not name.startswith("attempts")}
        raw_before = snapshot(self.data / "raw")
        self.publish(first.attempt_id)
        self.publish(second.attempt_id)
        self.rollback()
        self.publish(second.attempt_id)
        after = {name: value for name, value in snapshot(builds).items() if not name.startswith("attempts")}
        self.assertEqual(after, before)
        self.assertEqual(snapshot(self.data / "raw"), raw_before)

    # 25 — no token
    def test_25_publication_never_exposes_the_token(self):
        first, second = self.stage(), self.stage()
        out = io.StringIO()
        with redirect_stdout(out):
            results = [self.publish(first.attempt_id), self.publish(second.attempt_id), self.rollback(), self.publish("bad")]
            for result in results:
                print(pub.summary(result), json.dumps(result.as_dict()))
        self.assertNotIn(TOKEN, out.getvalue())
        for path in [p for p in self.publish_root.rglob("*") if p.is_file()]:
            self.assertNotIn(TOKEN.encode(), path.read_bytes(), path)
        self.assertIsNotNone(self.config.monday_token)                        # the token really was configured

    def test_token_inside_a_build_blocks_publication(self):
        attempt = self.stage()
        self._rewrite_metadata(attempt, lambda m: m.update(note=f"leak {TOKEN}"))
        result = self.publish(attempt.attempt_id)
        self.assert_rejected(result, "build_tampered", None)
        self.assertNotIn(TOKEN, json.dumps(result.as_dict()))

    # 26, 27 — CLI
    def cli(self, *argv):
        out = io.StringIO()
        with mock.patch.dict(os.environ, self.env, clear=True), redirect_stdout(out):
            code = sync_cli.main(list(argv))
        return code, out.getvalue()

    def test_26_cli_publish_exit_codes(self):
        attempt = self.stage()
        code, text = self.cli("publish", attempt.attempt_id)
        self.assertEqual(code, 0)
        self.assertIn("PUBLISH SUCCEEDED", text)
        self.assertEqual(Path(self.live()), self.site(attempt))
        code, text = self.cli("publish", "20260101T000000Z-000000000000")
        self.assertEqual(code, pub.EXIT_REJECTED)
        self.assertIn("REJECTED (live site unchanged)", text)
        other = self.stage()
        with mock.patch.object(pub.os, "replace", side_effect=OSError):
            self.assertEqual(self.cli("publish", other.attempt_id)[0], pub.EXIT_SWITCH_FAILED)
        with mock.patch.object(pub, "_write_current_metadata", side_effect=OSError):
            code, text = self.cli("publish", other.attempt_id)
        self.assertEqual(code, pub.EXIT_INCONSISTENT)
        self.assertIn("METADATA INCONSISTENT", text)
        code, text = self.cli("publish", "--json", other.attempt_id)
        self.assertEqual((code, json.loads(text)["status"]), (0, "published"))
        with mock.patch.dict(os.environ, {"ATLAS_DATA_DIR": "relative/path"}, clear=True), redirect_stdout(io.StringIO()):
            self.assertEqual(sync_cli.main(["publish", attempt.attempt_id]), pub.EXIT_CONFIG)

    def test_27_cli_rollback_exit_codes(self):
        first, second = self.stage(), self.stage()
        self.assertEqual(self.cli("rollback")[0], pub.EXIT_REJECTED)          # nothing published yet
        self.cli("publish", first.attempt_id)
        self.cli("publish", second.attempt_id)
        code, text = self.cli("rollback")
        self.assertEqual(code, 0)
        self.assertIn("ROLLBACK SUCCEEDED", text)
        self.assertEqual(Path(self.live()), self.site(first))
        code, _ = self.cli("rollback", second.attempt_id)
        self.assertEqual((code, Path(self.live())), (0, self.site(second)))

    # 28 — run-once still only stages
    def test_28_run_once_never_publishes(self):
        attempt = self.stage()
        self.assertFalse(self.publish_root.exists() and any(self.publish_root.iterdir()))
        self.assertFalse(self.pointer.exists() or self.pointer.is_symlink())
        self.assertEqual(sync.build_state(Path(attempt.staged_build_dir)), "complete")
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(sync_cli, "run_once", functools.partial(sync.run_once, transport=FakeMonday(logs(), items()),
                                                                          clock=Clock(start=T0 + timedelta(days=20)))), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(sync_cli.main(["run-once"]), 0)
        self.assertFalse(self.pointer.exists() or self.pointer.is_symlink())
        source = Path(sync.__file__).read_text()
        for forbidden in ("from .publish", "import publish", "symlink", "os.replace", "publish_dir"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
