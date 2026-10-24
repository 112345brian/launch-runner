# stackrun

Run a group of local services (API, web app, workers...) as **one foreground stack** in a terminal window.
One launch at a time, a clear refusal when a port is taken (naming the program and pid holding it), and Ctrl+C or
closing the window stops every service and everything they started.

```python
from pathlib import Path
from stackrun.api import ServiceSpec, Stack, default_launcher

stack = Stack("demo", (
    ServiceSpec("api", ("uvicorn", "app:app", "--port", "8000"), port=8000, cwd="apps/api"),
    ServiceSpec("web", ("npm", "run", "dev"), port=3000, env={"PORT": "3000"}, ready_url="http://localhost:3000"),
), stop_hint="`python run.py --stop`")

launcher = default_launcher(stack, state_dir=Path(".run"), root=Path.cwd(), open_url="http://localhost:3000")
raise SystemExit(launcher.stop() if "--stop" in __import__("sys").argv else launcher.run())
```

Or declaratively: `stackrun.toml` plus `python -m stackrun [run|stop|status]` (`stackrun[all]` installs the defaults):

```toml
name = "demo"
open_url = "http://localhost:3000"
[[service]]
name = "api"
command = "uvicorn app:app --port 8000"
port = 8000
```

Services start in order and stop in reverse. If any one exits, the rest are stopped and its exit code is returned.
The claim is a file holding the launcher's identity (pid **and** start time), created exclusively, so two clicks
racing cannot both start and a reused pid is never mistaken for the launcher. `Launcher.stop()` (from another
terminal) stops the recorded launcher and waits until it is really gone.

## Install

`pip install stackrun` has no dependencies and imports no third-party code. The default adapters use extras:
`stackrun[psutil]` (process identity), `stackrun[proclaunch]` (kill a whole process tree, the OS-specific part),
`stackrun[all]` for both.

## Ports

All are `typing.Protocol` classes in `stackrun.ports`; any object with the right methods fits, no import needed.
`stackrun.testing` has a fake of each and a conformance kit.

| Port | What it is | Default adapter | Needs |
|---|---|---|---|
| `ProcessRunner` / `ProcessHandle` | start a resolved argv with an env and cwd; poll; stop the whole tree | `SubprocessRunner` | proclaunch |
| `CommandResolver` | program name or path -> runnable path | `FilesystemResolver` (`shutil.which`) | - |
| `ConfigSource` | the stack-wide environment | `EnvironConfig` (process env) | - |
| `Hook` | optional `before_start(stack)`: publish an env file, migrate... | none (you supply it) | - |
| `Ports` | is a port in use; who holds it | `SocketPorts` (loopback sockets, PowerShell / `lsof`) | - |
| `Readiness` | does `ready_url` answer | `HttpReadiness` | - |
| `RunRecord` | the single-instance claim | `FileRunRecord` | - |
| `Processes` | current / alive / stop by identity | `PsutilProcesses` | psutil, proclaunch |
| `Shutdown` | window close / SIGTERM become KeyboardInterrupt around the whole run | `SignalShutdown` | - |
| `Browser` | open a URL once it answers | `BrowserOpener` | - |
| `Console` | say a line | `StdoutConsole` | - |

Constructor injection: `Launcher(stack, runner, resolver, config, console, sleep, *, open_url, browser, ports,
record, processes, shutdown, hook, readiness)`. Everything after `sleep` is optional and its behaviour is simply
absent without it. `default_launcher(...)` wires the real adapters.

Testing your own code or adapter:

```python
from stackrun.testing import FakeRunner, check_run_record
check_run_record(lambda me, processes: MyRecord(tmp_path / "x", processes))   # raises AssertionError on a broken contract
```

`check_run_record`, `check_processes` and `check_ports` are the conformance kit; the fakes pass it too.

## What stackrun leaves to the app

Which services to run, parsing `.env`, secrets, publishing env files for a web framework: the app builds the `Stack`
and supplies a `ConfigSource` / `Hook`. `examples/deepinterview_shape.py` shows a real app's stack (uv, npx, optional
voice servers read from `.env`) built this way.

Platforms: developed and tested on Windows. POSIX paths (process groups, SIGTERM/SIGHUP, `lsof`) are covered by
tests that are skipped on Windows and were not run; macOS is untested. See `DESIGN.md` for how this relates to
`proclaunch`.
