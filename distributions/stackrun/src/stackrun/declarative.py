"""``stackrun.toml`` -> ``Stack``: the declarative way to describe a stack. Pure: text in, values out.

::

    name = "demo"                       # required
    open_url = "http://localhost:3000"  # optional: opened in the browser once it answers
    stop_hint = "`stackrun stop`"       # optional: completes "stop it first (...)" in messages

    [[service]]
    name = "api"                        # required, unique
    command = "uvicorn app:app --port 8000"   # a string (split like a shell, same on every OS) ...
    # argv = ["uvicorn", "app:app"]     # ... or a list; exactly one of the two
    port = 8000                         # optional
    cwd = "apps/api"                    # optional
    ready_url = "http://localhost:8000/health"   # optional
    [service.env]                       # optional, this service only
    MODE = "dev"

Unknown keys are an error, so a typo is not silently ignored.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass

from .domain import ServiceSpec, Stack, StackrunError, split_command

__all__ = ["StackFile", "parse_stack"]

_TOP_KEYS = {"name", "open_url", "stop_hint", "service"}
_SERVICE_KEYS = {"name", "command", "argv", "port", "cwd", "ready_url", "env"}


@dataclass(frozen=True)
class StackFile:
    stack: Stack
    open_url: str | None = None


def _unknown(where: str, table: dict[str, object], allowed: set[str]) -> None:
    extra = sorted(set(table) - allowed)
    if extra:
        raise StackrunError(f"{where}: unknown key(s) {', '.join(extra)}; allowed: {', '.join(sorted(allowed))}")


def _service(index: int, table: object) -> ServiceSpec:
    if not isinstance(table, dict):
        raise StackrunError(f"service #{index}: expected a table")
    where = f"service #{index}"
    _unknown(where, table, _SERVICE_KEYS)
    command, argv = table.get("command"), table.get("argv")
    if (command is None) == (argv is None):
        raise StackrunError(f"{where}: give exactly one of `command` (string) or `argv` (list)")
    if command is not None:
        if not isinstance(command, str):
            raise StackrunError(f"{where}: `command` must be a string")
        words = tuple(split_command(command))
    else:
        if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
            raise StackrunError(f"{where}: `argv` must be a list of strings")
        words = tuple(argv)
    env = table.get("env")
    if env is not None and not (isinstance(env, dict) and all(isinstance(v, str) for v in env.values())):
        raise StackrunError(f"{where}: `env` must be a table of strings")
    for key in ("name", "cwd", "ready_url"):
        if key in table and not isinstance(table[key], str):
            raise StackrunError(f"{where}: `{key}` must be a string")
    return ServiceSpec(
        name=str(table.get("name", "")),
        argv=words,
        port=table.get("port"),  # type: ignore[arg-type]  # ServiceSpec validates it
        env=env,
        cwd=table.get("cwd"),  # type: ignore[arg-type]
        ready_url=table.get("ready_url"),  # type: ignore[arg-type]
    )


def parse_stack(text: str) -> StackFile:
    """Parse the text of a ``stackrun.toml``. Raises ``StackrunError`` for anything wrong with it."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise StackrunError(f"not valid TOML: {exc}") from exc
    _unknown("stackrun.toml", data, _TOP_KEYS)
    services = data.get("service", [])
    if not isinstance(services, list):
        raise StackrunError("`service` must be an array of tables ([[service]])")
    for key in ("name", "open_url", "stop_hint"):
        if key in data and not isinstance(data[key], str):
            raise StackrunError(f"`{key}` must be a string")
    stack = Stack(
        name=data.get("name", ""),
        services=tuple(_service(i, table) for i, table in enumerate(services, start=1)),
        stop_hint=data.get("stop_hint", ""),
    )
    return StackFile(stack, data.get("open_url"))
