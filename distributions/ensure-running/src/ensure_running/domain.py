"""Values and ports for "if this does not hold, start that". No I/O."""
from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Protocol


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


@dataclass(frozen=True)
class ServiceSpec:
    """What the reconciler asks to have started: a named command. Its own vocabulary, not a process library's."""

    name: str
    argv: tuple[str, ...]
    cwd: str | None = None
    log_path: Path | None = None


class StartOutcome(enum.Enum):
    """How a start request ended; the reconciliation policy depends on each of them."""

    STARTED = "started"  # this call started a new process
    ALREADY_RUNNING = "already_running"  # a live process already holds the name: nothing to do
    IN_PROGRESS = "in_progress"  # another start holds the reservation: not started, not known running
    FAILED = "failed"  # nothing started; see ``error``


@dataclass(frozen=True)
class StartResult:
    outcome: StartOutcome
    pid: int | None = None
    error: str | None = None

    @property
    def started(self) -> bool:
        return self.outcome is StartOutcome.STARTED


class ServiceStarter(Protocol):
    """What reconciliation requires of whatever starts services: start the named service unless it is already
    running, and say which of the four outcomes happened. Never raises."""

    def start(self, spec: ServiceSpec) -> StartResult: ...


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
    start: StartResult | None = None
    detail: str | None = None

    @property
    def healthy(self) -> bool:
        return self.outcome in (Outcome.OK, Outcome.STARTED)
