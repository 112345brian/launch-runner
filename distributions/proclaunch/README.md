# proclaunch

Start and stop long-running local background processes, detached and windowless, with process identity (pid *and*
creation time), exclusive start reservations, readiness probes and an optional OS supervisor (Windows Task
Scheduler). It defines its own `BackgroundLauncher` / `Supervisor` ports and launch types (`proclaunch.domain`, `proclaunch.ports`).

```python
from proclaunch.api import launch_background, start_service, stop_service
from proclaunch.domain import ProcessSpec

result = launch_background(ProcessSpec(("python", "-m", "myapp")))   # a LaunchResult; never raises
if not result.ok:
    print(result.error)
```

A named service (`ProcessSpec(name=...)`) is recorded so a second start is `ALREADY_RUNNING`, and a stop only acts
when the recorded identity still matches (a reused pid is left alone).

Tests: bind `proclaunch.testing.FakeLauncher` with `proclaunch.api.use_launcher(...)` and
`FakeSupervisors` with `use_supervisor(...)`.

## Replacing one collaborator

The operations keep proclaunch's invariants (exclusive reservation, pid + creation-time identity, the record);
what starts the process, how identity is read, where records live and the clock can each be replaced on its own:

```python
from proclaunch.api import PtySpawner, default_manager, start_service

# a different way to start the process; reservation, identity and records stay proclaunch's
start_service(ProcessSpec(("claude", "remote-control"), name="rc"), state_dir=state, spawner=PtySpawner())

manager = default_manager(state, spawner=PtySpawner())   # or hold a manager and use it repeatedly
```

`proclaunch.api.__all__` is the supported surface: the operations, the values they return, the ports you may
implement (`ProcessSpawner`, `Probe`, `Supervisor`, ...) and the ready-made implementations (`SubprocessSpawner`,
`PtySpawner`, `HttpProbe`, `TcpProbe`, `CallableProbe`). A launcher bound with `use_launcher` (a test seam) takes
precedence over an injected spawner, so code that injects one cannot start a real process inside a test.
