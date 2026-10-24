"""``Console`` on stdout."""

from __future__ import annotations

import sys

__all__ = ["StdoutConsole"]


class StdoutConsole:
    def say(self, message: str) -> None:
        print(message, file=sys.stdout, flush=True)
