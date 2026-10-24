"""stackrun's real adapters: identity, process trees, signals, the claim file, sockets, browser, resolver.

Needs psutil and proclaunch (both importable from this repo's source trees / the test environment).
POSIX-only tests keep their skip markers; this author could only run them on Windows.
"""
from __future__ import annotations

import contextlib
import http.server
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
import pytest

from stackrun.adapters import (
    BrowserOpener,
    EnvironConfig,
    FileRunRecord,
    FilesystemResolver,
    HttpReadiness,
    PsutilProcesses,
    SignalShutdown,
    SocketPorts,
    SubprocessRunner,
    scrub_environment,
)
from stackrun.domain import Identity
from stackrun.testing import FakeProcesses, check_ports, check_processes, check_run_record

POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="POSIX process groups / signals")
ROOT = Path(__file__).resolve().parent.parent
SRC_DIRS = [ROOT / "distributions" / n / "src" for n in ("stackrun", "proclaunch")]

_SLEEP = "import time; time.sleep(120)"
_SPAWN_GRANDCHILD = (
    "import subprocess, sys, time, pathlib\n"
    "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "pathlib.Path(sys.argv[1]).write_text(str(g.pid))\n"
    "time.sleep(120)\n"
)
_LEADER_EXITS_LEAVING_GRANDCHILD = (
    "import subprocess, sys, pathlib\n"
    "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "pathlib.Path(sys.argv[1]).write_text(str(g.pid))\n"
)


def _wait_for_file(path: Path, timeout: float = 15.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError):
            text = path.read_text(encoding="utf-8")
            if text:
                return text
        time.sleep(0.05)
    raise AssertionError(f"{path} was not written in time")


