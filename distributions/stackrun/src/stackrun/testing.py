"""In-memory fakes for every port, and a conformance kit for the ports with real-world adapters.

The fakes let you test a ``Launcher`` (or code that wraps one) without a process, a socket or a file. The kit
(``check_run_record``, ``check_processes``, ``check_ports``) is for people writing an adapter: call it from
any test runner with your implementation and it raises ``AssertionError`` naming the contract it broke.
The fakes themselves pass the kit (see ``tests/test_stackrun_testing.py``).

This module may use ``time``; the core may not.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path

from .domain import Identity, Stack
from .ports import Ports, Processes, RunRecord

__all__ = [
    "FakeBrowser",
    "FakeConfig",
    "FakeConsole",
    "FakeHook",
    "FakePorts",
    "FakeProcess",
    "FakeProcesses",
    "FakeReadiness",
    "FakeRecord",
    "FakeResolver",
    "FakeRunner",
    "FakeShutdown",
    "InMemoryRunRecord",
    "check_ports",
    "check_processes",
    "check_run_record",
]


# --- fakes ---------------------------------------------------------------------------------------------


class FakeProcess:
    """A ProcessHandle. ``exits_with`` is what ``poll`` returns; every ``stop`` is counted."""

    def __init__(self, exits_with: int | None = None) -> None:
        self.exits_with = exits_with
        self.stopped = 0

    def poll(self) -> int | None:
        return self.exits_with

    def stop(self) -> None:
        self.stopped += 1


class FakeRunner:
    """A ProcessRunner. ``exits`` maps a program's basename to the exit code its process reports at once;
    ``fail`` maps a basename to an exception ``start`` raises; ``make_handle`` builds custom handles."""

    def __init__(
        self,
        exits: Mapping[str, int] | None = None,
        *,
        fail: Mapping[str, BaseException] | None = None,
        make_handle: Callable[[], FakeProcess] | None = None,
    ) -> None:
        self.started: list[tuple[list[str], FakeProcess]] = []
        self.envs: list[dict[str, str]] = []
        self.cwds: list[str | None] = []
        self.exits = dict(exits or {})
        self.fail = dict(fail or {})
        self._make_handle = make_handle

    def start(self, argv: Sequence[str], env: Mapping[str, str], cwd: str | None = None) -> FakeProcess:
        name = Path(argv[0]).name
        if name in self.fail:
            raise self.fail[name]
        proc = self._make_handle() if self._make_handle else FakeProcess(self.exits.get(name))
        self.started.append((list(argv), proc))
        self.envs.append(dict(env))
        self.cwds.append(cwd)
        return proc

    @property
    def processes(self) -> list[FakeProcess]:
        return [proc for _, proc in self.started]


class FakeResolver:
    """A CommandResolver: every program resolves to ``/resolved/<program>`` except those in ``missing``."""

    def __init__(self, missing: set[str] | None = None) -> None:
        self.missing = missing or set()

    def resolve(self, program: str) -> str | None:
        return None if program in self.missing else f"/resolved/{program}"


class FakeConfig:
    """A ConfigSource returning ``values``, or raising ``error``."""

    def __init__(self, values: Mapping[str, str] | None = None, error: Exception | None = None) -> None:
        self.values, self.error = dict(values or {}), error

    def environment(self) -> Mapping[str, str]:
        if self.error is not None:
            raise self.error
        return self.values


class FakeHook:
    """A Hook that records the stacks it saw and optionally refuses with ``error``."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.seen: list[Stack] = []

    def before_start(self, stack: Stack) -> None:
        self.seen.append(stack)
        if self.error is not None:
            raise self.error


class FakeConsole:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def say(self, message: str) -> None:
        self.lines.append(message)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class FakePorts:
    """Ports: ``busy`` maps a port to what holds it (or None for "unknown"). ``listen`` opens a pretend
    listener, for the conformance kit."""

    def __init__(self, busy: Mapping[int, str | None] | None = None) -> None:
        self.busy: dict[int, str | None] = dict(busy or {})
        self._next = 40000

    def in_use(self, port: int) -> bool:
        return port in self.busy

    def owner(self, port: int) -> str | None:
        return self.busy.get(port)

    def listen(self) -> tuple[int, Callable[[], None]]:
        self._next += 1
        port = self._next
        self.busy[port] = f"fake (pid {port})"
        return port, lambda: self.busy.pop(port, None) and None


