"""The one place the Windows-vs-everything-else process split lives."""
from __future__ import annotations

import platform
import subprocess


# Win32 process-creation flag values; ``subprocess`` only exposes the names on Windows.
_CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_PROCESS_GROUP = 0x00000200


def is_windows() -> bool:
    return platform.system() == "Windows"


def windowless_flags() -> int:
    """``creationflags`` for any child that must not show a console window:
    ``CREATE_NO_WINDOW``. 0 off Windows. ``DETACHED_PROCESS`` is deliberately not
    used: a console program (python.exe) started with it still opens its own
    window, and CREATE_NO_WINDOW is ignored when combined with it. (CREATE_NO_WINDOW
    still creates a hidden console host; what matters is that no *window* is shown.)

    This is the one definition: application code never passes ``creationflags`` itself, it asks
    ``lifecycle_runner`` / ``proclaunch`` to start the process (``commandport.scan`` fails a raw call)."""
    return getattr(subprocess, "CREATE_NO_WINDOW", _CREATE_NO_WINDOW) if is_windows() else 0


def detached_flags() -> int:
    """Windowless plus its own process group, so the caller's Ctrl-C is not
    forwarded. For a background service, not a foreground child."""
    return windowless_flags() | (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", _CREATE_NEW_PROCESS_GROUP) if is_windows() else 0)
