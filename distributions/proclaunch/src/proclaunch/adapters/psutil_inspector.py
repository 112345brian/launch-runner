"""ProcessInspector on psutil: identity-checked liveness and termination.

Process-group and tree termination adapted from dmon (MIT); see
THIRD_PARTY_NOTICES.md. Nothing here acts on a process unless its creation time
still matches the recorded identity.
"""
from __future__ import annotations

import os
import signal
import time

import psutil

from proclaunch._vendor import proctree
from proclaunch.adapters.atomic_files import ON_WINDOWS
from proclaunch.domain import ProcessIdentity

_SINCE_TOLERANCE = 0.25


def same_executable(found: str, wanted: str) -> bool:
    """Same directory and interpreter name, treating ``pythonw`` as ``python``
    (a Windows task may run the windowless twin of the interpreter we were given).

    Also true when both resolve to the same file, or -- macOS framework builds --
    when a venv ``python`` re-execs into the framework's ``Python.app`` binary of
    the same installation, so the running process never shows the path it was
    launched with."""
    a, b = os.path.normcase(found), os.path.normcase(wanted)
    if os.path.dirname(a) == os.path.dirname(b):

        def stem(path: str) -> str:
            return os.path.splitext(os.path.basename(path))[0].removesuffix("w")

        if stem(a) == stem(b):
            return True
    real_found, real_wanted = os.path.realpath(found), os.path.realpath(wanted)
    if real_found == real_wanted:
        return True
    root = _framework_root(real_wanted)
    return root is not None and root == _framework_root(real_found)


def _framework_root(path: str) -> str | None:
    """``.../Python.framework/Versions/3.12`` for a path inside that framework build, else None."""
    marker = "/Python.framework/Versions/"
    head, sep, rest = path.partition(marker)
    if not sep:
        return None
    version = rest.split("/", 1)[0]
    return f"{head}{marker}{version}" if version else None


def _same_process(proc: psutil.Process, identity: ProcessIdentity) -> bool:
    return abs(proc.create_time() - identity.create_time) < 1e-3


def _process_group_exists(process_group: int) -> bool:
    for process in psutil.process_iter(["pid", "status"]):
        if process.info["status"] == psutil.STATUS_ZOMBIE:
            continue
        try:
            if os.getpgid(process.info["pid"]) == process_group:
                return True
        except (OSError, psutil.NoSuchProcess):
            continue
    return False


def _terminate_posix_group(proc: psutil.Process, process_group: int, timeout: float) -> bool:
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and _process_group_exists(process_group):
        try:
            proc.wait(timeout=0)
        except (psutil.NoSuchProcess, psutil.TimeoutExpired):
            pass
        time.sleep(0.05)
    if _process_group_exists(process_group):
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            return True
        except PermissionError:
            if _process_group_exists(process_group):
                return False
    try:
        proc.wait(timeout=1)
    except (psutil.NoSuchProcess, psutil.TimeoutExpired):
        pass
    return True


def _terminate_tree(proc: psutil.Process, timeout: float) -> bool:
    try:
        processes = [*proc.children(recursive=True), proc]
    except psutil.NoSuchProcess:
        return True
    return proctree.stop_processes(processes, timeout)


def _terminate(proc: psutil.Process, timeout: float) -> bool:
    """Stop *proc* and its descendants; True only when none of what could be found beforehand is left."""
    deadline = time.monotonic() + timeout
    known = proctree.descendants(proc.pid)
    stopped = _terminate_leader(proc, timeout)
    swept = proctree.stop_processes(known, max(0.5, deadline - time.monotonic()))
    return stopped and swept


def _terminate_leader(proc: psutil.Process, timeout: float) -> bool:
    if not ON_WINDOWS:
        try:
            group = os.getpgid(proc.pid)
        except (ProcessLookupError, psutil.NoSuchProcess):
            return True
        if group == proc.pid:
            return _terminate_posix_group(proc, group, timeout)
    return _terminate_tree(proc, timeout)


class PsutilInspector:
    def identify(self, pid: int) -> ProcessIdentity | None:
        try:
            return ProcessIdentity(pid, psutil.Process(pid).create_time())
        except (psutil.Error, ValueError, TypeError):
            return None  # gone, or not a real pid

    def current(self) -> ProcessIdentity | None:
        return self.identify(os.getpid())

    def _unique(self, identity: ProcessIdentity) -> psutil.Process | None:
        try:
            proc = psutil.Process(identity.pid)
            if _same_process(proc, identity) and proctree.alive(proc):
                return proc
        except psutil.NoSuchProcess:
            pass
        return None

    def is_live(self, identity: ProcessIdentity) -> bool:
        return self._unique(identity) is not None

    def pid_reused(self, identity: ProcessIdentity) -> bool:
        try:
            return not _same_process(psutil.Process(identity.pid), identity)
        except psutil.NoSuchProcess:
            return False

    def terminate(self, identity: ProcessIdentity, timeout: float) -> bool:
        proc = self._unique(identity)
        if proc is None:
            return True  # nothing of it remains (or it is not ours to touch)
        return _terminate(proc, timeout)

    def find_started(self, argv: tuple[str, ...], since: float) -> ProcessIdentity | None:
        want_tail = [os.path.normcase(a) for a in argv[1:]]
        matches: dict[int, tuple[int, float]] = {}  # pid -> (ppid, create_time)
        # Per-process attributes are slow on Windows (ppid for ~700 processes took ~10s),
        # so scan only pid + create_time, and read command line / parent just for the few
        # processes created since the launch -- the only ones that can be the one we want.
        for proc in psutil.process_iter(["pid", "create_time"]):
            try:
                if proc.info["create_time"] < since - _SINCE_TOLERANCE:
                    continue
                cmd = proc.cmdline()
                if (
                    len(cmd) == len(argv)
                    and [os.path.normcase(c) for c in cmd[1:]] == want_tail
                    and same_executable(cmd[0], argv[0])
                ):
                    matches[proc.info["pid"]] = (proc.ppid(), proc.info["create_time"])
            except (psutil.Error, ValueError):
                continue
        # A Windows venv launcher re-execs the real interpreter with the same command
        # line; the root of that pair is the process the supervisor started.
        roots = [pid for pid, (ppid, _) in matches.items() if ppid not in matches]
        if len(roots) != 1:
            return None  # nothing, or ambiguous: never guess which process is ours
        return ProcessIdentity(roots[0], matches[roots[0]][1])
