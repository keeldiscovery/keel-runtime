"""Tests for keel_runtime.heartbeat (spec 021): write/read round-trip, atomic write,
corrupt-file handling, pid liveness, and staleness (data-model.md, research.md §2-3).
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from keel_runtime import heartbeat


class HeartbeatWriteReadTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_round_trip_preserves_all_four_fields(self):
        hb = heartbeat.Heartbeat(
            pid=12345,
            agent_session_id="5b2e2f0a-9c3b-4b7e-8f3a-1e6c9b7a2d10",
            base_url="https://cloud.keel.example",
            last_heartbeat_at="2026-09-02T13:04:11.482Z",
        )
        heartbeat.write(self.home, hb)
        read_back = heartbeat.read(self.home)
        self.assertEqual(read_back, hb)

    def test_round_trip_preserves_the_launcher_version_and_the_job_in_hand(self):
        """spec `007-launcher-version`: the two optional fields survive a write and a read, and a
        heartbeat written before the spec -- no such keys at all -- reads back as an unknown
        launcher, idle."""
        hb = heartbeat.Heartbeat(
            pid=12345,
            agent_session_id="5b2e2f0a-9c3b-4b7e-8f3a-1e6c9b7a2d10",
            base_url="https://cloud.keel.example",
            last_heartbeat_at="2026-09-02T13:04:11.482Z",
            launcher_version="1.1.0",
            job_id="job-7",
        )
        heartbeat.write(self.home, hb)
        self.assertEqual(heartbeat.read(self.home), hb)
        heartbeat.path(self.home).write_text(json.dumps({
            "pid": 12345, "agent_session_id": None, "base_url": "https://cloud.keel.example",
            "last_heartbeat_at": "2026-09-02T13:04:11.482Z"}))
        old = heartbeat.read(self.home)
        self.assertIsNone(old.launcher_version)
        self.assertIsNone(old.job_id)

    def test_write_uses_the_documented_path(self):
        hb = heartbeat.Heartbeat(1, "a", "http://x", "2026-09-02T00:00:00.000Z")
        heartbeat.write(self.home, hb)
        self.assertTrue((self.home / "runtime.heartbeat.json").exists())

    def test_write_leaves_no_tmp_file_behind(self):
        hb = heartbeat.Heartbeat(1, "a", "http://x", "2026-09-02T00:00:00.000Z")
        heartbeat.write(self.home, hb)
        self.assertFalse((self.home / "runtime.heartbeat.json.tmp").exists())

    def test_read_of_missing_file_is_none(self):
        self.assertIsNone(heartbeat.read(self.home))

    def test_read_of_missing_home_directory_is_none(self):
        self.assertIsNone(heartbeat.read(self.home / "does-not-exist"))

    def test_read_of_corrupt_json_is_none(self):
        (self.home / "runtime.heartbeat.json").write_text("{not valid json")
        self.assertIsNone(heartbeat.read(self.home))

    def test_read_of_valid_json_missing_a_required_key_is_none(self):
        (self.home / "runtime.heartbeat.json").write_text(
            json.dumps({"pid": 1, "agent_session_id": "a", "base_url": "http://x"})
        )
        self.assertIsNone(heartbeat.read(self.home))

    def test_read_of_a_json_array_is_none(self):
        (self.home / "runtime.heartbeat.json").write_text(json.dumps([1, 2, 3]))
        self.assertIsNone(heartbeat.read(self.home))

    def test_remove_on_missing_file_does_not_raise(self):
        heartbeat.remove(self.home)  # should not raise

    def test_remove_deletes_an_existing_file(self):
        heartbeat.write(self.home, heartbeat.Heartbeat(1, "a", "http://x", "2026-09-02T00:00:00.000Z"))
        heartbeat.remove(self.home)
        self.assertIsNone(heartbeat.read(self.home))

    def test_write_then_write_again_overwrites_in_place(self):
        heartbeat.write(self.home, heartbeat.Heartbeat(1, "a", "http://x", "2026-09-02T00:00:00.000Z"))
        heartbeat.write(self.home, heartbeat.Heartbeat(2, "b", "http://y", "2026-09-02T00:00:01.000Z"))
        read_back = heartbeat.read(self.home)
        self.assertEqual(read_back.pid, 2)
        self.assertEqual(read_back.agent_session_id, "b")


class PidAliveTest(unittest.TestCase):
    def test_true_for_this_test_process_itself(self):
        self.assertTrue(heartbeat.pid_alive(os.getpid()))

    def test_false_for_a_pid_very_unlikely_to_exist(self):
        # PIDs are bounded well below this on every platform keel-runtime targets.
        self.assertFalse(heartbeat.pid_alive(2**30))

    def test_false_for_a_pid_that_just_exited(self):
        """A real child process, reaped by this process (its real parent) before the assertion --
        portable across platforms, unlike `os.fork` (POSIX-only; the real-zombie case below stays
        fork-based and POSIX-only, since Windows has no zombie state for `pid_alive` to see
        through in the first place).
        """
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        self.assertFalse(heartbeat.pid_alive(child.pid))

    @unittest.skipIf(sys.platform == "win32", "os.fork is POSIX-only; no zombie state on Windows")
    def test_false_for_a_real_zombie(self):
        """keel-e2e-eval DRIFT #57: a child that has exited but was never `wait()`-ed for is a
        zombie -- it still answers `os.kill(pid, 0)`, which is exactly what made `pid_alive`
        wrong before this fix. This test is deliberately its own parent (via `os.fork`, not
        `Popen`+detach) so it -- not init, not launchd -- is the one that would otherwise reap
        the child; it holds off on `os.waitpid` until after the assertion, so the pid is
        observably a zombie at the moment `pid_alive` is asked about it.
        """
        pid = os.fork()
        if pid == 0:  # pragma: no cover -- child process branch
            os._exit(0)
        try:
            # `os._exit` in the child races the parent resuming from `fork()`; retry briefly
            # rather than asserting on the very first sample, so this isn't flaky under load.
            # A broken `pid_alive` never turns False on its own, so this always spends the
            # full deadline and correctly fails, rather than passing by accident.
            deadline = time.monotonic() + 2.0
            alive = heartbeat.pid_alive(pid)
            while alive and time.monotonic() < deadline:
                time.sleep(0.01)
                alive = heartbeat.pid_alive(pid)
            self.assertFalse(alive)
        finally:
            os.waitpid(pid, 0)  # reap it -- this test's process is its real parent


class ProcStatStateParsingTest(unittest.TestCase):
    """`heartbeat._parse_proc_stat_state` in isolation -- a pure string parser, so this runs on
    every platform regardless of whether `/proc` exists here (research.md §3; man proc(5) for the
    format itself).
    """

    def test_zombie_state_from_a_plain_comm(self):
        raw = "4123 (python3) Z 1 4123 4123 0 -1 4194560 0 0 0 0 0 0 0 0"
        self.assertEqual(heartbeat._parse_proc_stat_state(raw), "Z")

    def test_running_state_from_a_plain_comm(self):
        raw = "99 (sleep) S 1 99 99 0 -1 4194304 0 0 0 0 0 0 0 0"
        self.assertEqual(heartbeat._parse_proc_stat_state(raw), "S")

    def test_comm_containing_spaces_and_parentheses(self):
        # A process may rename itself (`prctl(PR_SET_NAME, ...)`/`argv[0]`) to nearly anything,
        # including something that looks like it ends the comm field early -- the parser has to
        # split on the LAST ')' in the line, not the first, to get this right.
        raw = "777 (my worker (renamed) proc) Z 1 777 777 0 -1 4194304 0 0 0 0 0 0 0 0"
        self.assertEqual(heartbeat._parse_proc_stat_state(raw), "Z")

    def test_missing_closing_paren_is_none(self):
        self.assertIsNone(heartbeat._parse_proc_stat_state("garbage with no parens at all"))

    def test_closing_paren_with_nothing_after_it_is_none(self):
        self.assertIsNone(heartbeat._parse_proc_stat_state("4123 (python3)"))


class IsZombieTest(unittest.TestCase):
    def test_false_for_a_pid_very_unlikely_to_exist(self):
        self.assertFalse(heartbeat.is_zombie(2**30))

    def test_false_for_this_test_process_itself(self):
        self.assertFalse(heartbeat.is_zombie(os.getpid()))


class IsStaleTest(unittest.TestCase):
    def _hb(self, last_heartbeat_at: str) -> heartbeat.Heartbeat:
        return heartbeat.Heartbeat(1, "a", "http://x", last_heartbeat_at)

    def test_fresh_heartbeat_is_not_stale(self):
        now = datetime(2026, 9, 2, 13, 0, 30, tzinfo=timezone.utc)
        written_at = now - timedelta(seconds=10)
        hb = self._hb(written_at.strftime("%Y-%m-%dT%H:%M:%S.") + f"{written_at.microsecond // 1000:03d}Z")
        self.assertFalse(heartbeat.is_stale(hb, stale_after_seconds=50.0, now=now))

    def test_heartbeat_older_than_threshold_is_stale(self):
        now = datetime(2026, 9, 2, 13, 0, 30, tzinfo=timezone.utc)
        written_at = now - timedelta(seconds=51)
        hb = self._hb(written_at.strftime("%Y-%m-%dT%H:%M:%S.") + f"{written_at.microsecond // 1000:03d}Z")
        self.assertTrue(heartbeat.is_stale(hb, stale_after_seconds=50.0, now=now))

    def test_exactly_at_the_boundary_is_not_stale(self):
        now = datetime(2026, 9, 2, 13, 0, 30, tzinfo=timezone.utc)
        written_at = now - timedelta(seconds=50)
        hb = self._hb(written_at.strftime("%Y-%m-%dT%H:%M:%S.") + f"{written_at.microsecond // 1000:03d}Z")
        self.assertFalse(heartbeat.is_stale(hb, stale_after_seconds=50.0, now=now))

    def test_unparseable_timestamp_is_treated_as_stale(self):
        hb = self._hb("not-a-timestamp")
        self.assertTrue(heartbeat.is_stale(hb, stale_after_seconds=50.0))


class NowIso8601Test(unittest.TestCase):
    def test_round_trips_through_is_stale_as_fresh(self):
        hb = heartbeat.Heartbeat(1, "a", "http://x", heartbeat.now_iso8601())
        self.assertFalse(heartbeat.is_stale(hb, stale_after_seconds=50.0))


if __name__ == "__main__":
    unittest.main()
