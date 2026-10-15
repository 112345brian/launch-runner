"""The ports: what the application needs from the outside world.

Adapters in ``proclaunch.adapters`` implement these against subprocess, psutil,
the filesystem, Windows Task Scheduler and the network. Tests implement them
with in-memory fakes.
"""
from __future__ import annotations

from typing import Protocol

from commandport.domain import ProcessSpec
from proclaunch.domain import ProcessIdentity, ServiceRecord


class ProcessSpawner(Protocol):
    def spawn(self, spec: ProcessSpec) -> int:
        """Start ``spec.argv`` detached, windowless, with stdio sent to
        ``spec.log_path`` or discarded. Return the pid. Raise ``OSError`` on failure."""


class ProcessInspector(Protocol):
    def current(self) -> ProcessIdentity | None:
        """Identity of the calling process."""

    def identify(self, pid: int) -> ProcessIdentity | None:
        """Identity of the live process *pid*, or None if it is gone."""

    def is_live(self, identity: ProcessIdentity) -> bool:
        """The very process *identity* names is running (a reused pid is not)."""

    def pid_reused(self, identity: ProcessIdentity) -> bool:
        """The pid is alive but belongs to a different process than *identity*."""

    def terminate(self, identity: ProcessIdentity, timeout: float) -> bool:
        """Stop the process and its descendants, gracefully then by force, only
        if *identity* still matches. True when nothing of it, its group and the
        descendants found before it was signalled remains; False when any survived."""

    def find_started(self, argv: tuple[str, ...], since: float) -> ProcessIdentity | None:
        """The one live process that looks like *argv* (same arguments, equivalent
        executable) and was created at or after *since* (unix time, small tolerance).
        None when nothing matches or the match is ambiguous: never a guess."""


class RecordStore(Protocol):
    def load(self, name: str) -> ServiceRecord | None:
        """None if absent. Raise ``RecordUnreadable`` if present but untrusted."""

    def create_exclusive(self, name: str, record: ServiceRecord) -> bool:
        """Create the record only if none exists. False if one does."""

    def replace(self, name: str, record: ServiceRecord) -> None:
        """Atomically write the record. Raise ``OSError`` on failure."""

    def delete(self, name: str) -> None:
        """Remove the record; absent is fine."""

    def take_over(self, name: str, expected: ServiceRecord, new: ServiceRecord) -> bool:
        """Atomically replace the record with *new*, only if it still equals
        *expected*. False if someone changed or removed it first."""

    def delete_if(self, name: str, expected: ServiceRecord) -> bool:
        """Atomically remove the record, only if it still equals *expected*
        (a starter releases its own reservation, never someone else's)."""


class Clock(Protocol):
    def now(self) -> float:
        """Unix time."""

    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class Probe(Protocol):
    require_owned: bool

    def run(self, timeout: float) -> bool:
        """One health attempt. Never raises; failure is False."""
