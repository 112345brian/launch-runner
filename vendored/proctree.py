"""Stop processes, and the process groups they lead, and say honestly whether anything is left.

This is the single source of the module that ``lifecycle_runner`` and ``proclaunch`` each vendor into their own
distribution (``lifecycle_runner/_vendor/proctree.py``, ``proclaunch/_vendor/proctree.py``). Edit it here and run
``python tools/sync_vendored.py``; ``tests/test_vendored.py`` fails when a copy differs. It is private to those
two packages: neither exports it, and it imports nothing from either (only the standard library and psutil), so
the two libraries stay independent of each other and of any shared distribution.

What it provides is the mechanism both need; what it does not decide is *whom* to stop. Ownership belongs to the
caller: ``lifecycle_runner`` holds a ``Popen`` for a child it started, ``proclaunch`` checks a recorded pid and
creation time before acting on a service it did not just start.

- ``descendants`` snapshots what can be found now: do it *before* signalling anything, because descendants are
  re-parented once their parent dies. A ``psutil.Process`` keeps the creation time it was built with, so a reused
  pid is never mistaken for a member of a snapshot.
- ``stop_group`` signals a process group (POSIX) and waits until it is empty; it reaches orphans that a walk of
  descendants cannot see. It must only be called with a group id the caller knows is its own (a child it started
  as a group leader, still unreaped, or a recorded identity that still matches).
- ``stop_processes`` terminates, then kills, a list of processes and returns True only when none is left alive.
  It is how a snapshot is swept for what left the group (a new session) or is not in it at all.
- ``alive`` treats a process that cannot be inspected as alive: not proven gone is not gone.

Never raises for a process that is gone or that may not be signalled; such a process is simply still alive in
the answer.
"""
from __future__ import annotations

import os
import signal
import time

import psutil

POLL_SECONDS = 0.05
KILL_WAIT_SECONDS = 1.0


def alive(process: psutil.Process) -> bool:
    """Running and not a zombie. A process that cannot be inspected is assumed alive."""
    try:
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:
        return True


def descendants(pid: int) -> list[psutil.Process]:
    """The descendants of *pid* that can be found now (none if it is gone or cannot be inspected)."""
    try:
        return psutil.Process(pid).children(recursive=True)
    except psutil.Error:
        return []


def signal_process(process: psutil.Process, *, force: bool) -> None:
    """Terminate (or, with *force*, kill) *process*. Gone is fine; a process that may not be signalled stays
    alive and is reported by whoever checks afterwards."""
    try:
        process.kill() if force else process.terminate()
    except psutil.Error:
        pass


def group_members(pgid: int) -> list[int]:
    """Pids of the live (non-zombie) members of process group *pgid* (POSIX)."""
    try:
        os.killpg(pgid, 0)  # one syscall: any process, zombies included, in the group?
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
        pass  # gone, or not ours: the membership check afterwards reports what is left


def _wait_group_gone(pgid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        if not group_members(pgid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_SECONDS)


def stop_group(pgid: int, timeout: float, kill_wait: float = KILL_WAIT_SECONDS) -> bool:
    """SIGTERM the group, wait up to *timeout* for it to empty, then SIGKILL and wait up to *kill_wait*.
    True when no live member remains."""
    if not group_members(pgid):
        return True
    _killpg(pgid, signal.SIGTERM)
    if _wait_group_gone(pgid, timeout):
        return True
    _killpg(pgid, signal.SIGKILL)
    return _wait_group_gone(pgid, kill_wait)


def stop_processes(processes: list[psutil.Process], timeout: float, kill_wait: float = KILL_WAIT_SECONDS) -> bool:
    """Terminate, wait up to *timeout*, then kill what is left and wait up to *kill_wait*. True when none of
    *processes* is alive. None of them may be the caller's own un-reaped child (psutil would reap it)."""
    left = [p for p in processes if alive(p)]
    if not left:
        return True
    for process in reversed(left):
        signal_process(process, force=False)
    _, still = psutil.wait_procs(left, timeout=timeout)
    for process in still:
        signal_process(process, force=True)
    _, still = psutil.wait_procs(still, timeout=kill_wait)
    return not any(alive(p) for p in still)
