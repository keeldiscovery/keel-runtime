"""Command-line entry point: `python3 -m keel_runtime connect` / installed `keel connect`.

`main()` is also the `[project.scripts]` target (`keel = "keel_runtime.cli:main"`), but
this module never assumes it has been installed -- `keel_runtime/__main__.py` calls the
same `main()` so the package runs uninstalled from this directory, which is how the
E2E test launches it (spec FR-024, SC-002).
"""
from __future__ import annotations

import argparse
import json
import signal
import sys

from . import agent_session as agent_session_module
from . import auth as auth_module
from . import config as config_module
from . import heartbeat as heartbeat_module
from .cloud_client import AuthenticationExpired, CloudClient
from .credential_store import CredentialStore
from .executor import get_executor
from .poller import run_loop


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keel", description="Keel local runtime")
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
        "defaults to the bundled payroll-exceptions script)",
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

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "connect":
        return _run_connect(args)
    if args.command == "status":
        return _run_status(args)

    parser.print_help()  # pragma: no cover -- argparse's `required=True` makes this dead
    return 1


def _run_connect(args) -> int:
    config = config_module.load(args)
    config.home.mkdir(parents=True, exist_ok=True)
    _install_heartbeat_shutdown_handlers(config)

    if config.script_path and config.executor != "scripted":
        print(
            f"keel connect: --script is ignored because --executor is '{config.executor}', "
            "not 'scripted'",
            file=sys.stderr,
        )

    executor = get_executor(config.executor, config.script_path)
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
        run_loop(client, state, executor, store, config)
    except KeyboardInterrupt:
        pass
    return 0


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

    print(json.dumps(result))
    return 0


if __name__ == "__main__":  # pragma: no cover -- exercised via __main__.py instead
    sys.exit(main())
