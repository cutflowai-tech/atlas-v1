"""Cross-process production lock (Task 6): real flock between real processes, fake Monday only."""

import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest import mock

from test_ingest import FakeMonday, items
from test_sync_run import T0, TOKEN, Clock, Monotonic, logs

from atlas_sync import __main__ as sync_cli
from atlas_sync import lock as locking
from atlas_sync import publish as pub
from atlas_sync import run as sync
from atlas_sync.config import ConfigError, load_sync_config

ROOT = Path(__file__).resolve().parents[1]
HELPER = Path(__file__).resolve().parent / "lock_holder.py"
HISTORY = "2026-08-15T00:00:00Z"
OPERATIONS = ("run-once", "publish", "rollback")


class LockTests(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="atlas-lock-"))
        assert not any((parent / ".git").exists() for parent in [self.data, *self.data.parents])
        self.env = {"MONDAY_API_TOKEN": TOKEN, "ATLAS_DATA_DIR": str(self.data), "ATLAS_HISTORY_START": HISTORY}
        self.config = load_sync_config(self.env, now=T0)
        self.lock_file = self.data / "locks" / "production.lock"
        self.days = 0
        self.children = []

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)
            for stream in (child.stdin, child.stdout):
                if stream:
                    stream.close()
        shutil.rmtree(self.data, ignore_errors=True)

    # --- helpers -------------------------------------------------------------------------------------------------

    def child_env(self, env=None):
        return {**os.environ, **(env or self.env), "PYTHONPATH": f"{ROOT / 'src'}{os.pathsep}{ROOT / 'tests'}"}

    @contextmanager
    def holding(self, operation, target=None, env=None):
        """Another process holds the production lock (real flock) for the ``with`` block."""
        args = [sys.executable, str(HELPER), "hold", operation, *([target] if target else [])]
        child = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=self.child_env(env), text=True)
        self.children.append(child)
        line = child.stdout.readline()
        self.assertTrue(line, "lock holder did not start")
        try:
            yield child, json.loads(line)
        finally:
            if child.poll() is None:
                child.stdin.close()
                child.wait(timeout=10)

    def probe(self, env=None):
        """Can another process take the lock right now? (never waits)"""
        done = subprocess.run([sys.executable, str(HELPER), "probe"], capture_output=True, text=True, env=self.child_env(env), timeout=30, check=True)
        return json.loads(done.stdout)

    def stage(self, transport=None):
        self.days += 1
        result = sync.run_once(self.env, transport=transport or FakeMonday(logs(), items()), clock=Clock(start=T0 + timedelta(days=self.days)),
                               monotonic=Monotonic(), sleep=lambda s: None)
        self.assertEqual(result.status, "success", result.as_dict())
        return result

    def clock(self):
        return Clock(start=T0 + timedelta(days=40))

    def published_pair(self):
        """Two published builds (so rollback has a target) and a third, staged but unpublished."""
        first, second, third = self.stage(), self.stage(), self.stage()
        self.assertEqual(pub.publish(first.attempt_id, self.env, clock=self.clock()).status, pub.PUBLISHED)
        self.assertEqual(pub.publish(second.attempt_id, self.env, clock=self.clock()).status, pub.PUBLISHED)
        return first, second, third

    def state(self):
        """Everything a production operation could change."""
        publish_root = self.data / "published"
        raw = self.data / "raw" / "monday"
        builds = self.data / "builds"
        return {"raw_runs": sorted(p.name for p in raw.iterdir()) if raw.exists() else [],
                "builds": sorted(p.name for p in builds.iterdir()) if builds.exists() else [],
                "attempt_records": sorted(p.name for p in (builds / "attempts").iterdir()) if (builds / "attempts").exists() else [],
                "current": os.readlink(publish_root / "current") if (publish_root / "current").is_symlink() else None,
                "current_json": (publish_root / "CURRENT.json").read_bytes() if (publish_root / "CURRENT.json").exists() else None,
                "history": sorted(p.name for p in (publish_root / "history").iterdir()) if (publish_root / "history").exists() else []}

    def request(self, operation, fake, target):
        if operation == "run-once":
            return sync.run_once(self.env, transport=fake, clock=Clock(start=T0 + timedelta(days=50)), monotonic=Monotonic())
        if operation == "publish":
            return pub.publish(target, self.env, clock=self.clock())
        return pub.rollback(None, self.env, clock=self.clock())

    def assert_locked(self, result, operation, holder_operation):
        lock = result.lock
        self.assertEqual((result.status, lock["status"], lock["category"], lock["requested_operation"]),
                         ("locked", "locked", "operation_locked", operation))
        self.assertEqual(lock["holder"]["operation"], holder_operation)
        self.assertRegex(lock["at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        code = sync.exit_code(result) if operation == "run-once" else pub.exit_code(result)
        self.assertEqual(code, locking.EXIT_LOCKED)
        self.assertNotIn(TOKEN, json.dumps(result.as_dict()))

    # --- 1: run-once holds the lock for its whole operation ------------------------------------------------------

    def test_1_run_once_holds_the_lock_from_the_first_monday_request_to_the_end(self):
        seen = []
        fake = FakeMonday(logs(), items())

        def probing(query, variables):
            if not fake.queries:
                seen.append(self.probe())
            return fake(query, variables)

        real = sync.build_dashboard_files

        def dashboard(*args, **kwargs):
            seen.append(self.probe())
            return real(*args, **kwargs)

        with mock.patch.object(sync, "build_dashboard_files", dashboard):
            result = sync.run_once(self.env, transport=probing, clock=Clock(), monotonic=Monotonic())
        self.assertEqual(result.status, "success")
        self.assertEqual(len(seen), 2)
        for probe in seen:
            self.assertFalse(probe["acquired"])
            self.assertEqual((probe["holder"]["operation"], probe["holder"]["pid"], probe["holder"]["target"]),
                             ("run-once", os.getpid(), result.attempt_id))
        self.assertTrue(self.probe()["acquired"])                                  # 14: released on completion
        self.assertEqual(self.lock_file.read_bytes(), b"")                         # a clean release leaves no metadata

    def test_publish_and_rollback_hold_the_lock_while_validating_and_switching(self):
        _first, _second, third = self.published_pair()
        seen = []
        real = pub.validate_build

        def validating(config, attempt_id):
            seen.append(self.probe())
            return real(config, attempt_id)

        with mock.patch.object(pub, "validate_build", validating):
            self.assertEqual(pub.publish(third.attempt_id, self.env, clock=self.clock()).status, pub.PUBLISHED)
            self.assertEqual(pub.rollback(None, self.env, clock=self.clock()).status, pub.PUBLISHED)
        self.assertEqual([(p["acquired"], p["holder"]["operation"], p["holder"]["target"]) for p in seen],
                         [(False, "publish", third.attempt_id), (False, "rollback", None)])
        self.assertTrue(self.probe()["acquired"])

    # --- 2-13, 22: every operation is refused while any other holds the lock, and changes nothing ---------------

    def test_2_to_13_every_operation_is_refused_while_another_holds_the_lock(self):
        _first, _second, third = self.published_pair()
        for holder in OPERATIONS:
            with self.holding(holder, third.attempt_id if holder == "publish" else None) as (_child, metadata):
                self.assertEqual(metadata["operation"], holder)
                for operation in OPERATIONS:
                    with self.subTest(holder=holder, requested=operation):
                        before = self.state()
                        fake = FakeMonday(logs(), items())
                        result = self.request(operation, fake, third.attempt_id)
                        self.assert_locked(result, operation, holder)
                        self.assertEqual(fake.queries, [])                        # 9: no Monday request
                        self.assertEqual(self.state(), before)                    # 10-13: no raw run, build, record, switch or history
            self.assertTrue(self.probe()["acquired"])                              # released when the holder ends

    def test_22_public_entry_points_take_the_lock_and_helpers_are_private(self):
        """The Python entry points are the ownership layer; the unlocked bodies are private and documented as such."""
        self.assertTrue(callable(sync._attempt) and callable(pub._run_locked))   # unlocked bodies: private, called only under the lock
        self.assertIn("never call this without it", pub._run_locked.__doc__)
        for public in (sync.run_once, pub.publish, pub.rollback):
            self.assertFalse(public.__name__.startswith("_"))
        with self.holding("publish"):
            self.assertEqual(sync.run_once(self.env, transport=FakeMonday(logs(), items()), clock=Clock()).status, "locked")
            self.assertEqual(pub.publish("20260101T000000Z-000000000000", self.env).status, pub.LOCKED)
            self.assertEqual(pub.rollback("20260101T000000Z-000000000000", self.env).status, pub.LOCKED)

    # --- 14-16: release on normal completion, exceptions and interruption ----------------------------------------

    def test_14_15_16_the_lock_is_released_on_every_exit_path(self):
        _first, _second, third = self.published_pair()
        self.assertTrue(self.probe()["acquired"])                                  # after two publishes
        self.assertEqual(pub.rollback(None, self.env, clock=self.clock()).status, pub.PUBLISHED)
        self.assertTrue(self.probe()["acquired"])                                  # after a rollback
        with mock.patch.object(sync, "build_profiles", side_effect=RuntimeError("boom")):
            self.assertEqual(self.request("run-once", FakeMonday(logs(), items()), None).status, "failed")
        self.assertTrue(self.probe()["acquired"])                                  # after a failed attempt
        with mock.patch.object(pub, "_promote", side_effect=RuntimeError("unexpected")), self.assertRaises(RuntimeError):
            pub.publish(third.attempt_id, self.env)
        self.assertTrue(self.probe()["acquired"])                                  # after an exception escaping publish
        with mock.patch.object(sync, "build_dashboard_files", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.request("run-once", FakeMonday(logs(), items()), None)
        self.assertTrue(self.probe()["acquired"])                                  # after Ctrl-C
        with self.assertRaises(ValueError), locking.production_lock(self.config, "publish"):
            raise ValueError("inside the lock")
        self.assertTrue(self.probe()["acquired"])

    def test_16_sigint_to_a_holding_process_releases_the_lock(self):
        with self.holding("run-once") as (child, _metadata):
            self.assertFalse(self.probe()["acquired"])
            child.send_signal(signal.SIGINT)
            child.wait(timeout=10)
        self.assertTrue(self.probe()["acquired"])

    # --- 17, 18: a killed holder never leaves Atlas locked -------------------------------------------------------

    def test_17_18_killed_holder_leaves_a_file_but_no_lock(self):
        with self.holding("publish", "20260101T000000Z-000000000000") as (child, _metadata):
            child.kill()                                                           # SIGKILL: no cleanup code runs
            child.wait(timeout=10)
        self.assertTrue(self.lock_file.exists())                                   # the physical file stays...
        stale = json.loads(self.lock_file.read_text())
        self.assertEqual((stale["operation"], stale["pid"]), ("publish", child.pid))   # ...with the dead holder's metadata
        self.assertTrue(self.probe()["acquired"])                                  # but the OS lock is free
        self.assertEqual(self.stage().status, "success")                           # and a real attempt runs

    # --- 19, 20: metadata is safe and diagnostic only ------------------------------------------------------------

    def test_19_holder_metadata_is_safe(self):
        with self.holding("publish", "20260101T000000Z-0123456789ab") as (child, metadata):
            text = self.lock_file.read_text()
            on_disk = json.loads(text)
            locked = self.request("run-once", FakeMonday(logs(), items()), None)
        self.assertEqual(on_disk, metadata)
        self.assertEqual(set(on_disk), {"lock_version", "operation", "pid", "hostname", "acquired_at", "target"})
        self.assertEqual((on_disk["operation"], on_disk["pid"], on_disk["target"]), ("publish", child.pid, "20260101T000000Z-0123456789ab"))
        self.assertRegex(on_disk["acquired_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(locked.lock["holder"], on_disk)
        for secret in (TOKEN, "Authorization", "MONDAY_API_TOKEN"):
            self.assertNotIn(secret, text)
        with self.holding("publish", "../../etc/passwd") as (_child, metadata):
            self.assertEqual(metadata["target"], "invalid")                       # untrusted targets are never echoed

    def test_20_metadata_is_not_proof_of_ownership(self):
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file.write_text(json.dumps({"operation": "publish", "pid": 1, "acquired_at": "2026-01-01T00:00:00Z"}))
        self.assertEqual(self.stage().status, "success")                           # stale-looking metadata, nobody holding: runs
        with self.holding("run-once"):
            os.truncate(self.lock_file, 0)                                         # metadata erased, OS lock still held
            result = self.request("run-once", FakeMonday(logs(), items()), None)
        self.assertEqual((result.status, result.lock["holder"]), ("locked", None))

    # --- 21: unsafe lock locations fail closed -------------------------------------------------------------------

    def test_21_unsafe_lock_paths_are_rejected(self):
        elsewhere = Path(tempfile.mkdtemp(prefix="atlas-lock-elsewhere-"))
        self.addCleanup(shutil.rmtree, elsewhere, ignore_errors=True)
        locks = self.data / "locks"

        def refused(stage="lock", category="lock_configuration"):
            fake = FakeMonday(logs(), items())
            result = self.request("run-once", fake, None)
            self.assertEqual((result.status, result.failing_stage, result.error_category), ("failed", stage, category))
            self.assertEqual(sync.exit_code(result), 2)
            self.assertEqual(fake.queries, [])
            published = pub.publish("20260101T000000Z-000000000000", self.env)
            self.assertEqual((published.status, published.failure_category, published.history_record), (pub.REJECTED, category, None))
            self.assertEqual(pub.exit_code(published), pub.EXIT_CONFIG)

        os.symlink(elsewhere, locks)                     # symlinked lock directory escaping the data root: refused by configuration
        refused("configuration", "configuration")
        with self.assertRaises(locking.LockError), locking.production_lock(self.config, "run-once"):   # and by the lock itself
            pass
        self.assertEqual(list(elsewhere.iterdir()), [])
        locks.unlink()
        locks.mkdir()
        os.symlink(elsewhere / "target.lock", locks / "production.lock")           # symlinked lock file: never followed
        refused()
        self.assertFalse((elsewhere / "target.lock").exists())
        (locks / "production.lock").unlink()
        (elsewhere / "other").write_text("")
        os.link(elsewhere / "other", locks / "production.lock")                    # hard link to another file
        refused()
        self.assertEqual(self.state()["raw_runs"], [])

        for env, message in (({"ATLAS_LOCK_DIR": str(ROOT / "locks")}, "must be inside ATLAS_DATA_DIR"),
                             ({"ATLAS_LOCK_DIR": str(self.data / "builds" / "locks")}, "separate, non-nested"),
                             ({"ATLAS_LOCK_DIR": str(elsewhere)}, "must be inside ATLAS_DATA_DIR"),
                             ({"ATLAS_LOCK_DIR": "relative/locks"}, "absolute path")):
            with self.subTest(env=env), self.assertRaises(ConfigError) as caught:
                load_sync_config({**self.env, **env}, now=T0)
            self.assertIn(message, str(caught.exception))
        git_env = {**{k: v for k, v in self.env.items() if k != "ATLAS_DATA_DIR"}, "ATLAS_RAW_DIR": str(elsewhere / "raw"),
                   "ATLAS_BUILD_DIR": str(elsewhere / "b"), "ATLAS_PUBLISH_DIR": str(elsewhere / "p"), "ATLAS_LOCK_DIR": str(ROOT / "locks")}
        with self.assertRaisesRegex(ConfigError, "outside any Git checkout"):
            load_sync_config(git_env, now=T0)
        no_lock = {k: v for k, v in git_env.items() if k != "ATLAS_LOCK_DIR"}      # explicit dirs without a lock dir: fails closed
        fake = FakeMonday(logs(), items())
        result = sync.run_once(no_lock, transport=fake, clock=Clock())
        self.assertEqual((result.status, result.error_category, fake.queries), ("failed", "lock_configuration", []))
        self.assertEqual(pub.rollback(None, no_lock).failure_category, "lock_configuration")

    # --- 23: no self-deadlock ------------------------------------------------------------------------------------

    def test_23_cli_calls_the_locked_entry_points_once_without_deadlock(self):
        first = self.stage()
        cli = [sys.executable, "-c", "import sys; from atlas_sync.__main__ import main; sys.exit(main(sys.argv[1:]))"]
        done = subprocess.run([*cli, "publish", first.attempt_id], capture_output=True, text=True, env=self.child_env(), timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        second = self.stage()
        self.assertEqual(subprocess.run([*cli, "publish", second.attempt_id], capture_output=True, env=self.child_env(), timeout=60, check=False).returncode, 0)
        done = subprocess.run([*cli, "rollback"], capture_output=True, text=True, env=self.child_env(), timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(os.path.basename(os.path.dirname(os.readlink(self.data / "published" / "current"))), first.attempt_id)
        with locking.production_lock(self.config, "run-once"):                     # re-entry in one process fails fast, never hangs
            nested = self.request("run-once", FakeMonday(logs(), items()), None)
        self.assertEqual((nested.status, nested.lock["holder"]["pid"]), ("locked", os.getpid()))

    # --- 24: one exit code for contention -------------------------------------------------------------------------

    def test_24_all_three_commands_exit_75_when_locked(self):
        first, _second, third = self.published_pair()
        cli = [sys.executable, "-c", "import sys; from atlas_sync.__main__ import main; sys.exit(main(sys.argv[1:]))"]
        with self.holding("run-once"):
            for argv in (["run-once"], ["publish", third.attempt_id], ["rollback"], ["rollback", first.attempt_id]):
                done = subprocess.run([*cli, *argv], capture_output=True, text=True, env=self.child_env(), timeout=60, check=False)
                self.assertEqual(done.returncode, locking.EXIT_LOCKED, (argv, done.stdout, done.stderr))
                self.assertIn("LOCKED", done.stdout)
                self.assertNotIn(TOKEN, done.stdout + done.stderr)
        self.assertEqual(locking.EXIT_LOCKED, 75)
        self.assertNotIn(locking.EXIT_LOCKED, {sync.EXIT_OK, sync.EXIT_ACCESS, sync.EXIT_MONDAY, sync.EXIT_VERIFICATION, sync.EXIT_BUILD,
                                               sync.EXIT_TIMEOUT, pub.EXIT_CONFIG, pub.EXIT_REJECTED, pub.EXIT_SWITCH_FAILED, pub.EXIT_INCONSISTENT})
        out = io.StringIO()
        with self.holding("rollback"), mock.patch.dict(os.environ, self.env, clear=True), redirect_stdout(out):
            self.assertEqual(sync_cli.main(["rollback", "--json"]), locking.EXIT_LOCKED)
        self.assertEqual(json.loads(out.getvalue())["lock"]["holder"]["operation"], "rollback")

    # --- 26: relative publication link ---------------------------------------------------------------------------

    def test_26_current_is_a_relative_link_that_survives_moving_the_data_root(self):
        _first, second, _third = self.published_pair()
        link = os.readlink(self.data / "published" / "current")
        self.assertEqual(link, f"../builds/{second.attempt_id}/site")
        self.assertFalse(os.path.isabs(link))
        self.assertEqual((self.data / "published" / "current").resolve(), (self.data / "builds" / second.attempt_id / "site").resolve())
        moved = Path(tempfile.mkdtemp(prefix="atlas-lock-moved-")) / "data"
        self.addCleanup(shutil.rmtree, moved.parent, ignore_errors=True)
        os.rename(self.data, moved)                                                # same filesystem: the whole root moves
        try:
            config = load_sync_config({**self.env, "ATLAS_DATA_DIR": str(moved)}, now=T0)
            pointer = moved / "published" / "current"
            self.assertEqual(pointer.resolve(), (moved / "builds" / second.attempt_id / "site").resolve())
            self.assertEqual(pub.live_attempt(config), second.attempt_id)
            self.assertEqual((pointer / "dashboard.html").read_bytes(), (moved / "builds" / second.attempt_id / "site" / "dashboard.html").read_bytes())
            self.assertTrue(pub.current_consistency(config)["consistent"])
            # build.json records the absolute raw run path, so re-validating an old build after a move fails closed.
            moved_rollback = pub.rollback(None, {**self.env, "ATLAS_DATA_DIR": str(moved)})
            self.assertEqual((moved_rollback.status, moved_rollback.failure_category), (pub.REJECTED, "wrong_source_run"))
            self.assertEqual(os.readlink(pointer), link)
        finally:
            os.rename(moved, self.data)

    def test_26b_a_link_that_would_not_resolve_to_the_site_is_refused(self):
        attempt = self.stage()
        site = self.data / "builds" / attempt.attempt_id / "site"
        alias = self.data / "alias"
        os.symlink(self.data / "builds", alias)
        self.assertEqual(pub.link_text(self.config, site.resolve()), f"../builds/{attempt.attempt_id}/site")
        with self.assertRaises(pub.PublishRejected) as caught:
            pub.link_text(self.config, alias / attempt.attempt_id / "site")        # not the canonical site path
        self.assertEqual(caught.exception.category, "unsafe_path")

    # --- 27: build files untouched, lock state kept out of builds and the repository -----------------------------

    def test_27_lock_state_never_touches_builds_raw_or_the_repository(self):
        _first, _second, third = self.published_pair()
        builds_before = {p: p.read_bytes() for p in (self.data / "builds").rglob("*") if p.is_file() and "attempts" not in p.parts}
        pub.rollback(None, self.env, clock=self.clock())
        pub.publish(third.attempt_id, self.env, clock=self.clock())
        builds_after = {p: p.read_bytes() for p in (self.data / "builds").rglob("*") if p.is_file() and "attempts" not in p.parts}
        self.assertEqual(builds_after, builds_before)
        self.assertEqual(sorted(p.name for p in (self.data / "locks").iterdir()), ["production.lock"])
        self.assertFalse(any(re.search(r"production\.lock", p.name) for p in ROOT.rglob("*.lock")))


if __name__ == "__main__":
    unittest.main()
