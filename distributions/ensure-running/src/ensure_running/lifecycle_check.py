"""``CheckRunner`` over lifecycle-runner: a windowless, time-limited, never-raising command run.

The only place this library names lifecycle_runner; the reconciliation core and ``CommandCheck`` see only the
``CheckRunner`` port. A caller may pass any ``capture`` function (``CaptureSpec -> CaptureResult``), for
example a fake in a test or a remote runner.
"""
from __future__ import annotations

from collections.abc import Callable

from lifecycle_runner import api
from lifecycle_runner.domain import CaptureResult, CaptureSpec, RunOutcome

from ensure_running.domain import CheckOutput


class LifecycleCheckRunner:
    def __init__(self, capture: Callable[[CaptureSpec], CaptureResult] | None = None) -> None:
        self._capture = capture if capture is not None else api.capture

    def run(self, argv: tuple[str, ...], *, cwd: str | None, timeout_seconds: float) -> CheckOutput:
        done = self._capture(CaptureSpec(argv, cwd=cwd, timeout_seconds=timeout_seconds))
        if done.outcome is RunOutcome.COMPLETED:
            return CheckOutput(done.returncode)
        if done.outcome is RunOutcome.TIMED_OUT:
            return CheckOutput(None, f"timed out after {timeout_seconds:g}s")
        return CheckOutput(None, done.error or done.outcome.value)
