"""The driven ports: what the runner and the capturer need from the outside world.

Adapters in ``lifecycle_runner.adapters`` implement these against ``Popen``, the filesystem and proclaunch's
process-tree terminate. Tests implement them with in-memory fakes (a child that hangs forever, one that
fails to wait).

The operation ports application code depends on (``CommandCapturer`` / ``CommandStreamer`` /
``CommandRunner`` / ``LineStream``) and the spec/result types live in the pure ``commandport`` package, so an
inner ring can depend on them without importing anything that reaches an operating-system process.
"""
from __future__ import annotations

from typing import Protocol

from commandport.domain import CaptureSpec, RunSpec, StreamSpec
from commandport.ports import LineStream


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
