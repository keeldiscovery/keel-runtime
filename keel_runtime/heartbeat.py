"""Local liveness heartbeat for a running `keel connect` process (spec 021).

One file per `$KEEL_HOME`, `runtime.heartbeat.json` (sibling of `credentials.json`/
`config.json`), holding only the current state -- no history, overwritten in place on
every write. Written atomically (temp file in the same directory, then `os.replace`,
research.md §2) so a reader never observes a partial write. `read()` never raises to
its caller: a missing file, unreadable/malformed JSON, or a file missing a required
key is all treated identically to "no heartbeat" (data-model.md's validation rule,
spec Acceptance Scenario 6) -- this module only ever answers with a `Heartbeat` or
`None`.
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

HEARTBEAT_FILENAME = "runtime.heartbeat.json"

_REQUIRED_FIELDS = ("pid", "agent_session_id", "base_url", "last_heartbeat_at")

# `state` (keel-cloud DRIFT #51 / `canon/designs/keel-disconnect-design.md` §6, edge case (g)):
# a runtime blocked in device authorization has a pid and a home but no agent session yet. It is
# written by `write_awaiting_approval` and overwritten with `STATE_CONNECTED` the moment the real
# heartbeat exists (`agent_session.create_agent_session`, `poller._write_heartbeat`). A file with
# no `state` key at all -- every heartbeat this runtime ever wrote before this change -- is
# `STATE_CONNECTED`: it could only have been written *after* an agent session existed.
STATE_CONNECTED = "connected"
STATE_AWAITING_APPROVAL = "awaiting_approval"


@dataclass
class Heartbeat:
    pid: int
    agent_session_id: Optional[str]
    base_url: str
    last_heartbeat_at: str
    state: str = STATE_CONNECTED


def path(home: Path) -> Path:
    return Path(home) / HEARTBEAT_FILENAME


def write(home: Path, heartbeat: Heartbeat) -> None:
    """Atomic write: a `.tmp` file in the same directory, then `os.replace` (research.md
    §2) -- keeps the rename on the same filesystem, which is what makes it atomic.
    """
    target = path(home)
    tmp_path = target.with_name(target.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(heartbeat)))
    os.replace(tmp_path, target)


def write_awaiting_approval(home: Path, pid: int, base_url: str) -> None:
    """Written the moment `connect` has a pid and a home -- before the device code is even
    requested, let alone redeemed (keel-cloud DRIFT #51: a runtime alive and waiting for device
    approval was invisible to both `status` and `disconnect`, because the only heartbeat write
    used to happen after the agent session existed).

    Carries no `agent_session_id` -- none exists yet -- and `state=STATE_AWAITING_APPROVAL`, so
    `disconnect` (which only ever reads `pid`) finds and stops this process at any point in its
    life, and `status` can say "running, not yet connected" without claiming `connected: true`
    of a session that does not exist. `agent_session.create_agent_session` overwrites this same
    file with the real heartbeat -- `state=STATE_CONNECTED` -- the moment the agent session is
    created, exactly as it already overwrites whatever the previous run left behind.

    The caller (`auth.authorize_device`) also calls this once per poll tick while it waits, so a
    founder who takes minutes to click approve does not watch this record go stale.
    """
    write(
        home,
        Heartbeat(
            pid=pid,
            agent_session_id=None,
            base_url=base_url,
            last_heartbeat_at=now_iso8601(),
            state=STATE_AWAITING_APPROVAL,
        ),
    )


def read(home: Path) -> Optional[Heartbeat]:
    """Returns `None` on a missing file, unreadable/malformed JSON, or JSON missing any
    required field -- never raises (data-model.md's validation rule).
    """
    try:
        with open(path(home), "r", encoding="utf-8") as handle:
            raw = handle.read()
    except OSError:
        return None

    try:
        data = json.loads(raw)
    except ValueError:
        return None

    if not isinstance(data, dict) or any(field not in data for field in _REQUIRED_FIELDS):
        return None

    raw_agent_session_id = data["agent_session_id"]
    raw_state = data.get("state")
    try:
        return Heartbeat(
            pid=int(data["pid"]),
            agent_session_id=(
                None if raw_agent_session_id is None else str(raw_agent_session_id)
            ),
            base_url=str(data["base_url"]),
            last_heartbeat_at=str(data["last_heartbeat_at"]),
            state=str(raw_state) if raw_state is not None else STATE_CONNECTED,
        )
    except (TypeError, ValueError):
        return None


def remove(home: Path) -> None:
    """Deletes the heartbeat file; idempotent -- swallows `FileNotFoundError`."""
    try:
        path(home).unlink()
    except FileNotFoundError:
        pass


def pid_alive(pid: int) -> bool:
    """POSIX (macOS/Linux): `os.kill(pid, 0)` -- `ProcessLookupError` => False,
    `PermissionError` => True (a pid we can't signal still exists). Windows:
    `ctypes`/`OpenProcess`, since `os.kill(pid, 0)` is not the same signal-0 probe there
    (research.md §3; no `psutil` dependency, matching spec 020 FR-025's stdlib-only
    posture).
    """
    if sys.platform == "win32":
        return _pid_alive_windows(pid)  # pragma: no cover -- exercised on Windows only
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _pid_alive_windows(pid: int) -> bool:  # pragma: no cover -- exercised on Windows only
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
        PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
    return True


def is_stale(
    heartbeat: Heartbeat, stale_after_seconds: float, now: Optional[datetime] = None
) -> bool:
    """True when `heartbeat.last_heartbeat_at`'s age exceeds `stale_after_seconds`.

    An unparseable timestamp is treated as stale -- there is no fresher answer to give.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        written_at = _parse_iso8601(heartbeat.last_heartbeat_at)
    except ValueError:
        return True
    age_seconds = (now - written_at).total_seconds()
    return age_seconds > stale_after_seconds


def now_iso8601() -> str:
    """The current UTC time in the format this module writes/reads: millisecond
    precision, `Z` suffix (e.g. `2026-09-02T13:04:11.482Z`).
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _parse_iso8601(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
