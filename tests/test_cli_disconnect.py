"""Tests for `keel disconnect` (spec `003-keel-disconnect`; keel-cloud
`canon/designs/keel-disconnect-design.md` §8.1), one per outcome.

Two layers, deliberately:

* the **flow**, `disconnect.disconnect(...)`, driven through the seam the design names -- with
  real child processes where a real process can produce the outcome (`stopped` by `SIGTERM` and by
  `SIGKILL`), and with fakes for the two outcomes no real process can produce on demand
  (`timeout`: nothing survives `SIGKILL` to order) and for the assertions about what was *not*
  done (D2: a recording `kill` that must never be called);
* the **command**, as a real subprocess against a fabricated home -- the only way to genuinely
  verify the stable contract (`contracts/disconnect-cli-output.md`): exactly one JSON line on
  stdout, exit code 0, in every case, and a home resolved identically to `status`'s.

Every child process here is reaped by a thread of this test process, because `os.kill(pid, 0)` --
the liveness probe -- reports a **zombie** as alive, and an unreaped child of this process is a
zombie the moment it dies.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from keel_runtime import disconnect as disconnect_module
from keel_runtime import heartbeat

_RUNTIME_DIR = Path(__file__).resolve().parents[1]

# A child that installs the runtime's own handler shape (spec 021 FR-003): remove the heartbeat,
# then exit -- so the common path, where there is nothing left for `_remove_if_still_ours` to do,
# is the one being exercised.
_CHILD_WITH_HANDLER = """
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

# A child that takes SIGTERM's default disposition and removes nothing -- the pre-spec-021 runtime,
# and the case `_remove_if_still_ours` exists for.
_CHILD_PLAIN = """
import sys, time
print("ready", flush=True)
time.sleep(60)
"""

# A child that refuses SIGTERM outright, so the escalation to SIGKILL is a real one (D5).
_CHILD_IGNORING_SIGTERM = """
import signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
print("ready", flush=True)
time.sleep(60)
"""


def _stopped(home: Path) -> dict:
    """`stopped`, without a real child -- for the tests whose subject is not the signalling."""
    fake = _StopsOnSignal()
    return disconnect_module.disconnect(home, kill=fake.kill, alive=fake.alive)


def _write_heartbeat(home: Path, pid: int, base_url: str = "http://localhost:18081") -> None:
    heartbeat.write(
        home,
        heartbeat.Heartbeat(
            pid=pid,
            agent_session_id="5b2e2f0a-9c3b-4b7e-8f3a-1e6c9b7a2d10",
            base_url=base_url,
            last_heartbeat_at=heartbeat.now_iso8601(),
        ),
    )


class _RecordingKill:
    """A `kill` that records rather than signals -- so "nothing was signalled" (D2) is an
    assertion about a list, not an absence someone has to trust."""

    def __init__(self):
        self.calls = []

    def __call__(self, pid, signal_number):
        self.calls.append((pid, signal_number))


class _StopsOnSignal:
    """A fake process: alive until it is signalled, and not alive afterwards -- the `stopped`
    outcome without a real child, for the assertions that are about something else."""

    def __init__(self):
        self.calls = []

    def kill(self, pid, signal_number):
        self.calls.append((pid, signal_number))

    def alive(self, pid):
        return not self.calls


