# lifecycle-runner

Run a local command to completion. Three operations over one contract (`commandport`):

```python
from commandport.domain import CaptureSpec, RunSpec, StreamSpec
from lifecycle_runner.api import capture, run, stream

done = capture(CaptureSpec(("git", "rev-parse", "HEAD"), timeout_seconds=15))
if done.ok:
    print(done.stdout.strip())

for line in stream(StreamSpec(("pytest", "-q"), timeout_seconds=600)):   # a LineStream
    print(line, end="")

run(RunSpec(("make", "build"), inherit_stdio=True))   # attached to this console, or windowless without one
```

Also a scheduler-task entry point: `python -m lifecycle_runner --log run.log --timeout 1800 -- cmd args...`.

Tests: `lifecycle_runner.api.use_commands(commandport.testing.FakeCommandRunner())`.

It depends on `commandport` and `psutil` only: it owns its process-tree kill and its "no console window" flag,
so installing it does not install `proclaunch`. A timeout stops the child's whole process group (POSIX), a
console-attached run is stopped by walking its descendants, and the result says when something survived.
