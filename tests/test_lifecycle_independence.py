"""lifecycle_runner imports and runs with proclaunch absent: only commandport and psutil are on the path."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "distributions"

_PROGRAM = r"""
import importlib.abc, sys

class NoProclaunch(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] == "proclaunch":
            raise ImportError("proclaunch must not be needed: " + name)

sys.meta_path.insert(0, NoProclaunch())
from commandport.domain import CaptureSpec, RunOutcome, RunSpec
from lifecycle_runner import api

done = api.capture(CaptureSpec((sys.executable, "-c", "print(42)"), timeout_seconds=30))
assert done.ok and done.stdout.strip() == "42", done
hung = api.run(RunSpec((sys.executable, "-c", "import time; time.sleep(60)"), timeout_seconds=1))
assert hung.outcome is RunOutcome.TIMED_OUT and hung.error is None, hung
assert not any(m.split(".")[0] == "proclaunch" for m in sys.modules), "proclaunch was imported"
print("independent ok")
"""


def test_the_runner_imports_and_runs_with_proclaunch_blocked_and_off_the_path():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        str(SRC / name / "src") for name in ("commandport", "lifecycle-runner")
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    ran = subprocess.run(
        [sys.executable, "-c", _PROGRAM], capture_output=True, text=True, timeout=120, env=env,
        cwd=str(ROOT),
    )
    assert ran.returncode == 0 and "independent ok" in ran.stdout, ran.stderr or ran.stdout
