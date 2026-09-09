"""Command-line entry point: `python3 -m keel_runtime connect` / installed `keel connect`.

`main()` is also the `[project.scripts]` target (`keel = "keel_runtime.cli:main"`), but
this module never assumes it has been installed -- `keel_runtime/__main__.py` calls the
same `main()` so the package runs uninstalled from this directory, which is how the
E2E test launches it (spec FR-024, SC-002).
"""
from __future__ import annotations

import argparse
import json
import shutil
import signal
import sys

from . import COPYRIGHT, LICENSE_URL, __license__, __version__
from . import agent_session as agent_session_module
from . import auth as auth_module
from . import config as config_module
from . import disconnect as disconnect_module
from . import heartbeat as heartbeat_module
from .cloud_client import AuthenticationExpired, CloudClient
from .credential_store import CredentialStore
from .executor import get_executor
from .poller import run_loop


# Which CLI a named executor needs on `PATH`, for `status`'s `executor_on_path` (spec
# 004-shipped-runtime FR-009, design C-10). `scripted` and `stub` run in this process and are
# always available, so they are absent here and report `true`. Spec `005-copilot-executor` adds
# `copilot` when the executor it names exists; `claude_on_path` is never built, because it reads
# `false` on a healthy runtime that is not using Claude, which is a lie about health.
_EXECUTOR_BINARIES = {"claude-code": "claude"}
_IN_PROCESS_EXECUTORS = frozenset({"scripted", "stub"})


def version_line() -> str:
    """One line, and the whole of `--version` (FR-005). It names `CLOUD_BASE_URL` once that
    constant has a value -- design §13 step 8, whose entire edit is that string.
    """
    line = f"keel-runtime {__version__}"
    if config_module.CLOUD_BASE_URL:
        line += f" (Keel Cloud {config_module.CLOUD_BASE_URL})"
    return line


def license_text() -> str:
    return (
        f"keel-runtime {__version__}\n"
        f"{COPYRIGHT}\n"
        f"Licensed under the Apache License, Version 2.0 (SPDX: {__license__}); "
        f"the full text is at {LICENSE_URL}\n"
        "This runtime bundles no third-party code: it runs on the Python standard library alone. "
        "`keyring` and `jsonschema` are optional accelerators, used only if you install them "
        "yourself."
    )


