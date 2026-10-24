"""Process-tree termination: delegated to ``proclaunch`` (extra ``stackrun[proclaunch]``), imported lazily."""

from __future__ import annotations

from collections.abc import Callable

__all__ = ["Terminate", "proclaunch_terminate"]

# (pid, timeout seconds) -> True when nothing of the process (group / tree) remains
Terminate = Callable[[int, float], bool]


def proclaunch_terminate(pid: int, timeout: float) -> bool:
    """Gentle first, then force: the process group on POSIX (even after the leader exited), the process tree
    on Windows. This is ``proclaunch.api.terminate_process``."""
    try:
        from proclaunch.api import terminate_process
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise ImportError("stackrun's default process control needs proclaunch: pip install 'stackrun[proclaunch]'") from exc
    return terminate_process(pid, timeout=timeout)
