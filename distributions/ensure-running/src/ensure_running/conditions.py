"""Ready-made ``ShouldRun`` adapters. A client may pass any ``Callable[[Target], bool]`` instead."""
from __future__ import annotations

import subprocess
from pathlib import Path

from proclaunch.api import service_status

from ensure_running.domain import Target

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
    exit code, a timeout, or a command that cannot start raises ``CheckFailed``: the check could not tell."""

    def __init__(self, timeout_seconds: float = _CHECK_TIMEOUT_SECONDS) -> None:
        self._timeout = timeout_seconds

    def __call__(self, target: Target) -> bool:
        assert target.check, "CommandCheck needs target.check"
        try:
            done = subprocess.run(
                list(target.check), cwd=target.cwd, stdin=subprocess.DEVNULL, capture_output=True,
                timeout=self._timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CheckFailed(f"{type(exc).__name__}: {exc}") from exc
        if done.returncode in (0, 1):
            return done.returncode == 0
        raise CheckFailed(f"check exited {done.returncode}")
