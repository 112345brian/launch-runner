"""RecordStore on the filesystem: ``<state_dir>/<name>.json``, written atomically."""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

from proclaunch.adapters.atomic_files import dump_json, read_json
from proclaunch.domain import ProcessIdentity, RecordUnreadable, ServiceRecord


def _valid_name(name: str) -> str:
    if not name or any(c in name for c in "/\\\0") or name in (".", ".."):
        raise ValueError(f"invalid service name: {name!r}")
    return name


def _to_json(record: ServiceRecord) -> dict:
    ident = record.identity
    return {
        "name": record.name,
        "pid": ident.pid if ident else -1,
        "create_time": ident.create_time if ident else -1,
        "reserved_at": record.reserved_at,
        "argv": list(record.argv),
        "cwd": record.cwd,
        "method": record.method,
    }


def _from_json(path: Path, data: object) -> ServiceRecord:
    if not isinstance(data, dict) or "pid" not in data or "create_time" not in data:
        raise RecordUnreadable(f"{path}: record must be an object with pid and create_time; preserved")
    identity = None if data["pid"] == -1 else ProcessIdentity(data["pid"], data["create_time"])
    return ServiceRecord(
        name=str(data.get("name", path.stem)),
        identity=identity,
        reserved_at=data.get("reserved_at"),
        argv=tuple(data.get("argv") or ()),
        cwd=data.get("cwd"),
        method=data.get("method"),
    )


_LOCK_WAIT_SECONDS = 2.0
_LOCK_STALE_SECONDS = 10.0


class JsonFileRecordStore:
    def __init__(self, state_dir: Path) -> None:
        self._dir = Path(state_dir)

    def _path(self, name: str) -> Path:
        return self._dir / f"{_valid_name(name)}.json"

    def load(self, name: str) -> ServiceRecord | None:
        path = self._path(name)
        if not path.exists():
            return None
        try:
            return _from_json(path, read_json(path))
        except RecordUnreadable:
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise RecordUnreadable(f"cannot read {path}: {exc}") from exc

    def create_exclusive(self, name: str, record: ServiceRecord) -> bool:
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            dump_json(path, _to_json(record), exclusive=True)
        except FileExistsError:
            return False
        return True

    def replace(self, name: str, record: ServiceRecord) -> None:
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        dump_json(path, _to_json(record))

    def delete(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)

    @contextmanager
    def _locked(self, name: str):
        """A short-lived per-service lock file, so a compare-and-swap is one step.
        A lock left by a dead holder is broken after ``_LOCK_STALE_SECONDS``.
        Yields False if the lock could not be taken in time."""
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = path.with_suffix(".lock")
        deadline = time.monotonic() + _LOCK_WAIT_SECONDS
        held = False
        while not held:
            try:
                os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                held = True
            except (FileExistsError, PermissionError):  # Windows: PermissionError while the holder deletes it
                try:
                    if time.time() - lock.stat().st_mtime > _LOCK_STALE_SECONDS:
                        lock.unlink(missing_ok=True)
                        continue
                except OSError:
                    continue
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.01)
        try:
            yield held
        finally:
            if held:
                lock.unlink(missing_ok=True)

    def _current_equals(self, name: str, expected: ServiceRecord) -> bool:
        try:
            return self.load(name) == expected
        except RecordUnreadable:
            return False

    def take_over(self, name: str, expected: ServiceRecord, new: ServiceRecord) -> bool:
        with self._locked(name) as held:
            if not held or not self._current_equals(name, expected):
                return False
            dump_json(self._path(name), _to_json(new))
            return True

    def delete_if(self, name: str, expected: ServiceRecord) -> bool:
        with self._locked(name) as held:
            if not held or not self._current_equals(name, expected):
                return False
            self._path(name).unlink(missing_ok=True)
            return True
