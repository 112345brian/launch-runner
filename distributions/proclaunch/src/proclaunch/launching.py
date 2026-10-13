"""Launching: supervisor first, direct spawn as the fallback. Depends on ports only."""
from __future__ import annotations

from commandport.domain import LaunchMethod, LaunchResult, ProcessSpec
from proclaunch.ports import ProcessSpawner


class Launcher:
    def __init__(self, spawner: ProcessSpawner) -> None:
        self._spawner = spawner

    def launch(self, spec: ProcessSpec) -> LaunchResult:
        """Start *spec* detached and windowless. Never raises. Returns as soon as
        the launch was issued; whether the service came up is for the caller to probe."""
        supervisor_error: str | None = None
        sup = spec.supervisor
        if sup is not None and sup.available():
            try:
                return LaunchResult(LaunchMethod.SUPERVISED, pid=sup.start(spec))
            except Exception as exc:  # noqa: BLE001 -- fall back to a direct spawn
                supervisor_error = f"{type(exc).__name__}: {exc}"
        try:
            pid = self._spawner.spawn(spec)
        except Exception as exc:  # noqa: BLE001 -- the contract is a result, not a raise
            return LaunchResult(
                LaunchMethod.FAILED, error=f"{type(exc).__name__}: {exc}", supervisor_error=supervisor_error,
            )
        return LaunchResult(LaunchMethod.SPAWNED, pid=pid, supervisor_error=supervisor_error)
