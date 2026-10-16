"""The vendored process-stopping module: copies match the source, and the source works on real processes.

``vendored/proctree.py`` is the single source; ``lifecycle_runner`` and ``proclaunch`` each carry a generated copy
(an sdist cannot reach outside its directory). The behaviour tests run on the source; the drift test makes that
cover both copies.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import sync_vendored  # noqa: E402

_spec = importlib.util.spec_from_file_location("proctree_source", ROOT / "vendored" / "proctree.py")
proctree = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(proctree)

posix = pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
_SLEEP = "import time; time.sleep(120)"


def test_every_vendored_copy_equals_its_source():
    for path, text in sync_vendored.expected().items():
        assert path.exists(), f"{path.relative_to(ROOT)} is missing: run python tools/sync_vendored.py"
        assert path.read_text(encoding="utf-8") == text, f"{path.relative_to(ROOT)} differs from vendored/"


def test_the_vendored_module_imports_nothing_from_the_family():
    import ast

    for name in ("proclaunch", "lifecycle_runner", "commandport", "ensure_running"):
        for node in ast.walk(ast.parse((ROOT / "vendored" / "proctree.py").read_text(encoding="utf-8"))):
            modules = []
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            assert all(m.split(".")[0] != name for m in modules), f"proctree imports {name}"


def _gone(pid: int, within: float = 5.0) -> bool:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def reap():
    pids: list[int] = []
    yield pids
    for pid in pids:
        try:
            psutil.Process(pid).kill()
        except psutil.Error:
            pass


@posix
def test_stop_group_reaches_an_orphan_and_a_term_ignoring_member(reap):
    code = (
        "import signal, subprocess, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"c = subprocess.Popen([sys.executable, '-c', '{_SLEEP}'])\n"
        "print(c.pid, flush=True); time.sleep(120)\n"
    )
    leader = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, process_group=0)
    member = int(leader.stdout.readline())
    reap.extend([leader.pid, member])
    time.sleep(0.5)  # the leader has installed its SIGTERM handler
    assert proctree.group_members(leader.pid)
    assert proctree.stop_group(leader.pid, timeout=0.5) is True
    leader.wait(timeout=5)
    assert _gone(member) and proctree.group_members(leader.pid) == []


@posix
def test_stop_group_of_an_empty_group_is_true_and_signals_nothing():
    assert proctree.stop_group(2 ** 22 - 7, timeout=0.1) is True


@posix
def test_stop_processes_stops_a_snapshot_member_that_left_the_group(reap):
    code = (
        "import subprocess, sys, time\n"
        f"c = subprocess.Popen([sys.executable, '-c', '{_SLEEP}'], start_new_session=True)\n"
        "print(c.pid, flush=True); time.sleep(120)\n"
    )
    root = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, process_group=0)
    escaper = int(root.stdout.readline())
    reap.extend([root.pid, escaper])
    known = proctree.descendants(root.pid)
    assert [p.pid for p in known] == [escaper]
    assert proctree.stop_group(root.pid, timeout=2) is True
    root.wait(timeout=5)
    assert psutil.pid_exists(escaper) and not _gone(escaper, 0.3), "the group stop alone must not reach it"
    assert proctree.stop_processes(known, timeout=2) is True and _gone(escaper)


def test_a_process_nothing_can_stop_is_reported_alive(monkeypatch):
    class Stubborn:
        pid = 1

        def is_running(self):
            return True

        def status(self):
            return psutil.STATUS_SLEEPING

        def terminate(self):
            raise psutil.AccessDenied(1)

        kill = terminate

    monkeypatch.setattr(proctree.psutil, "wait_procs", lambda procs, timeout=None: ([], list(procs)))
    assert proctree.stop_processes([Stubborn()], timeout=0.1, kill_wait=0.1) is False


def test_an_uninspectable_process_is_assumed_alive():
    class Opaque:
        def is_running(self):
            return True

        def status(self):
            raise psutil.AccessDenied(1)

    assert proctree.alive(Opaque()) is True


def test_descendants_of_a_pid_that_is_gone_is_empty():
    assert proctree.descendants(2 ** 22 - 9) == []
    assert os.getpid() > 0
