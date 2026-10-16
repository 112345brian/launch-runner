"""The lifecycle_runner model: values and rules, no I/O."""
from __future__ import annotations

import enum
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


def _validate_command(
    label: str, argv: tuple[str, ...], timeout_seconds: float | None, env: Mapping[str, str] | None,
) -> None:
    if not argv or not argv[0].strip() or any("\0" in a for a in argv):
        raise ValueError(f"{label}.argv must be a non-empty command without NUL: {argv!r}")
    t = timeout_seconds
    if t is not None and (
        isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t <= 0
    ):
        raise ValueError(f"{label}.timeout_seconds must be a positive finite number or None: {t!r}")
    if env is not None:
        for key, value in env.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError(f"{label}.env must map str to str: {key!r}={value!r}")
            if not key or "=" in key or "\0" in key or "\0" in value:
                raise ValueError(f"{label}.env has an invalid entry: {key!r}")


@dataclass(frozen=True)
class RunSpec:
    """What to run. ``timeout_seconds=None`` means no limit.

    ``inherit_stdio`` runs the child attached to the caller's own stdin/stdout/stderr (a terminal
    passthrough: a developer tool streaming a build to the console); it excludes ``log_path``."""

    argv: tuple[str, ...]
    cwd: str | None = None
    env: Mapping[str, str] | None = None  # overlaid on the caller's environment
    log_path: Path | None = None  # stdout+stderr are appended here; None discards
    timeout_seconds: float | None = None
    inherit_stdio: bool = False

    def __post_init__(self) -> None:
        _validate_command("RunSpec", self.argv, self.timeout_seconds, self.env)
        if self.inherit_stdio and self.log_path is not None:
            raise ValueError("RunSpec.inherit_stdio and RunSpec.log_path are mutually exclusive")


class RunOutcome(enum.Enum):
    COMPLETED = "completed"  # the command ran and exited; see returncode
    TIMED_OUT = "timed_out"  # exceeded timeout_seconds and was killed
    FAILED_TO_START = "failed_to_start"  # nothing ran (missing executable, bad cwd, log not writable)
    ERROR = "error"  # waiting on the child failed; it was killed


@dataclass(frozen=True)
class RunResult:
    outcome: RunOutcome
    returncode: int | None = None  # None unless the child's exit code was read
    error: str | None = None  # why FAILED_TO_START / ERROR, or a surviving process tree
    elapsed: float = 0.0
    log_path: Path | None = None

    @property
    def ok(self) -> bool:
        """The command ran and exited 0. Nothing else is success."""
        return self.outcome is RunOutcome.COMPLETED and self.returncode == 0


@dataclass(frozen=True)
class CaptureSpec:
    """Run a short command and hand back everything it printed.

    ``stdin_text`` is written to the child's stdin (None: stdin is closed, so a child that prompts
    fails fast instead of hanging). ``merge_stderr`` folds stderr into ``stdout`` in emission order.
    Output is decoded as UTF-8 with undecodable bytes replaced; it is never the locale code page."""

    argv: tuple[str, ...]
    cwd: str | None = None
    env: Mapping[str, str] | None = None  # overlaid on the caller's environment
    timeout_seconds: float | None = None
    stdin_text: str | None = None
    merge_stderr: bool = False

    def __post_init__(self) -> None:
        _validate_command("CaptureSpec", self.argv, self.timeout_seconds, self.env)


@dataclass(frozen=True)
class CaptureResult:
    outcome: RunOutcome
    returncode: int | None = None  # None unless the child's exit code was read
    stdout: str = ""  # whatever was read, also for TIMED_OUT (the partial output)
    stderr: str = ""  # empty when merged into stdout
    error: str | None = None
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        """The command ran and exited 0. Nothing else is success."""
        return self.outcome is RunOutcome.COMPLETED and self.returncode == 0

    @property
    def completed(self) -> bool:
        """The command ran and exited (with any code), as opposed to timing out or not starting."""
        return self.outcome is RunOutcome.COMPLETED


@dataclass(frozen=True)
class StreamSpec:
    """Run a command and read its output line by line while it runs.

    stderr is merged into the stream. ``timeout_seconds`` is enforced by a watchdog that kills the
    child, so a command that hangs without closing its output is still stopped and reported."""

    argv: tuple[str, ...]
    cwd: str | None = None
    env: Mapping[str, str] | None = None  # overlaid on the caller's environment
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        _validate_command("StreamSpec", self.argv, self.timeout_seconds, self.env)
