# Changelog

Each distribution has its own version; see `distributions/README.md` for how they relate. 0.x: a minor release
may break the public surface, a patch release may not.

## Unreleased

### Fixed

- launch-runner: PyPI still serves `launch-runner` 0.1.1, which pins `commandport==0.1.1`,
  `lifecycle-runner==0.1.1` and `proclaunch==0.1.1`, while the libraries are published at 0.2.0. The repository
  already pins the 0.2.0 set; the meta-package 0.2.0 just has not been uploaded (the next `tools/release.sh
  --upload` publishes it, last). To keep the pins from drifting again, `tests/test_distributions.py` now fails when
  any distribution's requirement on a sibling is not satisfied by that sibling's version and when `release.sh`
  does not publish the meta-package last, and `tools/release.sh` refuses to upload the meta-package when a pinned
  version is neither on PyPI nor part of the same release.

## 0.2.0 — commandport, proclaunch, lifecycle-runner, launch-runner

### Breaking

- **`commandport.domain`, `commandport.ports` and `commandport.testing` are removed, with no shim.** The types,
  ports and fakes belong to the libraries that provide them:

  | was (`commandport…`) | now |
  |---|---|
  | `domain`: `RunSpec`, `CaptureSpec`, `StreamSpec`, `RunOutcome`, `RunResult`, `CaptureResult` | `lifecycle_runner.domain` |
  | `ports`: `CommandRunner`, `CommandCapturer`, `CommandStreamer`, `LineStream` | `lifecycle_runner.ports` |
  | `testing`: `FakeCommandRunner`, `FakeLineStream` | `lifecycle_runner.testing` |
  | `domain`: `ProcessSpec`, `LaunchResult`, `LaunchMethod`, `EndResult` | `proclaunch.domain` |
  | `ports`: `BackgroundLauncher`, `Supervisor` | `proclaunch.ports` |
  | `testing`: `FakeLauncher`, `FakeSupervisor`, `FakeSupervisors` | `proclaunch.testing` |

  `commandport` is now the process scan only (`commandport.scan`, `[tool.commandport]`); it has no dependencies.
- **The libraries no longer depend on each other.** `lifecycle-runner` and `proclaunch` depend on `psutil` only
  (previously `commandport`, and `lifecycle-runner` also required `proclaunch`). The `launch-runner`
  meta-package pins the exact 0.2.0 set.
- **lifecycle-runner: a detached child leads its own process group** (POSIX). Ctrl-C at the terminal no longer
  reaches it by itself; `run`, `capture` and `stream` kill it explicitly on `KeyboardInterrupt`. A console-attached
  run (`RunSpec(inherit_stdio=True)`) is unchanged.

### Fixed

- lifecycle-runner: a timeout left a descendant that had been orphaned before the deadline running while the
  result said `TIMED_OUT` with no error. The whole process group is now stopped, and a result says when something
  survived.
- proclaunch: `terminate_process` and `ServiceManager.stop` reported success while a descendant outside the
  leader's group survived (a new session; the child of a pty holder). Survivors of a snapshot taken before the
  signal are now stopped and counted, and a process that cannot be signalled or inspected is reported instead of
  raising. When a record cannot be saved and the new process cannot be stopped, the error says so.
- proclaunch: importing `proclaunch.api` no longer resolves the home directory (`LaunchdSupervisor`).

### Added

- proclaunch: `default_manager(state_dir, spawner=, inspector=, store=, clock=)`, `spawner=` on
  `launch_background` and `start_service`, and a declared `proclaunch.api.__all__` (including `PtySpawner`,
  `LaunchdSupervisor`, the probes and the ports).
- lifecycle-runner: `Commands(spawner=, capture_spawner=, stream_spawner=, clock=)` to replace how a child is
  started, and a declared `lifecycle_runner.api.__all__`.

### Compatibility notes

- Platform limits: Windows has no process group of this kind, so an orphaned descendant is not stopped there; a
  console-attached run cannot see an orphan; a descendant that starts a new session after the snapshot escapes.

## ensure-running 0.1.0 — first release

- Reconciles named commands: per target, a check decides whether to run; the restart cap holds back a command that
  keeps dying. `python -m ensure_running {run,status,install,uninstall}` and `ensure_running.api.run_once`.
- The reconciliation core owns its vocabulary (`ServiceSpec`, `StartResult`, `ServiceStarter`, `CheckRunner`) and
  imports no other library; `api` wires in proclaunch and lifecycle-runner.
- Requires `proclaunch>=0.2.0,<0.3` and `lifecycle-runner>=0.2.0,<0.3`. Only macOS launchd is implemented for
  `install`.
