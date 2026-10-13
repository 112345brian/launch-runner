"""Supervisor on Windows Task Scheduler: ``schtasks /run`` and ``/end``.

The task's own action decides what runs; ``spec.argv`` is only the fallback.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

from proclaunch.adapters.windows import is_windows, windowless_flags
from commandport.domain import EndResult, ProcessSpec

_SCHTASKS_TIMEOUT = 15


@dataclass(frozen=True)
class TaskSchedulerSupervisor:
    task_name: str

    def available(self) -> bool:
        return is_windows()

    def _schtasks(self, verb: str) -> None:
        subprocess.run(
            ["schtasks", verb, "/tn", self.task_name],
            capture_output=True, timeout=_SCHTASKS_TIMEOUT, creationflags=windowless_flags(), check=True,
        )

    def start(self, spec: ProcessSpec) -> int | None:
        self._schtasks("/run")
        return None  # the task launches it; the caller identifies the process

    def end(self) -> EndResult:
        if not self.available():
            return EndResult(ended=False, skipped=True)
        try:
            self._schtasks("/end")
        except Exception as exc:  # noqa: BLE001
            return EndResult(ended=False, error=f"{type(exc).__name__}: {exc}")
        return EndResult(ended=True)