class _FakeClock:
    """A monotonic clock that only moves when something sleeps, so the `timeout` path costs no
    real seconds (§8.1 case 5)."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class DisconnectFlowTest(unittest.TestCase):
    """The flow, `disconnect.disconnect(...)`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self._children = []

    def tearDown(self):
        for child in self._children:
            try:
                child.kill()
            except OSError:  # pragma: no cover -- already gone, which is the usual case
                pass
        self._tmp.cleanup()

    def _spawn(self, source: str, *args) -> subprocess.Popen:
        child = subprocess.Popen(
            [sys.executable, "-c", source, *args],
            stdout=subprocess.PIPE,
            text=True,
        )
        self._children.append(child)
        # Wait until the child says it has installed its handler; otherwise the signal can arrive
        # before the disposition it is meant to meet.
        self.assertEqual(child.stdout.readline().strip(), "ready")
        # `os.kill(pid, 0)` reports a zombie as alive, so an unreaped child would look immortal.
        threading.Thread(target=child.wait, daemon=True).start()
        return child

    # -- stopped ------------------------------------------------------------------------------

    def test_a_runtime_that_honours_sigterm_is_stopped_and_its_heartbeat_is_gone(self):
        child = self._spawn(_CHILD_WITH_HANDLER, str(self.home))
        _write_heartbeat(self.home, child.pid)

        result = disconnect_module.disconnect(self.home, grace=5.0, kill_after=2.0)

        self.assertEqual(result["outcome"], "stopped")
        self.assertEqual(result["pid"], child.pid)
        self.assertEqual(result["signal"], "SIGTERM")
        self.assertLess(result["waited_ms"], 5000)
        self.assertFalse(heartbeat.path(self.home).exists())
        self.assertFalse(heartbeat.pid_alive(child.pid))

    def test_a_runtime_that_removes_nothing_still_has_its_heartbeat_removed_for_it(self):
        """The pre-spec-021 runtime, and the SIGKILL path's case: the process leaves the file
        behind and `_remove_if_still_ours` clears it."""
        child = self._spawn(_CHILD_PLAIN)
        _write_heartbeat(self.home, child.pid)

        result = disconnect_module.disconnect(self.home, grace=5.0, kill_after=2.0)

        self.assertEqual(result["outcome"], "stopped")
        self.assertEqual(result["signal"], "SIGTERM")
        self.assertFalse(heartbeat.path(self.home).exists())

    @unittest.skipIf(
        sys.platform == "win32",
        "os.kill terminates unconditionally on Windows; a process cannot ignore SIGTERM there",
    )
    def test_a_runtime_that_ignores_sigterm_is_escalated_to_sigkill_after_the_grace(self):
        child = self._spawn(_CHILD_IGNORING_SIGTERM)
        _write_heartbeat(self.home, child.pid)

        result = disconnect_module.disconnect(self.home, grace=0.3, kill_after=5.0)

        self.assertEqual(result["outcome"], "stopped")
        self.assertEqual(result["pid"], child.pid)
        self.assertEqual(result["signal"], "SIGKILL")  # D5: never first, always after the grace
        self.assertGreaterEqual(result["waited_ms"], 300)
        self.assertFalse(heartbeat.path(self.home).exists())
        self.assertFalse(heartbeat.pid_alive(child.pid))

    @unittest.skipIf(sys.platform == "win32", "os.fork is POSIX-only; no zombie state on Windows")
    def test_a_process_that_dies_into_an_unreaped_zombie_is_stopped_fast(self):
        """keel-e2e-eval DRIFT #57, the finding itself: inside a container whose PID 1 never
        reaps, a runtime that dies on the first SIGTERM stays a zombie, and `os.kill(pid, 0)`
        still says it's alive. Unlike every other test above, this one deliberately skips
        `_spawn`'s background reaping thread -- forking directly instead -- so the child is this
        test process's real, un-reaped child, exactly the shape the referee isolated: `ppid`
        the test itself, state `Z` the moment SIGTERM's default disposition kills it. The fixed
        `pid_alive` has to see through that and report `stopped` in on the order of milliseconds,
        not `timeout` at the full 15-second bound the referee measured before this fix.
        """
        pid = os.fork()
        if pid == 0:  # pragma: no cover -- child process branch
            try:
                os.execvp(sys.executable, [sys.executable, "-c", "import time; time.sleep(60)"])
            finally:
                os._exit(127)  # pragma: no cover -- only reached if execvp itself fails
        _write_heartbeat(self.home, pid)
        try:
            result = disconnect_module.disconnect(self.home, grace=10.0, kill_after=5.0)
            self.assertEqual(result["outcome"], "stopped")
            self.assertEqual(result["pid"], pid)
            self.assertEqual(result["signal"], "SIGTERM")
            self.assertLess(result["waited_ms"], 2000)  # nowhere near the 10s grace
        finally:
            os.waitpid(pid, 0)  # this test's process is the real parent; reap it

    # -- not_running (D1) ---------------------------------------------------------------------

    def test_a_home_with_no_heartbeat_is_not_running(self):
        self.assertEqual(disconnect_module.disconnect(self.home), {"outcome": "not_running"})

    def test_a_malformed_or_short_heartbeat_reads_identically_to_no_heartbeat(self):
        """D1: missing, unreadable, malformed, or short a required field are **one** answer,
        exactly as `status` treats the same four cases."""
        for payload in ("{not json at all", json.dumps({"pid": 41213}), ""):
            with self.subTest(payload=payload):
                heartbeat.path(self.home).write_text(payload, encoding="utf-8")
                kill = _RecordingKill()
                result = disconnect_module.disconnect(self.home, kill=kill)
                self.assertEqual(result, {"outcome": "not_running"})
                self.assertEqual(kill.calls, [])
                # Nothing readable was named, so nothing was removed either.
                self.assertTrue(heartbeat.path(self.home).exists())
        heartbeat.remove(self.home)

    # -- stale_pid_cleared (D2) ---------------------------------------------------------------

    def test_a_heartbeat_naming_a_dead_pid_is_cleared_and_nothing_is_signalled(self):
        child = self._spawn(_CHILD_PLAIN)
        child.kill()
        child.wait()
        _write_heartbeat(self.home, child.pid)

        kill = _RecordingKill()
        result = disconnect_module.disconnect(self.home, kill=kill)

        self.assertEqual(result, {"outcome": "stale_pid_cleared", "pid": child.pid})
        self.assertEqual(kill.calls, [])  # D2 -- a dead pid is never signalled
        self.assertFalse(heartbeat.path(self.home).exists())

    # -- timeout (D6) -------------------------------------------------------------------------

    def test_a_process_that_survives_both_signals_times_out_and_keeps_its_heartbeat(self):
        """Unreachable with a real process -- nothing survives SIGKILL on demand -- so the seam
        supplies one: always alive, a kill that does nothing, and a clock that only moves when
        something sleeps."""
        _write_heartbeat(self.home, 41213)
        clock = _FakeClock()
        kill = _RecordingKill()

        result = disconnect_module.disconnect(
            self.home,
            grace=10.0,
            kill_after=5.0,
            kill=kill,
            alive=lambda pid: True,
            clock=clock,
            sleep=clock.sleep,
        )

        self.assertEqual(result["outcome"], "timeout")
        self.assertEqual(result["pid"], 41213)
        self.assertGreaterEqual(result["waited_ms"], 15000)
        self.assertEqual(
            [signal_number for _, signal_number in kill.calls],
            [disconnect_module.TERM_SIGNAL, disconnect_module.KILL_SIGNAL],
        )
        # D6: a process that is still polling must never read as not running.
        self.assertTrue(heartbeat.path(self.home).exists())

    def test_a_pid_this_user_may_not_signal_times_out_rather_than_crashing(self):
        _write_heartbeat(self.home, 41213)

        def _refuse(pid, signal_number):
            raise PermissionError(1, "Operation not permitted")

        result = disconnect_module.disconnect(
            self.home, kill=_refuse, alive=lambda pid: True, clock=_FakeClock()
        )

        self.assertEqual(result["outcome"], "timeout")
        self.assertTrue(heartbeat.path(self.home).exists())

    def test_a_process_that_leaves_between_the_check_and_the_signal_is_stopped(self):
        _write_heartbeat(self.home, 41213)

        def _already_gone(pid, signal_number):
            raise ProcessLookupError(3, "No such process")

        result = disconnect_module.disconnect(
            self.home, kill=_already_gone, alive=lambda pid: True
        )

        self.assertEqual(result["outcome"], "stopped")
        self.assertEqual(result["signal"], "SIGTERM")
        self.assertFalse(heartbeat.path(self.home).exists())

    # -- D3, D7, D10 --------------------------------------------------------------------------

    def test_a_heartbeat_rewritten_with_another_pid_survives_the_disconnect(self):
        """D3: the heartbeat is removed only while it still names the pid that was signalled --
        whatever wrote a new one is not the process that was just stopped."""
        _write_heartbeat(self.home, 41213)
        stopped = {"value": False}

        def _kill_and_let_another_runtime_claim_the_home(pid, signal_number):
            stopped["value"] = True
            _write_heartbeat(self.home, 40118)

        result = disconnect_module.disconnect(
            self.home,
            kill=_kill_and_let_another_runtime_claim_the_home,
            alive=lambda pid: not stopped["value"],
        )

        self.assertEqual(result["outcome"], "stopped")
        self.assertEqual(result["pid"], 41213)
        self.assertTrue(heartbeat.path(self.home).exists())
        self.assertEqual(heartbeat.read(self.home).pid, 40118)

    def test_the_credential_is_untouched_by_every_outcome(self):
        """D7: disconnect stops a process; it does not forget a machine."""
        credential_path = self.home / "credentials.json"
        original = json.dumps({"access_token": "tok", "device_id": "dev"})
        clock = _FakeClock()

        outcomes = {
            "not_running": lambda: disconnect_module.disconnect(self.home),
            "stale_pid_cleared": lambda: disconnect_module.disconnect(
                self.home, alive=lambda pid: False
            ),
            "stopped": lambda: _stopped(self.home),
            "timeout": lambda: disconnect_module.disconnect(
                self.home,
                kill=_RecordingKill(),
                alive=lambda pid: True,
                clock=clock,
                sleep=clock.sleep,
            ),
        }
        for name, run in outcomes.items():
            with self.subTest(outcome=name):
                credential_path.write_text(original, encoding="utf-8")
                if name != "not_running":
                    _write_heartbeat(self.home, 41213)
                result = run()
                self.assertEqual(result["outcome"], name)
                self.assertEqual(credential_path.read_text(encoding="utf-8"), original)
        heartbeat.remove(self.home)

    def test_a_second_disconnect_is_not_running(self):
        """D10: there is no state disconnect keeps between runs."""
        child = self._spawn(_CHILD_WITH_HANDLER, str(self.home))
        _write_heartbeat(self.home, child.pid)

        first = disconnect_module.disconnect(self.home, grace=5.0, kill_after=2.0)
        second = disconnect_module.disconnect(self.home, grace=5.0, kill_after=2.0)

        self.assertEqual(first["outcome"], "stopped")
        self.assertEqual(second, {"outcome": "not_running"})

    def test_no_outcome_makes_a_network_call(self):
        """D9: the whole module runs under a `urlopen` that raises."""
        clock = _FakeClock()
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call")):
            self.assertEqual(
                disconnect_module.disconnect(self.home)["outcome"], "not_running"
            )
            _write_heartbeat(self.home, 41213)
            self.assertEqual(
                disconnect_module.disconnect(self.home, alive=lambda pid: False)["outcome"],
                "stale_pid_cleared",
            )
            _write_heartbeat(self.home, 41213)
            self.assertEqual(_stopped(self.home)["outcome"], "stopped")
            _write_heartbeat(self.home, 41213)
            self.assertEqual(
                disconnect_module.disconnect(
                    self.home,
                    kill=_RecordingKill(),
                    alive=lambda pid: True,
                    clock=clock,
                    sleep=clock.sleep,
                )["outcome"],
                "timeout",
            )
        heartbeat.remove(self.home)

    def test_the_bounds_are_the_designs_two_numbers(self):
        self.assertEqual(disconnect_module.GRACE_SECONDS, 10.0)
        self.assertEqual(disconnect_module.KILL_AFTER_SECONDS, 5.0)


