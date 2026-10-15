"""Supervisor on macOS launchd: a per-user LaunchAgent (no admin rights).

``install`` writes ``~/Library/LaunchAgents/<label>.plist`` and loads it, so launchd runs ``argv`` at login
and, when ``interval_seconds`` is set, again on that cadence. ``start`` kickstarts the loaded job and
``end`` unloads it; ``uninstall`` also deletes the plist.
"""
from __future__ import annotations

import os
import plistlib
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path

from proclaunch.domain import EndResult, ProcessSpec

_TIMEOUT = 20


@dataclass(frozen=True)
class LaunchdSupervisor:
    label: str
    interval_seconds: int | None = None
    agents_dir: Path = Path.home() / "Library" / "LaunchAgents"

    @property
    def plist_path(self) -> Path:
        return self.agents_dir / f"{self.label}.plist"

    @property
    def _domain(self) -> str:
        return f"gui/{os.getuid()}"

    def available(self) -> bool:
        return platform.system() == "Darwin"

    def _launchctl(self, *args: str, check: bool = True) -> None:
        subprocess.run(["launchctl", *args], capture_output=True, timeout=_TIMEOUT, check=check)

    def render(self, spec: ProcessSpec) -> bytes:
        body: dict[str, object] = {
            "Label": self.label,
            "ProgramArguments": list(spec.argv),
            "RunAtLoad": True,
        }
        if spec.cwd:
            body["WorkingDirectory"] = spec.cwd
        if self.interval_seconds:
            body["StartInterval"] = int(self.interval_seconds)
        if spec.log_path is not None:
            body["StandardOutPath"] = body["StandardErrorPath"] = str(spec.log_path)
        return plistlib.dumps(body)

    def install(self, spec: ProcessSpec) -> None:
        """Write the plist and (re)load it. Raises on failure."""
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self.plist_path.write_bytes(self.render(spec))
        self._launchctl("bootout", f"{self._domain}/{self.label}", check=False)
        self._launchctl("bootstrap", self._domain, str(self.plist_path))

    def start(self, spec: ProcessSpec) -> int | None:
        self._launchctl("kickstart", "-k", f"{self._domain}/{self.label}")
        return None  # launchd owns the process; the caller identifies it

    def end(self) -> EndResult:
        if not self.available():
            return EndResult(ended=False, skipped=True)
        try:
            self._launchctl("bootout", f"{self._domain}/{self.label}")
        except Exception as exc:  # noqa: BLE001
            return EndResult(ended=False, error=f"{type(exc).__name__}: {exc}")
        return EndResult(ended=True)

    def uninstall(self) -> EndResult:
        result = self.end()
        self.plist_path.unlink(missing_ok=True)
        return result
