# lifecycle-runner

Run a local command to completion. Three operations, each returning an explicit result and never raising:

```python
from lifecycle_runner.api import capture, run, stream
from lifecycle_runner.domain import CaptureSpec, RunSpec, StreamSpec

done = capture(CaptureSpec(("git", "rev-parse", "HEAD"), timeout_seconds=15))
if done.ok:
    print(done.stdout.strip())

for line in stream(StreamSpec(("pytest", "-q"), timeout_seconds=600)):   # a LineStream
    print(line, end="")

run(RunSpec(("make", "build"), inherit_stdio=True))   # attached to this console, or windowless without one
```

Also a scheduler-task entry point: `python -m lifecycle_runner --log run.log --timeout 1800 -- cmd args...`.

Tests: `lifecycle_runner.api.use_commands(lifecycle_runner.testing.FakeCommandRunner())`.

It depends on `psutil` only: it owns its process-tree kill and its "no console window" flag,
so installing it does not install `proclaunch`. A timeout stops the child's whole process group (POSIX), a
console-attached run is stopped by walking its descendants, and the result says when something survived.

## Replacing how a child is started

`run`, `capture` and `stream` start real children with `Popen`. To run through ssh, a container or a pty, replace
just that step; the deadline, the kill, the never-raises contract and the result mapping stay this library's:

```python
from lifecycle_runner import api
from lifecycle_runner.api import Commands

class SshSpawner:                       # a ChildSpawner: spawn(RunSpec) -> a child with wait() and kill()
    def spawn(self, spec): ...

with api.use_commands(Commands(spawner=SshSpawner())):   # capture/stream keep their defaults
    api.run(RunSpec(("make", "build"), timeout_seconds=600))
```

`Commands(spawner=, capture_spawner=, stream_spawner=, clock=)` takes one keyword per operation; the ports
(`ChildSpawner`, `CaptureSpawner`, `StreamSpawner`, `Clock`) are in `lifecycle_runner.ports`, and
`lifecycle_runner.api.__all__` is the supported surface.
