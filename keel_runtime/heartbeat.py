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


@dataclass
class Heartbeat:
    pid: int
    agent_session_id: str
    base_url: str
    last_heartbeat_at: str


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

    try:
        return Heartbeat(
            pid=int(data["pid"]),
            agent_session_id=str(data["agent_session_id"]),
            base_url=str(data["base_url"]),
            last_heartbeat_at=str(data["last_heartbeat_at"]),
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