def _is_gone(pid: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.Error:
            return True
        time.sleep(0.05)
    return False


def _kill_pid(pid: int) -> None:
    with contextlib.suppress(psutil.Error):
        psutil.Process(pid).kill()


def _identity_of(pid: int) -> Identity:
    return Identity(pid, psutil.Process(pid).create_time())


def _wait_exit(handle, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while handle.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)


# --- ConfigSource / environment --------------------------------------------------------------------------


def test_environ_config_overlays_overrides_on_the_process_environment(monkeypatch):
    monkeypatch.setenv("STACKRUN_PROBE", "process")
    assert EnvironConfig().environment()["STACKRUN_PROBE"] == "process"
    assert EnvironConfig({"STACKRUN_PROBE": "fixed"}).environment()["STACKRUN_PROBE"] == "fixed"


def test_scrub_removes_the_named_variables_and_leaves_the_rest(monkeypatch):
    monkeypatch.setenv("VIRTUAL_ENV", "/tmp/throwaway-env")
    monkeypatch.setenv("STACKRUN_KEEP_ME", "yes")
    scrub_environment(["VIRTUAL_ENV"])
    assert "VIRTUAL_ENV" not in os.environ and os.environ["STACKRUN_KEEP_ME"] == "yes"
    scrub_environment(["VIRTUAL_ENV"])  # nothing left to remove: still fine


# --- resolver ----------------------------------------------------------------------------------------------


def _make_program(directory: Path, name: str) -> Path:
    """A file the platform considers runnable: .bat on Windows, an executable bit elsewhere."""
    if os.name == "nt":
        path = directory / f"{name}.bat"
        path.write_text("@echo off\r\n", encoding="utf-8")
    else:
        path = directory / name
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_resolver_finds_relative_programs_without_the_extension(tmp_path):
    (tmp_path / "bin").mkdir()
    program = _make_program(tmp_path / "bin", "server")
    found = FilesystemResolver(tmp_path).resolve("bin/server")
    assert found is not None and Path(found).samefile(program)
    if os.name == "nt":  # backslashes are separators only on Windows
        assert FilesystemResolver(tmp_path).resolve("bin\\server") is not None


def test_resolver_returns_none_for_unknown_programs_and_finds_the_interpreter(tmp_path):
    resolver = FilesystemResolver(tmp_path)
    assert resolver.resolve("bin/missing") is None
    assert resolver.resolve("definitely-not-a-real-program-xyz") is None
    assert resolver.resolve(sys.executable) is not None


# --- runner -------------------------------------------------------------------------------------------------


def test_runner_starts_polls_and_stops_a_real_process(tmp_path):
    handle = SubprocessRunner(tmp_path).start([sys.executable, "-c", _SLEEP], dict(os.environ))
    try:
        assert handle.poll() is None
    finally:
        handle.stop()
    _wait_exit(handle)
    assert handle.poll() is not None
    handle.stop()  # safe to call twice


def test_runner_hands_environment_and_cwd_to_the_process(tmp_path):
    (tmp_path / "sub").mkdir()
    out = tmp_path / "seen.txt"
    code = f"import os, pathlib; pathlib.Path({str(out)!r}).write_text(os.environ['STACKRUN_PROBE'] + '|' + os.getcwd())"
    handle = SubprocessRunner(tmp_path).start([sys.executable, "-c", code], {**os.environ, "STACKRUN_PROBE": "hi"}, "sub")
    _wait_exit(handle)
    probe, cwd = out.read_text(encoding="utf-8").split("|")
    assert probe == "hi" and Path(cwd).samefile(tmp_path / "sub")


def test_runner_reports_the_exit_code(tmp_path):
    handle = SubprocessRunner(tmp_path).start([sys.executable, "-c", "raise SystemExit(7)"], dict(os.environ))
    _wait_exit(handle)
    assert handle.poll() == 7


def test_stopping_a_service_takes_its_grandchild_down_too(tmp_path):
    marker = tmp_path / "grandchild.pid"
    handle = SubprocessRunner(tmp_path).start([sys.executable, "-c", _SPAWN_GRANDCHILD, str(marker)], dict(os.environ))
    grandchild = None
    try:
        grandchild = int(_wait_for_file(marker))
        assert handle.poll() is None
        handle.stop()
        assert handle.poll() is not None
        assert _is_gone(grandchild), "npx/uv/pnpm style wrappers must not leave their children behind"
        handle.stop()  # safe to call twice
    finally:
        handle.stop()
        if grandchild is not None:
            _kill_pid(grandchild)


@POSIX_ONLY
def test_stopping_still_kills_a_grandchild_after_the_group_leader_exited(tmp_path):
    marker = tmp_path / "grandchild.pid"
    handle = SubprocessRunner(tmp_path).start(
        [sys.executable, "-c", _LEADER_EXITS_LEAVING_GRANDCHILD, str(marker)], dict(os.environ)
    )
    grandchild = None
    try:
        grandchild = int(_wait_for_file(marker))
        _wait_exit(handle, 15)
        assert handle.poll() is not None, "the leader has exited, the grandchild is still in its group"
        assert psutil.pid_exists(grandchild) and not _is_gone(grandchild, timeout=0.2)
        handle.stop()
        assert _is_gone(grandchild)
    finally:
        if grandchild is not None:
            _kill_pid(grandchild)


def test_a_custom_terminator_is_used_instead_of_proclaunch(tmp_path):
    calls: list[int] = []
    handle = SubprocessRunner(tmp_path, terminate=lambda pid, timeout: calls.append(pid) or True).start(
        [sys.executable, "-c", "pass"], dict(os.environ)
    )
    _wait_exit(handle)
    handle.stop()
    assert len(calls) == 1


# --- PsutilProcesses ------------------------------------------------------------------------------------------


def test_the_current_process_is_alive_and_a_reused_pid_is_not_the_same_process():
    processes = PsutilProcesses()
    me = processes.current()
    assert me.pid == os.getpid() and processes.is_alive(me) is True
    assert processes.is_alive(Identity(me.pid, me.started - 1000)) is False
    assert processes.is_alive(Identity(me.pid, me.started + 1000)) is False


def test_a_dead_process_is_not_alive():
    child = subprocess.Popen([sys.executable, "-c", _SLEEP])
    try:
        identity = _identity_of(child.pid)
        assert PsutilProcesses().is_alive(identity) is True
        child.kill()
        child.wait(timeout=20)
        assert PsutilProcesses().is_alive(identity) is False
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=20)


