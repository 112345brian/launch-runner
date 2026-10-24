"""``python -m stackrun [-f stackrun.toml] run|stop|status``: the declarative composition root."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .api import StackrunError, default_launcher, parse_stack

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stackrun", description="Run the stack described in stackrun.toml.")
    parser.add_argument("-f", "--file", default="stackrun.toml", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("command", choices=["run", "stop", "status"], nargs="?", default="run")
    args = parser.parse_args(argv)
    try:
        path = args.file.resolve()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StackrunError(f"cannot read {path}: {exc}") from exc
        parsed = parse_stack(text)
        launcher = default_launcher(
            parsed.stack,
            state_dir=path.parent / ".stackrun",
            root=path.parent,
            open_url=parsed.open_url,
            browser=not args.no_browser,
        )
        if args.command == "stop":
            return 0 if launcher.stop() else 1
        if args.command == "status":
            running = launcher.is_running()
            print("running" if running else "not running")
            return 0 if running else 1
        if launcher.is_running():
            print(f"{parsed.stack.name} is already running.")
            launcher.reopen()
            return 0
        return launcher.run()
    except StackrunError as exc:
        print(f"stackrun: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
