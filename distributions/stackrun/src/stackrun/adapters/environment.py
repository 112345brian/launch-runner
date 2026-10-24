"""``ConfigSource`` adapters over the process environment, and the matching scrub."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

__all__ = ["EnvironConfig", "scrub_environment"]


class EnvironConfig:
    """The process environment, optionally with fixed ``overrides`` on top. Read fresh on every call."""

    def __init__(self, overrides: Mapping[str, str] | None = None) -> None:
        self._overrides = dict(overrides or {})

    def environment(self) -> Mapping[str, str]:
        return {**os.environ, **self._overrides}


def scrub_environment(names: Iterable[str]) -> None:
    """Drop variables that describe the launcher's own throwaway interpreter (``uv run`` points
    ``VIRTUAL_ENV`` at one), so the programs it starts do not inherit and warn about them."""
    for name in names:
        os.environ.pop(name, None)
