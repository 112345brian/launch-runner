"""ProcessSpawner on subprocess: detached, windowless, stdio to the log."""
from __future__ import annotations

import shutil
import subprocess

from proclaunch.adapters.windows import detached_flags, is_windows
from proclaunch.domain import ProcessSpec


class SubprocessSpawner:
    def spawn(self, spec: ProcessSpec) -> int:
        # Windows' CreateProcess does not apply PATHEXT the way shutil.which does.
        exe = shutil.which(spec.argv[0])
        if exe is None:
            raise FileNotFoundError(f"executable not found: {spec.argv[0]}")
        argv = [exe, *spec.argv[1:]]
        log = None
        try:
            if spec.log_path is not None:
                spec.log_path.parent.mkdir(parents=True, exist_ok=True)
                log = open(spec.log_path, "ab")
            out = log if log is not None else subprocess.DEVNULL
            proc = subprocess.Popen(
                argv, cwd=spec.cwd,
                stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                creationflags=detached_flags(),
                start_new_session=not is_windows(),
            )
            return proc.pid
        finally:
            if log is not None:
                log.close()
