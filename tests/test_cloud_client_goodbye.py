"""`CloudClient.end_agent_session` (keel-cloud spec `033-agent-session-goodbye`;
`003-keel-disconnect` design §4.2, §4.3) -- the goodbye's own wire call, the second pass adds:
`POST /v2/agent-sessions/{id}/disconnect`, body `{}`, expecting `204`.

Against a real, local `http.server` -- not a mock of `urlopen` -- because what this method exists
to prove is that a real request goes out, with a real bearer header, on a real socket, bounded by
a real timeout. `cli._say_goodbye` (`tests/test_shutdown_goodbye.py`) is the seam that swallows
every failure this method can raise (G1); this module tests the method itself, unswallowed, so a
regression here is never hidden behind that `except Exception`.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from keel_runtime.cloud_client import ApiError, CloudClient, NetworkError


class _DisconnectHandler(BaseHTTPRequestHandler):
    """One handler class per test process; `scenario`/`hang_seconds`/`seen` are set per-test by
    `_serve` on the class itself, since `HTTPServer` instantiates one handler per request."""

    scenario = "ok"
    hang_seconds = 0.0
    seen: list = []

    def do_POST(self):  # noqa: N802 -- BaseHTTPRequestHandler's own naming convention
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw_body = self.rfile.read(length) if length else b""
        type(self).seen.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": json.loads(raw_body) if raw_body else None,
            }
        )
        if type(self).hang_seconds:
            time.sleep(type(self).hang_seconds)
        if type(self).scenario == "ok":
            self.send_response(204)
            self.end_headers()
        elif type(self).scenario == "not_found":
            self._error(404, "AGENT_SESSION_NOT_FOUND", "no such agent session")
        elif type(self).scenario == "forbidden":
            self._error(403, "INSUFFICIENT_SCOPE", "missing agent.session.create")

    def _error(self, status: int, code: str, message: str) -> None:
        payload = json.dumps({"error": {"code": code, "message": message}}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # noqa: ARG002 -- silence; a test run is not this log's reader
        pass


class _Server(ThreadingHTTPServer):
    # Each request runs on its own thread, so a hanging handler never blocks `shutdown()` from
    # noticing the main accept loop should stop -- and those per-request threads are daemons, so
    # a still-sleeping one never holds the test process open.
    daemon_threads = True


def _serve(scenario="ok", hang_seconds=0.0):
    _DisconnectHandler.scenario = scenario
    _DisconnectHandler.hang_seconds = hang_seconds
    _DisconnectHandler.seen = []
    server = _Server(("127.0.0.1", 0), _DisconnectHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop(server, thread):
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


class EndAgentSessionTest(unittest.TestCase):
    def test_the_call_is_made_with_the_right_path_bearer_and_body(self):
        server, thread = _serve("ok")
        try:
            client = CloudClient(base_url=f"http://127.0.0.1:{server.server_port}")
            client.end_agent_session("agent-session-9", "token-9", timeout=2.0)
        finally:
            _stop(server, thread)

        self.assertEqual(len(_DisconnectHandler.seen), 1)
        call = _DisconnectHandler.seen[0]
        self.assertEqual(call["path"], "/v2/agent-sessions/agent-session-9/disconnect")
        self.assertEqual(call["authorization"], "Bearer token-9")
        self.assertEqual(call["body"], {})

    def test_a_404_from_an_older_keel_cloud_raises_ApiError(self):
        server, thread = _serve("not_found")
        try:
            client = CloudClient(base_url=f"http://127.0.0.1:{server.server_port}")
            with self.assertRaises(ApiError) as ctx:
                client.end_agent_session("agent-session-9", "token-9", timeout=2.0)
        finally:
            _stop(server, thread)
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(ctx.exception.code, "AGENT_SESSION_NOT_FOUND")

    def test_a_403_insufficient_scope_raises_ApiError(self):
        server, thread = _serve("forbidden")
        try:
            client = CloudClient(base_url=f"http://127.0.0.1:{server.server_port}")
            with self.assertRaises(ApiError) as ctx:
                client.end_agent_session("agent-session-9", "token-9", timeout=2.0)
        finally:
            _stop(server, thread)
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.code, "INSUFFICIENT_SCOPE")

    def test_a_hanging_server_is_bounded_by_the_callers_own_timeout(self):
        """The call never blocks shutdown forever: a server that answers, just too slowly,
        still hands back control -- as `NetworkError` -- within the timeout the caller chose,
        not the server's own pace."""
        server, thread = _serve("ok", hang_seconds=2.0)
        try:
            client = CloudClient(base_url=f"http://127.0.0.1:{server.server_port}")
            started = time.monotonic()
            with self.assertRaises(NetworkError):
                client.end_agent_session("agent-session-9", "token-9", timeout=0.3)
            elapsed = time.monotonic() - started
        finally:
            _stop(server, thread)
        self.assertLess(elapsed, 1.5)

    def test_nothing_listening_raises_NetworkError(self):
        # A briefly-bound, now-closed port: nothing answers there any more, which is the
        # unreachable-Cloud case a laptop off the wifi produces too.
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        client = CloudClient(base_url=f"http://127.0.0.1:{port}")
        with self.assertRaises(NetworkError):
            client.end_agent_session("agent-session-9", "token-9", timeout=1.0)


if __name__ == "__main__":
    unittest.main()
