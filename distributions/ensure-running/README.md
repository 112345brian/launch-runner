# ensure-running

Keep named commands running. For each target it asks "should this run?" and starts the command when it should and
is not running, with a restart cap so a command that keeps dying is held back instead of restarted forever.

```toml
# ensure-running.toml
state_dir = "~/.local/state/ensure-running"   # optional
interval_seconds = 120                         # how often the installed launchd job re-checks
pty = true                                     # give each command a terminal (Unix)

[[target]]
name = "notes"                                 # unique; letters, digits, . _ -
cwd = "~/notes"
command = "claude remote-control"              # or: argv = ["claude", "remote-control"]
check = "./is-wanted.sh"                       # optional: exit 0 = start it, 1 = leave it, else unknown
```

```
python -m ensure_running run --config ensure-running.toml          # reconcile once
python -m ensure_running status --config ensure-running.toml
python -m ensure_running install --config ensure-running.toml      # a per-user launchd job (macOS)
```

From Python, reconcile on your own schedule and with your own check or starter:

```python
from ensure_running import api, config

cfg = config.load(path)
for result in api.run_once(cfg):          # one TargetResult per target
    print(result.target, result.outcome.value)
```

The reconciliation core (`ensure_running.domain`, `.reconciler`) imports no other library: it asks a
`ServiceStarter` to start a `ServiceSpec` and a `ShouldRun` callable whether to, in its own vocabulary. `api` wires
in [`proclaunch`](https://github.com/112345brian/launch-runner/tree/main/distributions/proclaunch) (starting and
recording services) and [`lifecycle-runner`](https://github.com/112345brian/launch-runner/tree/main/distributions/lifecycle-runner)
(running check commands), through the `ensure_running.api` composition root only.

Only macOS launchd is implemented for `install`; systemd and Windows Task Scheduler are not.
