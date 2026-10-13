# commandport

The contract between an application and "something that runs a process", and the check that keeps it that way.
Standard library only; it imports no process, file or network module, so an application's core can depend on it.

- **Types** (`commandport.domain`): `CaptureSpec` / `RunSpec` / `StreamSpec`, `ProcessSpec`, their results with an
  explicit `RunOutcome` / `LaunchMethod`.
- **Ports** (`commandport.ports`): `CommandCapturer`, `CommandStreamer`, `CommandRunner`, `LineStream`,
  `BackgroundLauncher`, `Supervisor`. A use case takes one as an argument; an entrypoint chooses the implementation.
- **Fakes** (`commandport.testing`): `FakeCommandRunner`, `FakeLauncher`, `FakeSupervisors`: in-memory, no patching.
- **Scan** (`commandport.scan`): fails when code reaches for `subprocess` / `os.system` / ... outside the adapters.
  Configure it in `pyproject.toml` under `[tool.commandport]`, run `python -m commandport.scan`, or call
  `commandport.scan.assert_clean()` from a test.

Implementations: [`lifecycle-runner`](../lifecycle-runner) (run / capture / stream) and
[`proclaunch`](../proclaunch) (detached services). Install `launch-runner` to get all three.

Guarantees every implementation of the contract gives: it never raises (a failure is a result with an outcome),
never opens a console window on Windows, decodes text as UTF-8, closes stdin unless text is supplied, and on a
timeout kills the whole process tree and reports what was printed so far.
