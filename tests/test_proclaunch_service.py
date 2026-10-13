"""ServiceManager and readiness: duplicate starts, pid reuse, corrupt records,
save failure, identity-checked stop, bounded readiness.

Two layers: the application driven entirely through in-memory ports (fast,
deterministic, no OS), and the real adapters against real child processes."""
from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import replace

import psutil
import pytest

from proclaunch import api
from proclaunch.adapters.json_record_store import JsonFileRecordStore
from proclaunch.adapters.probes import CallableProbe
from commandport.domain import LaunchMethod, ProcessSpec
from proclaunch.domain import ProcessIdentity, RecordUnreadable, ServiceRecord, StopOutcome
from proclaunch.launching import Launcher
from proclaunch.readiness import wait_for_readiness
from proclaunch.services import ServiceManager

SLEEPER = (sys.executable, "-c", "import time; time.sleep(60)")


# ---------------- in-memory ports ----------------

class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def now(self):
        return self.t

    def monotonic(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class FakeWorld:
    """A tiny OS: processes by pid -> create_time, plus a spawner/inspector over it."""

    def __init__(self, clock):
        self.clock, self.procs, self.next_pid, self.terminated = clock, {}, 100, []
        self.survives: set[int] = set()
        self.spawn_error = None
        self.exit_immediately = False
        self.spawn_hook = None
        self._lock = threading.Lock()

    # ProcessSpawner
    def spawn(self, spec):
        if self.spawn_hook:
            self.spawn_hook()
        if self.spawn_error:
            raise self.spawn_error
        with self._lock:
            self.next_pid += 1
            pid = self.next_pid
            if not self.exit_immediately:
                self.procs[pid] = self.clock.now()
        return pid

    # ProcessInspector
    def current(self):
        return self.identify(1) if 1 in self.procs else None

    def identify(self, pid):
        return ProcessIdentity(pid, self.procs[pid]) if pid in self.procs else None

    def is_live(self, identity):
        return self.procs.get(identity.pid) == identity.create_time

    def pid_reused(self, identity):
        return identity.pid in self.procs and self.procs[identity.pid] != identity.create_time

    def terminate(self, identity, timeout):
        if not self.is_live(identity):
            return True
        self.terminated.append(identity.pid)
        if identity.pid in self.survives:
            return False
        del self.procs[identity.pid]
        return True

    def find_started(self, argv, since):
        for pid, created in self.procs.items():
            if created >= since - 1 and pid in getattr(self, "adoptable", ()):
                return ProcessIdentity(pid, created)
        return None


class FakeStore:
    def __init__(self):
        self.records, self.unreadable, self.replace_error = {}, set(), None
        self.lock = threading.Lock()

    def load(self, name):
        if name in self.unreadable:
            raise RecordUnreadable(f"{name}: corrupt")
        return self.records.get(name)

    def create_exclusive(self, name, record):
        with self.lock:
            if name in self.records:
                return False
            self.records[name] = record
            return True

    def replace(self, name, record):
        if self.replace_error:
            raise self.replace_error
        self.records[name] = record

    def delete(self, name):
        self.records.pop(name, None)

    def take_over(self, name, expected, new):
        with self.lock:
            if self.records.get(name) != expected:
                return False
            self.records[name] = new
            return True

    def delete_if(self, name, expected):
        with self.lock:
            if self.records.get(name) != expected:
                return False
            del self.records[name]
            return True


def build(adopt_wait=0.0):
    clock = FakeClock()
    world, store = FakeWorld(clock), FakeStore()
    manager = ServiceManager(launcher=Launcher(world), inspector=world, store=store, clock=clock, adopt_wait=adopt_wait)
    return manager, world, store, clock


SPEC = ProcessSpec(("svc", "run.py"), name="t")


# ---------------- ServiceManager over fakes ----------------

def test_start_records_identity_and_second_start_is_already_running():
    manager, world, store, _ = build()
    first = manager.start(SPEC)
    assert first.method is LaunchMethod.SPAWNED and first.pid in world.procs
    assert store.records["t"].identity.pid == first.pid
    assert manager.status("t").running

    spawned = len(world.procs)
    second = manager.start(SPEC)
    assert second.method is LaunchMethod.ALREADY_RUNNING and second.ok and not second.started and second.pid == first.pid
    assert len(world.procs) == spawned  # nothing new launched


def test_supersede_replaces_a_running_service():
    manager, world, store, _ = build()
    old = manager.start(SPEC)
    new = manager.start(SPEC, supersede=True)
    assert new.started and new.pid != old.pid and store.records["t"].identity.pid == new.pid


def test_fresh_reservation_blocks_and_stale_one_is_taken_over():
    manager, world, store, clock = build()
    store.records["t"] = ServiceRecord("t", None, reserved_at=clock.now())
    assert manager.start(SPEC).method is LaunchMethod.IN_PROGRESS
    clock.t += 10_000
    assert manager.start(SPEC).started


def test_losing_the_reservation_race_is_in_progress_not_a_second_launch():
    manager, world, store, _ = build()
    store.create_exclusive("t", ServiceRecord("t", None, reserved_at=1e12))  # another starter, just now
    store.load = lambda name: None  # we saw nothing, then lost the exclusive create
    result = manager.start(SPEC)
    assert result.method is LaunchMethod.IN_PROGRESS and not world.procs


def test_failed_launch_releases_the_reservation():
    manager, world, store, _ = build()
    world.spawn_error = FileNotFoundError("nope")
    result = manager.start(SPEC)
    assert result.method is LaunchMethod.FAILED and "t" not in store.records


def test_failure_to_save_the_record_terminates_the_new_process():
    manager, world, store, _ = build()
    store.replace_error = OSError("disk full")
    result = manager.start(SPEC)
    assert result.method is LaunchMethod.FAILED and "disk full" in result.error
    assert world.terminated and not world.procs and "t" not in store.records


def test_supervisor_launch_without_pid_adopts_the_process_it_started():
    class Sup:
        def available(self):
            return True

        def start(self, spec):
            world.next_pid += 1
            world.procs[world.next_pid] = clock.now()
            world.adoptable = {world.next_pid}
            return None

    manager, world, store, clock = build()
    result = manager.start(replace(SPEC, supervisor=Sup()))
    assert result.method is LaunchMethod.SUPERVISED and result.pid == world.next_pid
    assert store.records["t"].identity.pid == world.next_pid


def test_launched_but_unidentified_process_leaves_no_stale_record():
    class Sup:
        def available(self):
            return True

        def start(self, spec):
            return None

    manager, _, store, _ = build()
    result = manager.start(replace(SPEC, supervisor=Sup()))
    assert result.started and "t" not in store.records
    assert "could not be identified" in result.supervisor_error  # ok, but no ownership record: say so


def test_stop_terminates_then_is_idempotent():
    manager, world, store, _ = build()
    started = manager.start(SPEC)
    assert manager.stop("t").outcome is StopOutcome.STOPPED
    assert started.pid not in world.procs and "t" not in store.records
    assert manager.stop("t").outcome is StopOutcome.ALREADY_STOPPED


def test_stop_refuses_to_kill_a_reused_pid():
    manager, world, store, _ = build()
    world.procs[555] = 42.0
    store.records["t"] = ServiceRecord("t", ProcessIdentity(555, 1.0))  # right pid, wrong creation time
    result = manager.stop("t")
    assert result.outcome is StopOutcome.PID_REUSED and result.ok
    assert 555 in world.procs and not world.terminated and "t" not in store.records


def test_stop_of_an_exited_process_clears_the_record():
    manager, _, store, _ = build()
    store.records["t"] = ServiceRecord("t", ProcessIdentity(999, 1.0))
    assert manager.stop("t").outcome is StopOutcome.ALREADY_STOPPED and "t" not in store.records


def test_process_that_survives_stop_keeps_its_record_and_reports_uncertain():
    manager, world, store, _ = build()
    started = manager.start(SPEC)
    world.survives.add(started.pid)
    result = manager.stop("t")
    assert result.outcome is StopOutcome.UNCERTAIN and not result.ok and "t" in store.records


def test_unreadable_record_is_never_read_as_stopped_and_blocks_start():
    manager, world, store, _ = build()
    store.unreadable.add("t")
    stopped = manager.stop("t")
    assert stopped.outcome is StopOutcome.UNCERTAIN and not stopped.ok
    started = manager.start(SPEC)
    assert started.method is LaunchMethod.FAILED and not world.procs
    assert manager.status("t").error


def test_register_self_records_the_caller_unless_another_live_process_holds_it():
    manager, world, store, _ = build()
    world.procs[1] = 5.0  # "me"
    assert manager.register_self("t") and store.records["t"].identity.pid == 1
    world.procs[2] = 6.0
    store.records["t"] = ServiceRecord("t", ProcessIdentity(2, 6.0))
    assert not manager.register_self("t") and store.records["t"].identity.pid == 2
    world.procs.pop(2)
    assert manager.register_self("t") and store.records["t"].identity.pid == 1


def test_start_needs_a_name():
    manager, *_ = build()
    with pytest.raises(ValueError):
        manager.start(ProcessSpec(("svc",)))


def test_a_spawned_process_that_is_already_gone_is_a_failure_not_a_success():
    manager, world, store, _ = build()
    world.exit_immediately = True
    result = manager.start(SPEC)
    assert result.method is LaunchMethod.FAILED and not result.ok
    assert "exited before it could be recorded" in result.error and "t" not in store.records


def test_an_unexpected_error_while_identifying_releases_the_reservation():
    manager, world, store, _ = build()

    def boom(pid):
        raise RuntimeError("psutil exploded")

    world.identify = boom
    result = manager.start(SPEC)
    assert result.method is LaunchMethod.FAILED and "t" not in store.records


def test_even_keyboard_interrupt_releases_the_reservation():
    manager, world, store, _ = build()
    world.spawn_error = KeyboardInterrupt()  # not an Exception: escapes the launcher
    with pytest.raises(KeyboardInterrupt):
        manager.start(SPEC)
    assert "t" not in store.records
    world.spawn_error = None
    assert manager.start(SPEC).started  # not blocked for two minutes


def test_a_starter_never_releases_a_reservation_that_is_no_longer_its_own():
    manager, world, store, _ = build()
    other = ServiceRecord("t", None, reserved_at=1e12)

    def someone_else_takes_over():
        store.records["t"] = other

    world.spawn_hook = someone_else_takes_over
    world.spawn_error = FileNotFoundError("nope")
    assert manager.start(SPEC).method is LaunchMethod.FAILED
    assert store.records["t"] == other  # their reservation survives our cleanup


def test_losing_a_takeover_race_is_in_progress_and_launches_nothing():
    manager, world, store, clock = build()
    stale = ServiceRecord("t", None, reserved_at=clock.now() - 10_000)
    store.records["t"] = stale
    real_take_over = store.take_over

    def lose(name, expected, new):
        store.records["t"] = ServiceRecord("t", None, reserved_at=clock.now())  # a rival got there first
        return real_take_over(name, expected, new)

    store.take_over = lose
    result = manager.start(SPEC)
    assert result.method is LaunchMethod.IN_PROGRESS and not world.procs


def test_concurrent_takeover_of_a_stale_reservation_launches_exactly_one_process():
    clock = FakeClock()
    world, store = FakeWorld(clock), FakeStore()
    store.records["t"] = ServiceRecord("t", None, reserved_at=clock.now() - 10_000)
    results, barrier = [], threading.Barrier(8)

    def go():
        manager = ServiceManager(launcher=Launcher(world), inspector=world, store=store, clock=clock, adopt_wait=0)
        barrier.wait()
        results.append(manager.start(SPEC))

    threads = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(r.started for r in results) == 1
    assert len(world.procs) == 1


# ---------------- readiness over a fake clock ----------------

class FlagProbe:
    def __init__(self, results, require_owned=False):
        self.results, self.require_owned, self.calls = list(results), require_owned, 0

    def run(self, timeout):
        self.calls += 1
        return self.results.pop(0) if self.results else False


def test_readiness_ready_timeout_and_early_crash():
    clock = FakeClock()
    ok = wait_for_readiness(FlagProbe([True]), clock=clock, timeout=2)
    assert ok.ready and ok.reason == "ready"
    slow = wait_for_readiness(FlagProbe([]), clock=clock, timeout=0.3, interval=0.05)
    assert not slow.ready and slow.reason == "timeout" and slow.attempts >= 2
    crashed = wait_for_readiness(FlagProbe([True]), clock=clock, timeout=2, process_running=lambda: False)
    assert crashed.reason == "process-exited"


def test_readiness_unrelated_listener_does_not_count_as_healthy():
    states = iter([True, False])  # probe answers, but the process died while it did
    result = wait_for_readiness(FlagProbe([True]), clock=FakeClock(), timeout=2, process_running=lambda: next(states))
    assert not result.ready and result.reason == "process-exited"
    unowned = wait_for_readiness(
        FlagProbe([True, True, True], require_owned=True), clock=FakeClock(), timeout=0.3, interval=0.05,
        listener_owned=lambda: False,
    )
    assert unowned.reason == "listener-unverified"


# ---------------- JSON store adapter ----------------

@pytest.mark.parametrize("content", ["{not json", "[]", '{"pid": 5}', '{"pid": "x", "create_time": 1}'])
def test_json_store_reports_untrusted_records_and_leaves_them_in_place(tmp_path, content):
    (tmp_path / "t.json").write_text(content)
    with pytest.raises(RecordUnreadable):
        JsonFileRecordStore(tmp_path).load("t")
    assert (tmp_path / "t.json").read_text() == content


def test_json_store_roundtrip_exclusive_create_and_delete(tmp_path):
    store = JsonFileRecordStore(tmp_path / "svc")
    rec = ServiceRecord("t", ProcessIdentity(5, 1.5), argv=("a", "b"), cwd="/x", method="spawned")
    assert store.create_exclusive("t", rec) and not store.create_exclusive("t", rec)
    assert store.load("t") == rec
    store.replace("t", ServiceRecord("t", None, reserved_at=3.0))
    assert store.load("t").is_reservation
    store.delete("t")
    store.delete("t")
    assert store.load("t") is None


@pytest.mark.parametrize("name", ["", "a/b", "..", "a\\b"])
def test_json_store_rejects_invalid_names(tmp_path, name):
    with pytest.raises(ValueError):
        JsonFileRecordStore(tmp_path).load(name)


# ---------------- real adapters, real child processes ----------------

@pytest.fixture
def state(tmp_path):
    yield tmp_path / "svc"
    for rec in (tmp_path / "svc").glob("*.json"):
        try:
            data = json.loads(rec.read_text())
            proc = psutil.Process(data["pid"])
            for child in proc.children(recursive=True):
                child.kill()
            proc.kill()
        except Exception:  # noqa: BLE001 -- cleanup only
            pass


def _spec(**kw):
    return ProcessSpec(SLEEPER, name="t", **kw)


def test_real_start_status_duplicate_and_stop_with_children(state):
    code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); time.sleep(60)"
    spec = ProcessSpec((sys.executable, "-c", code), name="t")
    first = api.start_service(spec, state_dir=state)
    assert first.method is LaunchMethod.SPAWNED and first.pid
    assert api.service_status("t", state_dir=state).running
    assert api.start_service(spec, state_dir=state).method is LaunchMethod.ALREADY_RUNNING
    time.sleep(1.0)
    kids = psutil.Process(first.pid).children(recursive=True)
    assert api.stop_service("t", state_dir=state).outcome is StopOutcome.STOPPED
    assert not psutil.pid_exists(first.pid) or not psutil.Process(first.pid).is_running()
    assert not any(k.is_running() for k in kids)
    assert api.stop_service("t", state_dir=state).outcome is StopOutcome.ALREADY_STOPPED


