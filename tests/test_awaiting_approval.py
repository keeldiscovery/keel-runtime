"""Tests for the runtime that is alive and waiting for device approval (keel-cloud DRIFT #51;
`canon/designs/keel-disconnect-design.md` §6, edge case (g)).

Between `authorization_started` and approval there used to be a live runtime that `keel
disconnect` reported `not_running` and left running, because the only heartbeat write happened
after the agent session existed. The fix: `heartbeat.write_awaiting_approval` writes a launch
record -- same file, same required keys, `agent_session_id: null`, `state: "awaiting_approval"`
-- the moment `connect` has a pid and a home, refreshed on every poll tick of the device-
authorization wait, and overwritten with the real heartbeat the instant an agent session exists.

Four layers, in the style `test_cli_disconnect.py` and `test_shutdown_goodbye.py` already use:

* `heartbeat.py` itself -- the new field and the new write helper, module-level, no process;
* `status`, as a real subprocess against a fabricated home -- the shape a caller actually reads;
* `disconnect`, both as the flow (`disconnect.disconnect`, a real child process) and as the
  command (a real subprocess) -- proving a runtime in this state is found and stopped;
* `_run_connect`'s own SIGTERM/Ctrl-C handling while blocked in device authorization -- the
  pre-existing quirk the goodbye pass noted (a traceback instead of a clean exit) -- both through
  the seam (mocked `authorize_device`, a real signal) and end to end (a real subprocess against a
  fake local Keel that never approves).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from keel_runtime import cli, config as config_module, disconnect as disconnect_module, heartbeat
from keel_runtime.agent_session import RuntimeState
from keel_runtime.credential_store import Credential

_RUNTIME_DIR = Path(__file__).resolve().parents[1]


# == layer 1: heartbeat.py itself =============================================================


class WriteAwaitingApprovalTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_writes_a_readable_heartbeat_with_no_agent_session_id(self):
        heartbeat.write_awaiting_approval(self.home, 41213, "http://localhost:18081")
        hb = heartbeat.read(self.home)
        self.assertIsNotNone(hb, "the record must be readable by status and disconnect alike")
        self.assertEqual(hb.pid, 41213)
        self.assertIsNone(hb.agent_session_id)
        self.assertEqual(hb.base_url, "http://localhost:18081")
        self.assertEqual(hb.state, heartbeat.STATE_AWAITING_APPROVAL)

    def test_is_not_stale_the_instant_it_is_written(self):
        heartbeat.write_awaiting_approval(self.home, os.getpid(), "http://localhost:18081")
        hb = heartbeat.read(self.home)
        self.assertFalse(heartbeat.is_stale(hb, stale_after_seconds=50.0))

    def test_create_agent_session_overwrites_it_with_a_connected_heartbeat(self):
        """The real call site's own behaviour: the same file, same pid, now with a session."""
        heartbeat.write_awaiting_approval(self.home, 41213, "http://localhost:18081")
        heartbeat.write(
            self.home,
            heartbeat.Heartbeat(
                pid=41213,
                agent_session_id="5b2e2f0a-9c3b-4b7e-8f3a-1e6c9b7a2d10",
                base_url="http://localhost:18081",
                last_heartbeat_at=heartbeat.now_iso8601(),
            ),
        )
        hb = heartbeat.read(self.home)
        self.assertEqual(hb.state, heartbeat.STATE_CONNECTED)
        self.assertEqual(hb.agent_session_id, "5b2e2f0a-9c3b-4b7e-8f3a-1e6c9b7a2d10")


