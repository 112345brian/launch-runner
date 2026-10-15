"""Forwarding for the fakes that moved to the libraries that provide them.

``FakeCommandRunner`` / ``FakeLineStream`` are ``lifecycle_runner.testing``'s; ``FakeLauncher`` /
``FakeSupervisor`` / ``FakeSupervisors`` are ``proclaunch.testing``'s. Nothing is defined in this module.
"""
from __future__ import annotations

from commandport._moved import forward

forward(
    globals(),
    {
        **{name: "lifecycle_runner.testing" for name in ("FakeCommandRunner", "FakeLineStream")},
        **{name: "proclaunch.testing" for name in ['FakeLauncher', 'FakeSupervisor', 'FakeSupervisors']},
    },
    {"lifecycle_runner": "lifecycle-runner", "proclaunch": "proclaunch"},
)