class _PrintAndExit(argparse.Action):
    """A `--version`-style flag: print one thing, exit 0, ask for no subcommand.

    argparse runs an optional's action as it consumes the argument, so this fires before the
    `required=True` subparser check at the end of `parse_args` -- which is what lets
    `python3 -m keel_runtime --version` work with no command at all (§10.3 assertion 3).
    """

    def __init__(self, option_strings, dest, text=None, **kwargs):
        super().__init__(option_strings, dest, nargs=0, default=argparse.SUPPRESS, **kwargs)
        self._text = text

    def __call__(self, parser, namespace, values, option_string=None):
        print(self._text() if callable(self._text) else self._text)
        parser.exit(0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keel", description="Keel local runtime")
    parser.add_argument(
        "--version",
        action=_PrintAndExit,
        text=version_line,
        help="print this runtime's version and exit",
    )
    parser.add_argument(
        "--license",
        action=_PrintAndExit,
        text=license_text,
        help="print this runtime's licence notice and exit",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    connect = subparsers.add_parser(
        "connect", help="authorize this device against Keel Cloud and run the local runtime"
    )
    connect.add_argument("--base-url", dest="base_url", help="Keel Cloud base URL")
    connect.add_argument(
        "--executor",
        dest="executor",
        help="executor to run jobs with: claude-code (default), stub or scripted (test-only)",
    )
    connect.add_argument(
        "--script",
        dest="script",
        help="path to a scripted-executor script (only meaningful with --executor scripted; "
        "falls back to KEEL_SCRIPT, then to the bundled countly-problem script)",
    )
    connect.add_argument(
        "--context-keys",
        dest="context_keys",
        help="path to keel-cloud's exported context-keys.json, the scripted executor's "
        "screen-inference table (only meaningful with --executor scripted; falls back to "
        "KEEL_CONTEXT_KEYS, then to the bundled copy)",
    )
    connect.add_argument("--home", dest="home", help="overrides KEEL_HOME for this run")
    connect.add_argument(
        "--credential-backend",
        dest="credential_backend",
        choices=["auto", "file", "keyring"],
        help="where to store the issued credential",
    )
    connect.add_argument(
        "--no-browser",
        dest="no_browser",
        action="store_true",
        help="do not open a browser for device authorization; print the URL instead",
    )
    connect.add_argument(
        "--log-level",
        dest="log_level",
        default="INFO",
        help="log verbosity (informational only in this pass)",
    )

    status = subparsers.add_parser(
        "status",
        help="report whether a keel-runtime process is currently connected (spec 021)",
    )
    status.add_argument("--home", dest="home", help="overrides KEEL_HOME for this run")

    disconnect = subparsers.add_parser(
        "disconnect",
        help="stop the keel-runtime process running on this home (spec 003-keel-disconnect)",
    )
    disconnect.add_argument("--home", dest="home", help="overrides KEEL_HOME for this run")
    # Since spec `004-shipped-runtime` the home **follows the address**, so naming the Keel is a
    # way of naming the home: a caller that knows which Keel it means should not have to compute a
    # host slug to say which directory it means. It is never used to reach the network (D9).
    disconnect.add_argument(
        "--base-url",
        dest="base_url",
        help="the Keel whose derived home to act on, when no --home/KEEL_HOME is set",
    )

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "connect":
        return _run_connect(args)
    if args.command == "status":
        return _run_status(args)
    if args.command == "disconnect":
        return _run_disconnect(args)

    parser.print_help()  # pragma: no cover -- argparse's `required=True` makes this dead
    return 1


def _run_connect(args) -> int:
    config = config_module.load(args)
    config.home.mkdir(parents=True, exist_ok=True)
    # The first line of the log the skill is already reading, in the same machine-readable family
    # as `KEEL_USER_CODE=` (spec 004-shipped-runtime FR-010, design §6.3): which Keel this is, and
    # its address. The skill carries no address of its own (X-5) and reports what it is handed.
    print(
        f"KEEL_ENVIRONMENT={config.environment} base_url={config.base_url}",
        flush=True,
    )
    _install_heartbeat_shutdown_handlers(config)

    if config.script_path and config.executor != "scripted":
        print(
            f"keel connect: --script is ignored because --executor is '{config.executor}', "
            "not 'scripted'",
            file=sys.stderr,
        )

    if config.context_keys_path and config.executor != "scripted":
        print(
            f"keel connect: --context-keys is ignored because --executor is "
            f"'{config.executor}', not 'scripted'",
            file=sys.stderr,
        )

    executor = get_executor(
        config.executor,
        config.script_path,
        home=config.home,
        context_keys_path=config.context_keys_path,
        budget_usd=config.job_budget_usd,
        max_turns=config.job_max_turns,
        timeout_seconds=config.job_timeout_seconds,
    )
    store = CredentialStore(config.home, backend=config.credential_backend)
    client = CloudClient(base_url=config.base_url)

    credential = store.load()
    state = None
    if credential is not None:
        try:
            state = agent_session_module.create_agent_session(client, credential, config)
        except AuthenticationExpired:
            # A stored credential the server no longer accepts is exactly "none or
            # refused" (spec FR-026) -- fall through to a fresh device authorization.
            store.clear()
            credential = None

    if state is None:
        credential = auth_module.authorize_device(client, config)
        store.save(credential)
        state = agent_session_module.create_agent_session(client, credential, config)

    print(f"keel-runtime connected: agent_session_id={state.agent_session_id}")
    print("Polling for work. Press Ctrl+C to stop.")

    try:
        # FR-011: `run_loop` rebinds `state` when a credential expires mid-run (`_reauthorize`),
        # so the state to say goodbye with is the one it *finished* with, not the one it started
        # with. It returns None only if it never entered the loop.
        final_state = run_loop(client, state, executor, store, config)
        if final_state is not None:
            state = final_state
    except KeyboardInterrupt:
        pass

    try:
        _say_goodbye(client, state, config)
    except KeyboardInterrupt:
        # A second Ctrl+C/SIGTERM while the goodbye is in flight is still a clean exit (G1).
        pass
    return 0


# One call, a two-second timeout, no retry, no backoff -- the opposite of the poll loop, which
# retries forever because it has forever (G2).
GOODBYE_TIMEOUT_SECONDS = 2.0


def _say_goodbye(client, state, config) -> bool:
    """The runtime's last act, and the **seam** spec 003's second pass fills (FR-010; design §4.2,
    invariants G1-G3, G6). Returns whether a goodbye was attempted.

    **Today it is a no-op**, deliberately and tested as one: `CloudClient` has no
    `end_agent_session`, because keel-cloud has no `POST /v2/agent-sessions/{id}/disconnect` to
    call yet (keel-cloud spec `033-agent-session-goodbye`, design §10 step 3). The second pass adds
    that one client method and this call site starts working with no edit of its own.

    **Where it is, and where it must not be.** Not in the signal handler: that runs on the main
    thread's own stack, wherever that thread happens to be -- nine times in ten inside the
    long-poll's `urlopen` -- and opening a second socket from inside the first one's stack frame,
    in a handler that may be re-entered by a second SIGTERM, is the kind of code that works until
    the day it does not. The handler keeps doing exactly what spec 021 FR-003 gave it, and the
    goodbye goes here, after the stack has unwound. That placement also gets the ordering right
    for free (G3): the heartbeat is already gone, so a founder who runs `keel status` half a second
    later reads "not running" whether or not the network cooperated. **Local truth first, always.**

    **Best-effort.** Every exception is swallowed: a refused call, a 404 from an older Keel Cloud,
    a laptop already off the wifi. None of them delays the exit, changes the exit code, or changes
    `keel disconnect`'s outcome (G1). The goodbye is an accelerator, never a requirement (G5) --
    when it does not arrive, keel-cloud's existing staleness rule turns the founder's screen off
    exactly as it does today.
    """
    if state is None or not getattr(state, "agent_session_id", None):
        return False  # G6 -- a run interrupted during device authorization has nothing to end.

    end_agent_session = getattr(client, "end_agent_session", None)
    if end_agent_session is None:
        return False  # no endpoint in this runtime's client yet -- the second pass adds it.

    try:
        end_agent_session(
            state.agent_session_id,
            state.access_token,
            timeout=GOODBYE_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001 -- G1: everything, without exception, is swallowed here.
        pass
    return True


def _install_heartbeat_shutdown_handlers(config) -> None:
    """spec 021 FR-003 / research.md §6: on SIGINT (Ctrl+C) or SIGTERM, remove the
    heartbeat file before the existing shutdown path (spec 020 FR-026) runs its course,
    so `status` sees "not running" immediately rather than waiting out the staleness
    window. Re-raising as `KeyboardInterrupt` keeps `run_loop`'s and `_run_connect`'s
    existing `except KeyboardInterrupt` handling -- and therefore `connect`'s existing
    exit behavior/messages -- unchanged for both signals.
    """

    def _handle_shutdown_signal(signum, frame):  # noqa: ARG001 -- signal handler signature
        heartbeat_module.remove(config.home)
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)


def _run_status(args) -> int:
    """spec 021 FR-004/FR-005: no network call, always exits 0, exactly one line of
    JSON on stdout (contracts/status-cli-output.md).
    """
    status_config = config_module.load_status_config(args)
    hb = heartbeat_module.read(status_config.home)

    if hb is None:
        result = {"running": False}
    elif not heartbeat_module.pid_alive(hb.pid):
        # A dead pid is definitive, regardless of the heartbeat's age (Acceptance
        # Scenario 5).
        result = {"running": False, "stale_pid": hb.pid}
    elif heartbeat_module.is_stale(hb, status_config.heartbeat_stale_after):
        result = {"running": False, "stale_pid": hb.pid}
    else:
        result = {
            "running": True,
            "pid": hb.pid,
            "agent_session_id": hb.agent_session_id,
            "base_url": hb.base_url,
            "last_heartbeat_at": hb.last_heartbeat_at,
            "connected": True,
        }

    result.update(_environment_keys(status_config, hb))
    print(json.dumps(result))
    return 0


def _run_disconnect(args) -> int:
    """spec `003-keel-disconnect` FR-001/FR-005/FR-008: one line of JSON on stdout, exit 0 always,
    no network call (contracts/disconnect-cli-output.md).

    The wiring is four lines because the flow is `disconnect.py`'s: read the heartbeat once for
    the address it records, run the flow, and say what happened and which Keel it happened to.
    """
    status_config = config_module.load_status_config(args)
    # Read before the flow runs, because a `stopped` run removes the file the address comes from.
    hb = heartbeat_module.read(status_config.home)

    result = disconnect_module.disconnect(status_config.home)
    result.update(_address_keys(status_config, hb))
    print(json.dumps(result))
    return 0


def _address_keys(status_config, heartbeat_record) -> dict:
    """`home`, `base_url`, `environment` -- *which home, and which Keel* (spec 004 FR-009, spec 003
    FR-008). One helper, so exactly one place decides the address for both `status` and
    `disconnect`.

    When a heartbeat was readable the address is the *heartbeat's*: it describes the Keel the live
    (or just-stopped) process actually connected to, which is not necessarily the one a fresh
    resolution would pick now.
    """
    base_url = status_config.base_url
    if heartbeat_record is not None and getattr(heartbeat_record, "base_url", None):
        base_url = heartbeat_record.base_url

    return {
        "home": str(status_config.home),
        "base_url": base_url,
        "environment": config_module.environment_for(base_url),
    }


def _environment_keys(status_config, heartbeat_record) -> dict:
    """`home`, `base_url`, `environment`, `executor`, `executor_on_path` -- the four keys spec
    004-shipped-runtime FR-009 adds and the promotion of `base_url` to always-present. Every one
    of them is in **both** shapes (design C-10), which is why this is one helper and not two
    branches.

    In the running shape the address is the *heartbeat's*: it describes the Keel the live process
    actually connected to, which is not necessarily the one a fresh resolution would pick now.
    That part is `_address_keys`, shared with `disconnect`; the two executor keys are `status`'s
    alone, since no executor takes part in a disconnect.
    """
    keys = _address_keys(status_config, heartbeat_record)

    executor = status_config.executor
    binary = _EXECUTOR_BINARIES.get(executor)
    if binary is not None:
        executor_on_path = shutil.which(binary) is not None
    else:
        # An in-process executor (`scripted`, `stub`) has no CLI to find and is always available;
        # reporting `false` for it would read as "broken" on a healthy deterministic run. A name
        # this runtime does not know is not available at all, and says so.
        executor_on_path = executor in _IN_PROCESS_EXECUTORS

    keys["executor"] = executor
    keys["executor_on_path"] = executor_on_path
    return keys


if __name__ == "__main__":  # pragma: no cover -- exercised via __main__.py instead
    sys.exit(main())
