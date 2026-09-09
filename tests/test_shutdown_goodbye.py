"""The goodbye's **seam and call site** (spec `003-keel-disconnect` FR-010, FR-011; keel-cloud
`canon/designs/keel-disconnect-design.md` §4.2, invariants G1, G3, G6).

The goodbye itself -- one bounded, best-effort `POST /v2/agent-sessions/{id}/disconnect` that ends
the runtime's own agent session, so the founder's screen stops saying *Agent connected* in about
four seconds instead of up to ninety -- is `CloudClient.end_agent_session`
(`keel_runtime/cloud_client.py`; keel-cloud spec `033-agent-session-goodbye`, design §10 step 4),
and `tests/test_cloud_client_goodbye.py` holds its own wire-level promises against a real, local
server. What this module holds is the seam around that call and the promises its *placement*
makes, using a recording stub client (`_GoodbyeClient`) so the ordering and swallowing tests never
touch a socket:

* **the call is made once, with this session's own id and bearer** -- and nothing at all when a
  client carries no goodbye (a stub in a test, or a hypothetically older `CloudClient`);
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
    """A recording stand-in for `CloudClient`, so the seam's ordering and swallowing are proved
    without a socket. `test_cloud_client_goodbye.py` proves the real method against a real
    server; this fixture only needs to look like it."""

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

    def test_todays_client_has_the_goodbye(self):
        """The method this seam was built to call now exists for real (the second pass) --
        `test_cloud_client_goodbye.py` proves what it does against a real server; this only
        proves the seam finds it."""
        client = CloudClient(base_url="http://127.0.0.1:1")
        self.assertTrue(hasattr(client, "end_agent_session"))

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

    def test_connect_exits_cleanly_with_the_real_client_shape(self):
        """The whole of this pass, from the outside: `connect` exits exactly as it did before the
        goodbye existed, and the real client's `end_agent_session` is the one thing reached."""
        client = mock.Mock(spec=CloudClient)
        self.assertEqual(self._connect(client, lambda *a, **k: None), 0)
        client.end_agent_session.assert_called_once()

    def test_connect_exits_cleanly_even_if_the_client_carries_no_goodbye_at_all(self):
        """Defensive: the seam's `getattr` lookup, not a direct call, is what keeps a client with
        no `end_agent_session` at all a clean no-op instead of an `AttributeError` -- so `connect`
        would still exit 0 talking to a hypothetically older client shape."""
        client = object()
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
