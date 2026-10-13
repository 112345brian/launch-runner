# launch-runner

A small family of libraries for starting processes safely, built as ports and adapters so the code that asks for
a process never depends on how it is started.

| distribution | import | what it is |
|---|---|---|
| [`commandport`](distributions/commandport) | `commandport` | the contract: spec/result types, the ports, in-memory fakes, and a scan that enforces it |
| [`lifecycle-runner`](distributions/lifecycle-runner) | `lifecycle_runner` | run / capture / stream a command to completion |
| [`proclaunch`](distributions/proclaunch) | `proclaunch` | detached background services with identity, readiness and optional supervision |
| [`launch-runner`](distributions/launch-runner) | meta-package | all three at matching versions |

```
commandport        no dependencies
   ^      ^
   |      +-- proclaunch        <- psutil
   |             ^
   +-- lifecycle-runner  <------+
```

## Why

On Windows a child process started from a program with no console (a service, `pythonw`, a scheduled task) gets a
fresh console window unless it is created with `CREATE_NO_WINDOW`. Every raw `subprocess` call is one forgotten
flag away from a window flashing on someone's desktop, and also from an unbounded wait, a leaked child tree, or
mojibake from the locale code page. These libraries make the safe behaviour the only behaviour: every operation
never raises (a failure is a result with an outcome), never shows a console, decodes UTF-8, closes stdin unless
text is supplied, and on a timeout kills the whole process tree.

## Use

```python
from commandport.domain import CaptureSpec
from lifecycle_runner.api import capture

done = capture(CaptureSpec(("git", "rev-parse", "HEAD"), timeout_seconds=15))
if done.ok:
    print(done.stdout.strip())
```

Application code depends on the ports in `commandport`; only the program's entry point binds an implementation.
Tests bind `commandport.testing.FakeCommandRunner` instead of patching `subprocess`.

## Keep it that way

`commandport.scan` fails the build when code reaches for `subprocess` / `os.system` / ... outside the adapters:

```toml
[tool.commandport]
roots = ["myapp"]
```

```
python -m commandport.scan
```

## Develop

```
python -m pip install pytest psutil import-linter ruff setuptools
python -m pytest
```

MIT licensed. Source: https://github.com/112345brian/launch-runner
