"""Composition root: wires the real adapters into the runner, the capturer and the streamer.

The only module that imports both the application and the adapters. Application code depends on the
operation ports in ``lifecycle_runner.ports`` (``CommandRunner``, ``CommandCapturer``, ``CommandStreamer``)
and calls the module functions below, which delegate to the process-wide :class:`Commands` binding.

``use_commands`` swaps that binding for the duration of a ``with`` block: it is the one seam tests use,
passing ``lifecycle_runner.testing.FakeCommandRunner`` instead of patching ``subprocess``.
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator

from lifecycle_runner.adapters.popen_capture import PopenCaptureSpawner, PopenStreamSpawner
from lifecycle_runner.adapters.popen_spawner import PopenSpawner
from lifecycle_runner.adapters.system_clock import SystemClock
from lifecycle_runner.capture import Capturer
from lifecycle_runner.domain import CaptureResult, CaptureSpec, RunResult, RunSpec, StreamSpec
from lifecycle_runner.ports import CommandCapturer, CommandRunner, CommandStreamer, LineStream
from lifecycle_runner.runner import Runner


class Commands:
    """All three operations over real processes. Implements ``CommandRunner``, ``CommandCapturer`` and
    ``CommandStreamer``; a fake implements the same three methods."""

    def __init__(self) -> None:
        clock = SystemClock()
        self._runner = Runner(PopenSpawner(), clock)
        self._capturer = Capturer(PopenCaptureSpawner(), clock)
        self._streams = PopenStreamSpawner()

    def run(self, spec: RunSpec) -> RunResult:
        return self._runner.run(spec)

    def capture(self, spec: CaptureSpec) -> CaptureResult:
        return self._capturer.capture(spec)

    def stream(self, spec: StreamSpec) -> LineStream:
        return self._streams.open_stream(spec)


_commands: CommandRunner | CommandCapturer | CommandStreamer | Commands = Commands()


def default_runner() -> Runner:
    return Runner(PopenSpawner(), SystemClock())


def run(spec: RunSpec) -> RunResult:
    """Run to completion with a time limit; stdout/stderr go to ``spec.log_path``, are discarded, or are
    attached to the caller's console (``spec.inherit_stdio``). Never raises; see ``RunResult``."""
    return _commands.run(spec)  # type: ignore[union-attr]


def capture(spec: CaptureSpec) -> CaptureResult:
    """Run a short command and return everything it printed. Windowless, UTF-8, stdin closed unless given.
    Never raises; see ``CaptureResult``."""
    return _commands.capture(spec)  # type: ignore[union-attr]


def stream(spec: StreamSpec) -> LineStream:
    """Start a command and read its merged output line by line, with a watchdog on the timeout. Never
    raises: a command that could not start is a stream with ``start_error`` set."""
    return _commands.stream(spec)  # type: ignore[union-attr]


@contextlib.contextmanager
def use_commands(commands) -> Iterator[None]:
    """Bind *commands* (anything implementing ``run``/``capture``/``stream``) for the ``with`` block."""
    global _commands
    previous, _commands = _commands, commands
    try:
        yield
    finally:
        _commands = previous
