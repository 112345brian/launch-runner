"""Composition root and programmatic entry point.

The command line (``cli``) is one caller of this module; a program that wants to reconcile on its own schedule
calls :func:`run_once` directly, optionally replacing the starter, the check or the clock:

    from ensure_running import api, config

    cfg = config.load(path)
    for result in api.run_once(cfg):
        ...

The only module besides ``cli`` that names the sibling libraries: proclaunch starts and records the services,
and ``lifecycle_check`` runs command checks through lifecycle-runner. The reconciliation core never sees either.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from proclaunch.api import LaunchMethod, ProcessSpec, PtySpawner, ServiceManager, default_manager

from ensure_running import history as history_mod
from ensure_running.conditions import CommandCheck, service_not_running
from ensure_running.config import Config
from ensure_running.domain import (
    ServiceSpec, ServiceStarter, ShouldRun, StartOutcome, StartResult, Target, TargetResult,
)
from ensure_running.lifecycle_check import LifecycleCheckRunner
from ensure_running.reconciler import Reconciler

_OUTCOME = {
    LaunchMethod.SUPERVISED: StartOutcome.STARTED,
    LaunchMethod.SPAWNED: StartOutcome.STARTED,
    LaunchMethod.ALREADY_RUNNING: StartOutcome.ALREADY_RUNNING,
    LaunchMethod.IN_PROGRESS: StartOutcome.IN_PROGRESS,
    LaunchMethod.FAILED: StartOutcome.FAILED,
}


class _ServiceStarter:
    """Translates ``ServiceStarter`` (this library's vocabulary) to proclaunch's ``ServiceManager.start``, which
    records identity and refuses a second copy. The only place the two vocabularies meet."""

    def __init__(self, manager: ServiceManager) -> None:
        self._manager = manager

    def start(self, spec: ServiceSpec) -> StartResult:
        launch = self._manager.start(ProcessSpec(spec.argv, cwd=spec.cwd, log_path=spec.log_path, name=spec.name))
        return StartResult(_OUTCOME[launch.method], pid=launch.pid, error=launch.error)


def _manager(cfg: Config) -> ServiceManager:
    return default_manager(cfg.state_dir, spawner=PtySpawner() if cfg.pty else None)


def default_starter(cfg: Config) -> ServiceStarter:
    """Start services through proclaunch, on a pty when ``cfg.pty``."""
    return _ServiceStarter(_manager(cfg))


def default_should_run(cfg: Config) -> ShouldRun:
    """Per target: its own ``check`` command when it has one, else "its recorded service is not running"."""
    default, command = service_not_running(cfg.state_dir), CommandCheck(LifecycleCheckRunner())

    def should_run(target: Target) -> bool:
        return command(target) if target.check else default(target)

    return should_run


def run_once(
    cfg: Config,
    *,
    starter: ServiceStarter | None = None,
    should_run: ShouldRun | None = None,
    dry_run: bool = False,
    now: Callable[[], float] = time.time,
    history_path: Path | None = None,
) -> list[TargetResult]:
    """Reconcile every target in *cfg* once and return one result per target. Never raises for a target.

    The restart cap's history is loaded from, and saved back to, ``<state_dir>/history.json`` (or
    *history_path*) so it survives scheduled runs; a dry run saves nothing. *starter* and *should_run* replace
    the proclaunch- and lifecycle-runner-backed defaults."""
    path = history_path if history_path is not None else cfg.state_dir / "history.json"
    reconciler = Reconciler(
        starter if starter is not None else default_starter(cfg),
        should_run if should_run is not None else default_should_run(cfg),
        now=now, history=history_mod.load(path), dry_run=dry_run,
    )
    results = reconciler.reconcile(cfg.targets)
    if not dry_run:
        history_mod.save(path, reconciler.history)
    return results


__all__ = ["default_should_run", "default_starter", "run_once"]
