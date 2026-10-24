"""HTTP "does it answer?" probe (stdlib): the one definition used by ``HttpReadiness`` and ``BrowserOpener``."""

from __future__ import annotations

import urllib.error
import urllib.request

__all__ = ["HttpReadiness", "url_answers"]


def url_answers(url: str, timeout: float = 2.0) -> bool:
    """True if a server answers at ``url``. An error page (404, 500) still means the server is up. Never raises."""
    try:
        with urllib.request.urlopen(url, timeout=timeout):  # noqa: S310 - the caller chooses the URL
            return True
    except urllib.error.HTTPError:
        return True
    except (OSError, ValueError):  # refused, timed out, unreachable, or a malformed URL
        return False


class HttpReadiness:
    """Implements ``Readiness``."""

    def __init__(self, timeout: float = 2.0) -> None:
        self._timeout = timeout

    def is_ready(self, url: str) -> bool:
        return url_answers(url, self._timeout)
