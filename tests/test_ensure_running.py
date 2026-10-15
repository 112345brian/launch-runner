from __future__ import annotations

import pytest

from ensure_running import Outcome, Reconciler, Target
from ensure_running.domain import StartOutcome, StartResult


class Launcher:
    def __init__(self, result=None):
        self.specs, self.result = [], result or StartResult(StartOutcome.STARTED, pid=1)

    def start(self, spec):
        self.specs.append(spec)
        return self.result


def answer(value):
    """A client's check: a plain callable returning a bool, or raising when it cannot tell."""
    def should_run(target):
        if isinstance(value, Exception):
            raise value
        return value
    return should_run


T = Target("proj", ("claude", "remote-control"), cwd="/p", max_starts=2, window_seconds=100)


def run(state, launcher=None, **kw):
    launcher = launcher or Launcher()
    clock = kw.pop("clock", lambda: 1000.0)
    r = Reconciler(launcher, answer(state), now=clock, **kw)
    return r, launcher, r.reconcile([T])[0]


def test_not_wanted_starts_nothing():
    _, l, res = run(False)
    assert res.outcome is Outcome.OK and not l.specs


@pytest.mark.parametrize("state", [RuntimeError("boom")])
def test_a_check_that_raises_starts_nothing(state):
    _, l, res = run(state)
    assert res.outcome is Outcome.UNKNOWN and not l.specs


def test_wanted_starts_named_service():
    _, l, res = run(True)
    assert res.outcome is Outcome.STARTED and l.specs[0].name == "proj" and l.specs[0].cwd == "/p"


def test_failed_start_is_reported_not_raised():
    bad = Launcher(StartResult(StartOutcome.FAILED, error="nope"))
    _, _, res = run(True, bad)
    assert res.outcome is Outcome.START_FAILED and not res.healthy and res.detail == "nope"


def test_restart_cap_throttles_and_window_expires():
    t = [1000.0]
    r, l, _ = run(True, clock=lambda: t[0])
    r.reconcile([T])
    assert r.reconcile([T])[0].outcome is Outcome.THROTTLED and len(l.specs) == 2
    t[0] += 101
    assert r.reconcile([T])[0].outcome is Outcome.STARTED


def test_dry_run_starts_nothing():
    _, l, res = run(True, dry_run=True)
    assert res.outcome is Outcome.DRY_RUN and not l.specs


@pytest.mark.parametrize("value", [None, "yes", 1, 0])
def test_only_a_real_true_starts_a_target(value):
    _, l, res = run(value)
    assert res.outcome is Outcome.OK and not l.specs


def test_already_running_service_is_ok_not_a_failure():
    l = Launcher(StartResult(StartOutcome.ALREADY_RUNNING, pid=9))
    _, _, res = run(True, l)
    assert res.outcome is Outcome.OK and res.healthy


def test_in_progress_is_not_started_and_not_known_running():
    l = Launcher(StartResult(StartOutcome.IN_PROGRESS, error="another start is in progress"))
    r, _, res = run(True, l)
    assert res.outcome is Outcome.START_FAILED and not res.healthy and res.start.outcome is StartOutcome.IN_PROGRESS
    assert r.history["proj"] == [], "a start that did not happen must not count against the restart cap"


def test_every_proclaunch_launch_method_maps_to_a_start_outcome():
    from ensure_running import api
    from proclaunch.domain import LaunchMethod

    assert set(api._OUTCOME) == set(LaunchMethod)


# ---- command checks run through a port ------------------------------------------------------------------


class FakeChecks:
    def __init__(self, *outputs):
        self.outputs, self.calls = list(outputs), []

    def run(self, argv, *, cwd, timeout_seconds):
        self.calls.append((argv, cwd, timeout_seconds))
        return self.outputs.pop(0)


def _checked(output, **kw):
    from ensure_running.conditions import CommandCheck

    runner = FakeChecks(output)
    target = Target("p", ("srv",), cwd="/p", check=("check", "--now"))
    return CommandCheck(runner, **kw), target, runner


@pytest.mark.parametrize(("code", "expected"), [(0, True), (1, False)])
def test_a_command_check_maps_exit_0_and_1(code, expected):
    from ensure_running.domain import CheckOutput

    check, target, runner = _checked(CheckOutput(code))
    assert check(target) is expected
    assert runner.calls == [(("check", "--now"), "/p", 30.0)]


@pytest.mark.parametrize("output", [("exit", 7, None), ("timeout", None, "timed out after 30s"),
                                    ("start", None, "FileNotFoundError: executable not found")])
def test_a_check_that_could_not_tell_raises_check_failed(output):
    from ensure_running.conditions import CheckFailed
    from ensure_running.domain import CheckOutput

    _, code, error = output
    check, target, _ = _checked(CheckOutput(code, error))
    with pytest.raises(CheckFailed):
        check(target)