def test_psutil_stop_kills_a_process_and_its_grandchild(tmp_path):
    marker = tmp_path / "grandchild.pid"
    child = subprocess.Popen([sys.executable, "-c", _SPAWN_GRANDCHILD, str(marker)], start_new_session=True)
    grandchild = None
    try:
        grandchild = int(_wait_for_file(marker))
        identity = _identity_of(child.pid)
        processes = PsutilProcesses()
        processes.stop(identity)
        child.wait(timeout=20)  # reap it
        assert processes.is_alive(identity) is False
        assert _is_gone(grandchild), "the grandchild must die with its parent"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=20)
        if grandchild is not None:
            _kill_pid(grandchild)


def test_psutil_processes_pass_the_conformance_kit():
    spawned: list[subprocess.Popen] = []

    def spawn():
        child = subprocess.Popen([sys.executable, "-c", _SLEEP])
        spawned.append(child)
        return _identity_of(child.pid), lambda: (child.kill(), child.wait(timeout=20))

    check_processes(PsutilProcesses(), spawn)
    assert spawned[0].wait(timeout=20) is not None, "the kit's stop() really ended the process"


# --- ports -------------------------------------------------------------------------------------------------------


def _listen():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    return server.getsockname()[1], server.close


def test_socket_ports_pass_the_conformance_kit():
    check_ports(SocketPorts(), _listen)


@pytest.mark.skipif(os.name != "nt" and not shutil.which("lsof"), reason="needs lsof")
def test_socket_ports_names_the_process_holding_a_port():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        owner = SocketPorts().owner(server.getsockname()[1])
    assert owner is not None and f"pid {os.getpid()}" in owner
    assert SocketPorts().owner(1) is None  # nothing listens on port 1


# --- FileRunRecord (real files) ----------------------------------------------------------------------------------

OTHER_A = Identity(111111, 5000.0)
OTHER_B = Identity(222222, 6000.0)


def _write_record(path: Path, text: str, *, age: float = 0.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if age:
        old = time.time() - age
        os.utime(path, (old, old))
    return path


@pytest.fixture
def pidfile(tmp_path) -> Path:
    return tmp_path / "state" / "stack.pid"


def test_file_record_passes_the_conformance_kit(tmp_path):
    counter = iter(range(1000))
    base = tmp_path / next(str(i) for i in counter)
    check_run_record(lambda me, procs: FileRunRecord(base / "x.pid", procs))


def test_the_real_record_stores_this_process_identity(pidfile):
    processes = PsutilProcesses()
    record = FileRunRecord(pidfile, processes)
    assert record.load() is None and record.claim() is True and record.load() == processes.current()
    assert Identity.from_text(pidfile.read_text(encoding="utf-8")) == processes.current()
    record.clear()
    assert record.load() is None and not pidfile.exists()


def test_a_record_naming_a_reused_pid_is_stale_with_real_processes(pidfile):
    me = PsutilProcesses().current()
    _write_record(pidfile, Identity(me.pid, me.started - 1000).to_text())  # same pid, other program
    record = FileRunRecord(pidfile, PsutilProcesses())
    assert record.claim() is True and record.load() == me


def test_a_record_that_is_mid_write_is_treated_as_held_not_stale(pidfile):
    path = _write_record(pidfile, "")  # just created by a launch that has not written its identity yet
    record = FileRunRecord(pidfile, FakeProcesses(set(), me=OTHER_B))
    assert record.claim() is False
    old = time.time() - 60
    os.utime(path, (old, old))
    assert record.claim() is True


def test_an_old_garbage_record_is_replaced_and_a_fresh_one_is_held(pidfile):
    _write_record(pidfile, "not-an-identity", age=60)
    record = FileRunRecord(pidfile, FakeProcesses(set(), me=OTHER_B))
    assert record.load() is None and record.claim() is True and record.load() == OTHER_B
    _write_record(pidfile, "12")  # a half-written identity
    assert FileRunRecord(pidfile, FakeProcesses(set(), me=OTHER_A)).claim() is False


def test_a_record_with_undecodable_bytes_is_unusable_not_an_error(pidfile):
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.write_bytes(b"\xff\xfe\x00garbage")
    assert FileRunRecord(pidfile, FakeProcesses(me=OTHER_A)).load() is None


def test_claiming_survives_a_file_that_cannot_be_deleted(pidfile, monkeypatch):
    _write_record(pidfile, OTHER_A.to_text())
    record = FileRunRecord(pidfile, FakeProcesses(set(), me=OTHER_B))  # stale, but Windows will not let go

    def refuse(self, missing_ok=False):
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "unlink", refuse)
    assert record.claim() is False
    record.discard(OTHER_A)  # cleanup must not raise either


