"""Composition root: wires the real adapters into the application.

This is the only module that imports both the application and the adapters;
callers use these functions (or build a ``ServiceManager`` with their own
ports, as the tests do).
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path

from proclaunch.adapters.json_record_store import JsonFileRecordStore
from proclaunch.adapters.launchd import LaunchdSupervisor
from proclaunch.adapters.probes import CallableProbe, HttpProbe, TcpProbe
from proclaunch.adapters.psutil_inspector import PsutilInspector
from proclaunch.adapters.pty_spawner import PtySpawner
from proclaunch.adapters.subprocess_spawner import SubprocessSpawner
from proclaunch.adapters.system_clock import SystemClock
from proclaunch.adapters.task_scheduler import TaskSchedulerSupervisor
from proclaunch.adapters.windows import windowless_flags
from proclaunch.domain import (
    EndResult, LaunchMethod, LaunchResult, ProcessSpec, ServiceStatus, StopOutcome, StopResult, WaitResult,
)
from proclaunch.launching import Launcher
from proclaunch.ports import (
    BackgroundLauncher, Clock, Probe, ProcessInspector, ProcessSpawner, RecordStore, Supervisor,
)
from proclaunch.readiness import wait_for_readiness as _wait_for_readiness
from proclaunch.services import ServiceManager


_supervisor_factory_override = None


def task_scheduler_supervisor(task_name: str) -> Supervisor:
    """A Windows Task Scheduler ``Supervisor`` for the named task.

    A deliberate public factory, not a shortcut re-export: callers get the
    ``Supervisor`` port without naming the concrete adapter, so only this
    module imports ``proclaunch.adapters`` (enforced by
    ``tests/test_proclaunch_architecture.py``). Its ``end()`` is how callers
    end a logon task; ``available()`` is False off Windows.
    """
    if _supervisor_factory_override is not None:
        return _supervisor_factory_override(task_name)
    return TaskSchedulerSupervisor(task_name)


@contextlib.contextmanager
def use_supervisor(factory) -> Iterator[None]:
    """Bind *factory* (``task_name -> Supervisor``) for the ``with`` block: the seam tests use
    (``proclaunch.testing.FakeSupervisors``) so a test can never end a real scheduled task."""
    global _supervisor_factory_override
    previous, _supervisor_factory_override = _supervisor_factory_override, factory
    try:
        yield
    finally:
        _supervisor_factory_override = previous


def default_launcher(spawner: ProcessSpawner | None = None) -> BackgroundLauncher:
    """The launcher over *spawner* (default: a detached, windowless ``subprocess`` spawn), or the one a test
    bound with :func:`use_launcher`. A bound launcher takes precedence over *spawner*: it is the seam that keeps
    a test from starting a real process, so it must not be bypassable by code that injects its own spawner."""
    if _launcher_override is not None:
        return _launcher_override
    return Launcher(spawner if spawner is not None else SubprocessSpawner())


def default_manager(
    state_dir: Path,
    *,
    spawner: ProcessSpawner | None = None,
    inspector: ProcessInspector | None = None,
    store: RecordStore | None = None,
    clock: Clock | None = None,
) -> ServiceManager:
    """A :class:`ServiceManager` over the real collaborators; each keyword replaces just that one.

    Typical use is a different way of starting the process (``spawner=PtySpawner()``) while the reservation,
    identity and record handling stay proclaunch's own."""
    return ServiceManager(
        launcher=default_launcher(spawner),
        inspector=inspector if inspector is not None else PsutilInspector(),
        store=store if store is not None else JsonFileRecordStore(state_dir),
        clock=clock if clock is not None else SystemClock(),
    )


_launcher_override = None


def launch_background(spec: ProcessSpec, *, spawner: ProcessSpawner | None = None) -> LaunchResult:
    """Start *spec* detached and windowless. Never raises; see ``LaunchResult`` (callers must consume it).

    This does not record a service: ``spec.name`` is ignored here. Use :func:`start_service` for a named,
    recorded, identity-checked service. *spawner* replaces how the process is started (see
    :func:`default_launcher` for its precedence relative to a test-bound launcher)."""
    return default_launcher(spawner).launch(spec)


@contextlib.contextmanager
def use_launcher(launcher) -> Iterator[None]:
    """Bind *launcher* (anything with ``launch(spec) -> LaunchResult``) for the ``with`` block: the seam tests
    use (``proclaunch.testing.FakeLauncher``) instead of patching ``subprocess.Popen``."""
    global _launcher_override
    previous, _launcher_override = _launcher_override, launcher
    try:
        yield
    finally:
        _launcher_override = previous


def start_service(
    spec: ProcessSpec, *, state_dir: Path, supersede: bool = False, spawner: ProcessSpawner | None = None,
) -> LaunchResult:
    """Start *spec* as the service ``spec.name``: reserve, launch, identify, record. *spawner* replaces only
    how the process is started."""
    return default_manager(state_dir, spawner=spawner).start(spec, supersede=supersede)


def stop_service(name: str, *, state_dir: Path, timeout: float = 5.0) -> StopResult:
    return default_manager(state_dir).stop(name, timeout=timeout)


def service_status(name: str, *, state_dir: Path) -> ServiceStatus:
    return default_manager(state_dir).status(name)


def register_self(name: str, *, state_dir: Path) -> bool:
    return default_manager(state_dir).register_self(name)


def wait_for_readiness(probe: Probe, **kwargs) -> WaitResult:
    return _wait_for_readiness(probe, clock=SystemClock(), **kwargs)


def windowless_creationflags() -> int:
    """``creationflags`` for a foreground child that must not show a console window.

    The one definition of "no window", exposed so a sibling library that runs
    a command to completion does not copy it."""
    return windowless_flags()


def terminate_process(pid: int, *, timeout: float = 5.0) -> bool:
    """Stop *pid* and its descendants, gracefully then by force.

    True when nothing remains of *pid*, its process group (POSIX) and the descendants that could be found
    before it was signalled (including when it was already gone). False when any of those survived, or could not
    be signalled. A descendant that was already orphaned, or that starts a new session after the snapshot, is
    not known and is not covered; there is no Windows job object here yet.

    Acts on whichever process currently owns *pid*: pass the pid of a child you own, or use a recorded
    identity (``ServiceManager.stop``) when the pid may have been reused."""
    inspector = PsutilInspector()
    identity = inspector.identify(pid)
    if identity is None:
        return True
    return inspector.terminate(identity, timeout)


# The public surface of proclaunch. The operations enforce the service-management invariants; the rest are the
# values they speak in, the ports a caller may implement to replace one collaborator, and ready-made
# implementations of those ports. ``ServiceManager`` and ``Launcher`` are importable from ``proclaunch.services``
# / ``proclaunch.launching`` for a caller assembling its own wiring; ``default_manager`` is the short way.
__all__ = [
    # operations
    "launch_background", "start_service", "stop_service", "service_status", "register_self",
    "wait_for_readiness", "terminate_process", "windowless_creationflags", "task_scheduler_supervisor",
    "default_manager", "default_launcher",
    # test seams
    "use_launcher", "use_supervisor",
    # values
    "ProcessSpec", "LaunchResult", "LaunchMethod", "EndResult", "ServiceStatus", "StopResult", "StopOutcome",
    "WaitResult",
    # ports a caller may implement
    "ProcessSpawner", "Probe", "Supervisor", "BackgroundLauncher", "ProcessInspector", "RecordStore", "Clock",
    # ready-made implementations
    "SubprocessSpawner", "PtySpawner", "HttpProbe", "TcpProbe", "CallableProbe", "LaunchdSupervisor",
]
