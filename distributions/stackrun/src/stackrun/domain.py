"""Innermost ring: what a stack is. Plain values and pure functions; no I/O, no OS, no third-party imports."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

__all__ = [
    "Identity",
    "ServiceSpec",
    "Stack",
    "StackrunError",
    "already_running_message",
    "busy_ports_message",
    "child_environment",
    "split_command",
]

_QUOTES = "\"'"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


class StackrunError(Exception):
    """A problem the user can fix; the message says how."""


@dataclass(frozen=True)
class Identity:
    """A specific process: its pid AND when it started. A pid alone is not enough to tell the
    launcher we recorded from an unrelated program that was later given the same number."""

    pid: int
    started: float

    def to_text(self) -> str:
        return f"{self.pid} {self.started!r}"

    @staticmethod
    def from_text(text: str) -> Identity | None:
        """The identity written by ``to_text``, or None for anything else (blank, garbage, NUL, nan, a
        non-positive pid). Never raises."""
        parts = text.split()
        if len(parts) != 2:
            return None
        try:
            pid, started = int(parts[0]), float(parts[1])
        except ValueError:
            return None
        if pid <= 0 or not (0.0 <= started < float("inf")):  # also rejects nan
            return None
        return Identity(pid, started)


@dataclass(frozen=True)
class ServiceSpec:
    """One process of a stack.

    ``argv[0]`` is a program name or path, resolved later by a ``CommandResolver``. ``port`` is the TCP
    port it listens on, if known (used to refuse a clash before anything starts). ``env`` is layered over
    the stack-wide environment for this service only. ``cwd`` is where it runs (relative paths are the
    runner's business). ``ready_url``, when a ``Readiness`` probe is wired, must answer before the next
    service is started.
    """

    name: str
    argv: tuple[str, ...]
    port: int | None = None
    env: Mapping[str, str] | None = field(default=None, hash=False)
    cwd: str | None = None
    ready_url: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise StackrunError("a service needs a name")
        argv = tuple(self.argv)
        if not argv or not all(isinstance(part, str) for part in argv) or not argv[0].strip():
            raise StackrunError(f"{self.name}: argv must start with a program name")
        object.__setattr__(self, "argv", argv)
        if self.port is not None and (
            isinstance(self.port, bool) or not isinstance(self.port, int) or not 0 < self.port < 65536
        ):
            raise StackrunError(f"{self.name}: port must be 1-65535, got {self.port!r}")
        if self.env is not None:
            object.__setattr__(self, "env", dict(self.env))
        if self.cwd is not None:
            object.__setattr__(self, "cwd", str(self.cwd))


@dataclass(frozen=True)
class Stack:
    """An ordered group of services run together (started in order, stopped in reverse).

    ``name`` is shown to the user and names the run record. ``stop_hint`` completes "stop it first" in
    messages ("with `myapp --stop`"); leave it empty when the app has no stop command.
    """

    name: str
    services: tuple[ServiceSpec, ...]
    stop_hint: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _NAME.fullmatch(self.name):
            raise StackrunError(f"stack name must be letters, digits, '_', '.' or '-': {self.name!r}")
        services = tuple(self.services)
        if not services:
            raise StackrunError(f"{self.name}: a stack needs at least one service")
        names = [s.name for s in services]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise StackrunError(f"{self.name}: duplicate service names: {', '.join(duplicates)}")
        object.__setattr__(self, "services", services)

    @property
    def ports(self) -> tuple[tuple[str, int], ...]:
        """(service, port) for every service with a known port, in start order."""
        return tuple((s.name, s.port) for s in self.services if s.port is not None)


def child_environment(
    config: Mapping[str, str], overlay: Mapping[str, str] | None = None, *, drop: frozenset[str] = frozenset()
) -> dict[str, str]:
    """What a service sees as its environment: ``config`` minus blank values and the names in ``drop``,
    then ``overlay`` (the service's own ``env``) on top, kept as given.

    A blank config value is dropped so ``FOO=`` means "unset", not "".
    """
    base = {k: v for k, v in config.items() if v != "" and k not in drop}
    return {**base, **(overlay or {})}


def split_command(text: str) -> list[str]:
    """Split a command line on whitespace, honouring single and double quotes. Backslashes stay literal.

    Deliberately not ``shlex``: POSIX mode eats the backslashes of a Windows path, and
    non-POSIX mode keeps the quotes. This behaves the same on every platform.
    """
    tokens: list[str] = []
    current: list[str] = []
    quote: str | None = None
    started = False
    for ch in text:
        if quote:
            if ch == quote:
                quote = None
            else:
                current.append(ch)
        elif ch in _QUOTES:
            quote, started = ch, True
        elif ch.isspace():
            if started or current:
                tokens.append("".join(current))
                current, started = [], False
        else:
            current.append(ch)
    if quote:
        raise StackrunError(f"unterminated {quote} in command: {text}")
    if started or current:
        tokens.append("".join(current))
    return tokens


def already_running_message(stack: Stack) -> str:
    how = f"stop it first ({stack.stop_hint})" if stack.stop_hint else "stop it first"
    return (
        f"{stack.name} is already starting or running (started from another window or shortcut). "
        f"Use that one, or {how}."
    )


def busy_ports_message(stack: Stack, busy: Sequence[tuple[str, int, str | None]]) -> str:
    """``busy`` is (service, port, who holds it if known)."""
    lines = [f"  - {name}: port {port} is used by {owner or 'another program'}" for name, port, owner in busy]
    how = f"stop it first ({stack.stop_hint})" if stack.stop_hint else "stop it first"
    return (
        "Cannot start: these ports are already taken:\n"
        + "\n".join(lines)
        + f"\nIf that is {stack.name} from an earlier launch, {how}. "
        "Otherwise close the other program and try again."
    )
