"""The runtime's main loop (design §10.12): long-poll, execute, validate, complete/fail.

On ``NO_WORK`` it re-polls immediately -- the long-poll itself is the liveness signal,
so there is no additional short-interval polling (spec FR-027). Executor exceptions map
to `/fail` error codes; a ``422 INVALID_RESULT`` from `/complete` is treated the same as
the executor's own ``InvalidResponse``. A ``401`` anywhere discards the stored
credential and re-authorizes from scratch. A network error retries with capped
exponential backoff. ``KeyboardInterrupt`` exits cleanly.
"""
from __future__ import annotations

import os
import time

from . import agent_session as agent_session_module
from . import auth as auth_module
from . import heartbeat as heartbeat_module
from .cloud_client import ApiError, AuthenticationExpired, CloudClient, NetworkError
from .executor import (
    Executor,
    ExecutorAuthFailure,
    ExecutorTimeout,
    ExecutorUnavailable,
    InferenceRequest,
)
from .response_validator import InvalidResponse, validate_response

INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0


def run_loop(client: CloudClient, state, executor: Executor, store, config) -> None:
    backoff = INITIAL_BACKOFF_SECONDS
    try:
        while True:
            try:
                answer = client.poll(state.agent_session_id, state.access_token)
                backoff = INITIAL_BACKOFF_SECONDS
                if answer.get("type") == "NO_WORK":
                    _write_heartbeat(state, config)
                    continue
                _handle_job(client, state, executor, answer["job"])
                _write_heartbeat(state, config)
            except AuthenticationExpired:
                state = _reauthorize(client, store, config)
                continue
            except NetworkError:
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                continue
    except KeyboardInterrupt:
        return


def _write_heartbeat(state, config) -> None:
    # spec 021 FR-001: written after every poll cycle -- NO_WORK and a delivered job
    # alike -- so a runtime that is merely idle still reads as alive, not only one that
    # just completed a job.
    heartbeat_module.write(
        config.home,
        heartbeat_module.Heartbeat(
            pid=os.getpid(),
            agent_session_id=state.agent_session_id,
            base_url=config.base_url,
            last_heartbeat_at=heartbeat_module.now_iso8601(),
        ),
    )


def _handle_job(client: CloudClient, state, executor: Executor, job: dict) -> None:
    request = InferenceRequest(
        job_id=job["job_id"],
        interaction_id=job["interaction_id"],
        turn_number=job["turn_number"],
        request_payload=job["request_payload"],
    )

    try:
        response = executor.execute(request)
        validate_response(response, job["request_payload"]["response_contract"])
    except ExecutorUnavailable as exc:
        _fail(client, state, job["job_id"], "LLM_UNAVAILABLE", str(exc))
        return
    except ExecutorAuthFailure as exc:
        _fail(client, state, job["job_id"], "EXECUTOR_AUTH_FAILED", str(exc))
        return
    except ExecutorTimeout as exc:
        _fail(client, state, job["job_id"], "EXECUTOR_TIMEOUT", str(exc))
        return
    except InvalidResponse as exc:
        _fail(client, state, job["job_id"], "INVALID_LLM_RESPONSE", str(exc))
        return
    except Exception as exc:  # noqa: BLE001 -- anything else maps to INTERNAL_ERROR (FR-027)
        _fail(client, state, job["job_id"], "INTERNAL_ERROR", str(exc))
        return

    try:
        client.complete_job(job["job_id"], state.access_token, response)
    except ApiError as exc:
        if exc.status == 422:
            # A 422 INVALID_RESULT from /complete is treated as InvalidResponse (FR-027):
            # the runtime's own validator agreed, but the server's disagreed (or the
            # runtime has no jsonschema/subset gap) -- fail it honestly rather than retry.
            _fail(client, state, job["job_id"], "INVALID_LLM_RESPONSE", exc.message)
        else:
            raise


def _fail(client: CloudClient, state, job_id: str, code: str, message: str) -> None:
    client.fail_job(job_id, state.access_token, code, message[:500])


def _reauthorize(client: CloudClient, store, config):
    store.clear()
    credential = auth_module.authorize_device(client, config)
    store.save(credential)
    return agent_session_module.create_agent_session(client, credential, config)
