"""The one place this library names the Windows process-creation flag it needs."""
from __future__ import annotations

import subprocess
import sys

# ``subprocess`` only exposes the name on Windows.
_CREATE_NO_WINDOW = 0x08000000


def windowless_creationflags() -> int:
    """``creationflags`` for a foreground child that must not show a console window: ``CREATE_NO_WINDOW`` on
    Windows, 0 elsewhere. ``DETACHED_PROCESS`` is deliberately not used: a console program started with it
    still opens its own window, and ``CREATE_NO_WINDOW`` is ignored when combined with it."""
    return getattr(subprocess, "CREATE_NO_WINDOW", _CREATE_NO_WINDOW) if sys.platform == "win32" else 0
