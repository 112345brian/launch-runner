"""Give a detached foreground child a process group of its own, so a timeout can stop everything in it.

Without this a child shares the caller's group: the kill falls back to walking the child's *current* descendants,
which misses one that was re-parented to init before the deadline (its parent exited) and leaves it running.
With its own group the whole group is signalled, orphans included.

``process_group=0`` rather than ``start_new_session``: the child stays in the caller's *session* and keeps the
controlling terminal association, so only the foreground-group signals change. A Ctrl-C at the terminal no longer
reaches the child by itself (its group is in the background), which is why the runner and the stream kill it
explicitly when ``KeyboardInterrupt`` arrives. A child that attaches to the caller's console
(``RunSpec.inherit_stdio``) is deliberately *not* given its own group: it must stay in the terminal's
foreground group to read from it and to receive Ctrl-C.

Not applicable on Windows (``subprocess`` has no process groups of this kind there).
"""
from __future__ import annotations

import sys


def own_group() -> dict[str, int]:
    """``Popen`` keyword arguments that start the child as the leader of a new process group (POSIX)."""
    return {} if sys.platform == "win32" else {"process_group": 0}