def test_clear_removes_only_the_record_that_names_this_process(pidfile):
    _write_record(pidfile, OTHER_A.to_text())
    FileRunRecord(pidfile, FakeProcesses({OTHER_A}, me=OTHER_B)).clear()
    assert pidfile.exists(), "another launcher's record must survive"
    FileRunRecord(pidfile, FakeProcesses({OTHER_A}, me=OTHER_A)).clear()
    assert not pidfile.exists()


def test_discard_removes_only_a_matching_record(pidfile):
    _write_record(pidfile, OTHER_A.to_text())
    record = FileRunRecord(pidfile, FakeProcesses(me=OTHER_B))
    record.discard(OTHER_B)
    assert pidfile.exists()
    record.discard(OTHER_A)
    assert not pidfile.exists()
    record.discard(OTHER_A)  # already gone: no error


def test_launches_racing_for_the_claim_have_exactly_one_winner(tmp_path):
    """Separate processes (separate identities), released together by a go-file, like several clicks at
    once. Each stays alive until told to finish, so a loser always sees a live holder."""
    code = (
        "import sys, time, pathlib\n"
        "sys.path[:0] = sys.argv[1].split(';')\n"
        "from stackrun.adapters import FileRunRecord, PsutilProcesses\n"
        "root = pathlib.Path(sys.argv[2])\n"
        "while not (root / 'go').exists():\n"
        "    time.sleep(0.005)\n"
        "print(FileRunRecord(root / 'stack.pid', PsutilProcesses()).claim(), flush=True)\n"
        "while not (root / 'done').exists():\n"
        "    time.sleep(0.02)\n"
    )
    paths = ";".join(str(p) for p in SRC_DIRS)
    procs = [
        subprocess.Popen([sys.executable, "-c", code, paths, str(tmp_path)], stdout=subprocess.PIPE, text=True)
        for _ in range(6)
    ]
    try:
        time.sleep(1.0)  # let every process reach the starting line
        (tmp_path / "go").write_text("", encoding="utf-8")
        answers = [p.stdout.readline().strip() for p in procs]
        assert answers.count("True") == 1 and answers.count("False") == 5, answers
        winner = FileRunRecord(tmp_path / "stack.pid", PsutilProcesses()).load()
        assert winner is not None and PsutilProcesses().is_alive(winner), "the record names a live launcher"
        started = {p.pid for p in procs}  # on Windows a venv python is a stub whose child does the work
        assert winner.pid in started or psutil.Process(winner.pid).ppid() in started
    finally:
        (tmp_path / "done").write_text("", encoding="utf-8")
        for p in procs:
            try:
                p.wait(timeout=30)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=20)


# --- SignalShutdown ------------------------------------------------------------------------------------------------

_SIGNALS = [n for n in ("SIGTERM", "SIGHUP") if hasattr(signal, n)]


@pytest.mark.parametrize("name", _SIGNALS)
def test_the_guard_replaces_the_handler_inside_and_restores_it_after(name):
    number = getattr(signal, name)
    original = signal.getsignal(number)
    with SignalShutdown().guard():
        inside = signal.getsignal(number)
        assert inside is not original and callable(inside)
    assert signal.getsignal(number) == original


def test_the_guard_restores_handlers_when_the_block_raises():
    original = signal.getsignal(signal.SIGTERM)
    with pytest.raises(RuntimeError), SignalShutdown().guard():
        raise RuntimeError("boom")
    assert signal.getsignal(signal.SIGTERM) == original


