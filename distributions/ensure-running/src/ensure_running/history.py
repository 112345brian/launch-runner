"""The restart cap's memory: start times per target, kept in a JSON file across scheduled runs."""
from __future__ import annotations

import json
import os
from pathlib import Path


def load(path: Path) -> dict[str, list[float]]:
    """Missing or unreadable history is empty: the cap then starts over, which is the safe direction
    for a supervisor (a target is restarted, never silently held back by a damaged file)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): [float(x) for x in v] for k, v in data.items()}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def save(path: Path, history: dict[str, list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(history), encoding="utf-8")
    os.replace(tmp, path)
