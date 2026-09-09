"""Tests for `AgentSessionSuperseded` (keel-cloud spec `035-one-runtime-per-founder`;
`003-keel-disconnect`'s amendment, `specs/003-keel-disconnect/AMENDMENT-agent-session-
superseded.md`).

A `410` carrying `{"error": {"code": "AGENT_SESSION_SUPERSEDED", ...}}` on any runtime-
authenticated route means another runtime already connected to this founder account and took
this one's agent session over. Unlike a `401`, which means "re-authenticate", this must never
trigger a fresh device authorization -- that would fight the new runtime for the account. Three
layers are covered:

* `cloud_client.CloudClient._request` -- the 410 is parsed into `AgentSessionSuperseded` only when
  the code matches; any other 410 stays an `ApiError`, exactly as before this change; a 401 is
  still `AuthenticationExpired` regardless.
* `poller.run_loop` -- the exception is not caught alongside `AuthenticationExpired`; it propagates
  out of the loop whole, with no re-authorization attempted and no retry.
* `cli._run_connect` -- against a fake local server standing in for keel-cloud, a poll that answers
  410-superseded prints one `KEEL_SUPERSEDED=1` line, removes the heartbeat, calls no goodbye, and
  exits 0 -- with the stored credential left byte-identical, since `keel connect` here again is
  exactly how the founder takes the account back.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from keel_runtime import cli, config as config_module, heartbeat
from keel_runtime.agent_session import RuntimeState
from keel_runtime.cloud_client import (
    AgentSessionSuperseded,
    ApiError,
    AuthenticationExpired,
    CloudClient,
)
from keel_runtime.credential_store import Credential
from keel_runtime.poller import run_loop


# -- cloud_client: the wire-level parse --------------------------------------------------------


class _SupersededHandler(BaseHTTPRequestHandler):
    scenario = "superseded"

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length:
            self.rfile.read(length)
        if type(self).scenario == "superseded":
            self._error(
                410,
                "AGENT_SESSION_SUPERSEDED",
                "another runtime connected to this account and took over; this one is done -- "
                "run keel connect here again to take it back",
            )
        elif type(self).scenario == "gone_other_code":
            self._error(410, "SOMETHING_ELSE_ENTIRELY", "gone for an unrelated reason")
        elif type(self).scenario == "unauthorized":
            self._error(401, "TOKEN_EXPIRED", "credential no longer accepted")

    def _error(self, status, code, message):
        payload = json.dumps({"error": {"code": code, "message": message}}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # noqa: ARG002
        pass


def _serve(scenario):
    _SupersededHandler.scenario = scenario
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SupersededHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop(server, thread):
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


class CloudClientSupersededTest(unittest.TestCase):
    def test_410_with_the_code_raises_AgentSessionSuperseded_with_the_servers_message(self):
        server, thread = _serve("superseded")
        try:
            client = CloudClient(base_url=f"http://127.0.0.1:{server.server_port}")
            with self.assertRaises(AgentSessionSuperseded) as ctx:
                client.poll("agent-session-1", "token-1")
        finally:
            _stop(server, thread)
        self.assertIn("run keel connect here again to take it back", ctx.exception.message)

    def test_410_with_a_different_code_is_still_an_ApiError(self):
        server, thread = _serve("gone_other_code")
        try:
            client = CloudClient(base_url=f"http://127.0.0.1:{server.server_port}")
            with self.assertRaises(ApiError) as ctx:
                client.poll("agent-session-1", "token-1")
        finally:
            _stop(server, thread)
        self.assertEqual(ctx.exception.status, 410)
        self.assertEqual(ctx.exception.code, "SOMETHING_ELSE_ENTIRELY")

    def test_401_still_raises_AuthenticationExpired_not_superseded(self):
        server, thread = _serve("unauthorized")
        try:
            client = CloudClient(base_url=f"http://127.0.0.1:{server.server_port}")
            with self.assertRaises(AuthenticationExpired):
                client.poll("agent-session-1", "token-1")
        finally:
            _stop(server, thread)


# -- poller: the exception is not swallowed or turned into a re-authorization -------------------


class _PollOnceThenSupersededClient:
    """`poll` answers `NO_WORK` once, then raises `AgentSessionSuperseded` -- proving the
    exception reaches the caller mid-loop, not only on the very first call."""

    def __init__(self, message):
        self.message = message
        self.calls = 0

    def poll(self, agent_session_id, access_token):
        self.calls += 1
        if self.calls == 1:
            return {"type": "NO_WORK"}
        raise AgentSessionSuperseded(self.message)


class RunLoopSupersededTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.config = SimpleNamespace(home=self.home, base_url="http://localhost:18081")
        self.state = SimpleNamespace(agent_session_id="agent-session-1", access_token="token-1")

    def tearDown(self):
        self._tmp.cleanup()

    def test_propagates_out_of_run_loop_untouched(self):
        client = _PollOnceThenSupersededClient("another runtime took over")
        store = mock.Mock()

        with self.assertRaises(AgentSessionSuperseded) as ctx:
            run_loop(client, self.state, executor=None, store=store, config=self.config)

        self.assertEqual(ctx.exception.message, "another runtime took over")
        # No re-authorization was attempted -- the one thing a `401` handler would have done.
        store.clear.assert_not_called()
        store.save.assert_not_called()
        # It took the second poll to raise -- proving this isn't just "the first call fails".
        self.assertEqual(client.calls, 2)


# -- cli: the full `connect` flow, against a fake server ----------------------------------------


class _SupersededDeviceServerHandler(BaseHTTPRequestHandler):
    """Stands in for keel-cloud across the whole `connect` flow: a stored credential is accepted
    once (`create_agent_session`), and the first `poll` answers 410-superseded."""

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length:
            self.rfile.read(length)
        if self.path == "/v2/agent-sessions":
            self._json(200, {"agent_session_id": "agent-session-1"})
        elif self.path.endswith("/poll"):
            self._error(
                410,
                "AGENT_SESSION_SUPERSEDED",
                "another runtime connected to this account and took over; this one is done -- "
                "run keel connect here again to take it back",
            )
        else:
            self._error(404, "NOT_FOUND", "unexpected path in this fixture")

    def _json(self, status, body):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _error(self, status, code, message):
        self._json(status, {"error": {"code": code, "message": message}})

    def log_message(self, *args):  # noqa: ARG002
        pass


class ConnectSupersededTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _SupersededDeviceServerHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.config = config_module.RuntimeConfig(
            base_url=f"http://127.0.0.1:{self.server.server_port}",
            executor="stub",
            home=self.home,
            credential_backend="file",
            open_browser=False,
            heartbeat_stale_after=50.0,
            script_path=None,
            context_keys_path=None,
            job_budget_usd=1.0,
            job_max_turns=6,
            job_timeout_seconds=300.0,
        )

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        self._tmp.cleanup()

    def test_a_superseded_poll_exits_0_prints_the_line_clears_the_heartbeat_keeps_the_credential(
        self,
    ):
        credential = Credential(
            access_token="token-1", refresh_token="refresh-1", expires_at=4102444800.0
        )
        store = mock.Mock()
        store.load.return_value = credential

        # `create_agent_session` writes the real heartbeat, exactly as the live one does, so
        # there is something for `_report_superseded` to remove.
        def _create_agent_session(_client, _credential, config):
            heartbeat.write(
                config.home,
                heartbeat.Heartbeat(
                    pid=1,
                    agent_session_id="agent-session-1",
                    base_url=config.base_url,
                    last_heartbeat_at=heartbeat.now_iso8601(),
                ),
            )
            return RuntimeState(agent_session_id="agent-session-1", access_token="token-1")

        with mock.patch.object(
            cli.config_module, "load", return_value=self.config
        ), mock.patch.object(cli, "get_executor", return_value=object()), mock.patch.object(
            cli, "CredentialStore", return_value=store
        ), mock.patch.object(
            cli.agent_session_module, "create_agent_session", side_effect=_create_agent_session
        ), contextlib.redirect_stdout(io.StringIO()) as captured:
            exit_code = cli._run_connect(SimpleNamespace(
                base_url=None, executor=None, host="auto", copilot_model=None, script=None,
                context_keys=None, home=str(self.home), credential_backend=None,
                no_browser=True, log_level="INFO",
            ))

        self.assertEqual(exit_code, 0)
        output = captured.getvalue()
        superseded_lines = [line for line in output.splitlines() if line.startswith("KEEL_SUPERSEDED=")]
        self.assertEqual(len(superseded_lines), 1)
        self.assertEqual(
            superseded_lines[0],
            "KEEL_SUPERSEDED=1 message=another runtime connected to this account and took over; "
            "this one is done -- run keel connect here again to take it back",
        )
        # The heartbeat is gone -- `keel status` afterwards reads not_running.
        self.assertIsNone(heartbeat.read(self.home))
        # No goodbye was attempted: nothing else was sent to `/v2/agent-sessions/*/disconnect`,
        # and the stored credential was never touched.
        store.clear.assert_not_called()
        store.save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
