"""``Processes`` on psutil (identity) and proclaunch (termination)."""

from __future__ import annotations

import os

from ..domain import Identity
from .terminate import Terminate, proclaunch_terminate

__all__ = ["PsutilProcesses"]

_STOP_TIMEOUT_SECONDS = 5.0


class PsutilProcesses:
    """Process identity (pid + start time) through psutil (extra ``stackrun[psutil]``), and shutdown through
    ``terminate`` (default: proclaunch, extra ``stackrun[proclaunch]``). Both are imported on first use.

    A pid alone is not an identity: after a launcher dies the OS may give its pid to an unrelated
    program. Checking the start time as well means we never stop the wrong thing.
    """

    _START_TOLERANCE = 1.0  # seconds; a process's start time does not change, this absorbs rounding

    def __init__(self, terminate: Terminate | None = None) -> None:
        try:
            import psutil
        except ImportError as exc:  # pragma: no cover - depends on the install
            raise ImportError("stackrun's process identity needs psutil: pip install 'stackrun[psutil]'") from exc
        self._psutil = psutil
        self._terminate = terminate or proclaunch_terminate

    def current(self) -> Identity:
        return Identity(os.getpid(), self._psutil.Process().create_time())

    def is_alive(self, identity: Identity) -> bool:
        psutil = self._psutil
        try:
            process = psutil.Process(identity.pid)
            return (
                abs(process.create_time() - identity.started) < self._START_TOLERANCE
                and process.status() != psutil.STATUS_ZOMBIE
            )
        except psutil.Error:
            return False

    def stop(self, identity: Identity) -> None:
        if self.is_alive(identity):
            self._terminate(identity.pid, _STOP_TIMEOUT_SECONDS)
