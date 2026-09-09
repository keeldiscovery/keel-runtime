"""The goodbye's **seam** (spec `003-keel-disconnect` FR-010, FR-011; keel-cloud
`canon/designs/keel-disconnect-design.md` §4.2, invariants G1, G3, G6).

The goodbye itself -- one bounded, best-effort `POST /v2/agent-sessions/{id}/disconnect` that ends
the runtime's own agent session, so the founder's screen stops saying *Agent connected* in about
four seconds instead of up to ninety -- is the design's step 4 and is **not** implemented here:
keel-cloud has no such route yet. What is implemented, and what these tests hold, is the place it
goes and the promises that placement makes:

* **today it is a no-op** -- `CloudClient` has no `end_agent_session`, so nothing is called and no
  socket is opened (the first test below asserts exactly that, so the day the client grows the
  method, the day this seam starts working, is a day someone chose);
* **after the heartbeat, never before** (G3) -- local truth first: a founder who runs `keel status`
  half a second after stopping their runtime reads "not running" whether or not the network
  cooperated. Asserted here through the *real* shutdown handler, by signalling this process;
* **best-effort** (G1) -- a client that raises, times out or 404s changes neither the exit code
  nor anything else;
* **never when there is nothing to end** (G6) -- a run interrupted during device authorization has
  no agent session.
"""
import contextlib
import io
import signal
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel_runtime import cli, config as config_module, heartbeat
from keel_runtime.agent_session import RuntimeState
from keel_runtime.cloud_client import CloudClient
from keel_runtime.credential_store import Credential


class _GoodbyeClient:
    """A Keel Cloud that *does* have the goodbye -- what `CloudClient` becomes in the second
    pass."""

    def __init__(self, home=None, raises=None):
        self.calls = []
        self.heartbeat_present_at_call = None
        self._home = home
        self._raises = raises

    def end_agent_session(self, agent_session_id, access_token, timeout=None):
        if self._home is not None:
            self.heartbeat_present_at_call = heartbeat.path(self._home).exists()
        self.calls.append((agent_session_id, access_token, timeout))
        if self._raises is not None:
            raise self._raises


class SayGoodbyeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.config = _config(self.home)
        self.state = RuntimeState(agent_session_id="agent-session-1", access_token="token-1")

    def tearDown(self):
        self._tmp.cleanup()

    def test_todays_client_has_no_goodbye_and_none_is_sent(self):
        """The no-op, asserted from both ends: the client has no such method, and the seam
        reports that it attempted nothing."""
        client = CloudClient(base_url="http://127.0.0.1:1")
        self.assertFalse(hasattr(client, "end_agent_session"))
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call")):
            self.assertFalse(cli._say_goodbye(client, self.state, self.config))

    def test_a_client_with_the_goodbye_is_called_once_with_this_session_and_token(self):
        client = _GoodbyeClient()
        self.assertTrue(cli._say_goodbye(client, self.state, self.config))
        self.assertEqual(
            client.calls, [("agent-session-1", "token-1", cli.GOODBYE_TIMEOUT_SECONDS)]
        )

    def test_the_goodbye_is_bounded_to_one_call_with_a_two_second_timeout(self):
        """G2: one call, a 2s timeout, no retry, no backoff -- the opposite of the poll loop."""
        self.assertEqual(cli.GOODBYE_TIMEOUT_SECONDS, 2.0)

    def test_nothing_is_said_when_there_is_no_agent_session(self):
        """G6: a run interrupted during device authorization has nothing to end."""
        client = _GoodbyeClient()
        self.assertFalse(cli._say_goodbye(client, None, self.config))
        self.assertFalse(
            cli._say_goodbye(client, RuntimeState("", "token-1"), self.config)
        )
        self.assertEqual(client.calls, [])

    def test_every_failure_is_swallowed(self):
        """G1: a refused call, a timeout, a 404 from an older Keel Cloud, a laptop already off the
        wifi -- none of them delays the exit or changes anything."""
        for failure in (OSError("connection refused"), ValueError("404"), RuntimeError("boom")):
            with self.subTest(failure=type(failure).__name__):
                client = _GoodbyeClient(raises=failure)
                self.assertTrue(cli._say_goodbye(client, self.state, self.config))
                self.assertEqual(len(client.calls), 1)


