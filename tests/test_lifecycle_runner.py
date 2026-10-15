"""lifecycle_runner: run a command to completion with a time limit and a log.

Core behaviour is tested against fakes (a child that hangs forever, one whose
wait fails, a spawner that cannot start); the real ``Popen`` adapter gets a few
short integration tests with ``sys.executable``.
"""
from __future__ import annotations

import math
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from lifecycle_runner import __main__ as cli
from lifecycle_runner import api
from lifecycle_runner.domain import RunOutcome, RunResult, RunSpec
from lifecycle_runner.runner import Runner

REPO = Path(__file__).resolve().parent.parent


# ---- fakes ---------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def monotonic(self) -> float:
        self.t += 1.0
        return self.t


class FakeChild:
    pid = 1234

    def __init__(self, *, code=0, hang=False, wait_raises=None, kill_ok=True, code_after_kill=-9) -> None:
        self.code = code
        self.hang = hang
        self.wait_raises = wait_raises
        self.kill_ok = kill_ok
        self.code_after_kill = code_after_kill
        self.killed = False
        self.wait_timeouts: list[float | None] = []

    def wait(self, timeout):
        self.wait_timeouts.append(timeout)
        if self.wait_raises is not None:
            raise self.wait_raises
        if self.killed:
            return self.code_after_kill
        return None if self.hang else self.code

    def kill(self) -> bool:
        self.killed = True
        return self.kill_ok


class FakeSpawner:
    def __init__(self, child=None, raises=None) -> None:
        self.child = child
        self.raises = raises
        self.specs: list[RunSpec] = []

    def spawn(self, spec):
        self.specs.append(spec)
        if self.raises is not None:
            raise self.raises
        return self.child


def _run(child=None, raises=None, **spec_kwargs) -> tuple[RunResult, FakeChild | None]:
    spec = RunSpec(argv=("cmd",), **spec_kwargs)
    result = Runner(FakeSpawner(child, raises), FakeClock()).run(spec)
    return result, child


# ---- the result's meaning --------------------------------------------------


def test_a_clean_exit_is_ok():
    result, child = _run(FakeChild(code=0))
    assert result.outcome is RunOutcome.COMPLETED and result.returncode == 0 and result.ok
    assert not child.killed


def test_a_nonzero_exit_is_completed_but_not_ok():
    result, _ = _run(FakeChild(code=3))
    assert result.outcome is RunOutcome.COMPLETED
    assert result.returncode == 3
    assert not result.ok


def test_the_timeout_is_passed_to_the_wait_and_a_hang_is_killed_and_reported_as_timed_out():
    result, child = _run(FakeChild(hang=True), timeout_seconds=30)
    assert child.wait_timeouts[0] == 30
    assert child.killed
    assert result.outcome is RunOutcome.TIMED_OUT
    assert not result.ok
    assert result.error is None  # the tree was gone


def test_a_timed_out_run_is_not_ok_even_when_the_killed_child_reports_exit_zero():
    result, _ = _run(FakeChild(hang=True, code_after_kill=0), timeout_seconds=1)
    assert result.outcome is RunOutcome.TIMED_OUT
    assert result.returncode == 0
    assert not result.ok


def test_a_surviving_process_tree_is_reported_on_a_timeout():
    result, _ = _run(FakeChild(hang=True, kill_ok=False), timeout_seconds=1)
    assert result.outcome is RunOutcome.TIMED_OUT
    assert "survived" in (result.error or "")


def test_no_timeout_waits_without_a_deadline():
    result, child = _run(FakeChild(code=0))
    assert child.wait_timeouts == [None]
    assert result.ok


def test_a_failing_wait_kills_the_child_and_is_an_error_not_a_raise():
    result, child = _run(FakeChild(wait_raises=RuntimeError("pipe broke")))
    assert result.outcome is RunOutcome.ERROR
    assert "pipe broke" in result.error
    assert child.killed
    assert not result.ok


def test_a_spawn_failure_is_failed_to_start_with_the_reason():
    result, _ = _run(raises=FileNotFoundError("executable not found: cmd"))
    assert result.outcome is RunOutcome.FAILED_TO_START
    assert "executable not found" in result.error
    assert result.returncode is None and not result.ok


