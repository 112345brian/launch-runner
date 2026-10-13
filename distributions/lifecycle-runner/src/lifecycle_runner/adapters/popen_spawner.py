"""ChildSpawner on ``subprocess.Popen``: foreground, windowless, stdio to the log.

The log is the child's own stdout/stderr handle, so the OS writes to it as the
child produces output: nothing is buffered here and nothing is lost if this
process dies. The handle stays open here until the child is known to be gone.

``RunSpec.inherit_stdio`` attaches the child to the caller's own console instead (a terminal
passthrough). That only works when the caller *has* a console; a caller without one (the tracker under
pythonw, a scheduled task) would make the child allocate and show its own, so there the child is run
windowless with its output discarded.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from typing import IO

from commandport.domain import RunSpec
from proclaunch.api import terminate_process, windowless_creationflags

_TERMINATE_TIMEOUT_SECONDS = 5.0


def _caller_has_console() -> bool:
    """Whether this process is attached to a console a child could inherit."""
    if sys.platform != "win32":
        return sys.stdin is not None and sys.stdin.isatty() or sys.stdout is not None and sys.stdout.isatty()
    try:
        return bool(ctypes.windll.kernel32.GetConsoleWindow())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return False


class PopenChild:
    def __init__(self, proc: subprocess.Popen, log: IO[bytes] | None) -> None:
        self._proc = proc
        self._log = log
        self.pid = proc.pid

    def _close_log(self) -> None:
        log, self._log = self._log, None
        if log is not None:
            log.close()

    def wait(self, timeout: float | None) -> int | None:
        try:
            code = self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
        self._close_log()
        return code

    def kill(self) -> bool:
        try:
            gone = terminate_process(self.pid, timeout=_TERMINATE_TIMEOUT_SECONDS)
            if not gone:
                try:
                    self._proc.kill()
                except OSError:
                    pass
            try:
                self._proc.wait(timeout=1)
                gone = gone or self._proc.poll() is not None
            except subprocess.TimeoutExpired:
                pass
            return gone
        except Exception:  # noqa: BLE001 -- the port promises kill never raises
            return False
        finally:
            self._close_log()


class PopenSpawner:
    def spawn(self, spec: RunSpec) -> PopenChild:
        # Windows' CreateProcess does not apply PATHEXT the way shutil.which does.
        exe = shutil.which(spec.argv[0])
        if exe is None:
            raise FileNotFoundError(f"executable not found: {spec.argv[0]}")
        argv = [exe, *spec.argv[1:]]
        env = {**os.environ, **spec.env} if spec.env else None
        if spec.inherit_stdio and _caller_has_console():
            proc = subprocess.Popen(argv, cwd=spec.cwd, env=env)  # shares the caller's console
            return PopenChild(proc, None)
        log: IO[bytes] | None = None
        try:
            if spec.log_path is not None:
                spec.log_path.parent.mkdir(parents=True, exist_ok=True)
                log = open(spec.log_path, "ab")
            out = log if log is not None else subprocess.DEVNULL
            proc = subprocess.Popen(
                argv, cwd=spec.cwd, env=env,
                stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                creationflags=windowless_creationflags(),
            )
        except BaseException:
            if log is not None:
                log.close()
            raise
        return PopenChild(proc, log)
