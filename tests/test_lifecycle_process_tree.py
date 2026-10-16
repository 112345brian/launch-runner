"""lifecycle_runner's own tree termination and window flag, against real processes where the OS matters.

Posix-only where a signal or a process group is involved; the flag test is portable. ``terminate_tree`` is
tested directly here; the end-to-end timeout behaviour is in ``test_termination.py``.
"""
from __future__ import annotations

import subprocess
import sys
import time

import psutil
import pytest

from lifecycle_runner.adapters import process_tree
from lifecycle_runner.adapters.process_tree import terminate_tree
from lifecycle_runner.adapters.windows import windowless_creationflags

posix = pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals and process groups")

_SLEEP = "import time; time.sleep(120)"
_IGNORES_TERM = f"import signal; signal.signal(signal.SIGTERM, signal.SIG_IGN); {_SLEEP}"
# prints the pid of a grandchild that lives in a new session, then hangs
_ESCAPER = (
    "import subprocess, sys, time\n"
    f"c = subprocess.Popen([sys.executable, '-c', '{_SLEEP}'], start_new_session=True)\n"
    "print(c.pid, flush=True); time.sleep(120)\n"
)
# prints the pid of a grandchild in the same group that is parented to this child
_PARENTED = (
    "import subprocess, sys, time\n"
    f"c = subprocess.Popen([sys.executable, '-c', '{_SLEEP}'])\n"
    "print(c.pid, flush=True); time.sleep(120)\n"
)


def _alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _gone(pid: int, within: float = 5.0) -> bool:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline and _alive(pid):
        time.sleep(0.05)
    return not _alive(pid)


def _spawn(code: str, *, own_group: bool) -> subprocess.Popen:
    extra = {"process_group": 0} if own_group and sys.platform != "win32" else {}
    return subprocess.Popen(
        [sys.executable, "-c", code], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True, **extra,
    )


@pytest.fixture
def procs():
    spawned: list[int] = []
    yield spawned
    for pid in spawned:
        try:
            psutil.Process(pid).kill()
        except psutil.Error:
            pass


@posix
def test_a_child_that_ignores_sigterm_is_forced_and_reaped_with_its_signal(procs):
    child = _spawn(_IGNORES_TERM, own_group=True)
    procs.append(child.pid)
    time.sleep(0.5)  # let it install the handler
    assert terminate_tree(child, own_group=True, timeout=1.0) is True
    assert child.poll() is not None and child.returncode < 0, "the exit status must be the kill's, not 0"
    assert not _alive(child.pid)


@posix
@pytest.mark.parametrize("own_group", [True, False])
def test_a_parented_descendant_dies_with_the_child(own_group, procs):
    child = _spawn(_PARENTED, own_group=own_group)
    grandchild = int(child.stdout.readline())
    procs.extend([child.pid, grandchild])
    assert terminate_tree(child, own_group=own_group, timeout=2.0) is True
    assert _gone(grandchild)


@posix
@pytest.mark.parametrize("own_group", [True, False])
def test_a_descendant_in_a_new_session_is_stopped_and_counted(own_group, procs):
    child = _spawn(_ESCAPER, own_group=own_group)
    escaper = int(child.stdout.readline())
    procs.extend([child.pid, escaper])
    assert terminate_tree(child, own_group=own_group, timeout=2.0) is True
    assert _gone(escaper), "True was returned while a known descendant lived"


@posix
def test_an_already_exited_child_keeps_its_exit_code(procs):
    child = _spawn("import sys; sys.exit(7)", own_group=True)
    assert child.wait(timeout=10) == 7
    assert terminate_tree(child, own_group=True) is True
    assert child.returncode == 7


@posix
def test_a_survivor_that_cannot_be_stopped_is_reported_not_hidden(monkeypatch, procs):
    class Stubborn:
        pid = 2 ** 22 - 3

        def is_running(self):
            return True

        def status(self):
            return psutil.STATUS_SLEEPING

        def terminate(self):
            pass

        kill = terminate

    child = _spawn(_SLEEP, own_group=True)
    procs.append(child.pid)
    monkeypatch.setattr(process_tree.proctree, "descendants", lambda pid: [Stubborn()])
    monkeypatch.setattr(process_tree.proctree.psutil, "wait_procs", lambda items, timeout=None: ([], list(items)))
    assert terminate_tree(child, own_group=True, timeout=0.2) is False
    assert child.poll() is not None, "the child itself is still stopped"


def test_the_window_flag_is_create_no_window_on_windows_and_zero_elsewhere(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delattr(subprocess, "CREATE_NO_WINDOW", raising=False)
    assert windowless_creationflags() == 0x08000000
    monkeypatch.setattr(sys, "platform", "linux")
    assert windowless_creationflags() == 0


def test_the_window_flag_matches_proclaunchs_definition_on_this_platform():
    # The two libraries each own the constant now; this keeps them from drifting while both ship from one repo.
    from proclaunch.adapters.windows import windowless_flags

    assert windowless_creationflags() == windowless_flags()


@posix
def test_a_reaped_leader_is_not_followed_by_a_signal_to_its_old_group(monkeypatch):
    child = _spawn("pass", own_group=True)
    child.wait(timeout=10)
    called = []
    monkeypatch.setattr(process_tree.proctree, "stop_group", lambda pgid, timeout: called.append(pgid) or True)
    assert terminate_tree(child, own_group=True) is True
    assert called == [], "the group id of a reaped leader may have been recycled"
