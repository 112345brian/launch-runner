"""The command contract: how a program asks for a process to be run, and the check that keeps it that way.

A leaf library (standard library only, imports nothing from any application package) in two halves:

- **The contract** (``domain``, ``ports``): ``CaptureSpec`` / ``RunSpec`` / ``StreamSpec`` and their results
  with an explicit ``RunOutcome``; ``ProcessSpec`` / ``LaunchResult`` for a detached background process; and
  the narrow Protocols an application depends on (``CommandCapturer``, ``CommandStreamer``,
  ``CommandRunner``, ``LineStream``, ``BackgroundLauncher``, ``Supervisor``). Pure: no process, file or
  network module is imported, so domain, service and workflow code may depend on it.
  ``lifecycle_runner`` implements run / capture / stream and ``proclaunch`` implements the launcher.
- **The fakes** (``testing``): in-memory ``FakeCommandRunner``, ``FakeLauncher`` and ``FakeSupervisors``,
  so a consumer's tests bind the contract instead of patching ``subprocess``.
- **The enforcement** (``scan``): an AST scan, configured from ``[tool.commandport]`` in the project's
  ``pyproject.toml``, that fails when code reaches for ``subprocess`` / ``os.system`` / ... outside the
  adapters. ``python -m commandport.scan`` for a hook or CI, ``commandport.scan.assert_clean()`` for a test.

The guarantees every implementation of the contract gives (they are why the contract exists):

- Never raises: a command that could not start, timed out or failed while waiting is a result, not an
  exception. Callers branch on ``outcome``.
- Never opens a console window on Windows, whether or not the caller has a console.
- Text is UTF-8 with undecodable bytes replaced, never the locale code page; newlines are normalised.
- stdin is closed unless text is supplied, so a child that prompts fails fast instead of hanging.
- A timeout kills the whole process tree and reports ``TIMED_OUT`` with the output so far.
"""

__version__ = "0.1.1"
