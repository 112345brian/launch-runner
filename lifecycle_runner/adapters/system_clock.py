"""Clock on ``time.monotonic``."""
from __future__ import annotations

import time


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()
