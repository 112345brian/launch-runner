"""Forwarding for the ports that moved to the libraries that provide them.

``CommandRunner`` / ``CommandCapturer`` / ``CommandStreamer`` / ``LineStream`` are ``lifecycle_runner.ports``';
``BackgroundLauncher`` / ``Supervisor`` are ``proclaunch.ports``'. Nothing is defined in this module.
"""
from __future__ import annotations

from commandport._moved import forward

forward(
    globals(),
    {
        **{name: "lifecycle_runner.ports" for name in ("LineStream", "CommandCapturer", "CommandStreamer", "CommandRunner")},
        **{name: "proclaunch.ports" for name in ['BackgroundLauncher', 'Supervisor']},
    },
    {"lifecycle_runner": "lifecycle-runner", "proclaunch": "proclaunch"},
)
