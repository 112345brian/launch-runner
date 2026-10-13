"""The proclaunch model: values and rules, no I/O.

Nothing in this module imports an operating-system, process, file or network
module; ``tests/test_proclaunch_architecture.py`` and an import-linter contract
keep it that way. Adapters live in ``proclaunch.adapters``; the behaviour that
uses them lives in ``launching`` / ``services`` / ``readiness`` behind the
protocols in ``proclaunch.ports``.
"""
from __future__ import annotations

import enum
import math
from dataclasses import dataclass

RESERVATION_STALE_SECONDS = 120.0


@dataclass(frozen=True)
class ProcessIdentity:
    """A process by pid *and* creation time: the OS reuses pids, so a pid alone
    is not an identity."""

    pid: int
    create_time: float

    def __post_init__(self) -> None:
        if (
            not isinstance(self.pid, int) or isinstance(self.pid, bool) or self.pid <= 0
            or not isinstance(self.create_time, (int, float)) or isinstance(self.create_time, bool)
            or not math.isfinite(self.create_time) or self.create_time < 0
        ):
            raise ValueError(f"invalid process identity: pid={self.pid!r} create_time={self.create_time!r}")


class StopOutcome(enum.Enum):
    STOPPED = "stopped"
    ALREADY_STOPPED = "already_stopped"  # no record, or the recorded process is gone
    PID_REUSED = "pid_reused"  # record was stale; another process owns the pid, left alone
    UNCERTAIN = "uncertain"  # record unreadable / process survived; nothing killed on a guess


@dataclass(frozen=True)
class StopResult:
    outcome: StopOutcome
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome is not StopOutcome.UNCERTAIN


@dataclass(frozen=True)
class ServiceStatus:
    running: bool
    pid: int | None = None
    uptime: float | None = None
    error: str | None = None  # unreadable record


@dataclass(frozen=True)
class WaitResult:
    ready: bool
    reason: str  # ready | timeout | process-exited | stopped | listener-unverified
    elapsed: float
    attempts: int


@dataclass(frozen=True)
class ServiceRecord:
    """What is remembered about a named service. ``identity is None`` means a
    start is in flight (a reservation)."""

    name: str
    identity: ProcessIdentity | None
    reserved_at: float | None = None
    argv: tuple[str, ...] = ()
    cwd: str | None = None
    method: str | None = None

    @property
    def is_reservation(self) -> bool:
        return self.identity is None

    def reservation_is_stale(self, now: float) -> bool:
        return now - (self.reserved_at or 0.0) > RESERVATION_STALE_SECONDS


class RecordUnreadable(Exception):
    """A stored record exists but cannot be trusted. It is preserved, never
    treated as "the service is stopped"."""