class HeartbeatBackwardCompatibilityTest(unittest.TestCase):
    """A heartbeat written before this change never carried a `state` key -- it could only have
    been written after an agent session existed, so its absence means `STATE_CONNECTED`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_heartbeat_with_no_state_key_reads_as_connected(self):
        heartbeat.path(self.home).write_text(
            json.dumps(
                {
                    "pid": 41213,
                    "agent_session_id": "a",
                    "base_url": "http://x",
                    "last_heartbeat_at": heartbeat.now_iso8601(),
                }
            ),
            encoding="utf-8",
        )
        hb = heartbeat.read(self.home)
        self.assertEqual(hb.state, heartbeat.STATE_CONNECTED)

    def test_a_null_agent_session_id_does_not_round_trip_as_the_string_none(self):
        heartbeat.path(self.home).write_text(
            json.dumps(
                {
                    "pid": 41213,
                    "agent_session_id": None,
                    "base_url": "http://x",
                    "last_heartbeat_at": heartbeat.now_iso8601(),
                    "state": "awaiting_approval",
                }
            ),
            encoding="utf-8",
        )
        hb = heartbeat.read(self.home)
        self.assertIsNone(hb.agent_session_id)


# == layer 2: `status` ==========================================================================


def _clean_env(fake_home: Path, **overrides) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("KEEL_")}
    env["HOME"] = str(fake_home)
    env["USERPROFILE"] = str(fake_home)
    env.update(overrides)
    return env


def _run_status(home: Path, **env_overrides) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "keel_runtime", "status", "--home", str(home)],
        cwd=str(_RUNTIME_DIR),
        capture_output=True,
        text=True,
        timeout=10,
        env=_clean_env(home, **env_overrides),
    )
    lines = result.stdout.splitlines()
    assert result.returncode == 0, result.stderr
    assert len(lines) == 1, f"expected exactly one line, got: {result.stdout!r}"
    return json.loads(lines[0])


class StatusAwaitingApprovalTest(unittest.TestCase):
    """The shape chosen: the existing `running` shape, `agent_session_id: null`,
    `connected: false` -- no key added, only two keys' value sets widened (see cli._run_status's
    docstring for the exact keel-cloud contract amendment this needs)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.home.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_live_awaiting_approval_record_reports_running_but_not_connected(self):
        heartbeat.write_awaiting_approval(self.home, os.getpid(), "http://localhost:18081")
        payload = _run_status(self.home)
        self.assertEqual(
            payload,
            {
                "running": True,
                "pid": os.getpid(),
                "agent_session_id": None,
                "base_url": "http://localhost:18081",
                "last_heartbeat_at": payload["last_heartbeat_at"],
                "connected": False,
                "home": str(self.home),
                "environment": "localhost:18081",
                "executor": "claude",
                "executor_on_path": payload["executor_on_path"],
            },
        )

    def test_every_key_of_the_running_shape_is_still_present(self):
        """Guarantee 1 of the status contract: no key is ever conditionally omitted."""
        heartbeat.write_awaiting_approval(self.home, os.getpid(), "http://localhost:18081")
        payload = _run_status(self.home)
        for key in ("pid", "agent_session_id", "base_url", "last_heartbeat_at", "connected"):
            self.assertIn(key, payload)

    def test_a_stale_awaiting_approval_record_reports_not_running(self):
        (self.home / "config.json").write_text(json.dumps({"heartbeat_stale_after": 1}))
        heartbeat.write(
            self.home,
            heartbeat.Heartbeat(
                pid=os.getpid(),
                agent_session_id=None,
                base_url="http://localhost:18081",
                last_heartbeat_at="2000-01-01T00:00:00.000Z",
                state=heartbeat.STATE_AWAITING_APPROVAL,
            ),
        )
        payload = _run_status(self.home)
        self.assertEqual(payload["running"], False)
        self.assertEqual(payload["stale_pid"], os.getpid())

    def test_a_dead_pid_awaiting_approval_reports_not_running_with_stale_pid(self):
        dead_pid = 2**30
        heartbeat.write_awaiting_approval(self.home, dead_pid, "http://localhost:18081")
        payload = _run_status(self.home)
        self.assertEqual(payload["running"], False)
        self.assertEqual(payload["stale_pid"], dead_pid)

    def test_a_connected_heartbeat_is_unaffected_and_still_reports_connected_true(self):
        """The pre-existing shape, byte for byte, for every runtime that already has a session --
        this fix changes nothing about it."""
        heartbeat.write(
            self.home,
            heartbeat.Heartbeat(
                pid=os.getpid(),
                agent_session_id="5b2e2f0a-9c3b-4b7e-8f3a-1e6c9b7a2d10",
                base_url="http://localhost:18081",
                last_heartbeat_at=heartbeat.now_iso8601(),
            ),
        )
        payload = _run_status(self.home)
        self.assertEqual(payload["connected"], True)
        self.assertEqual(payload["agent_session_id"], "5b2e2f0a-9c3b-4b7e-8f3a-1e6c9b7a2d10")


# == layer 3: `disconnect` ======================================================================


