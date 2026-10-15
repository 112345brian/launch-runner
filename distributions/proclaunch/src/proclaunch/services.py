"""Named services: one record per service, identity-checked start and stop.

The start sequence (reserve -> launch -> save, or kill on save failure) and the
stop checks are adapted from dmon (MIT); see THIRD_PARTY_NOTICES.md. This module
depends on ports only: it never touches a process, file or clock directly.

While a start is in flight the record is a reservation created exclusively, so
two concurrent starts cannot both launch. A record that cannot be read is
preserved and reported, never treated as "stopped".
"""
from __future__ import annotations

from proclaunch.domain import (
    LaunchMethod, LaunchResult, ProcessIdentity, ProcessSpec, RecordUnreadable, ServiceRecord, ServiceStatus,
    StopOutcome, StopResult,
)
from proclaunch.ports import BackgroundLauncher, Clock, ProcessInspector, RecordStore

ADOPT_WAIT_SECONDS = 8.0


class ServiceManager:
    def __init__(
        self,
        *,
        launcher: BackgroundLauncher,
        inspector: ProcessInspector,
        store: RecordStore,
        clock: Clock,
        adopt_wait: float | None = None,
    ) -> None:
        self._launcher = launcher
        self._inspector = inspector
        self._store = store
        self._clock = clock
        self._adopt_wait = ADOPT_WAIT_SECONDS if adopt_wait is None else adopt_wait

    def _adopt(self, spec: ProcessSpec, since: float) -> ProcessIdentity | None:
        """After a supervisor launch that returned no pid: find the process it
        started (same arguments, created after the launch), or None."""
        deadline = self._clock.monotonic() + self._adopt_wait
        while True:
            found = self._inspector.find_started(spec.argv, since)
            if found is not None or self._clock.monotonic() >= deadline:
                return found
            self._clock.sleep(0.25)

    def _reserve(self, name: str, supersede: bool) -> tuple[ServiceRecord | None, LaunchResult | None]:
        """Take the start reservation. Returns (reservation, None) or (None, why-not).
        Every replacement of an existing record is a compare-and-swap against the
        record we inspected, so two starters cannot both win."""
        try:
            record = self._store.load(name)
        except RecordUnreadable as exc:
            return None, LaunchResult(LaunchMethod.FAILED, error=str(exc))
        reservation = ServiceRecord(name, None, reserved_at=self._clock.now())
        busy = LaunchResult(LaunchMethod.IN_PROGRESS, error="another start is in progress")
        if record is None:
            return (reservation, None) if self._store.create_exclusive(name, reservation) else (None, busy)
        if record.is_reservation:
            if not record.reservation_is_stale(reservation.reserved_at) and not supersede:
                return None, busy
        elif self._inspector.is_live(record.identity) and not supersede:
            return None, LaunchResult(LaunchMethod.ALREADY_RUNNING, pid=record.identity.pid)
        # stale: exited, pid reused, stale reservation, or superseded
        return (reservation, None) if self._store.take_over(name, record, reservation) else (None, busy)

    def start(self, spec: ProcessSpec, *, supersede: bool = False) -> LaunchResult:
        """Launch *spec* as the named service and record its identity.
        ``supersede=True`` lets the running service start its own replacement;
        without it a running service yields ALREADY_RUNNING and nothing launches.
        The reservation is always released unless the identity record replaced it,
        including when something unexpected (even KeyboardInterrupt) escapes."""
        if not spec.name:
            raise ValueError("ServiceManager.start needs ProcessSpec.name")
        name = spec.name
        reservation, refused = self._reserve(name, supersede)
        if refused is not None:
            return refused

        recorded = False
        try:
            launched_at = reservation.reserved_at
            result = self._launcher.launch(spec)
            if not result.started:
                return result

            try:
                identity = self._inspector.identify(result.pid) if result.pid else self._adopt(spec, launched_at)
            except Exception:  # noqa: BLE001 -- unidentifiable, handled below
                identity = None
            if identity is None:
                if result.method is LaunchMethod.SPAWNED:
                    return LaunchResult(
                        LaunchMethod.FAILED, pid=result.pid,
                        error=f"process {result.pid} exited before it could be recorded",
                        supervisor_error=result.supervisor_error,
                    )
                note = "started, but the process could not be identified; no ownership record was written"
                both = "; ".join(x for x in (result.supervisor_error, note) if x)
                return LaunchResult(result.method, pid=result.pid, supervisor_error=both)
            try:
                self._store.replace(name, ServiceRecord(
                    name, identity, argv=tuple(spec.argv), cwd=spec.cwd, method=result.method.value,
                ))
            except OSError as exc:
                self._inspector.terminate(identity, 2.0)  # never leave a process running without an ownership record
                return LaunchResult(LaunchMethod.FAILED, error=f"cannot save record: {exc}")
            recorded = True
            return LaunchResult(result.method, pid=identity.pid, supervisor_error=result.supervisor_error)
        finally:
            if not recorded:
                self._store.delete_if(name, reservation)

    def stop(self, name: str, *, timeout: float = 5.0) -> StopResult:
        """Stop the recorded process iff its identity still matches. Uncertainty
        (unreadable record, process survives) never authorizes killing anything else."""
        try:
            record = self._store.load(name)
        except RecordUnreadable as exc:
            return StopResult(StopOutcome.UNCERTAIN, str(exc))
        if record is None:
            return StopResult(StopOutcome.ALREADY_STOPPED)
        if record.is_reservation:  # an unfinished start; nothing to kill
            self._store.delete(name)
            return StopResult(StopOutcome.ALREADY_STOPPED)
        identity = record.identity
        if self._inspector.is_live(identity):
            if not self._inspector.terminate(identity, timeout):
                return StopResult(StopOutcome.UNCERTAIN, f"process {identity.pid} survived stop; record kept")
            self._store.delete(name)
            return StopResult(StopOutcome.STOPPED)
        reused = self._inspector.pid_reused(identity)
        self._store.delete(name)
        return StopResult(StopOutcome.PID_REUSED if reused else StopOutcome.ALREADY_STOPPED)

    def status(self, name: str) -> ServiceStatus:
        try:
            record = self._store.load(name)
        except RecordUnreadable as exc:
            return ServiceStatus(False, error=str(exc))
        if record is None or record.is_reservation or not self._inspector.is_live(record.identity):
            return ServiceStatus(False)
        return ServiceStatus(True, pid=record.identity.pid, uptime=self._clock.now() - record.identity.create_time)

    def register_self(self, name: str) -> bool:
        """Record the *calling* process as service *name* (for a process started by
        something other than ``start``, e.g. an OS logon trigger). False, leaving the
        record alone, if a different live process already holds it or it is unreadable."""
        try:
            record = self._store.load(name)
        except RecordUnreadable:
            return False
        me = self._inspector.current()
        if me is None:
            return False
        if record is not None and record.identity is not None:
            other = record.identity
            if other.pid != me.pid and self._inspector.is_live(other):
                return False
        try:
            self._store.replace(name, ServiceRecord(name, me, method="self"))
        except OSError:
            return False
        return True
