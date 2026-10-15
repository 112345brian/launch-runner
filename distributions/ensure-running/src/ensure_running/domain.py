"""Values and ports for "if this does not hold, start that". No I/O."""
from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from commandport.domain import LaunchResult


class ConditionState(enum.Enum):
    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    UNKNOWN = "unknown"  # could not tell; never a reason to start anything


@dataclass(frozen=True)
class Target:
    """One thing that should be running: a unique ``name``, the command, and where it runs."""

    name: str
    argv: tuple[str, ...]
    cwd: str | None = None
    log_path: Path | None = None
    max_starts: int = 5  # starts allowed inside ``window_seconds`` before the target is held back
    window_seconds: float = 3600.0

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.argv or not self.argv[0].strip():
            raise ValueError(f"Target needs a name and a command: {self!r}")
        if self.max_starts < 1 or self.window_seconds <= 0:
            raise ValueError("Target.max_starts must be >= 1 and window_seconds > 0")


class Condition(Protocol):
    def check(self, target: Target) -> ConditionState:
        """Never raises; a failure to find out is UNKNOWN."""


class Outcome(enum.Enum):
    OK = "ok"  # condition already held
    STARTED = "started"
    START_FAILED = "start_failed"
    UNKNOWN = "unknown"  # condition could not be evaluated; nothing was started
    THROTTLED = "throttled"  # restart cap reached; nothing was started
    DRY_RUN = "dry_run"  # would have started


@dataclass(frozen=True)
class TargetResult:
    target: str
    outcome: Outcome
    launch: LaunchResult | None = None
    detail: str | None = None

    @property
    def healthy(self) -> bool:
        return self.outcome in (Outcome.OK, Outcome.STARTED)
