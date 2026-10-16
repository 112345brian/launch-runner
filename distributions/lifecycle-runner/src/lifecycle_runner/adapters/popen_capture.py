"""CaptureSpawner and StreamSpawner on ``subprocess.Popen``: windowless, UTF-8, stdin never inherited.

Both resolve ``argv[0]`` through ``shutil.which`` (Windows' CreateProcess does not apply PATHEXT the way
``which`` does, so a ``.cmd`` shim would otherwise be "not found"), and both set ``CREATE_NO_WINDOW`` so a
caller with no console of its own (the tracker under pythonw, a scheduled task) never flashes one.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from collections.abc import Iterator

from lifecycle_runner.domain import CaptureSpec, StreamSpec
from lifecycle_runner.adapters.process_group import own_group
from lifecycle_runner.adapters.process_tree import terminate_tree
from lifecycle_runner.adapters.windows import windowless_creationflags

_TERMINATE_TIMEOUT_SECONDS = 5.0
_DRAIN_TIMEOUT_SECONDS = 2.0
_NEWLINES = re.compile(r"\r\n?")


def _resolve(argv: tuple[str, ...]) -> list[str]:
    exe = shutil.which(argv[0])
    if exe is None:
        raise FileNotFoundError(f"executable not found: {argv[0]}")
    return [exe, *argv[1:]]


def _environment(overlay) -> dict[str, str] | None:
    return {**os.environ, **overlay} if overlay else None


def _decode(data: bytes | None) -> str:
    """UTF-8 with undecodable bytes replaced, and universal newlines (what ``text=True`` gave callers)."""
    if not data:
        return ""
    return _NEWLINES.sub("\n", data.decode("utf-8", errors="replace"))


def _kill_tree(proc: subprocess.Popen) -> bool:
    """Stop *proc* and its descendants. True when nothing of it remains. Never raises."""
    try:
        gone = terminate_tree(proc, own_group=bool(own_group()), timeout=_TERMINATE_TIMEOUT_SECONDS)
        if not gone:
            try:
                proc.kill()
            except OSError:
                pass
        try:
            proc.wait(timeout=1)
            gone = gone or proc.poll() is not None
        except subprocess.TimeoutExpired:
            pass
        return gone
    except Exception:  # noqa: BLE001 -- the ports promise kill never raises
        return False


class PopenCapturedChild:
    def __init__(self, proc: subprocess.Popen) -> None:
        self._proc = proc
        self.pid = proc.pid
        self._partial = ("", "")

    def communicate(self, stdin_text: str | None, timeout: float | None) -> tuple[str, str, int] | None:
        data = stdin_text.encode("utf-8") if stdin_text is not None else None
        try:
            out, err = self._proc.communicate(input=data, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            self._partial = (_decode(exc.stdout), _decode(exc.stderr))
            return None
        return _decode(out), _decode(err), self._proc.returncode

    def partial_output(self) -> tuple[str, str]:
        # After a kill the pipes are at EOF: drain what the child had written but we had not read yet.
        try:
            out, err = self._proc.communicate(timeout=_DRAIN_TIMEOUT_SECONDS)
            return _decode(out) or self._partial[0], _decode(err) or self._partial[1]
        except Exception:  # noqa: BLE001
            return self._partial

    def kill(self) -> bool:
        return _kill_tree(self._proc)


class PopenCaptureSpawner:
    def spawn_captured(self, spec: CaptureSpec) -> PopenCapturedChild:
        proc = subprocess.Popen(
            _resolve(spec.argv), cwd=spec.cwd, env=_environment(spec.env),
            stdin=subprocess.PIPE if spec.stdin_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if spec.merge_stderr else subprocess.PIPE,
            creationflags=windowless_creationflags(), **own_group(),
        )
        return PopenCapturedChild(proc)


class PopenLineStream:
    def __init__(self, proc: subprocess.Popen, timeout_seconds: float | None) -> None:
        self._proc = proc
        self.pid: int | None = proc.pid
        self.start_error: str | None = None
        self._timed_out = threading.Event()
        self._timer: threading.Timer | None = None
        if timeout_seconds is not None:
            self._timer = threading.Timer(timeout_seconds, self._on_timeout)
            self._timer.daemon = True
            self._timer.start()

    def _on_timeout(self) -> None:
        # Only claim a timeout if the child was still running to kill: a timer that fires just as the
        # child exits normally must not mask its real exit code.
        if self._proc.poll() is None:
            self._timed_out.set()
            _kill_tree(self._proc)

    def __iter__(self) -> Iterator[str]:
        stdout = self._proc.stdout
        if stdout is None:
            return
        try:
            for raw in stdout:
                yield _decode(raw)
            self._proc.wait()
        except KeyboardInterrupt:
            # The child is in its own process group, so the terminal's Ctrl-C no longer reaches it.
            _kill_tree(self._proc)
            raise
        finally:
            self._cancel_timer()

    @property
    def returncode(self) -> int | None:
        return self._proc.poll()

    @property
    def timed_out(self) -> bool:
        return self._timed_out.is_set()

    def _cancel_timer(self) -> None:
        timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()

    def kill(self) -> None:
        _kill_tree(self._proc)

    def close(self) -> None:
        self._cancel_timer()
        if self._proc.poll() is None:
            _kill_tree(self._proc)
        try:
            if self._proc.stdout is not None:
                self._proc.stdout.close()
        except Exception:  # noqa: BLE001
            pass


class FailedLineStream:
    """What ``open_stream`` returns when the command could not start: empty, with the reason."""

    pid = None
    returncode = None
    timed_out = False

    def __init__(self, error: str) -> None:
        self.start_error = error

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def kill(self) -> None:
        return None

    def close(self) -> None:
        return None


class PopenStreamSpawner:
    def open_stream(self, spec: StreamSpec) -> PopenLineStream | FailedLineStream:
        try:
            proc = subprocess.Popen(
                _resolve(spec.argv), cwd=spec.cwd, env=_environment(spec.env),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=windowless_creationflags(), **own_group(),
            )
        except Exception as exc:  # noqa: BLE001 -- the port promises a stream, not a raise
            return FailedLineStream(f"{type(exc).__name__}: {exc}")
        return PopenLineStream(proc, spec.timeout_seconds)
