# proclaunch

Start and stop long-running local background processes, detached and windowless, with process identity (pid *and*
creation time), exclusive start reservations, readiness probes and an optional OS supervisor (Windows Task
Scheduler). It implements `commandport`'s `BackgroundLauncher` / `Supervisor`.

```python
from commandport.domain import ProcessSpec
from proclaunch.api import launch_background, start_service, stop_service

result = launch_background(ProcessSpec(("python", "-m", "myapp")))   # a LaunchResult; never raises
if not result.ok:
    print(result.error)
```

A named service (`ProcessSpec(name=...)`) is recorded so a second start is `ALREADY_RUNNING`, and a stop only acts
when the recorded identity still matches (a reused pid is left alone).

Tests: bind `commandport.testing.FakeLauncher` with `proclaunch.api.use_launcher(...)` and
`FakeSupervisors` with `use_supervisor(...)`.
