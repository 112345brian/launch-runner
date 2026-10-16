"""Stop a child this library started, and everything it started.

The runner owns its child: it holds the ``Popen`` for the whole run, so the pid cannot be someone else's while
the child is unreaped, and no identity record is needed (the long-lived services of ``proclaunch`` are the case
that needs one). What is needed is an honest answer to "is anything of it left?":

- A child started as the leader of its own process group (``adapters.process_group``) is stopped by signalling
  that group, which reaches descendants that were orphaned before the deadline. The group id stays reserved
  while any member lives, so signalling it after the leader exited cannot hit an unrelated process.
- A child that shares the caller's group (a console-attached run, and Windows) is stopped by walking its
  descendants, which cannot see an orphan; that limit is part of the contract.
- The descendants that can be found are snapshotted *before* anything is signalled, because they are
  re-parented once the child dies. Whatever of that snapshot outlives the group/tree stop (a descendant that
  started its own session) is stopped too, and counted: the result is True only when none of it remains.
  ``psutil.Process`` keeps the creation time it was built with, so a reused pid is never taken for a member.

Termination is graceful first (SIGTERM / ``terminate``), then forced after ``timeout``. Never raises.
"""
from __future__ import annotations

import subprocess
import sys
import time

import psutil

from lifecycle_runner._vendor import proctree

_ON_WINDOWS = sys.platform == "win32"
_KILL_WAIT_SECONDS = proctree.KILL_WAIT_SECONDS


def _reap(proc: subprocess.Popen, seconds: float) -> bool:
    try:
        proc.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        pass
    return proc.poll() is not None


def terminate_tree(proc: subprocess.Popen, *, own_group: bool, timeout: float = 5.0) -> bool:
    """Stop *proc* and its descendants; True only when nothing of what could be found remains. Never raises.

    *own_group*: the child was started as the leader of a new process group (POSIX), so the group is signalled.
    """
    try:
        return _terminate(proc, own_group, timeout)
    except Exception:  # noqa: BLE001 -- the port promises kill never raises
        return False


def _terminate(proc: subprocess.Popen, own_group: bool, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    running = proc.poll() is None
    known = proctree.descendants(proc.pid) if running else []

    if own_group and not _ON_WINDOWS and running:
        # Only while the leader is unreaped: its pid (the group id) cannot have been recycled for another group.
        stopped = proctree.stop_group(proc.pid, timeout)
        leader_gone = _reap(proc, _KILL_WAIT_SECONDS)
    elif running:
        try:
            leader = psutil.Process(proc.pid)
        except psutil.NoSuchProcess:
            leader = None
        everyone = [*known, *([leader] if leader is not None else [])]
        for process in reversed(everyone):
            proctree.signal_process(process, force=False)
        leader_gone = _reap(proc, timeout)
        if not leader_gone:
            if leader is not None:
                proctree.signal_process(leader, force=True)
            leader_gone = _reap(proc, _KILL_WAIT_SECONDS)
        stopped = True  # the descendants are checked by the sweep below
    else:
        stopped = leader_gone = True

    swept = proctree.stop_processes(known, max(0.5, deadline - time.monotonic()))
    return stopped and leader_gone and swept
