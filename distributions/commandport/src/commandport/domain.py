"""Forwarding for the types that moved to the libraries that provide them.

``RunSpec`` / ``CaptureSpec`` / ``StreamSpec`` / ``RunOutcome`` / the results are ``lifecycle_runner.domain``'s;
``ProcessSpec`` / ``LaunchMethod`` / ``LaunchResult`` / ``EndResult`` are ``proclaunch.domain``'s. The old names
here resolve lazily to those objects (see ``commandport._moved``); nothing is defined in this module.
"""
from __future__ import annotations

from commandport._moved import forward

forward(
    globals(),
    {
        **{name: "lifecycle_runner.domain" for name in ['RunSpec', 'RunOutcome', 'RunResult', 'CaptureSpec', 'CaptureResult', 'StreamSpec']},
        **{name: "proclaunch.domain" for name in ['ProcessSpec', 'LaunchMethod', 'LaunchResult', 'EndResult']},
    },
    {"lifecycle_runner": "lifecycle-runner", "proclaunch": "proclaunch"},
)
