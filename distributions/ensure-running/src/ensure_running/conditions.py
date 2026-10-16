"""Ready-made ``ShouldRun`` adapters. A client may pass any ``Callable[[Target], bool]`` instead."""
from __future__ import annotations

from pathlib import Path

from proclaunch.api import service_status

from ensure_running.domain import CheckRunner, Target

_CHECK_TIMEOUT_SECONDS = 30.0


class CheckFailed(RuntimeError):
    """A check could not be evaluated; the reconciler reports UNKNOWN and starts nothing."""


def service_not_running(state_dir: Path):
    """Default check: start when the target's recorded service is not a live process (pid *and* creation
    time, so a reused pid does not count). An unreadable record raises: starting a second copy on a guess
    is the one thing this must not do."""

    def should_run(target: Target) -> bool:
        status = service_status(target.name, state_dir=state_dir)
        if status.error is not None:
            raise CheckFailed(status.error)
        return not status.running

    return should_run


class CommandCheck:
    """A client's check as a terminal command: exit 0 means "run it", exit 1 means "leave it". Any other
    exit code, a timeout, or a command that cannot start raises ``CheckFailed``: the check could not tell.

    *runner* is what actually runs the command (the ``CheckRunner`` port); the composition root passes
    ``ensure_running.lifecycle_check.LifecycleCheckRunner``."""

    def __init__(self, runner: CheckRunner, timeout_seconds: float = _CHECK_TIMEOUT_SECONDS) -> None:
        self._runner = runner
        self._timeout = timeout_seconds

    def __call__(self, target: Target) -> bool:
        assert target.check, "CommandCheck needs target.check"
        out = self._runner.run(target.check, cwd=target.cwd, timeout_seconds=self._timeout)
        if out.exit_code in (0, 1):
            return out.exit_code == 0
        raise CheckFailed(out.error or f"check exited {out.exit_code}")
