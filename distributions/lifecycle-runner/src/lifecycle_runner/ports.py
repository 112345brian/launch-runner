"""The driven ports: what the runner and the capturer need from the outside world.

Adapters in ``lifecycle_runner.adapters`` implement these against ``Popen``, the filesystem and psutil's
process tree. Tests implement them with in-memory fakes (a child that hangs forever, one that
fails to wait).

The operation ports application code may depend on (``CommandCapturer`` / ``CommandStreamer`` /
``CommandRunner`` / ``LineStream``) are defined here too, next to the spec/result types in
``lifecycle_runner.domain``. Importing them does not import anything that reaches an operating-system
process, but it does name this library: a consumer that wants its own vocabulary defines a narrower local
protocol and lets this library satisfy it structurally.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from lifecycle_runner.domain import (
    CaptureResult, CaptureSpec, RunResult, RunSpec, StreamSpec,
)


class RunningChild(Protocol):
    pid: int

    def wait(self, timeout: float | None) -> int | None:
        """The exit code, or None if the child is still running after *timeout*
        seconds (``None`` waits forever). May raise; the runner kills the child."""

    def kill(self) -> bool:
        """Stop the child and its descendants. True when nothing of it remains.
        Never raises."""


class ChildSpawner(Protocol):
    def spawn(self, spec: RunSpec) -> RunningChild:
        """Start ``spec.argv`` windowless in the foreground with stdout and
        stderr appended to ``spec.log_path`` (or discarded), or attached to the
        caller's stdio when ``spec.inherit_stdio``. Raise ``OSError`` on
        failure; nothing is left running or open in that case."""


class CapturedChild(Protocol):
    pid: int

    def communicate(self, stdin_text: str | None, timeout: float | None) -> tuple[str, str, int] | None:
        """(stdout, stderr, exit code) once the child has exited, or None if it is still running after
        *timeout* seconds. May raise; the capturer kills the child."""

    def partial_output(self) -> tuple[str, str]:
        """Whatever stdout and stderr were read before a timeout. Never raises."""

    def kill(self) -> bool:
        """Stop the child and its descendants. True when nothing of it remains. Never raises."""


class CaptureSpawner(Protocol):
    def spawn_captured(self, spec: CaptureSpec) -> CapturedChild:
        """Start ``spec.argv`` windowless with stdout/stderr piped. Raise ``OSError`` on failure."""


class StreamSpawner(Protocol):
    def open_stream(self, spec: StreamSpec) -> LineStream:
        """Start ``spec.argv`` windowless with a watchdog on ``spec.timeout_seconds``. Never raises: a
        start failure is reported through the returned stream's ``start_error``."""


class Clock(Protocol):
    def monotonic(self) -> float: ...


# ---- the operation ports (what an application asks of "something that runs a command")


class LineStream(Protocol):
    """A running command whose merged stdout/stderr is read line by line.

    Iterating yields each line with its line ending (text mode, UTF-8, undecodable bytes replaced) until the
    child closes its output or is killed. ``start_error`` is set (and iteration is empty) when the command
    could not start."""

    pid: int | None
    start_error: str | None

    def __iter__(self) -> Iterator[str]: ...

    @property
    def returncode(self) -> int | None:
        """The exit code once known (after iteration finished or the child was killed)."""

    @property
    def timed_out(self) -> bool:
        """The watchdog killed the child because it ran past ``timeout_seconds``."""

    def kill(self) -> None:
        """Stop the child and its descendants. Never raises."""

    def close(self) -> None:
        """Cancel the watchdog and make sure nothing is left running. Idempotent, never raises."""


class CommandCapturer(Protocol):
    """Run a short command and get everything it printed. Never raises; see ``CaptureResult``."""

    def capture(self, spec: CaptureSpec) -> CaptureResult: ...


class CommandStreamer(Protocol):
    """Run a command and read its output as it is produced. Never raises; see ``LineStream.start_error``."""

    def stream(self, spec: StreamSpec) -> LineStream: ...


class CommandRunner(Protocol):
    """Run a command to completion with a time limit; output goes to a log, is discarded, or is attached."""

    def run(self, spec: RunSpec) -> RunResult: ...
