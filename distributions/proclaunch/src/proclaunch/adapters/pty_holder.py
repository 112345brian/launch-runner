"""Unix only: run a command on a pseudo-terminal and stay alive as its owner.

A TUI program (``claude remote-control``) exits without a terminal. A pty master that closes sends its
child SIGHUP, so something must keep the master open for as long as the child lives. That is this process:
it forks the command onto a fresh pty, copies the pty's output to ``--log`` (or discards it), forwards
SIGTERM/SIGINT to the child, and exits with the child's status. Its pid is the service's identity.

    python -m proclaunch.adapters.pty_holder [--log PATH] [--rows N] [--cols N] -- command args...
"""
from __future__ import annotations

import argparse
import fcntl
import os
import pty
import signal
import struct
import sys
import termios


def _set_size(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def run(argv: list[str], log_path: str | None, rows: int = 40, cols: int = 120) -> int:
    log = open(log_path, "ab", buffering=0) if log_path else None
    pid, master = pty.fork()
    if pid == 0:  # child: the pty slave is already its controlling terminal and stdio
        try:
            os.execvp(argv[0], argv)
        except OSError as exc:
            os.write(2, f"cannot start {argv[0]!r}: {exc}\n".encode())
            os._exit(127)
    _set_size(master, rows, cols)

    def forward(signum: int, _frame: object) -> None:
        try:
            os.kill(pid, signum)
        except ProcessLookupError:
            pass

    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    try:
        while True:
            try:
                data = os.read(master, 65536)
            except OSError:  # EIO: every slave fd is closed, the child is gone
                break
            if not data:
                break
            if log is not None:
                log.write(data)
    finally:
        os.close(master)
        if log is not None:
            log.close()
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


def main(args: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pty_holder")
    p.add_argument("--log")
    p.add_argument("--rows", type=int, default=40)
    p.add_argument("--cols", type=int, default=120)
    p.add_argument("command", nargs=argparse.REMAINDER)
    ns = p.parse_args(args)
    command = ns.command[1:] if ns.command[:1] == ["--"] else ns.command
    if not command:
        p.error("no command given")
    return run(command, ns.log, ns.rows, ns.cols)


if __name__ == "__main__":
    sys.exit(main())
