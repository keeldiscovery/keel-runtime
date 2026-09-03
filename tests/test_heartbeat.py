"""Tests for keel_runtime.heartbeat (spec 021): write/read round-trip, atomic write,
corrupt-file handling, pid liveness, and staleness (data-model.md, research.md §2-3).
"""
import json
import os
import tempfile
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
        pid = os.fork()
        if pid == 0:  # pragma: no cover -- child process branch
            os._exit(0)
        os.waitpid(pid, 0)
        self.assertFalse(heartbeat.pid_alive(pid))


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
