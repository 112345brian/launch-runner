"""Composition root and command line: ``python -m ensure_running {run,status,install,uninstall}``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from proclaunch.api import LaunchdSupervisor, ProcessSpec, service_status

from ensure_running import api
from ensure_running import config as config_mod
from ensure_running.config import Config, ConfigError
from ensure_running.domain import Outcome


def _job_spec(cfg: Config, config_path: Path) -> ProcessSpec:
    return ProcessSpec(
        (sys.executable, "-m", "ensure_running", "run", "--config", str(config_path.resolve())),
        log_path=cfg.state_dir / "logs" / "ensure-running.log",
    )


def cmd_run(cfg: Config, args: argparse.Namespace) -> int:
    results = api.run_once(cfg, dry_run=args.dry_run)
    for r in results:
        extra = f"  ({r.detail})" if r.detail else ""
        pid = f" pid={r.start.pid}" if r.start is not None and r.start.pid else ""
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
