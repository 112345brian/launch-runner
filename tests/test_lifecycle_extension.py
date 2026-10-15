"""A way of starting a child can be replaced; the deadline, kill and result mapping stay lifecycle_runner's."""
from __future__ import annotations

import sys

import pytest

from lifecycle_runner import api
from lifecycle_runner.api import Commands
from lifecycle_runner.domain import CaptureSpec, RunOutcome, RunSpec, StreamSpec


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def monotonic(self) -> float:
        self.t += 2.0
        return self.t


class SshChild:
    """What a remote execution would hand back: it exits with a code, or hangs until killed."""

    pid = 99

    def __init__(self, code: int | None) -> None:
        self.code, self.killed = code, False

    def wait(self, timeout):
        return None if self.code is None and not self.killed else (self.code if not self.killed else -9)

    def kill(self) -> bool:
        self.killed = True
        return True


class SshSpawner:
    def __init__(self, code: int | None = 0) -> None:
        self.code, self.specs, self.children = code, [], []

    def spawn(self, spec):
        self.specs.append(spec)
        child = SshChild(self.code)
        self.children.append(child)
        return child


class SshCaptureChild:
    pid = 5

    def __init__(self, result) -> None:
        self.result, self.killed = result, False

    def communicate(self, stdin_text, timeout):
        return self.result

    def partial_output(self):
        return ("partial", "")

    def kill(self) -> bool:
        self.killed = True
        return True


class SshCaptureSpawner:
    def __init__(self, result) -> None:
        self.result, self.specs = result, []

    def spawn_captured(self, spec):
        self.specs.append(spec)
        return SshCaptureChild(self.result)


def test_run_uses_the_injected_spawner_and_keeps_the_result_mapping():
    spawner = SshSpawner(code=3)
    commands = Commands(spawner=spawner, clock=Clock())
    result = commands.run(RunSpec(("remote", "job"), timeout_seconds=5))
    assert result.outcome is RunOutcome.COMPLETED and result.returncode == 3 and not result.ok
    assert [s.argv for s in spawner.specs] == [("remote", "job")]


def test_a_timeout_on_an_injected_spawner_is_killed_and_reported_by_the_runner():
    spawner = SshSpawner(code=None)
    result = Commands(spawner=spawner, clock=Clock()).run(RunSpec(("remote", "hang"), timeout_seconds=1))
    assert result.outcome is RunOutcome.TIMED_OUT and not result.ok
    assert spawner.children[0].killed and result.error is None


def test_capture_uses_the_injected_capture_spawner():
    spawner = SshCaptureSpawner(("out", "", 0))
    result = Commands(capture_spawner=spawner, clock=Clock()).capture(CaptureSpec(("remote", "cat")))
    assert result.ok and result.stdout == "out"
    assert [s.argv for s in spawner.specs] == [("remote", "cat")]


def test_stream_uses_the_injected_stream_spawner():
    class Stream:
        pid, start_error, returncode, timed_out = 1, None, 0, False

        def __iter__(self):
            return iter(["a\n", "b\n"])

        def kill(self):
            pass

        def close(self):
            pass

    class Spawner:
        def open_stream(self, spec):
            return Stream()

    lines = list(Commands(stream_spawner=Spawner()).stream(StreamSpec(("remote", "tail"))))
    assert lines == ["a\n", "b\n"]


def test_an_injected_commands_object_is_what_the_module_functions_use():
    spawner = SshSpawner(code=0)
    with api.use_commands(Commands(spawner=spawner, clock=Clock())):
        result = api.run(RunSpec(("remote", "x")))
    assert result.ok and [s.argv for s in spawner.specs] == [("remote", "x")]


def test_unreplaced_operations_still_run_real_children():
    commands = Commands(spawner=SshSpawner())  # only run() is replaced
    done = commands.capture(CaptureSpec((sys.executable, "-c", "print(5)"), timeout_seconds=30))
    assert done.ok and done.stdout.strip() == "5"


@pytest.mark.parametrize("name", api.__all__)
def test_every_declared_name_exists(name):
    assert hasattr(api, name)
