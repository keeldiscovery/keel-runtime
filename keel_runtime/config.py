"""Runtime configuration: precedence CLI flags > env vars > $KEEL_HOME/config.json.

Standard library only (spec FR-025). The home decides where the file-backed config, the
credential store and the heartbeat live -- and since spec `004-shipped-runtime` (design
`keel-skill-design.md` §6.3) **the home follows the address**: with no `KEEL_HOME` and no
`--home`, it is `~/.keel/<host-slug>/`, derived from the resolved base URL, so a credential
issued by one Keel is never presented to another (E-1). `KEEL_HOME`/`--home` still win
outright and are the one way to make two Keels share a home.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlsplit

from .cloud_client import DEFAULT_POLL_WINDOW_SECONDS, POLL_TIMEOUT_MARGIN_SECONDS

# The root every derived home hangs under, and the home itself when nothing resolves at all
# (§6.3: "the home falls back to today's `~/.keel` and `environment` is null"). Kept as a module
# constant because `executor.py` imports it for its per-job directory fallback; every resolution
# in this module calls `_default_home_root()` instead, so a test may point `HOME` at a temporary
# directory and see it.
DEFAULT_HOME = Path.home() / ".keel"

# The address a founder reaches with no configuration of any kind (design §6.2, decision 12).
# **This value is a placeholder and is deliberately empty.** keel-cloud's own AWS deployment has
# no hostname yet, so there is nothing true to put here; filling this constant in is the whole of
# **step 8** of the design's implementation order, and nothing else in this repository changes when
# it lands. Until then behaviour is exactly today's: `connect` exits with its one-line remedy when
# no other source supplies a base URL, and `status` answers with a null environment.
#
# It is the **last** term of the chain and never outranks `--base-url`, `KEEL_BASE_URL` or
# `$KEEL_HOME/config.json` (E-2). When it does have a value it is used *instead of* exiting -- that
# is what makes cloud the default a fresh install reaches with zero configuration.
CLOUD_BASE_URL = ""

# `~/.keel/bin/` is Keel's own. A Keel whose host would slug to a reserved name gets a different
# directory, so `ls ~/.keel/` shows host slugs and nothing else (design §10.4).
RESERVED_HOME_NAMES = frozenset({"bin"})
_RESERVED_SUFFIX = "-keel"

# Everything outside this class is replaced with `-` before a slug reaches the filesystem (§6.3).
_UNSAFE_SLUG_CHARACTERS = re.compile(r"[^a-z0-9.-]")

DEFAULT_EXECUTOR = "claude-code"

# Env var names (spec FR-026): "flags > env (KEEL_BASE_URL, KEEL_EXECUTOR, KEEL_HOME,
# KEEL_CREDENTIAL_BACKEND) > $KEEL_HOME/config.json".
ENV_BASE_URL = "KEEL_BASE_URL"
ENV_EXECUTOR = "KEEL_EXECUTOR"
ENV_HOME = "KEEL_HOME"
ENV_CREDENTIAL_BACKEND = "KEEL_CREDENTIAL_BACKEND"
# spec 001-scripted-executor FR-002: only meaningful with `--executor scripted`; same
# flag > env > `$KEEL_HOME/config.json` precedence as every other key.
ENV_SCRIPT = "KEEL_SCRIPT"
# spec 001-scripted-executor AMENDMENT-measured-beliefs RT-001: where the scripted
# executor's screen-inference table is loaded from -- keel-cloud's own
# `screenContracts export` writes it as `context-keys.json`. Same flag > env >
# `$KEEL_HOME/config.json` precedence; falling back to the copy bundled in
# `keel_runtime/testing/contracts/` when nothing sets it.
ENV_CONTEXT_KEYS = "KEEL_CONTEXT_KEYS"

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
    context_keys_path: str | None
    job_budget_usd: float
    job_max_turns: int
    job_timeout_seconds: float

    @property
    def environment(self) -> Optional[str]:
        """*Which Keel* this run is talking to (§6.3) -- derived, never stored, so it is true of
        whatever URL actually resolved."""
        return environment_for(self.base_url)


@dataclass
class StatusConfig:
    """The lighter-weight resolution `status` needs (contracts/status-cli-output.md).

    It carries `base_url` and `executor` since spec `004-shipped-runtime` (FR-009), because
    `status` now reports `base_url`, `environment`, `executor` and `executor_on_path` in both
    shapes -- but it still has no base-URL *requirement*: `status` must answer, and exit 0, even
    when no runtime has ever connected from this home and nothing names a Keel at all (spec 021
    Acceptance Scenario 1, R-4).
    """

    home: Path
    heartbeat_stale_after: float
    base_url: Optional[str] = None
    executor: str = DEFAULT_EXECUTOR

    @property
    def environment(self) -> Optional[str]:
        return environment_for(self.base_url)


def _default_home_root() -> Path:
    """`~/.keel`, resolved now rather than at import time (see DEFAULT_HOME's comment)."""
    return Path.home() / ".keel"


def _split_address(base_url) -> Optional[Tuple[str, Optional[int]]]:
    """The resolved base URL's `(host, port)`, or `None` when it names no address.

    No scheme, no userinfo, no path (§6.3) -- two base URLs differing only by scheme are one Keel
    with a misconfiguration, not two. A value with no scheme at all (`localhost:18081`) is read as
    a bare `host[:port]`, because that is what a human who typed it meant; a value with a scheme
    and no host (`http://`) names no address and gets `None`.
    """
    value = (base_url or "").strip()
    if not value:
        return None

    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
    except ValueError:
        # An unparseable authority (a malformed port, an unclosed IPv6 bracket) is not fatal
        # anywhere: resolution falls back to the root home and a null environment.
        return None

    if host:
        if not host.strip(".-"):
            return None  # `.` and `..` are legal hosts to nobody and directory names to no one
        return host.lower(), port

    if parts.scheme and "//" in value:
        return None

    bare = value.split("/", 1)[0]
    if not bare.strip(".-"):
        return None
    host_part, separator, port_part = bare.rpartition(":")
    if separator and port_part.isdigit() and host_part:
        return host_part.lower(), int(port_part)
    return bare.lower(), None


def host_slug(base_url) -> Optional[str]:
    """The directory name one Keel gets under `~/.keel/` (§6.3).

    The host lowercased, joined to the port with `-` when the URL states one, every character
    outside `[a-z0-9.-]` replaced with `-`. `None` when nothing but dots and dashes survives --
    a slug of `.` or `..` is the one thing this must never hand to the filesystem.
    """
    address = _split_address(base_url)
    if address is None:
        return None
    host, port = address
    raw = host if port is None else "{}-{}".format(host, port)
    slug = _UNSAFE_SLUG_CHARACTERS.sub("-", raw.lower())
    if not slug.strip(".-"):
        return None
    if slug in RESERVED_HOME_NAMES:
        return slug + _RESERVED_SUFFIX
    return slug


def derive_home(base_url) -> Optional[Path]:
    """`~/.keel/<host-slug>/` for a base URL that names an address; `None` otherwise."""
    slug = host_slug(base_url)
    if slug is None:
        return None
    return _default_home_root() / slug


def environment_for(base_url) -> Optional[str]:
    """*Which Keel*, named by its address (§6.3, §7): `"cloud"` for the built-in default,
    `host:port` for anything else, `None` when no base URL resolved at all. An address, not a
    host in the design's sense (D5), and never a named profile -- there is no `KEEL_ENV`.
    """
    value = (base_url or "").strip()
    if not value:
        return None
    if CLOUD_BASE_URL and value == CLOUD_BASE_URL.strip():
        return "cloud"
    address = _split_address(value)
    if address is None:
        return None
    host, port = address
    if ":" in host:  # an IPv6 literal keeps its brackets, as it is written in a URL
        host = "[{}]".format(host)
    return host if port is None else "{}:{}".format(host, port)


def _resolve_home_and_base_url(args) -> Tuple[Path, dict, Optional[str]]:
    """The home, its file config, and the resolved base URL -- in that order, because the home
    decides where the file is and the file may name the base URL (spec 004 FR-007).

    Two phases, so that a file can never contradict the directory it sits in:

    1. `--home`/`KEEL_HOME` set -> that home, and its `config.json` takes part in the base-URL
       chain exactly as it does today;
    2. else a base URL from `--base-url`/`KEEL_BASE_URL`/`CLOUD_BASE_URL` -> `~/.keel/<slug>/`,
       whose `config.json` supplies every key **except** `base_url`: a derived home's file may not
       rename the Keel that named it;
    3. else nothing resolved -> `~/.keel`, whose `config.json` may still supply `base_url` (today's
       behaviour, and the only branch that can now reach it).

    Never raises: `status` must answer in every one of these cases (R-4).
    """
    flag_home = getattr(args, "home", None) or os.environ.get(ENV_HOME)
    if flag_home:
        home = Path(flag_home).expanduser()
        file_config = _load_file_config(home)
        base_url = (
            getattr(args, "base_url", None)
            or os.environ.get(ENV_BASE_URL)
            or file_config.get("base_url")
            or CLOUD_BASE_URL
            or None
        )
        return home, file_config, base_url

    named_base_url = (
        getattr(args, "base_url", None)
        or os.environ.get(ENV_BASE_URL)
        or CLOUD_BASE_URL
        or None
    )
    if named_base_url:
        home = derive_home(named_base_url) or _default_home_root()
        return home, _load_file_config(home), named_base_url

    home = _default_home_root()
    file_config = _load_file_config(home)
    return home, file_config, file_config.get("base_url") or None


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
    home, file_config, base_url = _resolve_home_and_base_url(args)
    heartbeat_stale_after = _resolve_heartbeat_stale_after(args, file_config)
    executor = (
        getattr(args, "executor", None)
        or os.environ.get(ENV_EXECUTOR)
        or file_config.get("executor")
        or DEFAULT_EXECUTOR
    )
    return StatusConfig(
        home=home,
        heartbeat_stale_after=heartbeat_stale_after,
        base_url=base_url,
        executor=executor,
    )


def load(args) -> RuntimeConfig:
    """Build a RuntimeConfig from parsed CLI args, env vars, and the on-disk config file.

    Exits with a one-line remedy (spec FR-026) when no source supplies `base_url`.
    """
    home, file_config, base_url = _resolve_home_and_base_url(args)

    if not base_url:
        # Reachable only while `CLOUD_BASE_URL` is still the empty placeholder (E-2): a source
        # tree before step 8, with nothing else configured. The remedy is the one it always was.
        raise SystemExit(
            "keel connect: no base URL configured -- pass --base-url, set "
            f"{ENV_BASE_URL}, or add \"base_url\" to {home / 'config.json'}"
        )

    executor = (
        getattr(args, "executor", None)
        or os.environ.get(ENV_EXECUTOR)
        or file_config.get("executor")
        or DEFAULT_EXECUTOR
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

    context_keys_path = (
        getattr(args, "context_keys", None)
        or os.environ.get(ENV_CONTEXT_KEYS)
        or file_config.get("context_keys")
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
        context_keys_path=context_keys_path,
        job_budget_usd=job_budget_usd,
        job_max_turns=job_max_turns,
        job_timeout_seconds=job_timeout_seconds,
    )
