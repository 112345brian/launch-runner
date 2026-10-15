"""lifecycle_runner's capture / stream / attached operations.

Behaviour is tested against fake children (no process), the real Popen adapters are exercised end to end
with the current interpreter as the child, and the windowless contract is asserted on every adapter."""
from __future__ import annotations

import sys

import pytest

from lifecycle_runner import api
from lifecycle_runner.adapters import popen_capture, popen_spawner
from lifecycle_runner.capture import Capturer
from lifecycle_runner.domain import CaptureSpec, RunOutcome, RunSpec, StreamSpec
from lifecycle_runner.adapters.windows import windowless_creationflags
from lifecycle_runner.testing import FakeCommandRunner


class ScriptedClock:
    """Each call returns the next scripted reading, so a measured duration is exact and no time passes."""

    def __init__(self, *readings: float) -> None:
        self._readings = iter(readings)

    def __call__(self) -> float:
        return next(self._readings)


class _PortClock:
    """lifecycle_runner's Clock port is a ``monotonic()`` method; adapt the scripted callable to it."""

    def __init__(self, *readings: float) -> None:
        self._clock = ScriptedClock(*readings)

    def monotonic(self) -> float:
        return self._clock()

PY = sys.executable


def _py(code: str) -> tuple[str, ...]:
    return (PY, "-c", code)


# --------------------------------------------------------------------------- the capturer, with fake children
class _Child:
    pid = 1

    def __init__(self, *, answer=("out", "err", 0), raises=None, partial=("part", "")) -> None:
        self._answer, self._raises, self._partial = answer, raises, partial
        self.killed = False
        self.stdin_seen = "unset"

    def communicate(self, stdin_text, timeout):
        self.stdin_seen = stdin_text
        if self._raises is not None:
            raise self._raises
        return self._answer

    def partial_output(self):
        return self._partial

    def kill(self) -> bool:
        self.killed = True
        return True


class _Spawner:
    def __init__(self, child=None, raises=None) -> None:
        self.child, self.raises = child, raises

    def spawn_captured(self, spec):
        if self.raises is not None:
            raise self.raises
        return self.child


def _capturer(child=None, raises=None) -> Capturer:
    return Capturer(_Spawner(child, raises), _PortClock(*([0.0, 1.5] * 4)))


SPEC = CaptureSpec(("tool", "--flag"), timeout_seconds=5)


def test_a_completed_command_reports_its_output_and_exit_code():
    result = _capturer(_Child(answer=("hello", "warn", 3))).capture(SPEC)
    assert (result.outcome, result.returncode, result.stdout, result.stderr) == (RunOutcome.COMPLETED, 3, "hello", "warn")
    assert result.completed and not result.ok and result.elapsed == 1.5


def test_a_zero_exit_is_ok():
    assert _capturer(_Child(answer=("x", "", 0))).capture(SPEC).ok


def test_a_timeout_kills_the_child_and_keeps_the_partial_output():
    child = _Child(answer=None, partial=("half a line", "oops"))
    result = _capturer(child).capture(SPEC)
    assert result.outcome is RunOutcome.TIMED_OUT and child.killed
    assert (result.stdout, result.stderr, result.returncode) == ("half a line", "oops", None)
    assert not result.completed and not result.ok


def test_a_command_that_cannot_start_is_a_result_not_an_exception():
    result = _capturer(raises=FileNotFoundError("claude")).capture(SPEC)
    assert result.outcome is RunOutcome.FAILED_TO_START and "FileNotFoundError" in result.error


def test_a_wait_that_fails_kills_the_child_and_reports_error():
    child = _Child(raises=RuntimeError("pipe broke"))
    result = _capturer(child).capture(SPEC)
    assert result.outcome is RunOutcome.ERROR and child.killed and "pipe broke" in result.error


