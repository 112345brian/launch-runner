"""The launch types that proclaunch implements (still defined here until they move).

The run / capture / stream types live in ``lifecycle_runner.domain`` now; their old names are forwarded.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from commandport._moved import forward

if TYPE_CHECKING:
    from commandport.ports import Supervisor


@dataclass(frozen=True)
class ProcessSpec:
    """What to start. With no ``supervisor`` this is a direct spawn of ``argv``;
    with one, the supervisor is tried first and ``argv`` is the fallback."""

    argv: tuple[str, ...]
    cwd: str | None = None
    log_path: Path | None = None
    supervisor: Supervisor | None = None
    name: str | None = None  # set to make this a recorded service

    def __post_init__(self) -> None:
        if not self.argv or not self.argv[0].strip() or any("\0" in a for a in self.argv):
            raise ValueError(f"ProcessSpec.argv must be a non-empty command without NUL: {self.argv!r}")


class LaunchMethod(enum.Enum):
    SUPERVISED = "supervised"  # an OS supervisor started it
    SPAWNED = "spawned"  # direct, windowless, detached spawn
    ALREADY_RUNNING = "already_running"  # named service whose recorded identity is still live
    IN_PROGRESS = "in_progress"  # another start holds the reservation
    FAILED = "failed"


@dataclass(frozen=True)
class LaunchResult:
    method: LaunchMethod
    pid: int | None = None
    error: str | None = None  # why FAILED / IN_PROGRESS
    supervisor_error: str | None = None  # the supervisor failed but the direct spawn worked

    @property
    def started(self) -> bool:
        """This call launched a new process."""
        return self.method in (LaunchMethod.SUPERVISED, LaunchMethod.SPAWNED)

    @property
    def ok(self) -> bool:
        """The service is running because of this call (new or already)."""
        return self.started or self.method is LaunchMethod.ALREADY_RUNNING


@dataclass(frozen=True)
class EndResult:
    ended: bool
    skipped: bool = False  # supervisor not available on this platform
    error: str | None = None


forward(
    globals(),
    {name: "lifecycle_runner.domain" for name in ['RunSpec', 'RunOutcome', 'RunResult', 'CaptureSpec', 'CaptureResult', 'StreamSpec']},
    {"lifecycle_runner": "lifecycle-runner"},
)
