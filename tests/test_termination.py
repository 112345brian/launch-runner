"""Termination guarantees, against real processes (POSIX).

Two defects found by the architecture audit are pinned here as ``xfail(strict=True)`` so the suite stays green
while they exist; the fix commit removes the markers:

1. ``lifecycle_runner`` reported ``TIMED_OUT`` with ``error=None`` while a descendant that had been orphaned
   (re-parented) before the deadline kept running: its children shared the caller's process group, so the
   group kill was never taken and the tree walk cannot see an orphan.
2. ``terminate_process`` reported success for a service started on a pty while a child that ignores SIGTERM and
   SIGHUP kept running: the child is its own session leader, outside the holder's group.

The rest pin behaviour that must not change: nothing outside the child's own tree is signalled, and a run that
is attached to the caller's console stays in the caller's process group (so Ctrl-C and tty job control work).
Windows has its own mechanism and is not exercised here.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import psutil
import pytest

from commandport.domain import CaptureSpec, RunOutcome, RunSpec, StreamSpec
from lifecycle_runner import api
from lifecycle_runner.adapters import popen_spawner
from proclaunch.api import terminate_process

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups and sessions")

_SLEEP = "import time; time.sleep(120)"
# The child starts a helper whose own child sleeps; the helper exits at once, so that grandchild is orphaned.
# The orphan's stdio is detached so it does not hold the run's output pipe open (that would block a stream's
# iteration until the orphan exits, which would hide the survival this test is about).
# The child prints the orphan's pid and then hangs, so the deadline (not the child) ends the run.
_ORPHANING = (
    "import subprocess, sys, time\n"
    f"helper = \"import subprocess, sys; p = subprocess.Popen([sys.executable, '-c', '{_SLEEP}'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); print(p.pid, flush=True)\"\n"
    "mid = subprocess.Popen([sys.executable, '-c', helper], stdout=subprocess.PIPE, text=True)\n"
    "pid = mid.stdout.readline().strip()\n"
    "mid.wait()\n"
    "print(pid, flush=True)\n"
    "time.sleep(120)\n"
)
# The root starts a descendant in a new session (it escapes the root's process group) and hangs.
_ESCAPER = (
    "import subprocess, sys, time\n"
    f"c = subprocess.Popen([sys.executable, '-c', '{_SLEEP}'], start_new_session=True)\n"
    "print(c.pid, flush=True)\n"
    "time.sleep(120)\n"
)


def _alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _gone(pid: int, within: float = 5.0) -> bool:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return not _alive(pid)


def _reap(*pids: int) -> None:
    for pid in pids:
        try:
            psutil.Process(pid).kill()
        except psutil.Error:
            pass


# ---- defect 1: an orphaned descendant outlives a timeout ------------------


@pytest.mark.xfail(strict=True, reason="lifecycle children share the caller's process group; orphans are missed")
@pytest.mark.parametrize("operation", ["run", "capture", "stream"])
def test_a_timeout_kills_a_descendant_orphaned_before_the_deadline(operation, tmp_path):
    orphan = None
    try:
        if operation == "run":
            log = tmp_path / "out.log"
            result = api.run(RunSpec((sys.executable, "-c", _ORPHANING), log_path=log, timeout_seconds=3))
            output, outcome, error = log.read_text(encoding="utf-8"), result.outcome, result.error
        elif operation == "capture":
            result = api.capture(CaptureSpec((sys.executable, "-c", _ORPHANING), timeout_seconds=3))
            output, outcome, error = result.stdout, result.outcome, result.error
        else:
            stream = api.stream(StreamSpec((sys.executable, "-c", _ORPHANING), timeout_seconds=3))
            output = "".join(stream)
            outcome = RunOutcome.TIMED_OUT if stream.timed_out else RunOutcome.COMPLETED
            error = None
            stream.close()
        orphan = int(output.split()[0])
        assert outcome is RunOutcome.TIMED_OUT
        # Either the orphan is gone, or the result says something survived: never a silent TIMED_OUT.
        assert _gone(orphan) or error is not None
        assert _gone(orphan), "the orphaned descendant outlived the timeout kill"
    finally:
        if orphan is not None:
            _reap(orphan)


def test_a_timeout_leaves_a_bystander_in_the_callers_group_alone(tmp_path):
    bystander = subprocess.Popen([sys.executable, "-c", _SLEEP])
    try:
        result = api.run(RunSpec((sys.executable, "-c", _SLEEP), log_path=tmp_path / "o.log", timeout_seconds=1))
        assert result.outcome is RunOutcome.TIMED_OUT
        assert os.getpgid(bystander.pid) == os.getpgid(0)
        assert _alive(bystander.pid), "a process outside the child's tree was terminated"
    finally:
        bystander.kill()
        bystander.wait()


def _popen_kwargs(monkeypatch, spec: RunSpec, *, console: bool) -> dict:
    seen: dict = {}

    class _Proc:
        pid = 1

    def fake_popen(argv, **kwargs):
        seen.update(kwargs)
        return _Proc()

    monkeypatch.setattr(popen_spawner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(popen_spawner, "_caller_has_console", lambda: console)
    popen_spawner.PopenSpawner().spawn(spec)
    return seen


def test_a_console_attached_run_stays_in_the_callers_process_group(monkeypatch):
    kwargs = _popen_kwargs(monkeypatch, RunSpec((sys.executable, "-c", "pass"), inherit_stdio=True), console=True)
    assert "process_group" not in kwargs and not kwargs.get("start_new_session")


@pytest.mark.xfail(strict=True, reason="a detached run is not given a process group of its own yet")
def test_a_detached_run_gets_its_own_process_group_in_the_callers_session(monkeypatch):
    kwargs = _popen_kwargs(monkeypatch, RunSpec((sys.executable, "-c", "pass")), console=False)
    assert kwargs.get("process_group") == 0
    assert not kwargs.get("start_new_session"), "a new session would also drop the controlling terminal"


# ---- defect 2: success reported while a known child survives --------------


@pytest.mark.xfail(strict=True, reason="termination success ignores descendants outside the leader's group")
def test_terminate_process_does_not_report_success_over_a_session_escaper():
    root = subprocess.Popen(
        [sys.executable, "-c", _ESCAPER], stdout=subprocess.PIPE, text=True, start_new_session=True,
    )
    escaper = int(root.stdout.readline())
    try:
        gone = terminate_process(root.pid, timeout=3)
        root.wait(timeout=5)
        assert not gone or _gone(escaper, 2.0), "terminate_process returned True while a descendant lived"
    finally:
        _reap(escaper, root.pid)


@pytest.mark.xfail(strict=True, reason="a pty child is its own session leader, outside the holder's group")
def test_a_pty_child_that_ignores_termination_is_not_reported_stopped_while_alive(tmp_path):
    from commandport.domain import ProcessSpec
    from proclaunch.adapters.pty_spawner import PtySpawner

    marker = tmp_path / "child.pid"
    code = (
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "signal.signal(signal.SIGHUP, signal.SIG_IGN)\n"
        f"open({str(marker)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(120)\n"
    )
    holder = PtySpawner().spawn(ProcessSpec((sys.executable, "-c", code)))
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not (marker.exists() and marker.read_text()):
        time.sleep(0.1)
    child = int(marker.read_text())
    try:
        gone = terminate_process(holder, timeout=2)
        assert not gone or _gone(child, 2.0), "terminate_process returned True while the pty child lived"
    finally:
        _reap(child, holder)
