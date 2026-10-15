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

import os
import signal
import subprocess
import sys
import time

import psutil

_ON_WINDOWS = sys.platform == "win32"
_POLL_SECONDS = 0.05
_KILL_WAIT_SECONDS = 1.0


def _alive(process: psutil.Process) -> bool:
    """Running and not a zombie. A process that cannot be inspected is assumed alive: it is not proven gone."""
    try:
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:
        return True


def _descendants(pid: int) -> list[psutil.Process]:
    try:
        return psutil.Process(pid).children(recursive=True)
    except psutil.Error:
        return []


def _signal(process: psutil.Process, *, force: bool) -> None:
    """A process that is gone is fine; one that may not be signalled stays alive and is reported by the caller."""
    try:
        process.kill() if force else process.terminate()
    except psutil.Error:
        pass


def _group_members(pgid: int) -> list[int]:
    try:
        os.killpg(pgid, 0)  # one syscall: is there any process (zombies included) in the group?
    except ProcessLookupError:
        return []
    except PermissionError:
        pass  # exists, but not all of it is ours to signal: enumerate
    members = []
    for process in psutil.process_iter(["pid", "status"]):
        if process.info["status"] == psutil.STATUS_ZOMBIE:
            continue
        try:
            if os.getpgid(process.info["pid"]) == pgid:
                members.append(process.info["pid"])
        except (OSError, psutil.Error):
            continue
    return members


def _killpg(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass  # gone, or not ours to signal: the membership check afterwards reports what is left


def _wait_group_gone(pgid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        if not _group_members(pgid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(_POLL_SECONDS)


def _stop_group(pgid: int, timeout: float) -> bool:
    if not _group_members(pgid):
        return True
    _killpg(pgid, signal.SIGTERM)
    if _wait_group_gone(pgid, timeout):
        return True
    _killpg(pgid, signal.SIGKILL)
    return _wait_group_gone(pgid, _KILL_WAIT_SECONDS)


def _stop_processes(processes: list[psutil.Process], timeout: float) -> bool:
    """Terminate, then kill, *processes* (none of them our own child, so psutil may wait on them)."""
    left = [p for p in processes if _alive(p)]
    if not left:
        return True
    for process in reversed(left):
        _signal(process, force=False)
    _, alive = psutil.wait_procs(left, timeout=timeout)
    for process in alive:
        _signal(process, force=True)
    _, alive = psutil.wait_procs(alive, timeout=_KILL_WAIT_SECONDS)
    return not any(_alive(p) for p in alive)


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
    known = _descendants(proc.pid) if running else []

    if own_group and not _ON_WINDOWS and running:
        # Only while the leader is unreaped: its pid (the group id) cannot have been recycled for another group.
        stopped = _stop_group(proc.pid, timeout)
        leader_gone = _reap(proc, _KILL_WAIT_SECONDS)
    elif running:
        try:
            leader = psutil.Process(proc.pid)
        except psutil.NoSuchProcess:
            leader = None
        everyone = [*known, *([leader] if leader is not None else [])]
        for process in reversed(everyone):
            _signal(process, force=False)
        leader_gone = _reap(proc, timeout)
        if not leader_gone:
            if leader is not None:
                _signal(leader, force=True)
            leader_gone = _reap(proc, _KILL_WAIT_SECONDS)
        stopped = True  # the descendants are checked by the sweep below
    else:
        stopped = leader_gone = True

    swept = _stop_processes(known, max(0.5, deadline - time.monotonic()))
    return stopped and leader_gone and swept