class FakeReadiness:
    """Readiness: a URL is ready after ``answers_after`` probes (0: at once); ``never`` listed URLs never are."""

    def __init__(self, answers_after: int = 0, never: set[str] | None = None) -> None:
        self.answers_after, self.never = answers_after, never or set()
        self.probes: list[str] = []

    def is_ready(self, url: str) -> bool:
        self.probes.append(url)
        return url not in self.never and self.probes.count(url) > self.answers_after


class FakeRecord:
    """A scripted RunRecord: ``holder_alive`` makes every claim fail; ``identity`` is what ``load`` returns;
    every call is counted. Not a faithful store: use ``InMemoryRunRecord`` for that."""

    def __init__(self, holder_alive: bool = False, identity: Identity | None = None) -> None:
        self.holder_alive, self.identity = holder_alive, identity
        self.claims, self.clears = 0, 0
        self.discards: list[Identity] = []

    def claim(self) -> bool:
        self.claims += 1
        return not self.holder_alive

    def load(self) -> Identity | None:
        return self.identity

    def clear(self) -> None:
        self.clears += 1

    def discard(self, identity: Identity) -> None:
        self.discards.append(identity)
        if self.identity == identity:
            self.identity = None


class InMemoryRunRecord:
    """A faithful RunRecord over a shared ``store`` dict (one record per key), for several 'launchers' in one
    process. ``processes`` supplies this launcher's identity and the liveness of the holder."""

    def __init__(self, processes: FakeProcesses, store: dict[str, Identity], key: str = "stack") -> None:
        self._processes, self._store, self._key = processes, store, key

    def claim(self) -> bool:
        holder = self._store.get(self._key)
        me = self._processes.current()
        if holder is not None and holder != me and self._processes.is_alive(holder):
            return False
        self._store[self._key] = me
        return True

    def load(self) -> Identity | None:
        return self._store.get(self._key)

    def clear(self) -> None:
        self.discard(self._processes.current())

    def discard(self, identity: Identity) -> None:
        if self._store.get(self._key) == identity:
            del self._store[self._key]


class FakeProcesses:
    """Processes: a set of alive identities. After ``stop`` an identity dies at once (``dies_after=0``),
    after that many further ``is_alive`` polls, or never (``dies_after=None``). ``stopped`` lists every
    identity ``stop`` was called with. ``spawn`` adds a new live identity, for the conformance kit."""

    def __init__(
        self, alive: set[Identity] | None = None, dies_after: int | None = 0, me: Identity | None = None
    ) -> None:
        self.alive = set(alive or ())
        self.dies_after = dies_after
        self.me = me or Identity(1, 1.0)
        self.alive.add(self.me)
        self.stopped: list[Identity] = []
        self._countdown: dict[Identity, int] = {}
        self._next_pid = 5000

    def current(self) -> Identity:
        return self.me

    def is_alive(self, identity: Identity) -> bool:
        if identity in self._countdown:
            if self._countdown[identity] <= 0:
                self.alive.discard(identity)
                del self._countdown[identity]
            else:
                self._countdown[identity] -= 1
        return identity in self.alive

    def stop(self, identity: Identity) -> None:
        self.stopped.append(identity)
        if identity not in self.alive or self.dies_after is None:
            return
        if self.dies_after == 0:
            self.alive.discard(identity)
        else:
            self._countdown[identity] = self.dies_after

    def spawn(self) -> tuple[Identity, Callable[[], None]]:
        self._next_pid += 1
        identity = Identity(self._next_pid, 1000.0 + self._next_pid)
        self.alive.add(identity)
        return identity, lambda: self.alive.discard(identity)


class FakeShutdown:
    """Shutdown: records enter/exit; ``at_exit`` (optional) is sampled when the guard exits."""

    def __init__(self) -> None:
        self.entered, self.exited = 0, 0
        self.at_exit: Callable[[], object] | None = None
        self.exit_snapshot: object = None

    @contextlib.contextmanager
    def guard(self) -> Iterator[None]:
        self.entered += 1
        try:
            yield
        finally:
            self.exited += 1
            if self.at_exit is not None:
                self.exit_snapshot = self.at_exit()


class FakeBrowser:
    def __init__(self) -> None:
        self.when_ready: list[str] = []
        self.now: list[str] = []

    def open_when_ready(self, url: str) -> None:
        self.when_ready.append(url)

    def open_now(self, url: str) -> None:
        self.now.append(url)




# --- conformance kit ---------------------------------------------------------------------------------------


def _expect(condition: bool, contract: str) -> None:
    if not condition:
        raise AssertionError(f"contract broken: {contract}")


