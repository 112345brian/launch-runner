"""Start and stop long-running local background processes with a contract.

A leaf library: standard library plus ``psutil``. It imports nothing from any other library of this family or
from any application package, so it can be lifted into its own repository unchanged.

The launch vocabulary is its own: ``ProcessSpec``, ``LaunchResult`` / ``LaunchMethod``, ``EndResult`` in
``domain`` and the ``BackgroundLauncher`` / ``Supervisor`` ports in ``ports``, importable without importing
anything that does I/O. A consumer that wants its own vocabulary defines a narrower local protocol (for
example "start this named service") and lets ``ServiceManager`` satisfy it. Beyond the contract this package
holds what only an implementation can: service records with process identity, readiness probes and the
adapters.

Hexagonal layout (enforced by ``tests/test_proclaunch_architecture.py`` and an
import-linter contract):

- ``domain`` -- values and rules: the launch types (``ProcessSpec``, ``LaunchResult``, ``LaunchMethod``,
  ``EndResult``) and ``ProcessIdentity``, ``ServiceRecord``, the stop/status/wait results; no I/O imports.
- ``ports`` -- the driven protocols the behaviour needs: ``ProcessSpawner``, ``ProcessInspector``,
  ``RecordStore``, ``Clock``, ``Probe``; and the ones it provides: ``BackgroundLauncher``, ``Supervisor``.
- ``testing`` -- ``FakeLauncher`` and ``FakeSupervisors``, in-memory implementations of the launch ports.
- ``launching`` / ``services`` / ``readiness`` -- the behaviour (``Launcher``,
  ``ServiceManager``, ``wait_for_readiness``), written against ports only.
- ``adapters`` -- the real world behind each port: subprocess, psutil, JSON files,
  Windows Task Scheduler, HTTP/TCP probes, the system clock.
- ``api`` -- the composition root; the only module that sees both sides.

The contract:

- ``launch_background(spec)`` never raises and never returns a bare truthy value:
  a ``LaunchResult`` says *which* path started the process (``SUPERVISED`` /
  ``SPAWNED``) or that nothing did (``FAILED``, with the error).
- A launched process never opens a console window on Windows, and is detached from
  the caller with stdio redirected to ``spec.log_path`` or discarded.
- By default a launch is a direct spawn. An OS ``Supervisor`` (e.g.
  ``adapters.task_scheduler.TaskSchedulerSupervisor``) is optional; if it fails the
  launch falls back to a direct spawn and the result carries ``supervisor_error``.
- A named service (``ProcessSpec.name``) is recorded with its identity (pid +
  creation time). Concurrent starts cannot both launch (exclusive reservation);
  a second start of a running service is ``ALREADY_RUNNING``; stop acts only when
  the identity still matches (a reused pid is left alone) and an unreadable record
  is preserved and reported, never read as "stopped".
- ``wait_for_readiness`` waits for a ``Probe`` with a deadline and an early-crash check.

Callers must consume results; ``tests/test_proclaunch.py`` fails on a call that
discards one.
"""

__version__ = "0.2.0"
