"""``Browser`` on ``webbrowser`` and a stdlib HTTP probe."""

from __future__ import annotations

import threading
import time
import webbrowser
from collections.abc import Callable

from .http_probe import url_answers

__all__ = ["BrowserOpener"]


class BrowserOpener:
    """Opens the default browser once the URL answers, from a background thread so the launcher's
    supervising loop is never held up. Gives up quietly after ``timeout`` seconds."""

    def __init__(
        self,
        opener: Callable[[str], object] = webbrowser.open,
        poll_interval: float = 0.5,
        timeout: float = 120.0,
        probe: Callable[[str], bool] = url_answers,
    ) -> None:
        self._open = opener
        self._interval = poll_interval
        self._timeout = timeout
        self._probe = probe

    def open_when_ready(self, url: str) -> None:
        threading.Thread(target=self._wait_then_open, args=(url,), daemon=True).start()

    def open_now(self, url: str) -> None:
        self._open(url)

    def _wait_then_open(self, url: str) -> None:
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            if self._probe(url):
                self._open(url)
                return
            time.sleep(self._interval)
