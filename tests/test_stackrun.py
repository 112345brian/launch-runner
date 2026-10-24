"""stackrun: domain, the Launcher against fakes, the declarative loader, and the fakes against the kit."""
from __future__ import annotations

import pytest

from stackrun.declarative import parse_stack
from stackrun.domain import (
    Identity,
    ServiceSpec,
    Stack,
    StackrunError,
    child_environment,
    split_command,
)
from stackrun.launcher import Launcher
from stackrun.testing import (
    FakeBrowser,
    FakeConfig,
    FakeConsole,
    FakeHook,
    FakePorts,
    FakeProcess,
    FakeProcesses,
    FakeReadiness,
    FakeRecord,
    FakeResolver,
    FakeRunner,
    FakeShutdown,
    check_ports,
    check_processes,
    check_run_record,
)

URL = "http://localhost:3000/"
LAUNCHER_ID = Identity(777, 1000.5)


def stack(*, hint: str = "run `app --stop`") -> Stack:
    return Stack(
        "app",
        (
            ServiceSpec("api", ("uv", "run", "api"), port=8000, env={"MODE": "dev"}, cwd="apps/api"),
            ServiceSpec("web", ("npx", "web"), port=3000, ready_url=URL),
        ),
        stop_hint=hint,
    )


def build(*, runner=None, resolver=None, config=None, sleep=None, the_stack=None, **kw):
    runner = runner or FakeRunner(exits={"uv": 0})
    console = FakeConsole()
    launcher = Launcher(
        the_stack or stack(), runner, resolver or FakeResolver(), config or FakeConfig({}), console,
        sleep or (lambda s: None), **kw,
    )
    return launcher, runner, console


# --- domain ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", []), ("   ", []), ("a b  c", ["a", "b", "c"]),
        ('python "my dir/x.py" --port 8001', ["python", "my dir/x.py", "--port", "8001"]),
        ("run 'a b' c", ["run", "a b", "c"]), ('x ""', ["x", ""]),
        ("local_voice\\bin\\server.exe --dev", ["local_voice\\bin\\server.exe", "--dev"]),
        ('"C:\\Program Files\\x\\y.exe" -v', ["C:\\Program Files\\x\\y.exe", "-v"]), ("a\tb", ["a", "b"]),
    ],
)
def test_split_command_is_the_same_everywhere(text, expected):
    assert split_command(text) == expected


@pytest.mark.parametrize("text", ['a "b', "a 'b"])
def test_split_command_rejects_unterminated_quotes(text):
    with pytest.raises(StackrunError):
        split_command(text)


def test_child_environment_drops_blanks_and_named_variables_and_layers_the_overlay():
    assert child_environment({"A": "", "B": " ", "C": "0"}) == {"B": " ", "C": "0"}
    assert child_environment({"VIRTUAL_ENV": "/x", "K": "1"}, drop=frozenset({"VIRTUAL_ENV"})) == {"K": "1"}
    assert child_environment({"A": "1"}, {"A": "2", "B": ""}) == {"A": "2", "B": ""}


@pytest.mark.parametrize("identity", [Identity(1, 0.0), Identity(4242, 1700000000.123456), Identity(7, 1e-3)])
def test_identity_round_trips_through_text(identity):
    assert Identity.from_text(identity.to_text()) == identity


@pytest.mark.parametrize(
    "text",
    ["", "   ", "garbage", "123", "1 2 3", "abc 1.0", "12 notafloat", "1.5 2.0", "\x00 \x00", "12\x00 1.0",
     "0 1.0", "-5 1.0", "5 nan", "5 inf", "5 -1.0"],
)
def test_identity_from_unusable_text_is_none(text):
    assert Identity.from_text(text) is None


def test_identity_tolerates_surrounding_whitespace():
    assert Identity.from_text("  12   3.5\n") == Identity(12, 3.5)


