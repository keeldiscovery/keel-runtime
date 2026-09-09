"""Tests for `python3 -m keel_runtime status` (spec 021), exercised as a real subprocess
against a fabricated `$KEEL_HOME` -- the only way to genuinely verify the stable output
contract (contracts/status-cli-output.md): exactly one JSON line on stdout, exit code 0,
in every case, with no accidental extra output or non-zero exit sneaking in.

Since spec `004-shipped-runtime` (FR-009) both shapes also carry `home`, `base_url`,
`environment`, `executor` and `executor_on_path` -- the four keys keel-cloud's contract is
amended for, plus the promotion of `base_url` to always-present (design §6.3, C-10). Every
subprocess here runs with a **cleaned environment**: `KEEL_*` unset and `HOME` pointed at a
temporary directory, so a shell that happens to export `KEEL_BASE_URL` (the playground does)
cannot change what these assertions see.
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


def _clean_env(fake_home: Path, **overrides) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("KEEL_")}
    env["HOME"] = str(fake_home)
    env["USERPROFILE"] = str(fake_home)  # Windows' `Path.home()`
    env.update(overrides)
    return env


def _run_status(home=None, fake_home: Path = None, **env_overrides):
    argv = [sys.executable, "-m", "keel_runtime", "status"]
    if home is not None:
        argv += ["--home", str(home)]
    result = subprocess.run(
        argv,
        cwd=str(_RUNTIME_DIR),
        capture_output=True,
        text=True,
        timeout=10,
        env=_clean_env(fake_home if fake_home is not None else Path(home), **env_overrides),
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
        """`--home` is explicit and its `config.json` is absent, so `base_url` still resolves --
        to `CLOUD_BASE_URL`, the chain's last term (design §13 step 8) -- rather than `None`.
        """
        result = _run_status(self.home)
        payload = self._assert_single_json_line(result)
        self.assertEqual(
            payload,
            {
                "running": False,
                "home": str(self.home),
                "base_url": "https://app.keeldiscovery.com",
                "environment": "cloud",
                "executor": "claude",
                "executor_on_path": payload["executor_on_path"],
            },
        )

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
                "home": str(self.home),
                "environment": "cloud.keel.example",
                "executor": "claude",
                "executor_on_path": payload["executor_on_path"],
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
        self.assertEqual(payload["running"], False)
        self.assertEqual(payload["stale_pid"], os.getpid())

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
        self.assertEqual(payload["running"], False)
        self.assertEqual(payload["stale_pid"], dead_pid)

    def test_corrupt_heartbeat_file_reports_not_running(self):
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "runtime.heartbeat.json").write_text("{not valid json")
        result = _run_status(self.home)
        payload = self._assert_single_json_line(result)
        self.assertEqual(payload["running"], False)
        self.assertNotIn("stale_pid", payload)

    def test_status_exits_zero_and_prints_nothing_to_stderr_on_the_happy_paths(self):
        result = _run_status(self.home)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")



class StatusEnvironmentKeysTest(unittest.TestCase):
    """spec 004-shipped-runtime FR-009: the four added keys and the always-present `base_url`,
    in both shapes, and `status` still answering with exit 0 when nothing names a Keel at all.
    Since design §13 step 8, `CLOUD_BASE_URL` is a real address, so "nothing configured" now
    resolves to it rather than to the null environment §6.3 describes for the placeholder era.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fake_home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _payload(self, **kwargs) -> dict:
        result = _run_status(fake_home=self.fake_home, **kwargs)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 1, msg=f"expected exactly one line, got: {result.stdout!r}")
        return json.loads(lines[0])

    def test_nothing_configured_at_all_reaches_the_cloud_default(self):
        payload = self._payload()
        self.assertEqual(payload["running"], False)
        self.assertEqual(payload["base_url"], "https://app.keeldiscovery.com")
        self.assertEqual(payload["environment"], "cloud")
        self.assertEqual(payload["home"], str(self.fake_home / ".keel" / "app.keeldiscovery.com"))

    def test_a_local_base_url_names_its_address_and_derives_its_home(self):
        payload = self._payload(KEEL_BASE_URL="http://localhost:18081")
        self.assertEqual(payload["base_url"], "http://localhost:18081")
        self.assertEqual(payload["environment"], "localhost:18081")
        self.assertEqual(payload["home"], str(self.fake_home / ".keel" / "localhost-18081"))

    def test_keel_home_still_wins_outright(self):
        override = self.fake_home / "elsewhere"
        payload = self._payload(KEEL_BASE_URL="http://localhost:18081", KEEL_HOME=str(override))
        self.assertEqual(payload["home"], str(override))
        self.assertEqual(payload["environment"], "localhost:18081")

    def test_every_key_is_present_in_the_not_running_shape(self):
        payload = self._payload(KEEL_BASE_URL="http://localhost:18081")
        for key in ("running", "home", "base_url", "environment", "executor", "executor_on_path"):
            self.assertIn(key, payload)

    def test_an_in_process_executor_is_always_on_path(self):
        payload = self._payload(KEEL_EXECUTOR="scripted")
        self.assertEqual(payload["executor"], "scripted")
        self.assertTrue(payload["executor_on_path"])

    def test_an_unknown_executor_is_not_on_path(self):
        payload = self._payload(KEEL_EXECUTOR="no-such-executor")
        self.assertEqual(payload["executor"], "no-such-executor")
        self.assertFalse(payload["executor_on_path"])

    def test_the_running_shape_reports_the_keel_the_live_process_connected_to(self):
        home = self.fake_home / ".keel" / "localhost-18081"
        home.mkdir(parents=True)
        heartbeat.write(
            home,
            heartbeat.Heartbeat(
                pid=os.getpid(),
                agent_session_id="5b2e2f0a-9c3b-4b7e-8f3a-1e6c9b7a2d10",
                base_url="http://localhost:18081",
                last_heartbeat_at=heartbeat.now_iso8601(),
            ),
        )
        # The environment resolvable *now* is a different Keel; the running shape must describe
        # the one the live process is actually talking to.
        payload = self._payload(KEEL_HOME=str(home), KEEL_BASE_URL="http://localhost:18080")
        self.assertEqual(payload["running"], True)
        self.assertEqual(payload["base_url"], "http://localhost:18081")
        self.assertEqual(payload["environment"], "localhost:18081")


if __name__ == "__main__":
    unittest.main()
