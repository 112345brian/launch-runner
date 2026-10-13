"""Atomic JSON record files. Adapted from dmon (MIT); see THIRD_PARTY_NOTICES.md."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ON_WINDOWS = sys.platform == "win32"


def replace_file(source: Path, target: Path, timeout: float = 0.5) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def dump_json(path: Path, data: dict, *, exclusive: bool = False) -> None:
    """Write *data* atomically. ``exclusive=True`` fails with FileExistsError if
    *path* already exists (the start-reservation primitive)."""
    target = Path(path)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent,
            prefix=f".{target.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary_path, target)
        else:
            replace_file(temporary_path, target)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def read_json(path: Path, timeout: float = 0.5):
    # Windows can briefly deny opening a record during atomic replacement.
    deadline = time.monotonic() + timeout
    while True:
        try:
            with Path(path).open("r", encoding="utf-8") as stream:
                return json.load(stream)
        except PermissionError:
            if not ON_WINDOWS or time.monotonic() >= deadline:
                raise
            time.sleep(0.01)
