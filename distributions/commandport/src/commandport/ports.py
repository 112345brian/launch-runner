"""The launch ports that proclaunch implements (still defined here until they move).

The command operation ports (``CommandCapturer`` / ``CommandStreamer`` / ``CommandRunner`` / ``LineStream``) live in
``lifecycle_runner.ports`` now; their old names are forwarded.
"""
from __future__ import annotations

from typing import Protocol

from commandport._moved import forward
from commandport.domain import EndResult, LaunchResult, ProcessSpec


class BackgroundLauncher(Protocol):
    """Start a long-lived process detached from the caller, windowless, with its output sent to
    ``ProcessSpec.log_path`` or discarded. Returns as soon as the launch was issued; never raises (a launch that
    did not happen is ``LaunchResult.method == FAILED`` with the reason)."""

    def launch(self, spec: ProcessSpec) -> LaunchResult: ...


class Supervisor(Protocol):
    """An operating-system supervisor (Task Scheduler, launchd, systemd) that can start what it owns."""

    def available(self) -> bool:
        """False when this supervisor does not exist here; the launcher then
        spawns directly without reporting an error."""

    def start(self, spec: ProcessSpec) -> int | None:
        """Ask the supervisor to start the process; return its pid if known.
        Raise on failure; the launcher falls back to a direct spawn."""

    def end(self) -> EndResult:
        """Ask the supervisor to end what it started. Never raises."""


forward(
    globals(),
    {name: "lifecycle_runner.ports" for name in ("LineStream", "CommandCapturer", "CommandStreamer", "CommandRunner")},
    {"lifecycle_runner": "lifecycle-runner"},
)
