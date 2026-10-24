"""``CommandResolver`` on ``shutil.which``."""

from __future__ import annotations

import shutil
from pathlib import Path

__all__ = ["FilesystemResolver"]


class FilesystemResolver:
    """Finds a program on PATH, or relative to ``root`` when the name contains a separator.

    ``shutil.which`` applies the platform's own rules (PATHEXT on Windows, the executable bit
    elsewhere), so ``tools/bin/server`` finds ``server.exe`` on Windows.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def resolve(self, program: str) -> str | None:
        if "/" in program or "\\" in program:
            path = Path(program)
            candidate = path if path.is_absolute() else self._root / path
            return shutil.which(str(candidate))
        return shutil.which(program)