def test_real_concurrent_starts_launch_exactly_one_process(state):
    results = []
    barrier = threading.Barrier(5)

    def go():
        barrier.wait()
        results.append(api.start_service(_spec(), state_dir=state))

    threads = [threading.Thread(target=go) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(r.started for r in results) == 1
    assert all(r.ok or r.method is LaunchMethod.IN_PROGRESS for r in results)


def test_real_stop_leaves_an_unrelated_process_with_a_reused_pid_alone(state):
    bystander = psutil.Popen(SLEEPER)
    try:
        JsonFileRecordStore(state).replace(
            "t", ServiceRecord("t", ProcessIdentity(bystander.pid, bystander.create_time() - 500)),
        )
        result = api.stop_service("t", state_dir=state)
        assert result.outcome is StopOutcome.PID_REUSED and bystander.is_running()
    finally:
        bystander.kill()


def test_real_probe_adapter_never_raises_and_reports_health():
    assert CallableProbe(lambda: True).run(1) and not CallableProbe(lambda: 1 / 0).run(1)
    result = api.wait_for_readiness(CallableProbe(lambda: True), timeout=2)
    assert result.ready


def _record(state_dir, expected_pid=None):
    return JsonFileRecordStore(state_dir)


def test_json_store_compare_and_swap_only_succeeds_against_the_expected_record(tmp_path):
    store = JsonFileRecordStore(tmp_path)
    a = ServiceRecord("t", None, reserved_at=1.0)
    b = ServiceRecord("t", None, reserved_at=2.0)
    c = ServiceRecord("t", ProcessIdentity(9, 1.0))
    assert not store.take_over("t", a, b)  # nothing there yet
    assert store.create_exclusive("t", a)
    assert not store.take_over("t", b, c) and store.load("t") == a  # stale expectation
    assert store.take_over("t", a, b) and store.load("t") == b
    assert not store.delete_if("t", a) and store.load("t") == b  # not ours any more
    assert store.delete_if("t", b) and store.load("t") is None


def test_json_store_concurrent_takeover_has_exactly_one_winner(tmp_path):
    store = JsonFileRecordStore(tmp_path)
    old = ServiceRecord("t", None, reserved_at=1.0)
    store.create_exclusive("t", old)
    wins, barrier = [], threading.Barrier(8)

    def go(i):
        barrier.wait()
        wins.append(store.take_over("t", old, ServiceRecord("t", None, reserved_at=100.0 + i)))

    threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(wins) == 1


def test_json_store_breaks_a_stale_lock_left_by_a_dead_holder(tmp_path):
    import os

    store = JsonFileRecordStore(tmp_path)
    old = ServiceRecord("t", None, reserved_at=1.0)
    store.create_exclusive("t", old)
    lock = tmp_path / "t.lock"
    lock.write_text("")
    long_ago = time.time() - 3600
    os.utime(lock, (long_ago, long_ago))
    assert store.take_over("t", old, ServiceRecord("t", None, reserved_at=2.0))
    assert not lock.exists()


def test_same_executable_matches_the_windowless_twin_but_not_other_places_or_interpreters():
    from proclaunch.adapters.psutil_inspector import same_executable

    assert same_executable(r"C:\v\Scripts\pythonw.exe", r"C:\v\Scripts\python.exe")
    assert same_executable(r"C:\V\SCRIPTS\PYTHON.EXE", r"c:\v\scripts\python.exe") or sys.platform != "win32"
    assert not same_executable(r"C:\other\python.exe", r"C:\v\Scripts\python.exe")
    assert not same_executable(r"C:\v\Scripts\node.exe", r"C:\v\Scripts\python.exe")


def test_find_started_returns_the_one_matching_process_and_never_guesses():
    from proclaunch.adapters.psutil_inspector import PsutilInspector

    token = f"proclaunch-find-{time.time_ns()}"
    argv = (sys.executable, "-c", f"import time; time.sleep(60)  # {token}")
    inspector = PsutilInspector()
    before = time.time()
    first = psutil.Popen(list(argv))
    others = []
    try:
        time.sleep(0.5)
        found = inspector.find_started(argv, before)
        assert found is not None and found.pid == first.pid  # the root, not a launcher's child
        assert inspector.find_started(argv, time.time() + 60) is None  # started before the launch: not ours
        assert inspector.find_started((r"C:\nowhere\python.exe", *argv[1:]), before) is None  # wrong executable
        assert inspector.find_started((*argv[:-1], argv[-1] + " "), before) is None  # different arguments
        others.append(psutil.Popen(list(argv)))
        time.sleep(0.5)
        assert inspector.find_started(argv, before) is None  # two candidates: refuse to pick one
    finally:
        for proc in [first, *others]:
            try:
                for child in proc.children(recursive=True):
                    child.kill()
                proc.kill()
            except psutil.Error:
                pass