class DisconnectDuringAwaitingApprovalTest(unittest.TestCase):
    """The flow, against a real child process installed with the runtime's own shutdown-handler
    shape (spec 021 FR-003) -- same pattern `test_cli_disconnect.py` uses for the connected case."""

    _CHILD = """
import os, signal, sys, time
home = sys.argv[1]
def _handle(signum, frame):
    try:
        os.unlink(os.path.join(home, "runtime.heartbeat.json"))
    except OSError:
        pass
    sys.exit(0)
signal.signal(signal.SIGTERM, _handle)
print("ready", flush=True)
time.sleep(60)
"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self._children = []

    def tearDown(self):
        for child in self._children:
            try:
                child.kill()
            except OSError:  # pragma: no cover -- already gone, the usual case
                pass
        self._tmp.cleanup()

    def _spawn(self) -> subprocess.Popen:
        child = subprocess.Popen(
            [sys.executable, "-c", self._CHILD, str(self.home)],
            stdout=subprocess.PIPE,
            text=True,
        )
        self._children.append(child)
        self.assertEqual(child.stdout.readline().strip(), "ready")
        threading.Thread(target=child.wait, daemon=True).start()
        return child

    def test_a_runtime_awaiting_approval_is_found_and_stopped(self):
        child = self._spawn()
        heartbeat.write_awaiting_approval(self.home, child.pid, "http://localhost:18081")

        result = disconnect_module.disconnect(self.home, grace=5.0, kill_after=2.0)

        self.assertEqual(result["outcome"], "stopped")
        self.assertEqual(result["pid"], child.pid)
        self.assertEqual(result["signal"], "SIGTERM")
        self.assertFalse(heartbeat.path(self.home).exists())
        self.assertFalse(heartbeat.pid_alive(child.pid))

    def test_a_second_disconnect_against_the_same_home_is_not_running(self):
        """D10, extended to this state: idempotent regardless of which state stopped it."""
        child = self._spawn()
        heartbeat.write_awaiting_approval(self.home, child.pid, "http://localhost:18081")

        first = disconnect_module.disconnect(self.home, grace=5.0, kill_after=2.0)
        second = disconnect_module.disconnect(self.home, grace=5.0, kill_after=2.0)

        self.assertEqual(first["outcome"], "stopped")
        self.assertEqual(second, {"outcome": "not_running"})


def _run_disconnect(home: Path, **env_overrides) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "keel_runtime", "disconnect", "--home", str(home)],
        cwd=str(_RUNTIME_DIR),
        capture_output=True,
        text=True,
        timeout=30,
        env=_clean_env(home, **env_overrides),
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert len(lines) == 1, f"expected exactly one line, got: {result.stdout!r}"
    return json.loads(lines[0])


class CliDisconnectDuringAwaitingApprovalTest(unittest.TestCase):
    """The command, end to end: DRIFT #51's exact scenario -- `keel disconnect` against a home
    whose only runtime is still waiting for device approval."""

    _CHILD = DisconnectDuringAwaitingApprovalTest._CHILD

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fake_home = Path(self._tmp.name)
        self.home = self.fake_home / "home"
        self.home.mkdir()
        self._children = []

    def tearDown(self):
        for child in self._children:
            try:
                child.kill()
            except OSError:  # pragma: no cover
                pass
        self._tmp.cleanup()

    def test_stopped_not_not_running(self):
        child = subprocess.Popen(
            [sys.executable, "-c", self._CHILD, str(self.home)],
            stdout=subprocess.PIPE,
            text=True,
        )
        self._children.append(child)
        self.assertEqual(child.stdout.readline().strip(), "ready")
        threading.Thread(target=child.wait, daemon=True).start()
        heartbeat.write_awaiting_approval(self.home, child.pid, "http://localhost:18081")

        payload = _run_disconnect(self.home)

        self.assertEqual(payload["outcome"], "stopped")
        self.assertEqual(payload["pid"], child.pid)
        self.assertFalse(heartbeat.path(self.home).exists())


# == layer 4: `_run_connect`'s own SIGTERM/Ctrl-C handling while blocked in authorization ======


def _config(home: Path) -> config_module.RuntimeConfig:
    return config_module.RuntimeConfig(
        base_url="http://localhost:18081",
        executor="stub",
        home=home,
        credential_backend="file",
        open_browser=False,
        heartbeat_stale_after=50.0,
        script_path=None,
        context_keys_path=None,
        job_budget_usd=1.0,
        job_max_turns=6,
        job_timeout_seconds=300.0,
    )


class ConnectWritesTheLaunchRecordBeforeAuthorizingTest(unittest.TestCase):
    """`_run_connect` writes the awaiting-approval record before `authorize_device` is ever
    called -- so a founder who disconnects before clicking approve has something to find."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.config = _config(self.home)
        self._handlers = {
            number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)
        }

    def tearDown(self):
        for number, handler in self._handlers.items():
            signal.signal(number, handler)
        self._tmp.cleanup()

    def test_the_record_exists_and_names_this_process_by_the_time_authorize_device_runs(self):
        seen = {}

        def _authorize_device(client, config):
            hb = heartbeat.read(config.home)
            seen["hb"] = hb
            raise SystemExit("stop the test here -- the record is already proven")

        store = mock.Mock()
        store.load.return_value = None

        with mock.patch.object(
            cli.config_module, "load", return_value=self.config
        ), mock.patch.object(cli, "get_executor", return_value=object()), mock.patch.object(
            cli, "CredentialStore", return_value=store
        ), mock.patch.object(cli, "CloudClient", return_value=mock.Mock()), mock.patch.object(
            cli.auth_module, "authorize_device", side_effect=_authorize_device
        ), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli._run_connect(mock.Mock())

        hb = seen["hb"]
        self.assertIsNotNone(hb)
        self.assertEqual(hb.pid, os.getpid())
        self.assertIsNone(hb.agent_session_id)
        self.assertEqual(hb.state, heartbeat.STATE_AWAITING_APPROVAL)


