"""Bounded readiness wait. Adapted from dmon (MIT); see THIRD_PARTY_NOTICES.md.

Depends on the ``Probe`` and ``Clock`` ports only.
"""
from __future__ import annotations

from collections.abc import Callable

from proclaunch.domain import WaitResult
from proclaunch.ports import Clock, Probe

Check = Callable[[], bool]


def wait_for_readiness(
    probe: Probe,
    *,
    clock: Clock,
    timeout: float = 30.0,
    interval: float = 0.2,
    process_running: Check | None = None,
    stop_requested: Check | None = None,
    listener_owned: Check | None = None,
) -> WaitResult:
    """Poll until healthy, the deadline passes, or the process dies. The process
    is checked both before and after a successful probe, so an unrelated server
    answering on the port cannot make a crashed service look healthy."""
    started = clock.monotonic()
    deadline = started + timeout
    attempts = 0
    ownership_verified = not probe.require_owned

    def done(ready: bool, reason: str) -> WaitResult:
        return WaitResult(ready, reason, clock.monotonic() - started, attempts)

    while True:
        if stop_requested is not None and stop_requested():
            return done(False, "stopped")
        if process_running is not None and not process_running():
            return done(False, "process-exited")
        remaining = max(0.0, deadline - clock.monotonic())
        if remaining == 0:
            return done(False, "timeout" if ownership_verified else "listener-unverified")
        attempts += 1
        ownership_verified = not probe.require_owned or (listener_owned is not None and listener_owned())
        if ownership_verified and probe.run(min(max(1.0, interval), remaining)):
            if process_running is not None and not process_running():
                return done(False, "process-exited")
            if stop_requested is not None and stop_requested():
                return done(False, "stopped")
            if probe.require_owned and (listener_owned is None or not listener_owned()):
                ownership_verified = False
            else:
                return done(True, "ready")
        clock.sleep(min(interval, max(0.0, deadline - clock.monotonic())))
