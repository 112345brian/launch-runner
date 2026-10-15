# commandport

The check that keeps a codebase from starting processes outside its adapters.

- **Scan** (`commandport.scan`): fails when code reaches for `subprocess` / `os.system` / ... outside the adapters.
  Configure it in `pyproject.toml` under `[tool.commandport]`, run `python -m commandport.scan`, or call
  `commandport.scan.assert_clean()` from a test.

It was also the shared home of the command and launch contract. That contract now belongs to the libraries that
provide it, and the old import paths forward to them:

| old path | now |
|---|---|
| `commandport.domain`: `RunSpec`, `CaptureSpec`, `StreamSpec`, `RunOutcome`, `RunResult`, `CaptureResult` | `lifecycle_runner.domain` |
| `commandport.ports`: `CommandRunner`, `CommandCapturer`, `CommandStreamer`, `LineStream` | `lifecycle_runner.ports` |
| `commandport.testing`: `FakeCommandRunner` | `lifecycle_runner.testing` |
| `commandport.domain`: `ProcessSpec`, `LaunchResult`, `LaunchMethod`, `EndResult` | `proclaunch.domain` |
| `commandport.ports`: `BackgroundLauncher`, `Supervisor` | `proclaunch.ports` |
| `commandport.testing`: `FakeLauncher`, `FakeSupervisors` | `proclaunch.testing` |

The forwarding is lazy and returns the provider's own object: `commandport` stays dependency-free, imports nothing
until a moved name is used, and says which distribution to install when it is missing. Type checkers see the
forwarded names as `Any`; import from the new path for typing.

Implementations: [`lifecycle-runner`](https://github.com/112345brian/launch-runner/tree/main/distributions/lifecycle-runner) (run / capture / stream) and
[`proclaunch`](https://github.com/112345brian/launch-runner/tree/main/distributions/proclaunch) (detached services). Install `launch-runner` to get all three.