class ConnectInterruptedDuringAuthorizationTest(unittest.TestCase):
    """The pre-existing quirk the goodbye pass noted: a SIGTERM/Ctrl-C while blocked in device
    authorization used to propagate out of `_run_connect` uncaught -- a traceback, not a clean
    exit. Proved through the **real** shutdown handler, exactly as
    `test_shutdown_goodbye.ConnectSaysGoodbyeTest` proves G3."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.config = _config(self.home)
        self._handlers = {
            number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)
        }

    def tearDown(self):
        for number, handler in self._handlers.items():
            signal.signal(number, handler)
        self._tmp.cleanup()

    def _connect(self, authorize_device_side_effect):
        store = mock.Mock()
        store.load.return_value = None
        end_agent_session = mock.Mock()
        client = mock.Mock(end_agent_session=end_agent_session)

        with mock.patch.object(
            cli.config_module, "load", return_value=self.config
        ), mock.patch.object(cli, "get_executor", return_value=object()), mock.patch.object(
            cli, "CredentialStore", return_value=store
        ), mock.patch.object(cli, "CloudClient", return_value=client), mock.patch.object(
            cli.auth_module, "authorize_device", side_effect=authorize_device_side_effect
        ), contextlib.redirect_stdout(io.StringIO()):
            return cli._run_connect(mock.Mock()), end_agent_session

    def test_sigterm_while_blocked_in_device_authorization_exits_cleanly(self):
        def _blocked_then_interrupted(client, config):
            signal.raise_signal(signal.SIGTERM)
            raise AssertionError("the handler should have raised KeyboardInterrupt")

        exit_code, end_agent_session = self._connect(_blocked_then_interrupted)

        self.assertEqual(exit_code, 0)
        # G6: no agent session ever existed, so nothing was said goodbye to.
        end_agent_session.assert_not_called()
        # The launch record the handler is responsible for cleaning is gone.
        self.assertFalse(heartbeat.path(self.home).exists())

    def test_sigint_while_blocked_in_device_authorization_exits_cleanly(self):
        def _blocked_then_interrupted(client, config):
            signal.raise_signal(signal.SIGINT)
            raise AssertionError("the handler should have raised KeyboardInterrupt")

        exit_code, end_agent_session = self._connect(_blocked_then_interrupted)

        self.assertEqual(exit_code, 0)
        end_agent_session.assert_not_called()
        self.assertFalse(heartbeat.path(self.home).exists())

    def test_a_keyboard_interrupt_that_is_not_from_our_own_handler_is_also_clean(self):
        """Defensive: whatever raises it -- our handler, or Python's own default SIGINT
        disposition on a code path this test does not control -- `_run_connect` must not let it
        escape uncaught."""

        def _blocked_then_interrupted(client, config):
            raise KeyboardInterrupt()

        exit_code, end_agent_session = self._connect(_blocked_then_interrupted)

        self.assertEqual(exit_code, 0)
        end_agent_session.assert_not_called()


class ConnectAwaitingApprovalEndToEndTest(unittest.TestCase):
    """A real `connect` subprocess against a fake local Keel that never approves the device --
    the closest this suite comes, without a real Keel Cloud, to DRIFT #51's own reproduction
    (`runs/20260909T054513Z-s009-skill-distribution` steps 9-17): a live process, blocked on a
    code nobody will ever redeem, found and stopped by a second `keel disconnect` process."""

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            if self.path == "/v2/device-authorizations":
                body = json.dumps(
                    {
                        "device_authorization_id": "da-1",
                        "device_code": "secret-device-code",
                        "user_code": "KJRT-WXMP",
                        "verification_uri": "http://localhost/connect",
                        "verification_uri_complete": "http://localhost/connect?user_code=KJRT-WXMP",
                        "expires_in": 600,
                        "poll_interval": 0.2,
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
                return
            # /v2/device-authorizations/token -- pending forever; nobody approves in this test.
            body = json.dumps(
                {"error": {"code": "AUTHORIZATION_PENDING", "message": "not yet decided"}}
            ).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # noqa: ARG002
            pass

    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

        self._tmp = tempfile.TemporaryDirectory()
        self.fake_home = Path(self._tmp.name)
        self.home = self.fake_home / "home"
        self.home.mkdir()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self._tmp.cleanup()

    def _spawn_connect(self):
        """Returns `(child, reaped)`. `reaped` is set by a single background thread that owns
        `communicate()`/`wait()` for this child -- calling either from more than one place would
        race two `waitpid`s on the same pid. Tests read `child.returncode` and the captured
        output only after `reaped.wait(...)` -- never by calling `wait`/`communicate` themselves.
        `os.kill(pid, 0)` (the liveness probe both `status` and `disconnect` use) reports a
        zombie as alive, and an unreaped child of this test process is a zombie the moment it
        exits (the same note `test_cli_disconnect.py` makes for its own spawned children) -- this
        thread is what keeps that window shut for the whole life of the test.
        """
        env = _clean_env(self.fake_home)
        child = subprocess.Popen(
            [
                sys.executable, "-m", "keel_runtime", "connect",
                "--home", str(self.home),
                "--base-url", self.base_url,
                "--executor", "stub",
                "--no-browser",
            ],
            cwd=str(_RUNTIME_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        # Wait until the awaiting-approval record exists -- proof it is blocked in device
        # authorization, not merely starting up.
        deadline = time.monotonic() + 10
        hb = None
        while time.monotonic() < deadline:
            hb = heartbeat.read(self.home)
            if hb is not None and hb.state == heartbeat.STATE_AWAITING_APPROVAL:
                break
            time.sleep(0.05)
        self.assertIsNotNone(hb, "connect never wrote its awaiting-approval record")
        self.assertEqual(hb.state, heartbeat.STATE_AWAITING_APPROVAL)

        reaped = threading.Event()
        captured = {}

        def _reap():
            stdout, stderr = child.communicate()
            captured["stdout"] = stdout
            captured["stderr"] = stderr
            reaped.set()

        threading.Thread(target=_reap, daemon=True).start()
        return child, reaped, captured

    def test_disconnect_stops_a_runtime_that_is_still_waiting_for_approval(self):
        child, reaped, _captured = self._spawn_connect()
        try:
            payload = _run_disconnect(self.home)
            self.assertEqual(payload["outcome"], "stopped")
            self.assertEqual(payload["pid"], child.pid)

            self.assertTrue(reaped.wait(timeout=5), "connect did not exit after being stopped")
            self.assertEqual(child.returncode, 0)
            self.assertFalse(heartbeat.path(self.home).exists())
        finally:
            with contextlib.suppress(OSError):
                child.kill()

    def test_sigterm_against_the_real_process_exits_zero_with_no_traceback(self):
        child, reaped, captured = self._spawn_connect()
        try:
            child.send_signal(signal.SIGTERM)
            self.assertTrue(reaped.wait(timeout=5), "connect did not exit after SIGTERM")
            self.assertEqual(child.returncode, 0, msg=captured.get("stderr"))
            self.assertNotIn("Traceback", captured.get("stderr", ""))
            self.assertFalse(heartbeat.path(self.home).exists())
        finally:
            with contextlib.suppress(OSError):
                child.kill()


if __name__ == "__main__":
    unittest.main()
