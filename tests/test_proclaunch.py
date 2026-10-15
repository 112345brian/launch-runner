"""proclaunch launching and adapter contracts: a result object, never a raise,
never a console window. The application is driven through in-memory ports; the
real adapters are exercised against their OS surface with the OS mocked."""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from proclaunch.adapters import windows
from proclaunch.adapters.subprocess_spawner import SubprocessSpawner
from proclaunch.adapters.task_scheduler import TaskSchedulerSupervisor
from proclaunch.domain import EndResult, LaunchMethod, ProcessSpec
from proclaunch.launching import Launcher

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable


def _system(name):
    return mock.patch.object(windows.platform, "system", return_value=name)


def _fake_win_flags():
    # subprocess.CREATE_* only exist on Windows; give them values elsewhere.
    return mock.patch.multiple(subprocess, create=True, CREATE_NO_WINDOW=0x08000000, CREATE_NEW_PROCESS_GROUP=0x200)


class FakeSpawner:
    def __init__(self, pid=4242, error=None):
        self.pid, self.error, self.specs = pid, error, []

    def spawn(self, spec):
        self.specs.append(spec)
        if self.error:
            raise self.error
        return self.pid


class FakeSupervisor:
    def __init__(self, available=True, pid=123, error=None):
        self._available, self.pid, self.error, self.started = available, pid, error, 0

    def available(self):
        return self._available

    def start(self, spec):
        self.started += 1
        if self.error:
            raise self.error
        return self.pid

    def end(self):
        return EndResult(ended=True)


# ---- Launcher (application, ports faked) ----

def test_no_supervisor_means_a_direct_spawn():
    spawner = FakeSpawner(pid=7)
    result = Launcher(spawner).launch(ProcessSpec((PY, "x.py")))
    assert result.method is LaunchMethod.SPAWNED and result.pid == 7 and result.started and result.ok
    assert len(spawner.specs) == 1


def test_supervisor_starts_it_and_nothing_is_spawned():
    sup, spawner = FakeSupervisor(pid=123), FakeSpawner()
    result = Launcher(spawner).launch(ProcessSpec((PY, "x.py"), supervisor=sup))
    assert result.method is LaunchMethod.SUPERVISED and result.pid == 123
    assert spawner.specs == []


def test_failed_supervisor_falls_back_to_spawn_and_reports_why():
    sup = FakeSupervisor(error=FileNotFoundError("schtasks"))
    result = Launcher(FakeSpawner(pid=5)).launch(ProcessSpec((PY, "x.py"), supervisor=sup))
    assert result.method is LaunchMethod.SPAWNED and result.pid == 5
    assert "schtasks" in result.supervisor_error


def test_unavailable_supervisor_is_skipped_silently():
    sup = FakeSupervisor(available=False)
    result = Launcher(FakeSpawner()).launch(ProcessSpec((PY, "x.py"), supervisor=sup))
    assert result.method is LaunchMethod.SPAWNED and result.supervisor_error is None and sup.started == 0


@pytest.mark.parametrize("failure", [OSError("nope"), PermissionError("denied")])
def test_spawn_failure_is_a_failed_result_not_a_raise(failure):
    result = Launcher(FakeSpawner(error=failure)).launch(ProcessSpec((PY, "x.py")))
    assert result.method is LaunchMethod.FAILED and not result.started and not result.ok
    assert type(failure).__name__ in result.error


@pytest.mark.parametrize("argv", [(), ("",), ("   ",), (PY, "a\0b")])
def test_blank_or_nul_argv_is_rejected_up_front(argv):
    with pytest.raises(ValueError):
        ProcessSpec(argv)


# ---- adapters ----

def test_spawner_on_windows_is_windowless_and_detached_with_no_schtasks():
    with _system("Windows"), _fake_win_flags(), mock.patch.object(subprocess, "Popen") as popen, \
         mock.patch.object(subprocess, "run") as run:
        popen.return_value.pid = 4242
        pid = SubprocessSpawner().spawn(ProcessSpec((PY, "x.py")))
    assert pid == 4242
    run.assert_not_called()
    assert popen.call_args.kwargs["creationflags"] & 0x08000000
    assert popen.call_args.kwargs["start_new_session"] is False


