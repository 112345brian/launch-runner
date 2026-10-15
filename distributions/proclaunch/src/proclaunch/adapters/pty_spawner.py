"""ProcessSpawner that gives the child a pseudo-terminal (Unix).

The detached process that is spawned is ``pty_holder``; it owns the pty and the log. The returned pid is
the holder's, so a recorded service's identity, liveness and ``terminate`` (which stops descendants too)
all refer to the holder and the command under it as one unit.
"""
from __future__ import annotations

import dataclasses
import sys

from proclaunch.domain import ProcessSpec
from proclaunch.adapters.subprocess_spawner import SubprocessSpawner
from proclaunch.adapters.windows import is_windows


class PtySpawner:
    def __init__(self, inner: SubprocessSpawner | None = None, *, rows: int = 40, cols: int = 120) -> None:
        self._inner = inner or SubprocessSpawner()
        self._rows, self._cols = rows, cols

    def spawn(self, spec: ProcessSpec) -> int:
        if is_windows():
            raise OSError("PtySpawner needs a Unix pty; a ConPTY adapter is not implemented yet")
        held = [sys.executable, "-m", "proclaunch.adapters.pty_holder", "--rows", str(self._rows),
                "--cols", str(self._cols)]
        if spec.log_path is not None:
            spec.log_path.parent.mkdir(parents=True, exist_ok=True)
            held += ["--log", str(spec.log_path)]
        held += ["--", *spec.argv]
        # The holder writes the log itself; its own stdio is discarded.
        return self._inner.spawn(dataclasses.replace(spec, argv=tuple(held), log_path=None))