def _clean_env(fake_home: Path, **overrides) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("KEEL_")}
    env["HOME"] = str(fake_home)
    env["USERPROFILE"] = str(fake_home)  # Windows' `Path.home()`
    env.update(overrides)
    return env


def _run(command, *args, fake_home: Path, **env_overrides):
    return subprocess.run(
        [sys.executable, "-m", "keel_runtime", command, *args],
        cwd=str(_RUNTIME_DIR),
        capture_output=True,
        text=True,
        timeout=30,
        env=_clean_env(fake_home, **env_overrides),
    )


class CliDisconnectTest(unittest.TestCase):
    """The command as a real subprocess -- the contract, held end to end."""

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

    def _payload(self, result) -> dict:
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 1, msg=f"expected exactly one line, got: {result.stdout!r}")
        return json.loads(lines[0])

    def test_an_empty_home_is_one_json_line_of_not_running_and_exit_zero(self):
        """`--home` is explicit here and its `config.json` is absent, so `base_url` still
        resolves -- to `CLOUD_BASE_URL`, the chain's last term (design §13 step 8) -- rather than
        landing on `None`.
        """
        payload = self._payload(
            _run("disconnect", "--home", str(self.home), fake_home=self.fake_home)
        )
        self.assertEqual(payload["outcome"], "not_running")
        for key in ("outcome", "home", "base_url", "environment"):
            self.assertIn(key, payload)
        self.assertEqual(payload["home"], str(self.home))
        self.assertEqual(payload["base_url"], "https://keeldiscovery.com")
        self.assertEqual(payload["environment"], "cloud")
        # `status`'s two executor keys are deliberately absent: no executor takes part in a
        # disconnect (FR-008).
        self.assertNotIn("executor", payload)
        self.assertNotIn("executor_on_path", payload)

    def test_a_stale_pid_is_cleared_and_the_line_names_the_keel_it_was_talking_to(self):
        child = subprocess.Popen([sys.executable, "-c", _CHILD_PLAIN], stdout=subprocess.PIPE)
        self._children.append(child)
        child.stdout.readline()
        child.kill()
        child.wait()
        _write_heartbeat(self.home, child.pid, base_url="http://localhost:18081")

        payload = self._payload(
            _run("disconnect", "--home", str(self.home), fake_home=self.fake_home)
        )

        self.assertEqual(payload["outcome"], "stale_pid_cleared")
        self.assertEqual(payload["pid"], child.pid)
        # The address is the heartbeat's, not a fresh resolution's.
        self.assertEqual(payload["base_url"], "http://localhost:18081")
        self.assertEqual(payload["environment"], "localhost:18081")
        self.assertFalse(heartbeat.path(self.home).exists())

    def test_a_live_runtime_is_stopped_through_the_command(self):
        child = subprocess.Popen(
            [sys.executable, "-c", _CHILD_WITH_HANDLER, str(self.home)],
            stdout=subprocess.PIPE,
            text=True,
        )
        self._children.append(child)
        self.assertEqual(child.stdout.readline().strip(), "ready")
        threading.Thread(target=child.wait, daemon=True).start()
        _write_heartbeat(self.home, child.pid)

        payload = self._payload(
            _run("disconnect", "--home", str(self.home), fake_home=self.fake_home)
        )

        self.assertEqual(payload["outcome"], "stopped")
        self.assertEqual(payload["pid"], child.pid)
        self.assertEqual(payload["signal"], "SIGTERM")
        self.assertIsInstance(payload["waited_ms"], int)
        self.assertFalse(heartbeat.path(self.home).exists())
        # And the second call, against the home it just cleared (D10).
        again = self._payload(
            _run("disconnect", "--home", str(self.home), fake_home=self.fake_home)
        )
        self.assertEqual(again["outcome"], "not_running")

    def test_the_home_it_resolves_is_the_one_status_resolves(self):
        """FR-001: `--home` > `KEEL_HOME` > the home derived from the resolved base URL >
        `~/.keel`, resolved through the same `config.load_status_config` -- so the two commands can
        never disagree about which directory they are talking about."""
        cases = {
            "flag": (["--home", str(self.home)], {}),
            "env": ([], {"KEEL_HOME": str(self.home)}),
            "derived": ([], {"KEEL_BASE_URL": "http://localhost:18081"}),
            "nothing at all": ([], {}),
        }
        for name, (flags, env) in cases.items():
            with self.subTest(case=name):
                disconnected = self._payload(
                    _run("disconnect", *flags, fake_home=self.fake_home, **env)
                )
                status = self._payload(_run("status", *flags, fake_home=self.fake_home, **env))
                self.assertEqual(disconnected["home"], status["home"])
                self.assertEqual(disconnected["base_url"], status["base_url"])
                self.assertEqual(disconnected["environment"], status["environment"])

        # `--base-url` names a Keel, and since spec 004 the home follows the address -- so it is a
        # way of naming the home without computing a host slug.
        by_flag = self._payload(
            _run("disconnect", "--base-url", "http://localhost:18081", fake_home=self.fake_home)
        )
        by_env = self._payload(
            _run("status", fake_home=self.fake_home, KEEL_BASE_URL="http://localhost:18081")
        )
        self.assertEqual(by_flag["home"], by_env["home"])
        self.assertEqual(by_flag["environment"], "localhost:18081")

    def test_an_unknown_flag_is_a_usage_error_not_an_outcome(self):
        result = _run("disconnect", "--nonsense", fake_home=self.fake_home)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
