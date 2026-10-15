"""Load the desired state from TOML.

    state_dir = "~/.local/state/ensure-running"   # optional
    label = "dev.ensure-running"                   # optional: the launchd job label
    interval_seconds = 120                         # optional: how often the installed job re-checks
    pty = true                                     # optional: give each command a terminal

    [defaults]                                     # optional, applied to every target
    max_starts = 5
    window_seconds = 3600

    [[target]]
    name = "notes"                                 # unique; letters, digits, . _ -
    cwd = "~/notes"
    command = "claude remote-control"              # or: argv = ["claude", "remote-control"]
    check = "./is-wanted.sh"                       # optional: exit 0 = start it, 1 = leave it, else unknown
"""
from __future__ import annotations

import re
import shlex
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ensure_running.domain import Target

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_TOP = {"state_dir", "label", "interval_seconds", "pty", "defaults", "target"}
_TARGET = {"name", "cwd", "argv", "command", "check", "log_path", "max_starts", "window_seconds"}
_DEFAULTS = {"max_starts", "window_seconds"}


class ConfigError(ValueError):
    """The config file is unusable; the message says which key and why."""


@dataclass(frozen=True)
class Config:
    targets: tuple[Target, ...]
    state_dir: Path
    label: str = "dev.ensure-running"
    interval_seconds: int = 120
    pty: bool = True


def _path(value: object, what: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{what} must be a non-empty string")
    return Path(value).expanduser()


def _unknown(table: dict, allowed: set[str], where: str) -> None:
    extra = sorted(set(table) - allowed)
    if extra:
        raise ConfigError(f"{where}: unknown key(s) {', '.join(extra)}")


def _number(value: object, what: str, *, minimum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
        raise ConfigError(f"{what} must be a number >= {minimum:g}")
    return value


def _argv(value: object, what: str) -> tuple[str, ...]:
    """A command given as a shell-style string or as a list of strings."""
    if isinstance(value, str):
        try:
            parts = shlex.split(value)
        except ValueError as exc:
            raise ConfigError(f"{what}: {exc}") from exc
    elif isinstance(value, list) and all(isinstance(a, str) for a in value):
        parts = list(value)
    else:
        raise ConfigError(f"{what} must be a string or a list of strings")
    if not parts:
        raise ConfigError(f"{what} must not be empty")
    return tuple(parts)


def parse(text: str, *, default_state_dir: Path | None = None) -> Config:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"not valid TOML: {exc}") from exc
    _unknown(raw, _TOP, "config")
    defaults = raw.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ConfigError("[defaults] must be a table")
    _unknown(defaults, _DEFAULTS, "[defaults]")
    state_dir = _path(raw["state_dir"], "state_dir") if "state_dir" in raw else (
        default_state_dir or Path.home() / ".local" / "state" / "ensure-running")
    tables = raw.get("target", [])
    if not isinstance(tables, list) or not tables:
        raise ConfigError("define at least one [[target]]")
    targets: list[Target] = []
    seen: set[str] = set()
    for i, t in enumerate(tables, 1):
        where = f"[[target]] #{i}"
        if not isinstance(t, dict):
            raise ConfigError(f"{where} must be a table")
        _unknown(t, _TARGET, where)
        name = t.get("name")
        if not isinstance(name, str) or not _NAME.match(name):
            raise ConfigError(f"{where}: name must match {_NAME.pattern}: {name!r}")
        if name in seen:
            raise ConfigError(f"{where}: duplicate name {name!r}")
        seen.add(name)
        if ("argv" in t) == ("command" in t):
            raise ConfigError(f"{where} ({name}): give exactly one of argv or command")
        if "argv" in t:
            argv = t["argv"]
            if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
                raise ConfigError(f"{where} ({name}): argv must be a non-empty list of strings")
        else:
            try:
                argv = shlex.split(t["command"]) if isinstance(t["command"], str) else None
            except ValueError as exc:
                raise ConfigError(f"{where} ({name}): command: {exc}") from exc
            if not argv:
                raise ConfigError(f"{where} ({name}): command must be a non-empty string")
        check = None
        if "check" in t:
            check = _argv(t["check"], f"{where} ({name}): check")
        cwd = _path(t["cwd"], f"{where} ({name}): cwd") if "cwd" in t else None
        if cwd is not None and not cwd.is_dir():
            raise ConfigError(f"{where} ({name}): cwd is not a directory: {cwd}")
        log = _path(t["log_path"], f"{where} ({name}): log_path") if "log_path" in t else (
            state_dir / "logs" / f"{name}.log")
        merged = {**defaults, **{k: t[k] for k in _DEFAULTS if k in t}}
        try:
            targets.append(Target(
                name, tuple(argv), cwd=str(cwd) if cwd else None, log_path=log, check=check,
                max_starts=int(_number(merged.get("max_starts", 5), f"{where}: max_starts", minimum=1)),
                window_seconds=float(_number(merged.get("window_seconds", 3600), f"{where}: window_seconds",
                                             minimum=1)),
            ))
        except ValueError as exc:
            raise ConfigError(f"{where} ({name}): {exc}") from exc
    return Config(
        tuple(targets), state_dir,
        label=str(raw.get("label", "dev.ensure-running")),
        interval_seconds=int(_number(raw.get("interval_seconds", 120), "interval_seconds", minimum=10)),
        pty=bool(raw.get("pty", True)),
    )


def load(path: Path) -> Config:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    return parse(text)
