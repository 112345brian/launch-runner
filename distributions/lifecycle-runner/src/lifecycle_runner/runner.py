"""Running a command to completion: spawn, wait with a deadline, kill, report.

Depends on ports only. The decisions live here so they are testable with a fake
child: a timeout kills the child and is reported as ``TIMED_OUT`` (never as the
exit code of a process that was killed by us), a wait that fails kills the child
rather than leaving it running, and nothing raises out of ``run``.
"""
from __future__ import annotations

from lifecycle_runner.domain import RunOutcome, RunResult, RunSpec
from lifecycle_runner.ports import ChildSpawner, Clock, RunningChild

# After a kill, how long to wait for the exit code to become readable.
_POST_KILL_WAIT_SECONDS = 5.0


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


class Runner:
    def __init__(self, spawner: ChildSpawner, clock: Clock) -> None:
        self._spawner = spawner
        self._clock = clock

    def run(self, spec: RunSpec) -> RunResult:
        """Run *spec* and wait. Never raises (a ``KeyboardInterrupt`` kills the
        child first and then propagates: Ctrl-C is not a result)."""
        started = self._clock.monotonic()

        def elapsed() -> float:
            return self._clock.monotonic() - started

        try:
            child = self._spawner.spawn(spec)
        except Exception as exc:  # noqa: BLE001 -- the contract is a result, not a raise
            return RunResult(
                RunOutcome.FAILED_TO_START, error=_describe(exc), elapsed=elapsed(), log_path=spec.log_path,
            )

        try:
            code = child.wait(spec.timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            survived = not child.kill()
            error = _describe(exc) + ("; process tree survived the kill" if survived else "")
            return RunResult(RunOutcome.ERROR, error=error, elapsed=elapsed(), log_path=spec.log_path)
        except BaseException:
            child.kill()
            raise

        if code is not None:
            return RunResult(RunOutcome.COMPLETED, returncode=code, elapsed=elapsed(), log_path=spec.log_path)
        return self._timed_out(child, spec, elapsed)

    @staticmethod
    def _timed_out(child: RunningChild, spec: RunSpec, elapsed) -> RunResult:
        gone = child.kill()
        try:
            after = child.wait(_POST_KILL_WAIT_SECONDS)
        except Exception:  # noqa: BLE001 -- the exit code of a killed process is a nicety
            after = None
        error = None if gone else "process tree survived the kill"
        return RunResult(
            RunOutcome.TIMED_OUT, returncode=after, error=error, elapsed=elapsed(), log_path=spec.log_path,
        )
