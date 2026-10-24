"""Composition root: the public surface, and the default wiring of the real adapters."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from pathlib import Path

from .adapters import (
    BrowserOpener,
    EnvironConfig,
    FileRunRecord,
    FilesystemResolver,
    HttpReadiness,
    PsutilProcesses,
    SignalShutdown,
    SocketPorts,
    StdoutConsole,
    SubprocessRunner,
)
from .declarative import StackFile, parse_stack
from .domain import Identity, ServiceSpec, Stack, StackrunError
from .launcher import Launcher
from .ports import ConfigSource, Hook

__all__ = [
    "ConfigSource",
    "Hook",
    "Identity",
    "Launcher",
    "ServiceSpec",
    "Stack",
    "StackFile",
    "StackrunError",
    "default_launcher",
    "parse_stack",
]


def default_launcher(
    stack: Stack,
    *,
    state_dir: Path,
    root: Path | None = None,
    open_url: str | None = None,
    config: ConfigSource | None = None,
    hook: Hook | None = None,
    browser: bool = True,
    wait_for_ready: bool = True,
    sleep: Callable[[float], None] = time.sleep,
) -> Launcher:
    """A ``Launcher`` wired to the real adapters (needs ``stackrun[psutil,proclaunch]``).

    ``state_dir`` holds the run record (``<state_dir>/<stack name>.pid``); ``root`` is the default working
    directory and the base for relative program paths; ``config`` defaults to the process environment.
    """
    processes = PsutilProcesses()
    record_name = re.sub(r"[^A-Za-z0-9_.-]", "_", stack.name)
    return Launcher(
        stack,
        SubprocessRunner(root),
        FilesystemResolver(root or Path.cwd()),
        config or EnvironConfig(),
        StdoutConsole(),
        sleep,
        open_url=open_url,
        browser=BrowserOpener() if browser else None,
        ports=SocketPorts(),
        record=FileRunRecord(Path(state_dir) / f"{record_name}.pid", processes),
        processes=processes,
        shutdown=SignalShutdown(),
        hook=hook,
        readiness=HttpReadiness() if wait_for_ready else None,
    )