def test_keyboard_interrupt_kills_the_child_and_propagates():
    child = FakeChild(wait_raises=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        Runner(FakeSpawner(child), FakeClock()).run(RunSpec(argv=("cmd",)))
    assert child.killed


def test_elapsed_comes_from_the_clock():
    result, _ = _run(FakeChild(code=0))
    assert result.elapsed > 0


# ---- RunSpec edge inputs ---------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"argv": ()},
        {"argv": ("",)},
        {"argv": ("   ",)},
        {"argv": ("a\0b",)},
        {"argv": ("ok", "bad\0arg")},
        {"argv": ("ok",), "timeout_seconds": 0},
        {"argv": ("ok",), "timeout_seconds": -1},
        {"argv": ("ok",), "timeout_seconds": math.nan},
        {"argv": ("ok",), "timeout_seconds": math.inf},
        {"argv": ("ok",), "timeout_seconds": True},
        {"argv": ("ok",), "env": {"A=B": "x"}},
        {"argv": ("ok",), "env": {"": "x"}},
        {"argv": ("ok",), "env": {"A": "x\0"}},
        {"argv": ("ok",), "env": {"A": 1}},
    ],
)
def test_a_malformed_spec_is_rejected_up_front(kwargs):
    with pytest.raises(ValueError):
        RunSpec(**kwargs)


def test_an_unlimited_run_has_no_timeout_and_an_env_overlay_is_accepted():
    spec = RunSpec(argv=("ok",), env={"A": "1"})
    assert spec.timeout_seconds is None


# ---- the real adapter --------------------------------------------------------


def _py(code: str, **kwargs) -> RunSpec:
    return RunSpec(argv=(sys.executable, "-c", code), **kwargs)


def test_output_and_errors_are_appended_to_the_log(tmp_path):
    log = tmp_path / "logs" / "job.log"
    first = api.run(_py("import sys; print('out1'); print('err1', file=sys.stderr)", log_path=log, timeout_seconds=30))
    second = api.run(_py("print('out2')", log_path=log, timeout_seconds=30))
    assert first.ok and second.ok
    text = log.read_text(encoding="utf-8")
    assert "out1" in text and "err1" in text and "out2" in text
    assert text.index("out1") < text.index("out2")  # appended, not truncated


def test_the_exit_code_is_reported(tmp_path):
    result = api.run(_py("raise SystemExit(7)", log_path=tmp_path / "x.log", timeout_seconds=30))
    assert result.outcome is RunOutcome.COMPLETED
    assert result.returncode == 7 and not result.ok


def test_env_overlay_reaches_the_child(tmp_path):
    log = tmp_path / "env.log"
    result = api.run(_py(
        "import os; print(os.environ['LR_PROBE'])", log_path=log, env={"LR_PROBE": "hello-env"}, timeout_seconds=30,
    ))
    assert result.ok
    assert "hello-env" in log.read_text(encoding="utf-8")


def test_a_hang_is_killed_at_the_deadline_and_its_children_with_it(tmp_path):
    log = tmp_path / "hang.log"
    grandchild = (
        "import subprocess, sys, time\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "print(p.pid, flush=True)\n"
        "time.sleep(120)\n"
    )
    started = time.monotonic()
    result = api.run(_py(grandchild, log_path=log, timeout_seconds=3))
    took = time.monotonic() - started
    assert result.outcome is RunOutcome.TIMED_OUT and not result.ok
    assert took < 30
    pid = int(log.read_text(encoding="utf-8").split()[0])
    deadline = time.monotonic() + 5
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not psutil.pid_exists(pid), "the grandchild outlived the timeout kill"


def test_a_missing_executable_is_failed_to_start():
    result = api.run(RunSpec(argv=("definitely-not-a-real-executable-xyz",), timeout_seconds=5))
    assert result.outcome is RunOutcome.FAILED_TO_START
    assert "not found" in result.error


def test_a_missing_cwd_is_failed_to_start(tmp_path):
    result = api.run(_py("pass", cwd=str(tmp_path / "nope"), timeout_seconds=5))
    assert result.outcome is RunOutcome.FAILED_TO_START


def test_an_unwritable_log_is_failed_to_start_and_runs_nothing(tmp_path):
    log = tmp_path / "is_a_dir.log"
    log.mkdir()
    marker = tmp_path / "ran"
    result = api.run(_py(f"open({str(marker)!r}, 'w').close()", log_path=log, timeout_seconds=5))
    assert result.outcome is RunOutcome.FAILED_TO_START
    assert not marker.exists()


