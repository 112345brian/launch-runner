"""``python -m lifecycle_runner --log PATH [--timeout SECONDS] [--cwd DIR] -- CMD ...``

What a scheduler task invokes in place of ``cmd.exe /c "CMD >> LOG 2>&1"``. Exit
status: the command's own exit code when it completed (so the scheduler sees
the routine's real result), else a ``timeout(1)``-style code:

    124  the command exceeded --timeout and was killed
    127  the command could not be started
    125  the runner itself failed (bad arguments, wait error)

A note line is appended to the log for each of the non-completed cases, so the
log says why a run produced no output of its own.

Deliberately its own entry point rather than a ``job-search`` subcommand: this
wrapper exists to log a routine's failure, so it must not import ``jobsearch``
(a broken import there would otherwise fail before anything is logged). argparse,
not Typer, for the same stdlib-only reason (see ``__init__``).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lifecycle_runner.api import run
from commandport.domain import RunOutcome, RunResult, RunSpec

EXIT_TIMED_OUT = 124
EXIT_RUNNER_FAILED = 125
EXIT_NOT_STARTED = 127


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m lifecycle_runner",
        description="Run a command to completion, appending its output to a log, with a time limit.",
    )
    p.add_argument("--log", type=Path, help="append the command's stdout+stderr here (default: discard)")
    p.add_argument("--timeout", type=float, help="kill the command (and its children) after this many seconds")
    p.add_argument("--cwd", help="working directory for the command")
    p.add_argument("command", nargs=argparse.REMAINDER, help="-- CMD [ARG ...]")
    return p


def _stderr(message: str) -> None:
    # Under pythonw.exe (how Task Scheduler runs this) there is no stderr at all.
    if sys.stderr is not None:
        sys.stderr.write(message + "\n")


def _note(log: Path | None, message: str) -> None:
    _stderr(message)
    if log is None:
        return
    try:
        with open(log, "ab") as fh:
            fh.write((message + "\n").encode("utf-8", errors="replace"))
    except OSError:
        pass


def exit_code_for(result: RunResult) -> int:
    if result.outcome is RunOutcome.COMPLETED:
        return result.returncode if result.returncode is not None else EXIT_RUNNER_FAILED
    if result.outcome is RunOutcome.TIMED_OUT:
        return EXIT_TIMED_OUT
    if result.outcome is RunOutcome.FAILED_TO_START:
        return EXIT_NOT_STARTED
    return EXIT_RUNNER_FAILED


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        _stderr("lifecycle_runner: no command given (use: -- CMD [ARG ...])")
        return EXIT_RUNNER_FAILED
    try:
        spec = RunSpec(
            argv=tuple(command), cwd=args.cwd, log_path=args.log, timeout_seconds=args.timeout,
            # UTF-8 for the log, and unbuffered so a Python child's output is in the
            # log in order and survives being killed at the deadline (a killed
            # process does not flush a block-buffered stdout).
            env={"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
        )
    except ValueError as exc:
        _stderr(f"lifecycle_runner: {exc}")
        return EXIT_RUNNER_FAILED

    result = run(spec)
    if result.outcome is RunOutcome.TIMED_OUT:
        _note(args.log, f"[lifecycle_runner] killed after {args.timeout:g}s timeout")
    elif result.outcome is RunOutcome.FAILED_TO_START:
        _note(args.log, f"[lifecycle_runner] could not start: {result.error}")
    elif result.outcome is RunOutcome.ERROR:
        _note(args.log, f"[lifecycle_runner] run failed: {result.error}")
    return exit_code_for(result)


if __name__ == "__main__":
    raise SystemExit(main())
