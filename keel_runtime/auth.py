"""Device authorization flow (design §10.2): create, print, poll until decided.

Prints two stable, machine-readable lines to stdout, flushed immediately, so a harness
tailing the runtime's log can parse them (spec FR-026):
``KEEL_USER_CODE=<display code>`` and ``KEEL_VERIFICATION_URI=<verification_uri_complete>``.
"""
from __future__ import annotations

import time
import webbrowser

from .cloud_client import ApiError, CloudClient, NetworkError
from .credential_store import Credential


class AuthorizationError(Exception):
    """Raised when the device authorization ends in anything other than approval."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def authorize_device(client: CloudClient, config) -> Credential:
    created = client.create_device_authorization()
    device_code = created["device_code"]
    user_code = created["user_code"]
    verification_uri_complete = created["verification_uri_complete"]
    poll_interval = created.get("poll_interval", 5)

    print(f"To authorize this device, visit: {verification_uri_complete}")
    print(f"Enter code: {user_code}")
    print(f"KEEL_USER_CODE={user_code}", flush=True)
    print(f"KEEL_VERIFICATION_URI={verification_uri_complete}", flush=True)

    if getattr(config, "open_browser", True):
        try:
            webbrowser.open(verification_uri_complete)
        except Exception:
            pass  # best-effort; the printed URL is the fallback for a headless machine

    while True:
        try:
            token = client.get_agent_token(device_code)
            return Credential(
                access_token=token["access_token"],
                refresh_token=token["refresh_token"],
                expires_at=time.time() + token["expires_in"],
                scope=list(token.get("scope") or []),
            )
        except ApiError as exc:
            if exc.code == "AUTHORIZATION_PENDING":
                time.sleep(poll_interval)
                continue
            # ACCESS_DENIED, AUTHORIZATION_EXPIRED, CREDENTIAL_ALREADY_ISSUED, or
            # anything else the server names -- all end the flow (spec FR-026).
            raise AuthorizationError(exc.code, exc.message) from exc
        except NetworkError:
            # A transient network failure while polling for a decision is not itself a
            # decision; keep polling at the server's own cadence rather than aborting
            # the whole authorization (judgement call -- not specified by FR-026/FR-027,
            # which only describe backoff for the *job* poll loop).
            time.sleep(poll_interval)
            continue