@POSIX_ONLY
def test_a_terminate_request_inside_the_guard_becomes_keyboard_interrupt():
    with pytest.raises(KeyboardInterrupt), SignalShutdown().guard():
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(2)  # the handler runs as soon as the interpreter gets control


def test_the_guard_does_not_raise_off_the_main_thread():
    errors: list[BaseException] = []
    ran: list[bool] = []

    def work():
        try:
            with SignalShutdown().guard():
                ran.append(True)
        except BaseException as exc:  # noqa: BLE001 - the test is that nothing escapes
            errors.append(exc)

    thread = threading.Thread(target=work)
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive() and errors == [] and ran == [True]


# --- browser and readiness -------------------------------------------------------------------------------------------


class _Quiet(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(self.server.status)  # type: ignore[attr-defined]
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):  # silence
        pass


def _serve(status: int):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Quiet)
    server.status = status  # type: ignore[attr-defined]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.mark.parametrize("status", [200, 404, 500])
def test_browser_opens_once_the_app_answers_even_with_an_error_page(status):
    server = _serve(status)
    opened: list[str] = []
    url = f"http://127.0.0.1:{server.server_address[1]}/setup"
    try:
        BrowserOpener(opener=opened.append, poll_interval=0.05, timeout=10).open_when_ready(url)
        assert HttpReadiness().is_ready(url) is True
        deadline = time.monotonic() + 10
        while not opened and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        server.shutdown()
    assert opened == [url]


def test_browser_gives_up_if_nothing_answers_and_readiness_is_false():
    opened: list[str] = []
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}/"
    BrowserOpener(opener=opened.append, poll_interval=0.05, timeout=0.5).open_when_ready(url)
    time.sleep(1.2)
    assert opened == [] and HttpReadiness(timeout=0.5).is_ready(url) is False
    assert HttpReadiness().is_ready("not a url") is False  # never raises


def test_open_now_does_not_wait():
    opened: list[str] = []
    BrowserOpener(opener=opened.append).open_now("http://127.0.0.1:1/")
    assert opened == ["http://127.0.0.1:1/"]


# --- end to end: the default wiring really runs and stops a stack ----------------------------------------------------------


def test_default_wiring_runs_a_one_service_stack_and_a_second_launch_is_refused(tmp_path):
    from stackrun.api import ServiceSpec, Stack, default_launcher

    stack = Stack("e2e", (ServiceSpec("sleeper", (sys.executable, "-c", "import time; time.sleep(3)")),))
    first = default_launcher(stack, state_dir=tmp_path, root=tmp_path, browser=False)
    result: list[int] = []
    thread = threading.Thread(target=lambda: result.append(first.run()))
    # signal guards only apply on the main thread; off it the launcher still runs, just unguarded
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not (tmp_path / "e2e.pid").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        # a second launch is another process (the claim is per process identity, so a same-process retry is not "another")
        code = "\n".join([
            "import sys; sys.path[:0] = sys.argv[1].split(';')",
            "from stackrun.api import ServiceSpec, Stack, StackrunError, default_launcher",
            "from pathlib import Path",
            "stack = Stack('e2e', (ServiceSpec('sleeper', (sys.executable, '-c', 'pass')),))",
            "try:",
            "    default_launcher(stack, state_dir=Path(sys.argv[2]), root=Path(sys.argv[2]), browser=False).run()",
            "except StackrunError as exc:",
            "    print('REFUSED', exc)",
        ])
        done = subprocess.run(
            [sys.executable, "-c", code, ";".join(str(p) for p in SRC_DIRS), str(tmp_path)],
            capture_output=True, text=True, timeout=60,
        )
        assert "REFUSED" in done.stdout and "already starting or running" in done.stdout, done.stdout + done.stderr
    finally:
        thread.join(timeout=30)
    assert result == [0], "the service exited by itself with code 0 and the launcher followed"
    assert not (tmp_path / "e2e.pid").exists(), "the claim is released"
