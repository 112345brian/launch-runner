"""The reconciliation core runs against a fake starter with every sibling library blocked and off the path."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_PROGRAM = r"""
import importlib.abc, sys

class NoSiblings(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] in ("proclaunch", "commandport", "lifecycle_runner", "psutil"):
            raise ImportError("not needed by the core: " + name)

sys.meta_path.insert(0, NoSiblings())
from ensure_running import Outcome, Reconciler, Target
from ensure_running.domain import StartOutcome, StartResult

class FakeStarter:
    def __init__(self, outcome): self.outcome, self.specs = outcome, []
    def start(self, spec): self.specs.append(spec); return StartResult(self.outcome, pid=7)

expected = {StartOutcome.STARTED: Outcome.STARTED, StartOutcome.ALREADY_RUNNING: Outcome.OK,
            StartOutcome.IN_PROGRESS: Outcome.START_FAILED, StartOutcome.FAILED: Outcome.START_FAILED}
for outcome, want in expected.items():
    starter = FakeStarter(outcome)
    got = Reconciler(starter, lambda t: True, now=lambda: 0.0).reconcile([Target("web", ("srv",))])[0]
    assert got.outcome is want and starter.specs[0].name == "web", (outcome, got)
assert not any(m.split(".")[0] in ("proclaunch", "commandport", "lifecycle_runner") for m in sys.modules)
print("core ok")
"""


def test_the_reconciler_runs_without_any_sibling_library_installed():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "distributions" / "ensure-running" / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    ran = subprocess.run([sys.executable, "-c", _PROGRAM], capture_output=True, text=True, timeout=60, env=env,
                         cwd=str(ROOT))
    assert ran.returncode == 0 and "core ok" in ran.stdout, ran.stderr or ran.stdout
