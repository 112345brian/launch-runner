"""One collaborator of proclaunch can be replaced without reassembling the service manager.

The operations keep their invariants (reservation, identity, record) whatever spawner starts the process; a
launcher bound with ``use_launcher`` still wins, so a test cannot be made to start a real process by code that
injects its own spawner.
"""
from __future__ import annotations

import os

import pytest

from proclaunch import api
from proclaunch.domain import LaunchMethod, ProcessIdentity, ProcessSpec
from proclaunch.testing import FakeLauncher


class RecordingSpawner:
    """A ProcessSpawner that starts nothing and reports a pid it was told to."""

    def __init__(self, pid: int | None = None, error: Exception | None = None) -> None:
        self.pid = os.getpid() if pid is None else pid
        self.error = error
        self.specs: list[ProcessSpec] = []

    def spawn(self, spec: ProcessSpec) -> int:
        self.specs.append(spec)
        if self.error is not None:
            raise self.error
        return self.pid


def test_launch_background_uses_the_injected_spawner():
    spawner = RecordingSpawner(pid=4321)
    result = api.launch_background(ProcessSpec(("srv",), cwd="/w"), spawner=spawner)
    assert result.method is LaunchMethod.SPAWNED and result.pid == 4321
    assert [s.argv for s in spawner.specs] == [("srv",)] and spawner.specs[0].cwd == "/w"


def test_a_spawner_that_raises_is_a_failed_result_not_a_raise():
    spawner = RecordingSpawner(error=FileNotFoundError("nope"))
    result = api.launch_background(ProcessSpec(("srv",)), spawner=spawner)
    assert result.method is LaunchMethod.FAILED and "nope" in result.error


def test_start_service_keeps_the_records_and_identity_with_an_injected_spawner(tmp_path):
    spawner = RecordingSpawner()  # reports this very (live) process so identity can be taken
    first = api.start_service(ProcessSpec(("srv",), name="svc"), state_dir=tmp_path, spawner=spawner)
    assert first.method is LaunchMethod.SPAWNED and first.pid == os.getpid()
    status = api.service_status("svc", state_dir=tmp_path)
    assert status.running and status.pid == os.getpid()
    # the second start is refused by the record, so the spawner is not asked again
    second = api.start_service(ProcessSpec(("srv",), name="svc"), state_dir=tmp_path, spawner=spawner)
    assert second.method is LaunchMethod.ALREADY_RUNNING and len(spawner.specs) == 1


def test_a_launcher_bound_for_a_test_wins_over_an_injected_spawner():
    fake = FakeLauncher()
    spawner = RecordingSpawner()
    with api.use_launcher(fake):
        result = api.launch_background(ProcessSpec(("srv",)), spawner=spawner)
    assert result.method is LaunchMethod.SPAWNED and fake.argvs() == [("srv",)]
    assert spawner.specs == [], "an injected spawner must not bypass the test seam"


def test_default_manager_replaces_only_the_collaborators_it_is_given(tmp_path):
    class Inspector:
        def __init__(self):
            self.identified = []

        def identify(self, pid):
            self.identified.append(pid)
            return ProcessIdentity(pid, 100.0)

        def is_live(self, identity):
            return False

        def current(self):
            return None

        def pid_reused(self, identity):
            return False

        def terminate(self, identity, timeout):
            return True

        def find_started(self, argv, since):
            return None

    inspector, spawner = Inspector(), RecordingSpawner(pid=777)
    manager = api.default_manager(tmp_path, spawner=spawner, inspector=inspector)
    result = manager.start(ProcessSpec(("srv",), name="svc"))
    assert result.method is LaunchMethod.SPAWNED and result.pid == 777
    assert inspector.identified == [777], "the injected inspector took the identity"
    assert (tmp_path / "svc.json").exists() or any(tmp_path.iterdir()), "the default store wrote the record"


@pytest.mark.parametrize("name", api.__all__)
def test_every_declared_name_exists(name):
    assert hasattr(api, name)


def test_the_pty_spawner_and_probes_are_reachable_from_the_public_module():
    assert callable(api.PtySpawner) and callable(api.HttpProbe) and callable(api.TcpProbe)
    assert api.CallableProbe(lambda: True).run(0.1) is True
