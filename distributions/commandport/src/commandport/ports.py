"""The operation ports: what application code may ask of "something that runs a command".

This is the interface the inner rings depend on. A use case takes a ``CommandCapturer`` (or a
``CommandStreamer`` / ``CommandRunner``) as an argument and never reaches for ``subprocess`` itself; an
entrypoint hands it the real implementation (``lifecycle_runner.api``) and a test hands it
``commandport.testing.FakeCommandRunner``.

Nothing here imports a process, file or network module, so a domain, service or workflow module may import
this package without becoming an I/O client.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from commandport.domain import (
    CaptureResult, CaptureSpec, EndResult, LaunchResult, ProcessSpec, RunResult, RunSpec, StreamSpec,
)


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


class BackgroundLauncher(Protocol):
    """Start a long-lived process detached from the caller, windowless, with its output sent to
    ``ProcessSpec.log_path`` or discarded. Returns as soon as the launch was issued; never raises (a launch that
    did not happen is ``LaunchResult.method == FAILED`` with the reason)."""

    def launch(self, spec: ProcessSpec) -> LaunchResult: ...


class Supervisor(Protocol):
    """An operating-system supervisor (Task Scheduler, launchd, systemd) that can start what it owns."""

    def available(self) -> bool:
        """False when this supervisor does not exist here; the launcher then
        spawns directly without reporting an error."""

    def start(self, spec: ProcessSpec) -> int | None:
        """Ask the supervisor to start the process; return its pid if known.
        Raise on failure; the launcher falls back to a direct spawn."""

    def end(self) -> EndResult:
        """Ask the supervisor to end what it started. Never raises."""
