"""``Shutdown`` on POSIX signals / the Windows console break."""

from __future__ import annotations

import contextlib
import signal
from collections.abc import Iterator
from contextlib import AbstractContextManager

__all__ = ["SignalShutdown"]


class SignalShutdown:
    """Turns "the terminal window was closed" (SIGHUP) and "something asked us to stop" (SIGTERM) into
    KeyboardInterrupt while the launcher runs, so its cleanup stops every service. Without this, closing
    the window would kill only the launcher and leave the services running on their ports."""

    def guard(self) -> AbstractContextManager[None]:
        return self._guard()

    @contextlib.contextmanager
    def _guard(self) -> Iterator[None]:
        def interrupt(signum, frame):
            raise KeyboardInterrupt

        previous: dict[int, object] = {}
        for name in ("SIGTERM", "SIGHUP", "SIGBREAK"):  # not every signal exists on every OS
            number = getattr(signal, name, None)
            if number is None:
                continue
            try:
                previous[number] = signal.signal(number, interrupt)
            except (ValueError, OSError):
                continue  # not the main thread, or this signal cannot be handled here
        try:
            yield
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)
