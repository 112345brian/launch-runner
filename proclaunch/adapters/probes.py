"""Probe adapters: HTTP, TCP and callable health checks."""
from __future__ import annotations

import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.request import urlopen


@dataclass(frozen=True)
class HttpProbe:
    url: str
    require_owned: bool = False

    def run(self, timeout: float) -> bool:
        try:
            with urlopen(self.url, timeout=max(0.01, timeout)) as response:
                return 200 <= response.status < 400
        except Exception:  # noqa: BLE001 -- a failing probe is "not ready", never a raise
            return False


@dataclass(frozen=True)
class TcpProbe:
    host: str
    port: int
    require_owned: bool = False

    def run(self, timeout: float) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=max(0.01, timeout)):
                return True
        except Exception:  # noqa: BLE001
            return False


@dataclass(frozen=True)
class CallableProbe:
    check: Callable[[], bool]
    require_owned: bool = False

    def run(self, timeout: float) -> bool:
        try:
            return bool(self.check())
        except Exception:  # noqa: BLE001
            return False