def test_no_log_discards_output(tmp_path):
    result = api.run(_py("print('x' * 100000)", timeout_seconds=30))
    assert result.ok and result.log_path is None


# ---- callers must consume results -----------------------------------------




# ---- ``python -m lifecycle_runner``: the form a scheduler task invokes ------


def _invoke(*args: str, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "lifecycle_runner", *args],
        cwd=REPO, capture_output=True, text=True, timeout=timeout,
    )


def test_cli_passes_the_commands_exit_code_through_and_logs_its_output(tmp_path):
    log = tmp_path / "r.log"
    done = _invoke("--log", str(log), "--timeout", "30", "--", sys.executable, "-c",
                   "import sys; print('hello'); sys.exit(5)")
    assert done.returncode == 5
    assert "hello" in log.read_text(encoding="utf-8")


def test_cli_a_clean_run_exits_zero(tmp_path):
    assert _invoke("--log", str(tmp_path / "ok.log"), "--", sys.executable, "-c", "pass").returncode == 0


def test_cli_a_timeout_exits_124_and_the_log_says_why(tmp_path):
    log = tmp_path / "t.log"
    done = _invoke("--log", str(log), "--timeout", "2", "--", sys.executable, "-c",
                   "import time; print('start', flush=True); time.sleep(60)")
    assert done.returncode == cli.EXIT_TIMED_OUT
    text = log.read_text(encoding="utf-8")
    assert "start" in text and "killed after 2s timeout" in text


def test_cli_a_hung_python_childs_unflushed_output_survives_the_kill(tmp_path):
    # A Python child writing to a file block-buffers stdout and a kill does not
    # flush it, so without PYTHONUNBUFFERED the log would not show what the
    # routine was doing when it hung -- exactly when the log is wanted.
    log = tmp_path / "hang.log"
    done = _invoke("--log", str(log), "--timeout", "2", "--", sys.executable, "-c",
                   "print('before-hang'); import time; time.sleep(60)")
    assert done.returncode == cli.EXIT_TIMED_OUT
    assert "before-hang" in log.read_text(encoding="utf-8")


def test_cli_stdout_and_stderr_reach_the_log_in_the_order_they_were_written(tmp_path):
    log = tmp_path / "order.log"
    done = _invoke("--log", str(log), "--timeout", "30", "--", sys.executable, "-c",
                   "import sys; print('out-line'); print('err-line', file=sys.stderr)")
    assert done.returncode == 0
    text = log.read_text(encoding="utf-8")
    assert text.index("out-line") < text.index("err-line")


def test_cli_an_unstartable_command_exits_127_and_the_log_says_why(tmp_path):
    log = tmp_path / "n.log"
    done = _invoke("--log", str(log), "--", "definitely-not-a-real-executable-xyz")
    assert done.returncode == cli.EXIT_NOT_STARTED
    assert "could not start" in log.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "args",
    [
        [],  # no command
        ["--log", "x.log", "--"],  # nothing after the separator
        ["--timeout", "0", "--", "cmd"],  # invalid limit
        ["--timeout", "nan", "--", "cmd"],
    ],
)
def test_cli_bad_arguments_exit_125_and_run_nothing(args, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(args) == cli.EXIT_RUNNER_FAILED


def test_cli_the_command_may_carry_option_like_arguments(tmp_path):
    log = tmp_path / "o.log"
    done = _invoke("--log", str(log), "--", sys.executable, "-c", "print('--log', '-x')")
    assert done.returncode == 0
    assert "--log -x" in log.read_text(encoding="utf-8")


def test_cli_does_not_import_the_application():
    # Its job is to log a routine's failure, so a broken application import must
    # not be able to take it down first.
    code = (
        "import sys, runpy\n"
        "from lifecycle_runner import __main__ as m\n"
        "m.main(['--', sys.executable, '-c', 'pass'])\n"
        "bad = sorted(n for n in sys.modules if n.split('.')[0] in "
        "{'jobsearch', 'tracker', 'state', 'llm', 'jobsearch_cli'})\n"
        "print('IMPORTED', bad)\n"
    )
    done = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=60)
    assert "IMPORTED []" in done.stdout, done.stdout + done.stderr