def test_spawner_off_windows_uses_its_own_session():
    for system in ("Darwin", "Linux"):
        with _system(system), mock.patch.object(subprocess, "Popen") as popen:
            popen.return_value.pid = 9
            SubprocessSpawner().spawn(ProcessSpec((PY, "x.py")))
        assert popen.call_args.kwargs["start_new_session"] is True
        assert popen.call_args.kwargs["creationflags"] == 0


def test_missing_executable_raises_oserror_from_the_adapter_and_launcher_reports_it():
    spawner = SubprocessSpawner()
    with pytest.raises(FileNotFoundError):
        spawner.spawn(ProcessSpec(("definitely-not-a-real-exe-xyz",)))
    result = Launcher(spawner).launch(ProcessSpec(("definitely-not-a-real-exe-xyz",)))
    assert not result.started and "not found" in result.error


def test_log_path_receives_output_and_is_appended(tmp_path):
    import psutil
    log = tmp_path / "sub" / "out.log"
    for text in ("one", "two"):
        pid = SubprocessSpawner().spawn(ProcessSpec((PY, "-c", f"print({text!r})"), log_path=log))
        try:
            psutil.Process(pid).wait(timeout=20)
        except psutil.NoSuchProcess:
            pass
    assert log.read_text().split() == ["one", "two"]


def test_task_scheduler_supervisor_runs_schtasks_without_a_window():
    with _system("Windows"), _fake_win_flags(), mock.patch.object(subprocess, "run") as run:
        sup = TaskSchedulerSupervisor("t")
        assert sup.available() and sup.start(ProcessSpec((PY, "x.py"))) is None
    assert run.call_args.args[0] == ["schtasks", "/run", "/tn", "t"]
    assert run.call_args.kwargs["creationflags"] & 0x08000000


def test_task_scheduler_supervisor_is_unavailable_off_windows_and_end_skips():
    with _system("Darwin"), mock.patch.object(subprocess, "run") as run:
        sup = TaskSchedulerSupervisor("t")
        assert not sup.available()
        assert sup.end() == EndResult(ended=False, skipped=True)
    run.assert_not_called()


def test_task_scheduler_supervisor_end_reports_errors():
    sup = TaskSchedulerSupervisor("t")
    with _system("Windows"), _fake_win_flags(), \
         mock.patch.object(subprocess, "run", side_effect=subprocess.CalledProcessError(1, "schtasks")):
        result = sup.end()
    assert not result.ended and result.error
    with _system("Windows"), _fake_win_flags(), mock.patch.object(subprocess, "run") as run:
        assert sup.end().ended
    assert run.call_args.args[0] == ["schtasks", "/end", "/tn", "t"]


# ---- callers must consume results ----

def _calls(tree, names):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and (getattr(n.func, "id", None) or getattr(n.func, "attr", None)) in names]




# ---- one definition of "no window", owned by the library ----



def test_foreground_children_keep_the_callers_ctrl_c_but_services_get_their_own_group():
    with _system("Windows"), _fake_win_flags():
        assert windows.windowless_flags() == 0x08000000
        assert windows.detached_flags() == 0x08000000 | 0x200
    with _system("Linux"):
        assert windows.windowless_flags() == 0 and windows.detached_flags() == 0


def test_detached_flags_include_the_windowless_flag():
    assert windows.detached_flags() & windows.windowless_flags() == windows.windowless_flags()


def test_a_process_that_cannot_be_inspected_is_assumed_alive_not_raised():
    import psutil
    from proclaunch.adapters import psutil_inspector

    class Opaque:
        def is_running(self):
            return True

        def status(self):
            raise psutil.AccessDenied(1)

    assert psutil_inspector._alive(Opaque()) is True


def test_the_launchd_supervisor_does_not_resolve_the_home_directory_at_import(monkeypatch):
    import importlib
    import pathlib

    from proclaunch.adapters import launchd

    def boom():
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(pathlib.Path, "home", staticmethod(boom))
    importlib.reload(launchd)  # must not raise
    assert launchd.LaunchdSupervisor("x", agents_dir=pathlib.Path("/tmp/a")).plist_path.name == "x.plist"
