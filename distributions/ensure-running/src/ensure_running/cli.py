"""Composition root and command line: ``python -m ensure_running {run,status,install,uninstall}``."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from commandport.domain import LaunchResult, ProcessSpec
from proclaunch.adapters.json_record_store import JsonFileRecordStore
from proclaunch.adapters.launchd import LaunchdSupervisor
from proclaunch.adapters.psutil_inspector import PsutilInspector
from proclaunch.adapters.pty_spawner import PtySpawner
from proclaunch.adapters.subprocess_spawner import SubprocessSpawner
from proclaunch.adapters.system_clock import SystemClock
from proclaunch.api import service_status
from proclaunch.launching import Launcher
from proclaunch.services import ServiceManager

from ensure_running import config as config_mod
from ensure_running import history as history_mod
from ensure_running.conditions import ServiceRunning
from ensure_running.config import Config, ConfigError
from ensure_running.domain import Outcome
from ensure_running.reconciler import Reconciler


class _ServiceStarter:
    """Adapts ``ServiceManager.start`` (records identity, refuses a second copy) to the launcher port."""

    def __init__(self, manager: ServiceManager) -> None:
        self._manager = manager

    def launch(self, spec: ProcessSpec) -> LaunchResult:
        return self._manager.start(spec)


def _manager(cfg: Config) -> ServiceManager:
    spawner = PtySpawner() if cfg.pty else SubprocessSpawner()
    return ServiceManager(
        launcher=Launcher(spawner), inspector=PsutilInspector(),
        store=JsonFileRecordStore(cfg.state_dir), clock=SystemClock(),
    )


def _job_spec(cfg: Config, config_path: Path) -> ProcessSpec:
    return ProcessSpec(
        (sys.executable, "-m", "ensure_running", "run", "--config", str(config_path.resolve())),
        log_path=cfg.state_dir / "logs" / "ensure-running.log",
    )


def cmd_run(cfg: Config, args: argparse.Namespace) -> int:
    hist_path = cfg.state_dir / "history.json"
    reconciler = Reconciler(
        _ServiceStarter(_manager(cfg)), ServiceRunning(cfg.state_dir),
        now=time.time, history=history_mod.load(hist_path), dry_run=args.dry_run,
    )
    results = reconciler.reconcile(cfg.targets)
    if not args.dry_run:
        history_mod.save(hist_path, reconciler.history)
    for r in results:
        extra = f"  ({r.detail})" if r.detail else ""
        pid = f" pid={r.launch.pid}" if r.launch is not None and r.launch.pid else ""
        print(f"{r.target}: {r.outcome.value}{pid}{extra}")
    bad = [r for r in results if r.outcome not in (Outcome.OK, Outcome.STARTED, Outcome.DRY_RUN)]
    return 1 if bad else 0


def cmd_status(cfg: Config, _args: argparse.Namespace) -> int:
    down = 0
    for t in cfg.targets:
        s = service_status(t.name, state_dir=cfg.state_dir)
        if s.error:
            state = f"unknown ({s.error})"
        elif s.running:
            state = f"running pid={s.pid} up {int(s.uptime or 0)}s"
        else:
            state, down = "not running", down + 1
        print(f"{t.name}: {state}")
    return 1 if down else 0


def cmd_install(cfg: Config, args: argparse.Namespace) -> int:
    sup = LaunchdSupervisor(cfg.label, interval_seconds=cfg.interval_seconds)
    if not sup.available():
        print("install: only macOS launchd is implemented so far (systemd and Task Scheduler are not)",
              file=sys.stderr)
        return 2
    try:
        sup.install(_job_spec(cfg, args.config))
    except Exception as exc:  # noqa: BLE001
        print(f"install failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"installed {sup.plist_path} (every {cfg.interval_seconds}s and at login)")
    return 0


def cmd_uninstall(cfg: Config, _args: argparse.Namespace) -> int:
    sup = LaunchdSupervisor(cfg.label)
    if not sup.available():
        print("uninstall: only macOS launchd is implemented so far", file=sys.stderr)
        return 2
    result = sup.uninstall()
    print("uninstalled" if result.ended else f"removed the plist; job was not loaded ({result.error})")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ensure_running")
    p.add_argument("command", choices=("run", "status", "install", "uninstall"))
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--dry-run", action="store_true", help="run: report what would start, start nothing")
    args = p.parse_args(argv)
    try:
        cfg = config_mod.load(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    return {"run": cmd_run, "status": cmd_status, "install": cmd_install, "uninstall": cmd_uninstall}[
        args.command](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
