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
from proclaunch.adapters.psutil_inspector import PsutilInspector
from proclaunch.adapters.subprocess_spawner import SubprocessSpawner
from proclaunch.adapters.system_clock import SystemClock
from proclaunch.adapters.task_scheduler import TaskSchedulerSupervisor
from proclaunch.adapters.windows import windowless_flags
from commandport.domain import LaunchResult, ProcessSpec
from proclaunch.domain import ServiceStatus, StopResult, WaitResult
from proclaunch.launching import Launcher
from commandport.ports import Supervisor
from proclaunch.ports import Probe
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
    (``commandport.testing.FakeSupervisors``) so a test can never end a real scheduled task."""
    global _supervisor_factory_override
    previous, _supervisor_factory_override = _supervisor_factory_override, factory
    try:
        yield
    finally:
        _supervisor_factory_override = previous


def default_launcher() -> Launcher:
    """The real launcher, or the one a test bound with :func:`use_launcher`."""
    if _launcher_override is not None:
        return _launcher_override
    return Launcher(SubprocessSpawner())


def default_manager(state_dir: Path) -> ServiceManager:
    return ServiceManager(
        launcher=default_launcher(),
        inspector=PsutilInspector(),
        store=JsonFileRecordStore(state_dir),
        clock=SystemClock(),
    )


_launcher_override = None


def launch_background(spec: ProcessSpec) -> LaunchResult:
    """Start *spec* detached and windowless. Never raises; see ``LaunchResult`` (callers must consume it)."""
    return default_launcher().launch(spec)


@contextlib.contextmanager
def use_launcher(launcher) -> Iterator[None]:
    """Bind *launcher* (anything with ``launch(spec) -> LaunchResult``) for the ``with`` block: the seam tests
    use (``commandport.testing.FakeLauncher``) instead of patching ``subprocess.Popen``."""
    global _launcher_override
    previous, _launcher_override = _launcher_override, launcher
    try:
        yield
    finally:
        _launcher_override = previous


def start_service(spec: ProcessSpec, *, state_dir: Path, supersede: bool = False) -> LaunchResult:
    return default_manager(state_dir).start(spec, supersede=supersede)


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

    True when nothing of it remains (including when it was already gone)."""
    inspector = PsutilInspector()
    identity = inspector.identify(pid)
    if identity is None:
        return True
    return inspector.terminate(identity, timeout)
