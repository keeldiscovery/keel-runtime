"""Tests for keel_runtime.auth's stdout contract (spec FR-026) using a fake client.

No network: FakeClient stands in for CloudClient so these tests never touch a socket.
"""
import io
import unittest
from contextlib import redirect_stdout

from keel_runtime.auth import AuthorizationError, authorize_device
from keel_runtime.cloud_client import ApiError


class FakeConfig:
    open_browser = False


class FakeClient:
    def __init__(self, pending_polls=0, final_error=None):
        self._pending_polls = pending_polls
        self._polls = 0
        self._final_error = final_error

    def create_device_authorization(self):
        return {
            "device_authorization_id": "da-1",
            "device_code": "secret-device-code",
            "user_code": "KJRT-WXMP",
            "verification_uri": "http://localhost:3000/connect",
            "verification_uri_complete": "http://localhost:3000/connect?user_code=KJRT-WXMP",
            "expires_in": 600,
            "poll_interval": 0,
        }

    def get_agent_token(self, device_code):
        if self._polls < self._pending_polls:
            self._polls += 1
            raise ApiError(400, "AUTHORIZATION_PENDING", "not yet decided")
        if self._final_error is not None:
            raise self._final_error
        return {
            "access_token": "access-token-value",
            "refresh_token": "refresh-token-value",
            "expires_in": 3600,
            "scope": ["agent.session.create", "agent.session.poll", "inference.complete"],
        }


class AuthOutputTest(unittest.TestCase):
    def test_prints_the_two_stable_machine_readable_lines(self):
        client = FakeClient()
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            credential = authorize_device(client, FakeConfig())

        output = buffer.getvalue()
        self.assertIn("KEEL_USER_CODE=KJRT-WXMP\n", output)
        self.assertIn(
            "KEEL_VERIFICATION_URI=http://localhost:3000/connect?user_code=KJRT-WXMP\n",
            output,
        )
        self.assertEqual(credential.access_token, "access-token-value")
        self.assertEqual(credential.refresh_token, "refresh-token-value")

    def test_polls_through_authorization_pending_until_approved(self):
        client = FakeClient(pending_polls=2)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            credential = authorize_device(client, FakeConfig())
        self.assertEqual(credential.access_token, "access-token-value")

    def test_access_denied_raises_authorization_error(self):
        client = FakeClient(final_error=ApiError(403, "ACCESS_DENIED", "the founder denied it"))
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            with self.assertRaises(AuthorizationError) as ctx:
                authorize_device(client, FakeConfig())
        self.assertEqual(ctx.exception.code, "ACCESS_DENIED")

    def test_expired_raises_authorization_error(self):
        client = FakeClient(
            final_error=ApiError(400, "AUTHORIZATION_EXPIRED", "the code expired")
        )
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            with self.assertRaises(AuthorizationError) as ctx:
                authorize_device(client, FakeConfig())
        self.assertEqual(ctx.exception.code, "AUTHORIZATION_EXPIRED")


if __name__ == "__main__":
    unittest.main()