@pytest.mark.parametrize(
    "bad",
    [
        lambda: ServiceSpec("", ("x",)), lambda: ServiceSpec("a", ()), lambda: ServiceSpec("a", ("",)),
        lambda: ServiceSpec("a", ("x",), port=0), lambda: ServiceSpec("a", ("x",), port=70000),
        lambda: ServiceSpec("a", ("x",), port=True), lambda: Stack("s", ()), lambda: Stack("bad name", (ServiceSpec("a", ("x",)),)),
        lambda: Stack("s", (ServiceSpec("a", ("x",)), ServiceSpec("a", ("y",)))),
    ],
)
def test_invalid_specs_and_stacks_are_rejected(bad):
    with pytest.raises(StackrunError):
        bad()


def test_specs_are_normalised_and_hashable_values():
    spec = ServiceSpec("a", ["x", "y"], env={"K": "v"}, cwd=".")  # type: ignore[arg-type]
    assert spec.argv == ("x", "y") and spec.env == {"K": "v"}
    assert hash(spec) == hash(ServiceSpec("a", ("x", "y"), env={"K": "other"}, cwd="."))  # env is not hashed
    assert stack().ports == (("api", 8000), ("web", 3000))


# --- Launcher: start, supervise, stop --------------------------------------------------------------------


def test_starts_resolved_programs_in_order_and_stops_everything_in_reverse():
    order: list[str] = []

    class Tracked(FakeProcess):
        def __init__(self, name):
            super().__init__(0 if name == "uv" else None)
            self.name = name

        def stop(self):
            super().stop()
            order.append(self.name)

    runner = FakeRunner(make_handle=None)
    runner.start = (  # type: ignore[method-assign]
        lambda argv, env, cwd=None: runner.started.append((list(argv), (h := Tracked(argv[0].split("/")[-1])))) or h
    )
    launcher, _, console = build(runner=runner)
    assert launcher.run() == 0
    assert [a[0] for a, _ in runner.started] == ["/resolved/uv", "/resolved/npx"]
    assert order == ["npx", "uv"], "last started is stopped first"
    assert "api exited with code 0" in console.text


def test_each_service_gets_the_config_minus_blanks_overlaid_with_its_own_env_and_its_cwd():
    launcher, runner, _ = build(config=FakeConfig({"PATH": "/bin", "BLANK": "", "MODE": "prod"}))
    launcher.run()
    assert runner.envs[0] == {"PATH": "/bin", "MODE": "dev"}
    assert runner.envs[1] == {"PATH": "/bin", "MODE": "prod"}
    assert runner.cwds == ["apps/api", None]


def test_a_missing_program_fails_before_anything_is_claimed_started_or_prepared():
    record, hook = FakeRecord(), FakeHook()
    launcher, runner, _ = build(resolver=FakeResolver({"npx"}), record=record, hook=hook)
    with pytest.raises(StackrunError, match="web: cannot find 'npx'"):
        launcher.run()
    assert runner.started == [] and record.claims == 0 and hook.seen == []


def test_config_errors_propagate_untouched():
    launcher, runner, _ = build(config=FakeConfig(error=StackrunError(".env missing")))
    with pytest.raises(StackrunError, match=".env missing"):
        launcher.run()
    assert runner.started == []


def test_ctrl_c_stops_everything_and_exits_cleanly():
    def interrupt(_s):
        raise KeyboardInterrupt

    record = FakeRecord()
    launcher, runner, _ = build(sleep=interrupt, runner=FakeRunner(), record=record)
    assert launcher.run() == 0
    assert len(runner.started) == 2 and all(p.stopped == 1 for p in runner.processes) and record.clears == 1


def test_it_polls_with_the_injected_sleep_not_the_clock():
    sleeps: list[float] = []
    runner = FakeRunner()

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            runner.processes[0].exits_with = 9

    launcher, _, _ = build(runner=runner, sleep=sleep)
    assert launcher.run() == 9 and sleeps == [1, 1, 1]


def test_a_start_failure_midway_stops_what_started_and_releases_the_claim():
    runner, shutdown, record = FakeRunner(fail={"npx": OSError("boom")}), FakeShutdown(), FakeRecord()
    launcher, _, _ = build(runner=runner, shutdown=shutdown, record=record)
    with pytest.raises(OSError, match="boom"):
        launcher.run()
    assert len(runner.started) == 1 and runner.processes[0].stopped == 1
    assert record.clears == 1 and shutdown.exited == 1