def check_run_record(make_record: Callable[[Identity, FakeProcesses], RunRecord]) -> None:
    """Exercise a ``RunRecord`` implementation.

    ``make_record(me, processes)`` must return a NEW record for a launcher whose identity is ``me`` and whose
    view of who is alive is ``processes`` (a ``FakeProcesses``; ``processes.current()`` is ``me``). Every
    record it returns, within one call of this function, must share one backing store that starts empty
    (e.g. ``lambda me, p: FileRunRecord(tmp_path / "x.pid", p)`` with a fresh ``tmp_path``).
    """
    me, other, third = Identity(101, 1000.0), Identity(202, 2000.0), Identity(303, 3000.0)
    world = {me, other, third}
    first = make_record(me, FakeProcesses(world, me=me))
    second = make_record(other, FakeProcesses(world, me=other))

    _expect(first.load() is None, "load() is None before anyone claimed")
    first.clear()  # clearing with nothing recorded is harmless
    second.discard(me)  # discarding an absent record is harmless

    _expect(first.claim() is True, "the first claim wins")
    _expect(first.load() == me, "load() names the claimant")
    _expect(second.load() == me, "every record over the same store sees the claimant")
    _expect(second.claim() is False, "a live holder blocks a second claim")
    _expect(second.load() == me, "a refused claim leaves the holder's record alone")

    second.clear()
    _expect(first.load() == me, "clear() by a launcher that does not hold the claim removes nothing")
    second.discard(other)
    _expect(first.load() == me, "discard(identity) removes only a record naming that identity")

    first.clear()
    _expect(first.load() is None, "clear() by the holder releases the claim")
    _expect(second.claim() is True and second.load() == other, "after a release the next launcher can claim")

    # A record naming a launcher that is no longer alive is stale and is replaced.
    third_record = make_record(third, FakeProcesses(world - {other}, me=third))
    _expect(third_record.claim() is True, "a record naming a dead launcher is replaced")
    _expect(third_record.load() == third, "the replacement names the new claimant")
    third_record.discard(third)
    _expect(third_record.load() is None, "discard(identity) removes a matching record")


def check_processes(
    processes: Processes,
    spawn: Callable[[], tuple[Identity, Callable[[], None]]],
    *,
    timeout: float = 15.0,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Exercise a ``Processes`` implementation against disposable processes.

    ``spawn()`` starts a process that lives until stopped and returns ``(identity, cleanup)``; ``cleanup`` is
    called at the end whatever happened. ``FakeProcesses.spawn`` is an example. ``timeout`` bounds how long a
    stopped process may take to be reported dead.
    """
    me = processes.current()
    _expect(isinstance(me, Identity) and me.pid > 0, "current() returns an Identity with a real pid")
    _expect(processes.is_alive(me) is True, "the calling process is alive")
    _expect(
        processes.is_alive(Identity(me.pid, me.started - 1000)) is False
        and processes.is_alive(Identity(me.pid, me.started + 1000)) is False,
        "the same pid with another start time is a different process (a reused pid)",
    )

    target, cleanup = spawn()
    try:
        _expect(processes.is_alive(target) is True, "a spawned process is alive")
        processes.stop(Identity(target.pid, target.started - 1000))
        _expect(
            processes.is_alive(target) is True, "stop() of an identity that is not alive leaves the real process alone"
        )
        processes.stop(target)
        deadline = time.monotonic() + timeout
        while processes.is_alive(target) and time.monotonic() < deadline:
            sleep(0.05)
        _expect(not processes.is_alive(target), "stop() makes the process not alive")
        processes.stop(target)  # stopping something already gone is harmless
    finally:
        cleanup()


def check_ports(ports: Ports, listen: Callable[[], tuple[int, Callable[[], None]]]) -> None:
    """Exercise a ``Ports`` implementation.

    ``listen()`` opens a listener on a free port and returns ``(port, close)``. ``FakePorts.listen`` is an
    example. ``owner`` is only required to return a non-empty string or None and never raise; whether it can
    name the holder is the adapter's own test.
    """
    port, close = listen()
    try:
        _expect(ports.in_use(port) is True, "a listening port is in use")
        holder = ports.owner(port)
        _expect(holder is None or (isinstance(holder, str) and holder != ""), "owner() is None or a non-empty string")
    finally:
        close()
    _expect(ports.in_use(port) is False, "a port nobody listens on any more is free")
    _expect(ports.owner(port) is None, "owner() of a free port is None")