class ConnectSaysGoodbyeTest(unittest.TestCase):
    """The call site: `_run_connect`, on the far side of `run_loop`'s return."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.config = _config(self.home)
        # `_run_connect` installs process-wide signal handlers; put the runner's own back.
        self._handlers = {
            number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)
        }

    def tearDown(self):
        for number, handler in self._handlers.items():
            signal.signal(number, handler)
        self._tmp.cleanup()

    def _connect(self, client, run_loop):
        credential = Credential(
            access_token="token-1", refresh_token="refresh-1", expires_at=4102444800.0
        )
        state = RuntimeState(agent_session_id="agent-session-1", access_token="token-1")

        def _create_agent_session(_client, _credential, config):
            # What the real one does, and the reason the ordering assertion below means anything.
            heartbeat.write(
                config.home,
                heartbeat.Heartbeat(
                    pid=1,
                    agent_session_id=state.agent_session_id,
                    base_url=config.base_url,
                    last_heartbeat_at=heartbeat.now_iso8601(),
                ),
            )
            return state

        store = mock.Mock()
        store.load.return_value = credential

        with mock.patch.object(
            cli.config_module, "load", return_value=self.config
        ), mock.patch.object(cli, "get_executor", return_value=object()), mock.patch.object(
            cli, "CredentialStore", return_value=store
        ), mock.patch.object(cli, "CloudClient", return_value=client), mock.patch.object(
            cli.agent_session_module, "create_agent_session", side_effect=_create_agent_session
        ), mock.patch.object(
            cli, "run_loop", side_effect=run_loop
        ), contextlib.redirect_stdout(io.StringIO()):
            # `connect`'s own two lines of output are not this test's subject, and `unittest`
            # (unlike pytest) does not capture them.
            return cli._run_connect(mock.Mock())

    def test_the_goodbye_is_said_after_the_heartbeat_is_gone(self):
        """G3, through the **real** shutdown handler: the loop is interrupted by an actual
        SIGTERM, whose handler removes the heartbeat and raises `KeyboardInterrupt`; the goodbye
        happens on the far side of that, with the file already gone."""
        client = _GoodbyeClient(home=self.home)

        def _interrupted_loop(*args, **kwargs):
            signal.raise_signal(signal.SIGTERM)
            raise AssertionError("the handler should have raised KeyboardInterrupt")

        self.assertEqual(self._connect(client, _interrupted_loop), 0)
        self.assertEqual(len(client.calls), 1)
        self.assertIs(client.heartbeat_present_at_call, False)
        self.assertFalse(heartbeat.path(self.home).exists())

    def test_a_goodbye_that_fails_does_not_change_the_exit_code(self):
        client = _GoodbyeClient(raises=OSError("connection refused"))
        self.assertEqual(self._connect(client, lambda *a, **k: None), 0)
        self.assertEqual(len(client.calls), 1)

    def test_the_session_said_goodbye_to_is_the_one_the_loop_finished_with(self):
        """FR-011: `run_loop` rebinds `state` when a credential expires mid-run, so it returns the
        state it finished with and the goodbye addresses the session that was actually live."""
        client = _GoodbyeClient()
        reauthorized = RuntimeState(agent_session_id="agent-session-2", access_token="token-2")

        self.assertEqual(self._connect(client, lambda *a, **k: reauthorized), 0)
        self.assertEqual(
            client.calls, [("agent-session-2", "token-2", cli.GOODBYE_TIMEOUT_SECONDS)]
        )

    def test_todays_runtime_says_nothing_and_still_exits_cleanly(self):
        """The whole of this pass, from the outside: with a client that has no goodbye, `connect`
        exits exactly as it does now."""
        client = mock.Mock(spec=CloudClient)
        self.assertEqual(self._connect(client, lambda *a, **k: None), 0)
        self.assertFalse(hasattr(client, "end_agent_session"))


def _config(home: Path):
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


if __name__ == "__main__":
    unittest.main()
