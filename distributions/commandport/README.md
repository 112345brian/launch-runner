# commandport

The check that keeps a codebase from starting processes outside its adapters.

- **Scan** (`commandport.scan`): fails when code reaches for `subprocess` / `os.system` / ... outside the adapters.
  Configure it in `pyproject.toml` under `[tool.commandport]`, run `python -m commandport.scan`, or call
  `commandport.scan.assert_clean()` from a test.

Standard library only, no dependencies, and it imports none of the libraries it checks.

It used to be the shared home of the command and launch contract. That contract now belongs to the libraries that
provide it, and the `commandport.domain`, `commandport.ports` and `commandport.testing` modules are gone:

| was | now |
|---|---|
| `RunSpec`, `CaptureSpec`, `StreamSpec`, `RunOutcome`, `RunResult`, `CaptureResult` | `lifecycle_runner.domain` |
| `CommandRunner`, `CommandCapturer`, `CommandStreamer`, `LineStream` | `lifecycle_runner.ports` |
| `FakeCommandRunner` | `lifecycle_runner.testing` |
| `ProcessSpec`, `LaunchResult`, `LaunchMethod`, `EndResult` | `proclaunch.domain` |
| `BackgroundLauncher`, `Supervisor` | `proclaunch.ports` |
| `FakeLauncher`, `FakeSupervisors` | `proclaunch.testing` |

Libraries: [`lifecycle-runner`](https://github.com/112345brian/launch-runner/tree/main/distributions/lifecycle-runner) (run / capture / stream) and
[`proclaunch`](https://github.com/112345brian/launch-runner/tree/main/distributions/proclaunch) (detached services). Install `launch-runner` to get all three.
