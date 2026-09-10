"""Installs a fake host CLI (`claude`, `copilot`) on `PATH` for a test's own `bin_dir`.

Shared by `test_executor.py` and `test_copilot_executor.py`, which each write a small Python
script recording every invocation and replaying a queued response -- the shape is identical,
only the resolution differs by platform.

On macOS/Linux, `shutil.which`/`subprocess.run` resolve a plain extensionless file as long as
it is executable and its shebang names an interpreter, so the script is written straight to
`bin_dir/<name>` and marked `+x`.

On Windows there is no shebang and no executable bit: `shutil.which` (and the `CreateProcess`
call underneath `subprocess.run`) only resolves a name against `PATHEXT` -- `.EXE`, `.CMD`,
`.BAT`, ... -- so a bare `bin_dir/claude` is invisible to both, and the executor raises
`ExecutorUnavailable: 'claude' executable not found on PATH` before the fake ever runs. The fix
used here is the standard one for a Python-backed CLI shim on Windows: the real script is written
as `bin_dir/<name>.py`, and `bin_dir/<name>.cmd` -- resolved by `PATHEXT`, and itself one of the
extensions `CreateProcess` natively hands off to `cmd.exe` even without `shell=True` -- forwards
argv (`%*`) and the inherited stdin/stdout/stderr straight to `sys.executable` running it.
"""
from __future__ import annotations

import stat
import sys
from pathlib import Path


def install_fake_cli(bin_dir: Path, name: str, source: str) -> None:
    """Writes a fake `name` CLI into `bin_dir`, resolvable by `shutil.which(name)` and runnable
    by `subprocess.run([name, ...])` on this platform.
    """
    if sys.platform == "win32":
        impl = bin_dir / f"{name}.py"
        impl.write_text(source, encoding="utf-8")
        shim = bin_dir / f"{name}.cmd"
        shim.write_text(
            f'@echo off\r\n"{sys.executable}" "%~dp0{name}.py" %*\r\n',
            encoding="utf-8",
        )
    else:
        script = bin_dir / name
        script.write_text(source)
        script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
