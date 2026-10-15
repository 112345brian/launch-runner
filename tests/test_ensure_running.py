from __future__ import annotations

import pytest

from commandport.domain import LaunchMethod, LaunchResult
from ensure_running import ConditionState, Outcome, Reconciler, Target


class Launcher:
    def __init__(self, result=None):
        self.specs, self.result = [], result or LaunchResult(LaunchMethod.SPAWNED, pid=1)

    def launch(self, spec):
        self.specs.append(spec)
        return self.result


class Cond:
    def __init__(self, state):
        self.state = state

    def check(self, target):
        if isinstance(self.state, Exception):
            raise self.state
        return self.state


T = Target("proj", ("claude", "remote-control"), cwd="/p", max_starts=2, window_seconds=100)


def run(state, launcher=None, **kw):
    launcher = launcher or Launcher()
    clock = kw.pop("clock", lambda: 1000.0)
    r = Reconciler(launcher, Cond(state), now=clock, **kw)
    return r, launcher, r.reconcile([T])[0]


def test_satisfied_starts_nothing():
    _, l, res = run(ConditionState.SATISFIED)
    assert res.outcome is Outcome.OK and not l.specs


@pytest.mark.parametrize("state", [ConditionState.UNKNOWN, RuntimeError("boom")])
def test_unknown_or_raising_condition_starts_nothing(state):
    _, l, res = run(state)
    assert res.outcome is Outcome.UNKNOWN and not l.specs


def test_unsatisfied_starts_named_service():
    _, l, res = run(ConditionState.UNSATISFIED)
    assert res.outcome is Outcome.STARTED and l.specs[0].name == "proj" and l.specs[0].cwd == "/p"


def test_failed_start_is_reported_not_raised():
    bad = Launcher(LaunchResult(LaunchMethod.FAILED, error="nope"))
    _, _, res = run(ConditionState.UNSATISFIED, bad)
    assert res.outcome is Outcome.START_FAILED and not res.healthy and res.detail == "nope"


def test_restart_cap_throttles_and_window_expires():
    t = [1000.0]
    r, l, _ = run(ConditionState.UNSATISFIED, clock=lambda: t[0])
    r.reconcile([T])
    assert r.reconcile([T])[0].outcome is Outcome.THROTTLED and len(l.specs) == 2
    t[0] += 101
    assert r.reconcile([T])[0].outcome is Outcome.STARTED


def test_dry_run_starts_nothing():
    _, l, res = run(ConditionState.UNSATISFIED, dry_run=True)
    assert res.outcome is Outcome.DRY_RUN and not l.specs