def test_ctrl_c_kills_the_child_then_propagates():
    child = _Child(raises=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        _capturer(child).capture(SPEC)
    assert child.killed


def test_stdin_text_reaches_the_child():
    child = _Child()
    _capturer(child).capture(CaptureSpec(("tool",), stdin_text="payload"))
    assert child.stdin_seen == "payload"


# --------------------------------------------------------------------------- spec validation
@pytest.mark.parametrize("make", [
    lambda: CaptureSpec(()),
    lambda: CaptureSpec(("",)),
    lambda: CaptureSpec(("a\0b",)),
    lambda: CaptureSpec(("a",), timeout_seconds=0),
    lambda: CaptureSpec(("a",), timeout_seconds=True),
    lambda: CaptureSpec(("a",), timeout_seconds=float("inf")),
    lambda: CaptureSpec(("a",), env={"K=": "v"}),
    lambda: StreamSpec(()),
    lambda: StreamSpec(("a",), timeout_seconds=-1),
    lambda: RunSpec(("a",), inherit_stdio=True, log_path=__import__("pathlib").Path("x.log")),
])
def test_bad_specs_are_rejected_at_construction(make):
    with pytest.raises(ValueError):
        make()


# --------------------------------------------------------------------------- real processes (the adapters)
def test_capture_separates_stdout_and_stderr_and_reads_the_exit_code():
    code = "import sys; print('out'); print('err', file=sys.stderr); sys.exit(4)"
    result = api.capture(CaptureSpec(_py(code), timeout_seconds=30))
    assert result.completed and result.returncode == 4
    assert result.stdout == "out\n" and result.stderr == "err\n"


def test_capture_can_merge_stderr_into_stdout():
    code = "import sys; print('a'); sys.stdout.flush(); print('b', file=sys.stderr)"
    result = api.capture(CaptureSpec(_py(code), timeout_seconds=30, merge_stderr=True))
    assert result.ok and sorted(result.stdout.split()) == ["a", "b"] and result.stderr == ""


def test_capture_feeds_stdin_and_closes_it_otherwise():
    echo = _py("import sys; sys.stdout.write(sys.stdin.read().upper())")
    assert api.capture(CaptureSpec(echo, timeout_seconds=30, stdin_text="abc")).stdout == "ABC"
    # No stdin_text: stdin is closed, so a child that reads gets EOF at once instead of hanging.
    assert api.capture(CaptureSpec(echo, timeout_seconds=30)).stdout == ""


def test_capture_decodes_utf8_and_replaces_bad_bytes_and_normalises_newlines():
    code = (
        "import sys; sys.stdout.buffer.write("
        "'caf\\u00e9 \\u2014 ok'.encode('utf-8') + b'\\xff\\r\\nline2\\r')"
    )
    out = api.capture(CaptureSpec(_py(code), timeout_seconds=30)).stdout
    assert out.startswith("café — ok") and "�" in out
    assert "\r" not in out and out.endswith("line2\n")


def test_capture_times_out_kills_and_returns_what_was_printed():
    code = "import sys, time; print('started', flush=True); time.sleep(60)"
    result = api.capture(CaptureSpec(_py(code), timeout_seconds=1.5))
    assert result.outcome is RunOutcome.TIMED_OUT and result.returncode is None
    assert "started" in result.stdout and result.elapsed < 30


def test_capture_of_a_missing_executable_is_failed_to_start():
    result = api.capture(CaptureSpec(("definitely-not-a-real-binary-xyz",), timeout_seconds=5))
    assert result.outcome is RunOutcome.FAILED_TO_START and "not found" in result.error


def test_capture_passes_cwd_and_overlays_env(tmp_path):
    code = "import os; print(os.getcwd()); print(os.environ['LC_PROBE'])"
    result = api.capture(CaptureSpec(_py(code), cwd=str(tmp_path), env={"LC_PROBE": "yes"}, timeout_seconds=30))
    cwd_line, probe = result.stdout.split()
    assert probe == "yes" and cwd_line.lower().endswith(tmp_path.name.lower())


def test_stream_yields_lines_then_the_exit_code():
    stream = api.stream(StreamSpec(_py("print('one'); print('two')"), timeout_seconds=30))
    assert stream.start_error is None
    assert list(stream) == ["one\n", "two\n"]
    assert stream.returncode == 0 and not stream.timed_out
    stream.close()
    stream.close()  # idempotent


def test_stream_watchdog_kills_a_command_that_hangs_without_closing_output():
    code = "import time; print('tick', flush=True); time.sleep(60)"
    stream = api.stream(StreamSpec(_py(code), timeout_seconds=1.5))
    assert list(stream)[0] == "tick\n"
    assert stream.timed_out and stream.returncode != 0
    stream.close()


def test_stream_of_a_missing_executable_reports_start_error():
    stream = api.stream(StreamSpec(("definitely-not-a-real-binary-xyz",)))
    assert stream.start_error and list(stream) == [] and stream.pid is None


def test_stream_close_kills_a_child_the_caller_abandoned():
    stream = api.stream(StreamSpec(_py("import time; time.sleep(60)")))
    assert stream.pid is not None
    stream.close()
    assert stream.returncode is not None


def test_run_attached_without_a_console_discards_output_and_reports_the_exit_code():
    # The test process has no console to inherit under a runner, so this exercises the windowless path.
    result = api.run(RunSpec(_py("import sys; print('x'); sys.exit(2)"), inherit_stdio=True, timeout_seconds=30))
    assert result.outcome is RunOutcome.COMPLETED and result.returncode == 2


# --------------------------------------------------------------------------- the windowless contract
def test_every_adapter_spawn_is_windowless(monkeypatch):
    seen: list[tuple[str, int | None]] = []

    class _Proc:
        pid = 9
        stdout = None
        returncode = 0

        def communicate(self, input=None, timeout=None):
            return b"", b""

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    def fake_popen(argv, **kwargs):
        seen.append((argv[0], kwargs.get("creationflags")))
        return _Proc()

    monkeypatch.setattr(popen_capture.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(popen_spawner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(popen_capture.shutil, "which", lambda name: name)
    monkeypatch.setattr(popen_spawner.shutil, "which", lambda name: name)
    monkeypatch.setattr(popen_spawner, "_caller_has_console", lambda: False)

    popen_capture.PopenCaptureSpawner().spawn_captured(CaptureSpec(("capture-me",)))
    popen_capture.PopenStreamSpawner().open_stream(StreamSpec(("stream-me",))).close()
    popen_spawner.PopenSpawner().spawn(RunSpec(("run-me",)))
    popen_spawner.PopenSpawner().spawn(RunSpec(("attach-me",), inherit_stdio=True))

    assert [name for name, _ in seen] == ["capture-me", "stream-me", "run-me", "attach-me"]
    assert all(flags == windowless_creationflags() for _, flags in seen), seen


def test_the_fake_command_runner_implements_the_operation_ports():
    fake = FakeCommandRunner().when("agents", stdout="[]").timeout("slow").not_found("ghost")
    with api.use_commands(fake):
        assert api.capture(CaptureSpec(("claude", "agents", "--json"))).stdout == "[]"
        assert api.capture(CaptureSpec(("slow", "thing"))).outcome is RunOutcome.TIMED_OUT
        assert api.capture(CaptureSpec(("ghost",))).outcome is RunOutcome.FAILED_TO_START
        with pytest.raises(AssertionError, match="no rule matches"):
            api.capture(CaptureSpec(("unscripted",)))
    assert fake.argvs()[0] == ("claude", "agents", "--json")
    # The binding is restored afterwards: a real command runs again.
    assert api.capture(CaptureSpec(_py("print('real')"), timeout_seconds=30)).stdout == "real\n"


def test_a_watchdog_that_fires_after_the_child_already_exited_is_not_reported_as_a_timeout():
    """A timer firing just as the child exits normally must not mask its real exit code with a spurious
    timeout (the refresh stream's old, hand-rolled version of this guard moved here)."""

    class _Exited:
        pid = 7
        stdout = None
        killed = False

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.killed = True

    proc = _Exited()
    stream = popen_capture.PopenLineStream(proc, None)
    stream._on_timeout()  # what the timer would call
    assert stream.timed_out is False and stream.returncode == 0 and proc.killed is False
