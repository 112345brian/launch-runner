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
from lifecycle_runner.domain import CaptureResult, CaptureSpec, RunOutcome, RunResult, RunSpec, StreamSpec
from lifecycle_runner.ports import (
    CaptureSpawner, ChildSpawner, Clock, CommandCapturer, CommandRunner, CommandStreamer, LineStream, StreamSpawner,
)
from lifecycle_runner.runner import Runner


class Commands:
    """All three operations. Implements ``CommandRunner``, ``CommandCapturer`` and ``CommandStreamer``; a fake
    implements the same three methods.

    By default every operation starts a real child with ``Popen``. Each way of starting one can be replaced on
    its own (to run through ssh, a container, a pty, ...) while the deadline, the kill, the never-raises
    contract and the result mapping stay this library's:

    - *spawner*: ``ChildSpawner`` for :meth:`run`;
    - *capture_spawner*: ``CaptureSpawner`` for :meth:`capture`;
    - *stream_spawner*: ``StreamSpawner`` for :meth:`stream`;
    - *clock*: ``Clock`` for the elapsed time in results.

    Bind an instance with :func:`use_commands` to make the module-level ``run`` / ``capture`` / ``stream`` use it.
    """

    def __init__(
        self,
        *,
        spawner: ChildSpawner | None = None,
        capture_spawner: CaptureSpawner | None = None,
        stream_spawner: StreamSpawner | None = None,
        clock: Clock | None = None,
    ) -> None:
        clock = clock if clock is not None else SystemClock()
        self._runner = Runner(spawner if spawner is not None else PopenSpawner(), clock)
        self._capturer = Capturer(capture_spawner if capture_spawner is not None else PopenCaptureSpawner(), clock)
        self._streams = stream_spawner if stream_spawner is not None else PopenStreamSpawner()

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


# The public surface of lifecycle_runner: the three operations, the values they speak in, the ports a caller may
# implement to replace how a child is started, and the default implementation to build on.
__all__ = [
    "run", "capture", "stream", "use_commands", "Commands",
    "RunSpec", "CaptureSpec", "StreamSpec", "RunOutcome", "RunResult", "CaptureResult",
    "ChildSpawner", "CaptureSpawner", "StreamSpawner", "Clock",
    "CommandRunner", "CommandCapturer", "CommandStreamer", "LineStream",
]
