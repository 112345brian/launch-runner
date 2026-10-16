"""Make the three source trees importable for the test process *and* for the subprocesses it starts.

Each distribution keeps its package under ``distributions/<name>/src``. ``pytest``'s ``pythonpath`` covers the
test process; exporting ``PYTHONPATH`` covers children (``python -m lifecycle_runner``, the install smoke test).
An editable install (``pip install -e distributions/<name>``) makes this unnecessary and is what CI does.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = [
    ROOT / "distributions" / name / "src"
    for name in ("commandport", "proclaunch", "lifecycle-runner", "ensure-running")
]


def pytest_configure(config) -> None:
    existing = os.environ.get("PYTHONPATH", "")
    parts = [str(p) for p in SOURCE_DIRS] + ([existing] if existing else [])
    os.environ["PYTHONPATH"] = os.pathsep.join(parts)
