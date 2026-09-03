"""Tests for `python3 -m keel_runtime status` (spec 021), exercised as a real subprocess
against a fabricated `$KEEL_HOME` -- the only way to genuinely verify the stable output
contract (contracts/status-cli-output.md): exactly one JSON line on stdout, exit code 0,
in every case, with no accidental extra output or non-zero exit sneaking in.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from keel_runtime import heartbeat

_RUNTIME_DIR = Path(__file__).resolve().parents[1]


def _run_status(home: Path):
    result = subprocess.run(
        [sys.executable, "-m", "keel_runtime", "status", "--home", str(home)],
        cwd=str(_RUNTIME_DIR),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result


class CliStatusTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _assert_single_json_line(self, result) -> dict:
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 1, msg=f"expected exactly one line, got: {result.stdout!r}")
        return json.loads(lines[0])

    def test_no_heartbeat_file_reports_not_running(self):
        result = _run_status(self.home)
        payload = self._assert_single_json_line(result)
        self.assertEqual(payload, {"running": False})

    def test_fresh_heartbeat_naming_a_live_pid_reports_running(self):
        heartbeat.write(
            self.home,
            heartbeat.Heartbeat(
                pid=os.getpid(),
                agent_session_id="5b2e2f0a-9c3b-4b7e-8f3a-1e6c9b7a2d10",
                base_url="https://cloud.keel.example",
                last_heartbeat_at=heartbeat.now_iso8601(),
            ),
        )
        result = _run_status(self.home)
        payload = self._assert_single_json_line(result)
        self.assertEqual(
            payload,
            {
                "running": True,
                "pid": os.getpid(),
                "agent_session_id": "5b2e2f0a-9c3b-4b7e-8f3a-1e6c9b7a2d10",
                "base_url": "https://cloud.keel.example",
                "last_heartbeat_at": payload["last_heartbeat_at"],
                "connected": True,
            },
        )

    def test_stale_heartbeat_naming_a_live_pid_reports_not_running_with_stale_pid(self):
        (self.home).mkdir(parents=True, exist_ok=True)
        (self.home / "config.json").write_text(json.dumps({"heartbeat_stale_after": 1}))
        old_timestamp = "2000-01-01T00:00:00.000Z"
        heartbeat.write(
            self.home,
            heartbeat.Heartbeat(
                pid=os.getpid(),
                agent_session_id="5b2e2f0a-9c3b-4b7e-8f3a-1e6c9b7a2d10",
                base_url="https://cloud.keel.example",
                last_heartbeat_at=old_timestamp,
            ),
        )
        result = _run_status(self.home)
        payload = self._assert_single_json_line(result)
        self.assertEqual(payload, {"running": False, "stale_pid": os.getpid()})

    def test_heartbeat_naming_a_dead_pid_reports_not_running_with_stale_pid_even_if_fresh(self):
        dead_pid = 2**30  # guaranteed not to exist
        heartbeat.write(
            self.home,
            heartbeat.Heartbeat(
                pid=dead_pid,
                agent_session_id="5b2e2f0a-9c3b-4b7e-8f3a-1e6c9b7a2d10",
                base_url="https://cloud.keel.example",
                last_heartbeat_at=heartbeat.now_iso8601(),
            ),
        )
        result = _run_status(self.home)
        payload = self._assert_single_json_line(result)
        self.assertEqual(payload, {"running": False, "stale_pid": dead_pid})

    def test_corrupt_heartbeat_file_reports_not_running(self):
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "runtime.heartbeat.json").write_text("{not valid json")
        result = _run_status(self.home)
        payload = self._assert_single_json_line(result)
        self.assertEqual(payload, {"running": False})

    def test_status_exits_zero_and_prints_nothing_to_stderr_on_the_happy_paths(self):
        result = _run_status(self.home)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
