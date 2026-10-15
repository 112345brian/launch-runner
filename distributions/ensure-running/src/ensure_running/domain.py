"""Values and ports for "if this does not hold, start that". No I/O."""
from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable

from commandport.domain import LaunchResult


@dataclass(frozen=True)
class Target:
    """One thing that should be running: a unique ``name``, the command, and where it runs."""

    name: str
    argv: tuple[str, ...]
    cwd: str | None = None
    log_path: Path | None = None
    check: tuple[str, ...] | None = None  # a client's "should this run?" command (see config); None: the default
    max_starts: int = 5  # starts allowed inside ``window_seconds`` before the target is held back
    window_seconds: float = 3600.0

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.argv or not self.argv[0].strip():
            raise ValueError(f"Target needs a name and a command: {self!r}")
        if self.max_starts < 1 or self.window_seconds <= 0:
            raise ValueError("Target.max_starts must be >= 1 and window_seconds > 0")


ShouldRun = Callable[[Target], bool]
"""The one question the library asks of a client: should this target be started now?

True: start it (subject to the restart cap and to the service record refusing a second copy).
False: leave it alone. Raising means "could not tell" and also starts nothing."""


class Outcome(enum.Enum):
    OK = "ok"  # no start needed
    STARTED = "started"
    START_FAILED = "start_failed"
    UNKNOWN = "unknown"  # the check raised, so it could not be told; nothing was started
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
