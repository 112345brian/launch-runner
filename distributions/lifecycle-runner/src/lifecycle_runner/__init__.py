"""Run a local command to completion, with a time limit: log it, capture it, or stream it.

The sibling of ``proclaunch``: proclaunch *starts* a long-lived process and
returns at once; this *runs* one and waits. They are independent capability
libraries: this one imports nothing from ``proclaunch`` and nothing from any
application package.

Same hexagonal layout as proclaunch (enforced by
``tests/test_lifecycle_runner_architecture.py`` and an import-linter contract):

- ``domain`` -- ``RunSpec`` / ``CaptureSpec`` / ``StreamSpec``, ``RunOutcome`` and the results; no I/O imports.
- ``ports`` -- ``ChildSpawner`` / ``RunningChild`` / ``Clock``: what the runner needs from the world; and the
  operation ports (``CommandRunner`` / ``CommandCapturer`` / ``CommandStreamer`` / ``LineStream``) it provides.
- ``testing`` -- ``FakeCommandRunner``, the in-memory implementation of the operation ports.
- ``runner`` -- the behaviour (``Runner``): spawn, wait with a deadline, kill on
  timeout, report. Written against ports only.
- ``adapters`` -- ``Popen`` + a log file, its own process-tree stop (``process_tree``), process group
  (``process_group``) and Windows flag (``windows``).
- ``api`` -- the composition root; the only module that sees both sides.
- ``__main__`` -- ``python -m lifecycle_runner --log PATH --timeout S -- CMD ...``,
  the form a scheduler task invokes.

The contract:

- ``run(spec)`` never raises and never returns a bare truthy value: a
  ``RunResult`` says the command ``COMPLETED`` (with its exit code),
  ``TIMED_OUT`` (and was killed, with the whole process tree), ``FAILED_TO_START``,
  or hit an ``ERROR`` while waiting.
- ``RunResult.ok`` is true only for a ``COMPLETED`` run that exited 0. A non-zero
  exit is a completed run, not an error of the runner.
- The command's stdout and stderr are appended to ``spec.log_path`` or discarded.
  The runner itself buffers nothing (the child writes straight to the file, so a
  five-hour run is fine), but a child may buffer its own output and lose it if
  killed; ``python -m lifecycle_runner`` sets ``PYTHONUNBUFFERED=1`` so a Python
  child does not. Other children are on their own.
- A foreground child never opens a console window on Windows.
- On POSIX a detached child (everything except ``RunSpec(inherit_stdio=True)`` with a console) leads its own
  process group, in the caller's session, so a timeout signals the whole group: a descendant that was orphaned
  before the deadline is stopped too. A descendant that starts its own session or group escapes the group and
  is stopped only while it is still a descendant of the child. A console-attached child stays in the
  caller's group (it needs the terminal's job control) and is stopped by walking its descendants, which
  cannot see an orphan. Windows has no process groups of this kind; see ``adapters/process_group.py``.
- Ctrl-C / ``KeyboardInterrupt`` while waiting kills the child, then propagates.

Two more operations share the same guarantees (never raises, never opens a console window on
Windows, an explicit outcome, UTF-8 text) and are what application code uses instead of a raw
``subprocess`` call:

- ``capture(CaptureSpec)`` runs a short command and returns a ``CaptureResult`` (``COMPLETED`` with
  exit code, stdout and stderr; ``TIMED_OUT`` with the partial output; ``FAILED_TO_START``). stdin is
  closed unless ``stdin_text`` is given.
- ``stream(StreamSpec)`` returns a ``LineStream``: iterate it for merged stdout/stderr lines as the
  command prints them, with a watchdog on ``timeout_seconds``; a command that could not start is a
  stream with ``start_error`` set.
- ``run(RunSpec(inherit_stdio=True))`` attaches the child to the caller's console (a terminal
  passthrough) when it has one, and runs it windowless otherwise.

Application code depends on the operation ports (``CommandRunner`` / ``CommandCapturer`` /
``CommandStreamer`` in ``ports``); ``api.use_commands`` binds a fake for a test
(``lifecycle_runner.testing``). ``commandport.scan`` (``[tool.commandport]``) fails on a raw
``subprocess`` call outside the adapters of this package and of proclaunch.

Callers must consume results; ``tests/test_lifecycle_runner.py`` fails on a call
that discards one.
"""

__version__ = "0.2.0"
