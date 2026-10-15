"""Conditions backed by proclaunch's recorded services."""
from __future__ import annotations

from pathlib import Path

from proclaunch.api import service_status

from ensure_running.domain import ConditionState, Target


class ServiceRunning:
    """SATISFIED when the target's named service has a recorded process that is still the same live
    process (pid *and* creation time, so a reused pid does not count). An unreadable record is UNKNOWN,
    never UNSATISFIED: starting a second copy on a guess is the one thing this must not do."""

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir

    def check(self, target: Target) -> ConditionState:
        try:
            status = service_status(target.name, state_dir=self._state_dir)
        except Exception:  # noqa: BLE001 -- the Condition contract is a state, not a raise
            return ConditionState.UNKNOWN
        if status.error is not None:
            return ConditionState.UNKNOWN
        return ConditionState.SATISFIED if status.running else ConditionState.UNSATISFIED
