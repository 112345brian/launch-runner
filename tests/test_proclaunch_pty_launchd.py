from __future__ import annotations

import os
import plistlib
import sys
import time
from pathlib import Path

import pytest

from commandport.domain import ProcessSpec
from proclaunch.adapters.launchd import LaunchdSupervisor
from proclaunch.adapters.pty_spawner import PtySpawner

SRC = Path(__file__).resolve().parent.parent / "distributions" / "proclaunch" / "src"


@pytest.mark.skipif(sys.platform == "win32", reason="Unix pty")
def test_pty_spawner_gives_the_child_a_terminal_and_logs_its_output(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(SRC), os.environ.get("PYTHONPATH", "")]))
    log = tmp_path / "out.log"
    code = "import sys; print('tty', sys.stdout.isatty(), sys.stdin.isatty())"
    PtySpawner().spawn(ProcessSpec((sys.executable, "-c", code), log_path=log))
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and "tty" not in (log.read_text() if log.exists() else ""):
        time.sleep(0.1)
    assert "tty True True" in log.read_text()


def test_launchd_plist_runs_at_load_on_an_interval(tmp_path):
    sup = LaunchdSupervisor("com.example.ensure", interval_seconds=120, agents_dir=tmp_path)
    spec = ProcessSpec(("/usr/bin/python3", "-m", "ensure_running"), cwd="/work", log_path=tmp_path / "l.log")
    body = plistlib.loads(sup.render(spec))
    assert body["Label"] == "com.example.ensure" and body["RunAtLoad"] is True
    assert body["StartInterval"] == 120 and body["WorkingDirectory"] == "/work"
    assert body["ProgramArguments"] == list(spec.argv)
    assert sup.plist_path == tmp_path / "com.example.ensure.plist"
