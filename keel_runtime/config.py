"""Runtime configuration: precedence CLI flags > env vars > $KEEL_HOME/config.json.

Standard library only (spec FR-025). `KEEL_HOME` (env, default `~/.keel`) decides where
the file-backed config and, later, the credential store live -- it is resolved first,
independently of the other keys, since the config file's own location depends on it.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .cloud_client import DEFAULT_POLL_WINDOW_SECONDS, POLL_TIMEOUT_MARGIN_SECONDS

DEFAULT_HOME = Path.home() / ".keel"

# Env var names (spec FR-026): "flags > env (KEEL_BASE_URL, KEEL_EXECUTOR, KEEL_HOME,
# KEEL_CREDENTIAL_BACKEND) > $KEEL_HOME/config.json".
ENV_BASE_URL = "KEEL_BASE_URL"
ENV_EXECUTOR = "KEEL_EXECUTOR"
ENV_HOME = "KEEL_HOME"
ENV_CREDENTIAL_BACKEND = "KEEL_CREDENTIAL_BACKEND"
# spec 001-scripted-executor FR-002: only meaningful with `--executor scripted`; same
# flag > env > `$KEEL_HOME/config.json` precedence as every other key.
ENV_SCRIPT = "KEEL_SCRIPT"

# spec 021 FR-006: a runtime that is merely waiting on a slow long-poll must never be
# mistaken for dead -- the default is one full poll cycle's worst case (the long-poll
# window plus the client's own timeout margin, cloud_client.py) plus 15s of slack for
# job execution/validation/complete round-trip time (research.md §4). With spec 020's
# defaults (25s window, 10s margin) this is 50s.
ENV_HEARTBEAT_STALE_AFTER = "KEEL_HEARTBEAT_STALE_AFTER"
DEFAULT_HEARTBEAT_STALE_AFTER = DEFAULT_POLL_WINDOW_SECONDS + POLL_TIMEOUT_MARGIN_SECONDS + 15.0

# spec 002-words-are-words FR-007, amended by FR-009 (2026-09-04, the founder's live
# run): the per-job cap the closed `claude` invocation is given (`--max-budget-usd`,
# `--max-turns` in executor.py's `ClaudeCodeExecutor`) -- generous for one answer, small
# for a runaway tool loop or an attacker-lengthened conversation. Same flag > env >
# `$KEEL_HOME/config.json` precedence as every other key. The original 0.25/2 stopped
# two real jobs in a row; a legitimate breakdown job spends around $0.25 and three to
# five turns, so the defaults now leave headroom for a retry within the cap.
ENV_JOB_BUDGET_USD = "KEEL_JOB_BUDGET_USD"
DEFAULT_JOB_BUDGET_USD = 1.00
ENV_JOB_MAX_TURNS = "KEEL_JOB_MAX_TURNS"
DEFAULT_JOB_MAX_TURNS = 6

# The wall clock one closed `claude` invocation is given before the runtime gives up on
# it (`ClaudeCodeExecutor.timeout_seconds`). It sat hard-coded at 120s beside the two
# caps above until keel-e2e-eval's instruction eval measured what a real breakdown job
# actually costs in seconds: the 21 `*_ASSUMPTIONS` jobs of run
# `20260906T170528Z-instructions-baseline` ran 81-120s, six of them hit the limit, and
# the slowest survivor finished with eleven seconds to spare. The whole distribution sat
# against the number, and keel-cloud spec 029 makes those instructions longer, not
# shorter. 300s is chosen to be clear of the measured spread rather than round -- and it
# is a *ceiling on a stuck job*, not a target: a healthy job still answers in about 90.
ENV_JOB_TIMEOUT_SECONDS = "KEEL_JOB_TIMEOUT_SECONDS"
DEFAULT_JOB_TIMEOUT_SECONDS = 300.0


@dataclass
class RuntimeConfig:
    base_url: str
    executor: str
    home: Path
    credential_backend: str
    open_browser: bool
    heartbeat_stale_after: float
    script_path: str | None
    job_budget_usd: float
    job_max_turns: int
    job_timeout_seconds: float


@dataclass
class StatusConfig:
    """The lighter-weight resolution `status` needs (contracts/status-cli-output.md):
    just `home` and the staleness threshold -- no `base_url` requirement, since
    `status` must answer even when no runtime has ever connected from this
    `$KEEL_HOME` (spec Acceptance Scenario 1).
    """

    home: Path
    heartbeat_stale_after: float


def _resolve_home(args) -> Path:
    flag_home = getattr(args, "home", None)
    if flag_home:
        return Path(flag_home).expanduser()
    env_home = os.environ.get(ENV_HOME)
    if env_home:
        return Path(env_home).expanduser()
    return DEFAULT_HOME


def _load_file_config(home: Path) -> dict:
    config_path = home / "config.json"
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        # A malformed or unreadable config file is not fatal -- flags/env can still
        # supply everything needed, and a missing base_url is reported on its own below.
        return {}
    return data if isinstance(data, dict) else {}


def _resolve_heartbeat_stale_after(args, file_config: dict) -> float:
    flag_value = getattr(args, "heartbeat_stale_after", None)
    if flag_value is not None:
        return float(flag_value)

    env_value = os.environ.get(ENV_HEARTBEAT_STALE_AFTER)
    if env_value:
        try:
            return float(env_value)
        except ValueError:
            pass  # an unparseable override is not fatal -- fall through to file/default

    file_value = file_config.get("heartbeat_stale_after")
    if file_value is not None:
        try:
            return float(file_value)
        except (TypeError, ValueError):
            pass

    return DEFAULT_HEARTBEAT_STALE_AFTER


def _resolve_job_budget_usd(args, file_config: dict) -> float:
    flag_value = getattr(args, "job_budget_usd", None)
    if flag_value is not None:
        return float(flag_value)

    env_value = os.environ.get(ENV_JOB_BUDGET_USD)
    if env_value:
        try:
            return float(env_value)
        except ValueError:
            pass  # an unparseable override is not fatal -- fall through to file/default

    file_value = file_config.get("budget_usd")
    if file_value is not None:
        try:
            return float(file_value)
        except (TypeError, ValueError):
            pass

    return DEFAULT_JOB_BUDGET_USD


def _resolve_job_max_turns(args, file_config: dict) -> int:
    flag_value = getattr(args, "job_max_turns", None)
    if flag_value is not None:
        return int(flag_value)

    env_value = os.environ.get(ENV_JOB_MAX_TURNS)
    if env_value:
        try:
            return int(env_value)
        except ValueError:
            pass  # an unparseable override is not fatal -- fall through to file/default

    file_value = file_config.get("max_turns")
    if file_value is not None:
        try:
            return int(file_value)
        except (TypeError, ValueError):
            pass

    return DEFAULT_JOB_MAX_TURNS


def _resolve_job_timeout_seconds(args, file_config: dict) -> float:
    flag_value = getattr(args, "job_timeout_seconds", None)
    if flag_value is not None:
        return float(flag_value)

    env_value = os.environ.get(ENV_JOB_TIMEOUT_SECONDS)
    if env_value:
        try:
            return float(env_value)
        except ValueError:
            pass  # an unparseable override is not fatal -- fall through to file/default

    file_value = file_config.get("job_timeout_seconds")
    if file_value is not None:
        try:
            return float(file_value)
        except (TypeError, ValueError):
            pass

    return DEFAULT_JOB_TIMEOUT_SECONDS


def load_status_config(args) -> StatusConfig:
    """Resolves just what `status` needs -- `home` and `heartbeat_stale_after` -- with
    the same flag > env > `$KEEL_HOME/config.json` precedence as every other key, but
    without `load()`'s `base_url` requirement (`status` must never exit for a missing
    `base_url`; it has no use for one).
    """
    home = _resolve_home(args)
    file_config = _load_file_config(home)
    heartbeat_stale_after = _resolve_heartbeat_stale_after(args, file_config)
    return StatusConfig(home=home, heartbeat_stale_after=heartbeat_stale_after)


def load(args) -> RuntimeConfig:
    """Build a RuntimeConfig from parsed CLI args, env vars, and the on-disk config file.

    Exits with a one-line remedy (spec FR-026) when no source supplies `base_url`.
    """
    home = _resolve_home(args)
    file_config = _load_file_config(home)

    base_url = (
        getattr(args, "base_url", None)
        or os.environ.get(ENV_BASE_URL)
        or file_config.get("base_url")
    )
    if not base_url:
        raise SystemExit(
            "keel connect: no base URL configured -- pass --base-url, set "
            f"{ENV_BASE_URL}, or add \"base_url\" to {home / 'config.json'}"
        )

    executor = (
        getattr(args, "executor", None)
        or os.environ.get(ENV_EXECUTOR)
        or file_config.get("executor")
        or "claude-code"
    )

    credential_backend = (
        getattr(args, "credential_backend", None)
        or os.environ.get(ENV_CREDENTIAL_BACKEND)
        or file_config.get("credential_backend")
        or "auto"
    )

    open_browser = True
    if getattr(args, "no_browser", False):
        open_browser = False
    elif file_config.get("open_browser") is False:
        open_browser = False

    heartbeat_stale_after = _resolve_heartbeat_stale_after(args, file_config)

    script_path = (
        getattr(args, "script", None)
        or os.environ.get(ENV_SCRIPT)
        or file_config.get("script")
    )

    job_budget_usd = _resolve_job_budget_usd(args, file_config)
    job_max_turns = _resolve_job_max_turns(args, file_config)
    job_timeout_seconds = _resolve_job_timeout_seconds(args, file_config)

    return RuntimeConfig(
        base_url=base_url,
        executor=executor,
        home=home,
        credential_backend=credential_backend,
        open_browser=open_browser,
        heartbeat_stale_after=heartbeat_stale_after,
        script_path=script_path,
        job_budget_usd=job_budget_usd,
        job_max_turns=job_max_turns,
        job_timeout_seconds=job_timeout_seconds,
    )
