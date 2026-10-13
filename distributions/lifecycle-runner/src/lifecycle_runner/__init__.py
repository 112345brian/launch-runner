"""Run a local command to completion, with a time limit: log it, capture it, or stream it.

The sibling of ``proclaunch``: proclaunch *starts* a long-lived process and
returns at once; this *runs* one and waits. Both are leaf libraries on the
``libraries`` layer; this one may import ``proclaunch`` (``tach.toml`` declares
the edge) and nothing from ``jobsearch``, ``tracker`` or any application package.

Same hexagonal layout as proclaunch (enforced by
``tests/test_lifecycle_runner_architecture.py`` and an import-linter contract):

- ``domain`` -- ``RunSpec``, ``RunOutcome``, ``RunResult``; no I/O imports.
- ``ports`` -- ``ChildSpawner`` / ``RunningChild`` / ``Clock``: what the runner
  needs from the world.
- ``runner`` -- the behaviour (``Runner``): spawn, wait with a deadline, kill on
  timeout, report. Written against ports only.
- ``adapters`` -- ``Popen`` + a log file + proclaunch's process-tree terminate.
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
(``commandport.testing``). ``commandport.scan`` (``[tool.commandport]``) fails on a raw
``subprocess`` call outside this package's and proclaunch's adapters.

Callers must consume results; ``tests/test_lifecycle_runner.py`` fails on a call
that discards one.
"""

__version__ = "0.1.0"
