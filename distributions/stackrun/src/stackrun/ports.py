"""Ports the inner rings own. Adapters implement them; the ``Launcher`` depends only on these.

They are ``typing.Protocol`` classes, so an implementation needs no import from this package: any object
with the right methods fits. ``stackrun.testing`` has an in-memory fake of each and a conformance check for
``RunRecord``, ``Processes`` and ``Ports``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Protocol

from .domain import Identity, Stack

__all__ = [
    "Browser",
    "CommandResolver",
    "ConfigSource",
    "Console",
    "Hook",
    "Ports",
    "ProcessHandle",
    "ProcessRunner",
    "Processes",
    "Readiness",
    "RunRecord",
    "Shutdown",
]


class ProcessHandle(Protocol):
    def poll(self) -> int | None:
        """Exit code, or None while still running."""
        ...

    def stop(self) -> None:
        """Stop the process and everything it started. Safe to call twice."""
        ...


class ProcessRunner(Protocol):
    def start(self, argv: Sequence[str], env: Mapping[str, str], cwd: str | None = None) -> ProcessHandle:
        """Start ``argv`` (already resolved) with exactly ``env`` as its environment, in ``cwd`` (None: the
        runner's default)."""
        ...


class CommandResolver(Protocol):
    def resolve(self, program: str) -> str | None:
        """A runnable path for a program name or path, or None if not found."""
        ...


class ConfigSource(Protocol):
    """Where the stack-wide environment comes from (a .env file, the process environment, a secret store...)."""

    def environment(self) -> Mapping[str, str]:
        """The settings every service starts with. Raises ``StackrunError`` if they cannot be had."""
        ...


class Hook(Protocol):
    """An optional seam for app-specific preparation (publish an env file, run a migration, ...)."""

    def before_start(self, stack: Stack) -> None:
        """Called once per launch, after the claim and the port check and before the first service starts.
        Raise ``StackrunError`` to refuse the launch; services already started (none yet) are stopped."""
        ...


class Ports(Protocol):
    def in_use(self, port: int) -> bool:
        """True if something on this machine is already listening on ``port``."""
        ...

    def owner(self, port: int) -> str | None:
        """A human description of what holds ``port`` ("node (pid 4242)"), if it can be found. Never raises."""
        ...


class Readiness(Protocol):
    def is_ready(self, url: str) -> bool:
        """One probe: True once something answers at ``url``. Never raises; failure is False."""
        ...


class RunRecord(Protocol):
    """Remembers which process is the running launcher, so a later run can stop it, and makes
    sure only one launch runs at a time."""

    def claim(self) -> bool:
        """Atomically become THE launcher. False if another live launcher already holds it."""
        ...

    def load(self) -> Identity | None: ...

    def clear(self) -> None:
        """Release the claim, but only if this process holds it (never another launcher's)."""
        ...

    def discard(self, identity: Identity) -> None:
        """Remove the record if it still names ``identity`` (after that launcher was stopped)."""
        ...


class Processes(Protocol):
    """Process identity and shutdown, delegated to a library that knows each OS."""

    def current(self) -> Identity:
        """The identity of the calling process."""
        ...

    def is_alive(self, identity: Identity) -> bool:
        """True only if that exact process (pid AND start time) is still running."""
        ...

    def stop(self, identity: Identity) -> None:
        """Stop that process and everything it started. Does nothing if ``identity`` is not alive."""
        ...


class Shutdown(Protocol):
    def guard(self) -> AbstractContextManager[None]:
        """Within the block, a termination request (closing the terminal window, a kill) is turned
        into KeyboardInterrupt, so the launcher's cleanup runs instead of leaving services behind."""
        ...


class Browser(Protocol):
    def open_when_ready(self, url: str) -> None:
        """Open ``url`` in the user's browser once something answers there. Never blocks."""
        ...

    def open_now(self, url: str) -> None:
        """Open ``url`` in the user's browser right away."""
        ...


class Console(Protocol):
    def say(self, message: str) -> None: ...
