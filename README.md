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

## Layout

Each distribution owns its source, so each builds (and its sdist is) self-contained:

```
distributions/
  commandport/       pyproject.toml  README.md  LICENSE  src/commandport/
  proclaunch/        pyproject.toml  README.md  LICENSE  src/proclaunch/
  lifecycle-runner/  pyproject.toml  README.md  LICENSE  src/lifecycle_runner/
  launch-runner/     pyproject.toml  README.md  LICENSE  (meta-package, no code)
tests/               the contract, the three libraries, and the release gate
```

## Develop

```
python -m pip install pytest import-linter ruff setuptools
python -m pip install -e distributions/commandport -e distributions/proclaunch -e distributions/lifecycle-runner
python -m pytest
python -m commandport.scan
lint-imports
```

## Release

Versions move together (`tests/test_distributions.py` fails on drift). Build with either tool; the sdists are
self-contained:

```
python -m build distributions/commandport
python -m build distributions/proclaunch
python -m build distributions/lifecycle-runner
python -m build distributions/launch-runner
```

Upload in dependency order: `commandport`, `proclaunch`, `lifecycle-runner`, `launch-runner`.

MIT licensed. Portions of `proclaunch` are adapted from dmon (MIT, (c) 2025 Atomie CHEN); the
notice ships with that distribution (`distributions/proclaunch/THIRD_PARTY_NOTICES.md`).

Source: https://github.com/112345brian/launch-runner
