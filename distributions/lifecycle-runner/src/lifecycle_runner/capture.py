"""Capturing a short command's output: spawn, wait with a deadline, kill, report.

Depends on ports only, like ``runner.Runner``. A timeout kills the child and is reported as
``TIMED_OUT`` with whatever the child had printed; a command that cannot start is
``FAILED_TO_START``; nothing raises out of ``capture`` (a ``KeyboardInterrupt`` kills the child first
and then propagates: Ctrl-C is not a result).
"""
from __future__ import annotations

from commandport.domain import CaptureResult, CaptureSpec, RunOutcome
from lifecycle_runner.ports import CaptureSpawner, Clock


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


class Capturer:
    def __init__(self, spawner: CaptureSpawner, clock: Clock) -> None:
        self._spawner = spawner
        self._clock = clock

    def capture(self, spec: CaptureSpec) -> CaptureResult:
        started = self._clock.monotonic()

        def elapsed() -> float:
            return self._clock.monotonic() - started

        try:
            child = self._spawner.spawn_captured(spec)
        except Exception as exc:  # noqa: BLE001 -- the contract is a result, not a raise
            return CaptureResult(RunOutcome.FAILED_TO_START, error=_describe(exc), elapsed=elapsed())

        try:
            got = child.communicate(spec.stdin_text, spec.timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            survived = not child.kill()
            stdout, stderr = child.partial_output()
            error = _describe(exc) + ("; process tree survived the kill" if survived else "")
            return CaptureResult(RunOutcome.ERROR, stdout=stdout, stderr=stderr, error=error, elapsed=elapsed())
        except BaseException:
            child.kill()
            raise

        if got is not None:
            stdout, stderr, code = got
            return CaptureResult(
                RunOutcome.COMPLETED, returncode=code, stdout=stdout, stderr=stderr, elapsed=elapsed(),
            )

        gone = child.kill()
        stdout, stderr = child.partial_output()
        return CaptureResult(
            RunOutcome.TIMED_OUT, stdout=stdout, stderr=stderr,
            error=None if gone else "process tree survived the kill", elapsed=elapsed(),
        )
