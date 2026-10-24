"""``RunRecord`` on one file holding the launcher's identity."""

from __future__ import annotations

import os
import time
from pathlib import Path

from ..domain import Identity
from ..ports import Processes

__all__ = ["FileRunRecord"]


class FileRunRecord:
    """The running launcher's identity in the file ``path``.

    ``claim`` creates the file exclusively, so two launches racing cannot both succeed. A file left
    behind by a launcher that is gone (``processes`` says so) is replaced. It needs only the ``Processes``
    port, so it works with any identity implementation.
    """

    _GRACE_SECONDS = 5  # a file this new may be mid-write by the launch that just created it

    def __init__(self, path: Path, processes: Processes) -> None:
        self._path = Path(path)
        self._processes = processes

    @property
    def path(self) -> Path:
        return self._path

    def claim(self) -> bool:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        me = self._processes.current()
        for _ in range(2):
            try:
                fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._held_by_someone_else(me):
                    return False
                try:
                    self._path.unlink(missing_ok=True)  # stale: its launcher is gone
                except OSError:
                    return False  # in use right now (Windows refuses to delete an open file): not ours
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(me.to_text())
            return True
        return False

    def _held_by_someone_else(self, me: Identity) -> bool:
        holder = self.load()
        if holder is None:
            try:
                return time.time() - self._path.stat().st_mtime < self._GRACE_SECONDS
            except OSError:
                return False
        return holder != me and self._processes.is_alive(holder)

    def load(self) -> Identity | None:
        try:
            return Identity.from_text(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            return None

    def clear(self) -> None:
        self.discard(self._processes.current())

    def discard(self, identity: Identity) -> None:
        if self.load() == identity:
            try:
                self._path.unlink(missing_ok=True)
            except OSError:
                pass  # a record naming a dead launcher is replaced by the next claim, so never fail cleanup
