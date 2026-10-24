"""The ``Launcher`` use case. Depends on the domain and the ports, never on subprocess, the OS or the disk."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext

from .domain import (
    StackrunError,
    ServiceSpec,
    Stack,
    already_running_message,
    busy_ports_message,
    child_environment,
)
from .ports import (
    Browser,
    CommandResolver,
    ConfigSource,
    Console,
    Hook,
    Ports,
    ProcessHandle,
    ProcessRunner,
    Processes,
    Readiness,
    RunRecord,
    Shutdown,
)

__all__ = ["Launcher"]

_STOP_POLLS = 20  # how long stop() waits for the launcher to exit: 20 x 0.5 s
_STOP_INTERVAL = 0.5
_READY_INTERVAL = 0.5
_SUPERVISE_INTERVAL = 1


class Launcher:
    """Runs a ``Stack`` in the foreground: start in order, supervise, stop everything on exit.

    Every collaborator is injected. ``runner``, ``resolver``, ``config``, ``console`` and ``sleep`` are
    required; the rest are optional and the matching behaviour is simply absent without them (no ``ports``:
    no clash check; no ``record``: no single-instance claim and no ``stop()``; no ``shutdown``: closing the
    terminal is not turned into an interrupt; no ``readiness``: ``ready_url`` is not waited for).
    """

    def __init__(
        self,
        stack: Stack,
        runner: ProcessRunner,
        resolver: CommandResolver,
        config: ConfigSource,
        console: Console,
        sleep: Callable[[float], None],
        *,
        open_url: str | None = None,
        browser: Browser | None = None,
        ports: Ports | None = None,
        record: RunRecord | None = None,
        processes: Processes | None = None,
        shutdown: Shutdown | None = None,
        hook: Hook | None = None,
        readiness: Readiness | None = None,
        ready_timeout: float = 120.0,
    ) -> None:
        self._stack = stack
        self._runner = runner
        self._resolver = resolver
        self._config = config
        self._console = console
        self._sleep = sleep
        self._open_url = open_url
        self._browser = browser
        self._ports = ports
        self._record = record
        self._processes = processes
        self._shutdown = shutdown
        self._hook = hook
        self._readiness = readiness
        self._ready_polls = max(1, int(ready_timeout / _READY_INTERVAL))

    @property
    def stack(self) -> Stack:
        return self._stack

    def is_running(self) -> bool:
        """True when every service of the stack that declares a port already has something on it."""
        if self._ports is None:
            return False
        declared = self._stack.ports
        return bool(declared) and all(self._ports.in_use(port) for _, port in declared)

    def reopen(self) -> None:
        """Already running: just bring the app up in the browser again."""
        if self._browser is not None and self._open_url is not None:
            self._browser.open_now(self._open_url)

    def stop(self) -> bool:
        """Stop a launch started earlier by a launcher. False if there was none to stop."""
        name = self._stack.name
        identity = self._record.load() if self._record else None
        if self._record is None or identity is None or self._processes is None or not self._processes.is_alive(identity):
            self._console.say(f"{name} is not running (or was not started by this launcher).")
            if self._record is not None and identity is not None:
                self._record.discard(identity)  # a leftover record from a launcher that is gone
            return False
        self._processes.stop(identity)
        for _ in range(_STOP_POLLS):
            if not self._processes.is_alive(identity):
                break
            self._sleep(_STOP_INTERVAL)
        else:
            self._console.say(f"{name} did not stop in time; try again or close its window.")
            return False
        self._record.discard(identity)
        self._console.say(f"{name} stopped.")
        return True

    def run(self) -> int:
        """Run the stack until a service exits or the user interrupts. Returns the exit code; raises
        ``StackrunError`` (after cleaning up) when the launch cannot happen."""
        base = self._config.environment()
        commands = [self._resolved(spec) for spec in self._stack.services]  # fail before claiming anything

        # Only one launch at a time: the claim is atomic, so two clicks racing cannot both start.
        if self._record and not self._record.claim():
            raise StackrunError(already_running_message(self._stack))
        started: dict[str, ProcessHandle] = {}
        guard = self._shutdown.guard() if self._shutdown else nullcontext()
        # The guard encloses the cleanup as well: a window closed WHILE services are being stopped must
        # not kill the launcher halfway and leave the rest running.
        with guard:
            try:
                self._refuse_busy_ports()
                if self._hook is not None:
                    self._hook.before_start(self._stack)
                for spec, argv in zip(self._stack.services, commands, strict=True):
                    self._console.say(f"Starting {spec.name}...")
                    env = child_environment(base, spec.env)
                    started[spec.name] = self._runner.start(argv, env, spec.cwd)
                    self._await_ready(spec, started[spec.name])
                self._announce()
                if self._browser is not None and self._open_url is not None:
                    self._browser.open_when_ready(self._open_url)
                return self._supervise(started)
            except KeyboardInterrupt:
                return 0
            finally:
                try:
                    self._stop_all(started)
                finally:
                    if self._record:
                        self._record.clear()

    def _announce(self) -> None:
        where = f" Your browser will open at {self._open_url} when it is ready." if self._open_url else ""
        self._console.say(
            f"{self._stack.name} is starting.{where}\n"
            "Leave this window open while it runs. Press Ctrl+C here (or close the window) to stop."
        )

    def _stop_all(self, started: dict[str, ProcessHandle]) -> None:
        """Stop every service, last started first. A second interrupt (a second Ctrl+C) while stopping must
        not abandon the rest, so each stop is retried once if it is interrupted; a service that fails to
        stop is reported and the rest are still stopped."""
        for name, handle in reversed(list(started.items())):
            for _attempt in range(2):
                try:
                    handle.stop()
                    break
                except KeyboardInterrupt:
                    continue
                except Exception as exc:  # noqa: BLE001 - one broken service must not strand the others
                    self._console.say(f"Could not stop {name}: {exc}")
                    break

    def _refuse_busy_ports(self) -> None:
        if self._ports is None:
            return
        busy = [
            (name, port, self._ports.owner(port)) for name, port in self._stack.ports if self._ports.in_use(port)
        ]
        if busy:
            raise StackrunError(busy_ports_message(self._stack, busy))

    def _resolved(self, spec: ServiceSpec) -> list[str]:
        program = self._resolver.resolve(spec.argv[0])
        if program is None:
            raise StackrunError(f"{spec.name}: cannot find {spec.argv[0]!r} (command: {' '.join(spec.argv)})")
        return [program, *spec.argv[1:]]

    def _await_ready(self, spec: ServiceSpec, handle: ProcessHandle) -> None:
        if self._readiness is None or spec.ready_url is None:
            return
        for _ in range(self._ready_polls):
            code = handle.poll()
            if code is not None:
                raise StackrunError(f"{spec.name} exited with code {code} before it was ready")
            if self._readiness.is_ready(spec.ready_url):
                return
            self._sleep(_READY_INTERVAL)
        raise StackrunError(f"{spec.name} did not answer at {spec.ready_url} in time")

    def _supervise(self, started: dict[str, ProcessHandle]) -> int:
        while True:
            for name, handle in started.items():
                code = handle.poll()
                if code is not None:
                    self._console.say(f"{name} exited with code {code}; stopping the rest")
                    return code
            self._sleep(_SUPERVISE_INTERVAL)
