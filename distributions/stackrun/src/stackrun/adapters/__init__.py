"""Outer ring: processes, the filesystem and the operating system. The only place that knows them.

Everything platform-specific lives here, behind the ports, so the rings above behave the same on Windows,
macOS and Linux. Importing this package needs nothing beyond the standard library: ``psutil`` and
``proclaunch`` (extras ``stackrun[psutil]`` / ``stackrun[proclaunch]``) are imported on first use by
``PsutilProcesses`` and ``SubprocessRunner``/``PsutilProcesses`` respectively.
"""

from __future__ import annotations

from .browser import BrowserOpener
from .console import StdoutConsole
from .environment import EnvironConfig, scrub_environment
from .file_record import FileRunRecord
from .http_probe import HttpReadiness, url_answers
from .psutil_processes import PsutilProcesses
from .resolver import FilesystemResolver
from .signals import SignalShutdown
from .socket_ports import SocketPorts
from .subprocess_runner import SubprocessRunner
from .terminate import Terminate, proclaunch_terminate

__all__ = [
    "BrowserOpener",
    "EnvironConfig",
    "FileRunRecord",
    "FilesystemResolver",
    "HttpReadiness",
    "PsutilProcesses",
    "SignalShutdown",
    "SocketPorts",
    "StdoutConsole",
    "SubprocessRunner",
    "Terminate",
    "proclaunch_terminate",
    "scrub_environment",
    "url_answers",
]
