"""``ProcessRunner`` on ``subprocess.Popen``; the whole process tree is stopped, not just the child."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..ports import ProcessHandle
from .terminate import Terminate, proclaunch_terminate

__all__ = ["SubprocessRunner"]

_STOP_TIMEOUT_SECONDS = 5.0


class _Process:
    """Implements ProcessHandle. Kills the whole tree: npx, uv and pnpm all spawn children."""

    def __init__(self, popen: subprocess.Popen[bytes], terminate: Terminate) -> None:
        self._popen = popen
        self._terminate = terminate

    def poll(self) -> int | None:
        return self._popen.poll()

    def stop(self) -> None:
        # The terminator knows each OS: gentle first, then force. Even after the child exited, its group
        # can still hold grandchildren (POSIX), so it is asked unconditionally.
        self._terminate(self._popen.pid, _STOP_TIMEOUT_SECONDS)
        try:
            self._popen.wait(timeout=_STOP_TIMEOUT_SECONDS)  # reap it
        except subprocess.TimeoutExpired:
            pass


class SubprocessRunner:
    """Starts each service as the leader of its own process group (POSIX) so its tree can be taken down.

    ``cwd`` is the default working directory; a service's own ``cwd``, if relative, is taken from it.
    ``terminate`` defaults to proclaunch's ``terminate_process`` (extra ``stackrun[proclaunch]``), imported on
    first use.
    """

    def __init__(self, cwd: Path | None = None, terminate: Terminate | None = None) -> None:
        self._cwd = cwd
        self._terminate = terminate or proclaunch_terminate

    def start(self, argv: Sequence[str], env: Mapping[str, str], cwd: str | None = None) -> ProcessHandle:
        where: Path | None = self._cwd
        if cwd is not None:
            where = self._cwd / cwd if self._cwd is not None else Path(cwd)
        # start_new_session makes the child its own process-group leader on POSIX (what lets the terminator
        # take its whole group down); Python ignores it on Windows.
        popen = subprocess.Popen(list(argv), cwd=where, env=dict(env), start_new_session=True)
        return _Process(popen, self._terminate)