def test_a_second_interrupt_while_stopping_does_not_abandon_the_remaining_services():
    class Interrupted(FakeProcess):
        def stop(self):
            super().stop()
            if self.stopped == 1:
                raise KeyboardInterrupt

    launcher, runner, _ = build(runner=FakeRunner(make_handle=Interrupted), sleep=lambda s: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert launcher.run() == 0
    assert [p.stopped for p in runner.processes] == [2, 2], "each is retried once, none is skipped"


def test_a_service_that_fails_to_stop_is_reported_and_the_rest_are_still_stopped():
    class Broken(FakeProcess):
        def stop(self):
            super().stop()
            raise RuntimeError("stuck")

    handles = iter([FakeProcess(), Broken()])
    launcher, runner, console = build(
        runner=FakeRunner(make_handle=lambda: next(handles)),
        sleep=lambda s: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    assert launcher.run() == 0
    assert runner.processes[0].stopped == 1 and "Could not stop web: stuck" in console.text


def test_run_works_with_no_optional_collaborator_wired():
    launcher, runner, _ = build()
    assert launcher.run() == 0 and all(p.stopped == 1 for p in runner.processes)


# --- one launch at a time, ports -------------------------------------------------------------------------


def test_a_second_launch_is_refused_before_anything_starts_and_does_not_touch_the_first():
    record = FakeRecord(holder_alive=True)
    launcher, runner, _ = build(record=record)
    with pytest.raises(StackrunError, match="already starting or running") as caught:
        launcher.run()
    assert "run `app --stop`" in str(caught.value)
    assert runner.started == [] and record.clears == 0, "the loser must not erase the winner's claim"


def test_the_claim_is_released_after_a_normal_run_and_after_a_refused_launch():
    record = FakeRecord()
    build(record=record)[0].run()
    assert record.claims == 1 and record.clears == 1
    failing = FakeRecord()
    with pytest.raises(StackrunError):
        build(record=failing, ports=FakePorts({8000: "python (pid 1)"}))[0].run()
    assert failing.clears == 1


def test_busy_ports_are_named_with_what_holds_them_and_nothing_starts_or_is_prepared():
    hook = FakeHook()
    launcher, runner, _ = build(ports=FakePorts({3000: "node (pid 4242)", 8000: None}), hook=hook)
    with pytest.raises(StackrunError) as caught:
        launcher.run()
    message = str(caught.value)
    assert "web: port 3000 is used by node (pid 4242)" in message
    assert "api: port 8000 is used by another program" in message and "--stop" in message
    assert runner.started == [] and hook.seen == []


def test_running_means_every_declared_port_is_taken():
    assert build(ports=FakePorts({8000: "a", 3000: "b"}))[0].is_running() is True
    assert build(ports=FakePorts({8000: "a"}))[0].is_running() is False
    assert build(ports=FakePorts())[0].is_running() is False
    assert build()[0].is_running() is False
    portless = Stack("p", (ServiceSpec("w", ("x",)),))
    assert build(ports=FakePorts({1: "a"}), the_stack=portless)[0].is_running() is False


# --- hook, readiness, browser ------------------------------------------------------------------------------


def test_the_hook_runs_once_after_the_port_check_and_before_the_first_start():
    seen_started: list[int] = []
    runner = FakeRunner(exits={"uv": 0})
    hook = FakeHook()
    hook.before_start = lambda s: seen_started.append(len(runner.started)) or FakeHook.before_start(hook, s)  # type: ignore[method-assign]
    build(runner=runner, hook=hook)[0].run()
    assert seen_started == [0] and hook.seen == [stack()]


def test_a_hook_that_refuses_stops_the_launch_and_releases_the_claim():
    record, shutdown = FakeRecord(), FakeShutdown()
    launcher, runner, _ = build(hook=FakeHook(StackrunError("no")), record=record, shutdown=shutdown)
    with pytest.raises(StackrunError, match="no"):
        launcher.run()
    assert runner.started == [] and record.clears == 1 and shutdown.exited == 1


def test_a_service_with_ready_url_must_answer_before_the_launch_goes_on():
    readiness = FakeReadiness(answers_after=2)
    sleeps: list[float] = []
    launcher, _, _ = build(readiness=readiness, sleep=sleeps.append)
    launcher.run()
    assert readiness.probes == [URL] * 3 and sleeps[:2] == [0.5, 0.5]


def test_a_service_that_dies_before_it_is_ready_fails_the_launch_and_stops_the_rest():
    runner = FakeRunner(exits={"npx": 5})
    launcher, _, _ = build(runner=runner, readiness=FakeReadiness(never={URL}))
    with pytest.raises(StackrunError, match="web exited with code 5 before it was ready"):
        launcher.run()
    assert all(p.stopped == 1 for p in runner.processes)


def test_a_service_that_never_answers_times_out_and_ready_url_is_ignored_without_a_probe():
    runner = FakeRunner()
    launcher, _, _ = build(runner=runner, readiness=FakeReadiness(never={URL}), ready_timeout=2)
    with pytest.raises(StackrunError, match="did not answer"):
        launcher.run()
    assert all(p.stopped == 1 for p in runner.processes)
    quick = build(runner=FakeRunner(exits={"uv": 0}))[0]  # no readiness wired: ready_url is not waited for
    assert quick.run() == 0


def test_the_browser_opens_when_ready_after_everything_started_and_reopen_opens_now():
    browser = FakeBrowser()
    launcher, runner, console = build(browser=browser, open_url=URL)
    launcher.run()
    assert browser.when_ready == [URL] and len(runner.started) == 2 and URL in console.text
    launcher.reopen()
    assert browser.now == [URL]


def test_no_browser_without_open_url_or_when_startup_fails():
    browser = FakeBrowser()
    build(browser=browser)[0].run()
    build(browser=browser)[0].reopen()
    assert browser.when_ready == [] and browser.now == []
    with pytest.raises(StackrunError):
        build(browser=browser, open_url=URL, ports=FakePorts({3000: "x"}))[0].run()
    assert browser.when_ready == []


# --- shutdown guard -----------------------------------------------------------------------------------------


def test_the_guard_is_entered_once_and_left_even_when_startup_fails():
    shutdown = FakeShutdown()
    build(shutdown=shutdown)[0].run()
    assert (shutdown.entered, shutdown.exited) == (1, 1)
    failing = FakeShutdown()
    with pytest.raises(StackrunError):
        build(shutdown=failing, ports=FakePorts({3000: "x"}))[0].run()
    assert (failing.entered, failing.exited) == (1, 1)


def test_the_guard_is_left_only_after_the_services_were_stopped():
    shutdown = FakeShutdown()
    launcher, runner, _ = build(shutdown=shutdown)
    shutdown.at_exit = lambda: [p.stopped for p in runner.processes]
    launcher.run()
    assert shutdown.exit_snapshot == [1, 1]


# --- Launcher.stop ------------------------------------------------------------------------------------------


def test_stop_kills_a_recorded_live_launcher_then_discards_the_record():
    record, processes = FakeRecord(identity=LAUNCHER_ID), FakeProcesses({LAUNCHER_ID})
    launcher, _, console = build(record=record, processes=processes)
    assert launcher.stop() is True
    assert processes.stopped == [LAUNCHER_ID] and record.discards == [LAUNCHER_ID] and "stopped" in console.text


def test_stop_polls_with_the_injected_sleep_until_the_launcher_is_gone():
    record, processes = FakeRecord(identity=LAUNCHER_ID), FakeProcesses({LAUNCHER_ID}, dies_after=3)
    sleeps: list[float] = []
    launcher, _, _ = build(record=record, processes=processes, sleep=sleeps.append)
    assert launcher.stop() is True and len(sleeps) == 3 and record.discards == [LAUNCHER_ID]


def test_stop_gives_up_when_the_launcher_never_exits_and_keeps_the_record():
    record, processes = FakeRecord(identity=LAUNCHER_ID), FakeProcesses({LAUNCHER_ID}, dies_after=None)
    sleeps: list[float] = []
    launcher, _, console = build(record=record, processes=processes, sleep=sleeps.append)
    assert launcher.stop() is False and len(sleeps) == 20 and record.discards == []
    assert "did not stop in time" in console.text


def test_stop_never_stops_a_recorded_identity_that_is_not_alive_and_drops_its_record():
    record, processes = FakeRecord(identity=LAUNCHER_ID), FakeProcesses(set())
    launcher, _, console = build(record=record, processes=processes)
    assert launcher.stop() is False and processes.stopped == [] and record.discards == [LAUNCHER_ID]
    assert "not running" in console.text


def test_stop_with_nothing_recorded_or_nothing_wired_just_says_so():
    record, processes = FakeRecord(identity=None), FakeProcesses({LAUNCHER_ID})
    launcher, _, console = build(record=record, processes=processes)
    assert launcher.stop() is False and "not running" in console.text and record.discards == []
    assert build()[0].stop() is False


# --- declarative loader -------------------------------------------------------------------------------------

TOML = """
name = "demo"
open_url = "http://localhost:3000"
stop_hint = "`stackrun stop`"

[[service]]
name = "api"
command = 'uvicorn app:app --port 8000'
port = 8000
cwd = "apps/api"
[service.env]
MODE = "dev"

[[service]]
name = "web"
argv = ["npx", "web"]
ready_url = "http://localhost:3000"
"""


def test_toml_builds_the_stack():
    parsed = parse_stack(TOML)
    assert parsed.open_url == "http://localhost:3000" and parsed.stack.stop_hint == "`stackrun stop`"
    api, web = parsed.stack.services
    assert api == ServiceSpec("api", ("uvicorn", "app:app", "--port", "8000"), 8000, {"MODE": "dev"}, "apps/api")
    assert web.argv == ("npx", "web") and web.ready_url == "http://localhost:3000"


@pytest.mark.parametrize(
    "text",
    [
        "", "name = 'x'", "name = 'x'\n[[service]]\nname='a'", "name='x'\n[[service]]\nname='a'\ncommand='c'\nargv=['c']",
        "name='x'\ntypo=1\n[[service]]\nname='a'\ncommand='c'", "name='x'\n[[service]]\nname='a'\ncommand='c'\nbogus=1",
        "name='x'\n[[service]]\nname='a'\ncommand='c'\nport='80'", "name='x'\n[[service]]\nname='a'\nargv=[1]",
        "name='x'\n[[service]]\nname='a'\ncommand='c'\nenv={K=1}", "name = [", "name='x'\nservice=3",
        "name='x'\n[[service]]\nname='a'\ncommand='a \"b'",
    ],
)
def test_bad_toml_is_a_stackrun_error(text):
    with pytest.raises(StackrunError):
        parse_stack(text)


# --- the fakes satisfy the conformance kit ------------------------------------------------------------------


# A faithful in-memory RunRecord: it exists only to prove the conformance kit accepts a good record, so it
# lives with the tests instead of in the public testing module.
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
def test_in_memory_record_passes_the_kit():
    store: dict[str, Identity] = {}
    check_run_record(lambda me, procs: InMemoryRunRecord(procs, store))


def test_fake_processes_and_ports_pass_the_kit():
    procs = FakeProcesses()
    check_processes(procs, procs.spawn, sleep=lambda s: None)
    ports = FakePorts()
    check_ports(ports, ports.listen)


def test_the_kit_fails_a_record_that_lets_two_launchers_claim():
    class Careless(InMemoryRunRecord):
        def claim(self) -> bool:
            self._store[self._key] = self._processes.current()
            return True

    store: dict[str, Identity] = {}
    with pytest.raises(AssertionError, match="live holder blocks"):
        check_run_record(lambda me, procs: Careless(procs, store))
