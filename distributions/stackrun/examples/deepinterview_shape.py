"""A DeepInterview-shaped stack built on stackrun, with everything app-specific kept HERE (not in stackrun).

DeepInterview runs an agent API (uv + uvicorn), a web app (npx + pnpm) and, optionally, a voice worker plus
LiveKit / STT / TTS servers whose commands come from ``.env``. The pieces below are what its old launcher
had hard-wired into its core and what stackrun now leaves to the app:

- ``build_stack``  -- the old ``plan()``: which services, their ports, how a port is read from a command;
- ``DotenvConfig`` -- the old ``Workspace.config()``: ``.env`` overlaid with the process environment;
- ``PublishWebEnv`` -- the old ``Workspace.publish_web_env()``, now a ``Hook`` run before the first start.

It imports nothing from DeepInterview. Run it from a checkout laid out like DeepInterview's:
``python deepinterview_shape.py [--no-worker] [--no-browser] [--stop]`` (needs ``stackrun[all]``).
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Mapping
from itertools import pairwise
from pathlib import Path

from stackrun.api import ServiceSpec, Stack, StackrunError, default_launcher
from stackrun.domain import split_command

UV, NPX, PNPM = "uv", "npx", "pnpm@11.5.2"
START_URL = "http://localhost:3000/setup"
VOICE_COMMAND_KEYS = (("livekit", "LIVEKIT_SERVER_CMD"), ("stt", "STT_SERVER_CMD"), ("tts", "TTS_SERVER_CMD"))
LIVEKIT_DEFAULT_PORT = 7880
TRANSIENT_ENV = frozenset({"VIRTUAL_ENV"})  # describes the launcher's own throwaway interpreter


def parse_env(text: str) -> dict[str, str]:
    """``KEY=VALUE`` lines of a .env file; comments and blanks skipped, one pair of quotes removed."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip().removeprefix("export ").strip()] = value
    return values


def _port_in(argv: tuple[str, ...], default: int | None = None) -> int | None:
    for flag, value in pairwise(argv):
        if flag == "--port" and value.isdigit():
            return int(value)
    return default


def build_stack(config: Mapping[str, str], *, with_voice: bool = True) -> Stack:
    agent = (UV, "run", "--project", "apps/agent")
    services = [
        ServiceSpec("api", (*agent, "uvicorn", "deepinterview_agent.app:app", "--port", "8000"), port=8000),
        ServiceSpec("web", (NPX, "--yes", PNPM, "--dir", "apps/web", "dev"), port=3000, ready_url=START_URL),
    ]
    if with_voice:
        worker = [*agent, "python", "-m", "deepinterview_agent.worker", "dev"]
        if level := config.get("WORKER_LOG_LEVEL", "").strip():
            worker += ["--log-level", level]
        services.append(ServiceSpec("worker", tuple(worker)))
        for name, key in VOICE_COMMAND_KEYS:
            argv = tuple(split_command(config.get(key, "")))
            if argv:
                services.append(ServiceSpec(name, argv, port=_port_in(argv, LIVEKIT_DEFAULT_PORT if name == "livekit" else None)))
    return Stack("DeepInterview", tuple(services), stop_hint="`python deepinterview_shape.py --stop`")


class DotenvConfig:
    """ConfigSource: repo-root ``.env`` under the process environment (a secret-store layer would go here too)."""

    def __init__(self, root: Path, environ: Mapping[str, str]) -> None:
        self._root, self._environ = root, environ

    def environment(self) -> Mapping[str, str]:
        path = self._root / ".env"
        if not path.is_file():
            raise StackrunError(".env missing: copy .env.example to .env")
        merged = {**parse_env(path.read_text(encoding="utf-8")), **self._environ}
        return {k: v for k, v in merged.items() if k not in TRANSIENT_ENV}


class PublishWebEnv:
    """Hook: Next.js only reads ``apps/web/.env.local``, so copy ``.env`` there (keeping its permissions)."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def before_start(self, stack: Stack) -> None:
        source, copy = self._root / ".env", self._root / "apps" / "web" / ".env.local"
        shutil.copyfile(source, copy)
        shutil.copymode(source, copy)


def main(argv: list[str], root: Path, environ: Mapping[str, str]) -> int:
    config = DotenvConfig(root, environ)
    try:
        stack = build_stack(config.environment(), with_voice="--no-worker" not in argv)
        launcher = default_launcher(
            stack, state_dir=root / ".local" / "run", root=root, open_url=START_URL, config=config,
            hook=PublishWebEnv(root), browser="--no-browser" not in argv,
        )
        if "--stop" in argv:
            return 0 if launcher.stop() else 1
        if launcher.is_running():
            launcher.reopen()
            return 0
        return launcher.run()
    except StackrunError as exc:
        print(f"Could not start DeepInterview: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    import os

    sys.exit(main(sys.argv[1:], Path.cwd(), os.environ))
