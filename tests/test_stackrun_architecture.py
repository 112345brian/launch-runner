"""stackrun's dependency rule, as one declarative table (read from the AST; lazy imports count).

Rings, innermost first: domain -> ports -> launcher/declarative -> adapters -> composition roots (api, cli).
A module may import only what its row allows. Every module must have a row, so none escapes the rules.
OS branching (``os.name``, ``sys.platform``, ``platform.*``) is allowed only in adapters.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parent.parent / "distributions" / "stackrun" / "src" / "stackrun"

PURE = {"__future__", "collections", "contextlib", "dataclasses", "re", "typing", "tomllib"}
STDLIB_ADAPTER = {
    "__future__", "collections", "contextlib", "os", "pathlib", "shutil", "signal", "socket", "subprocess", "sys",
    "threading", "time", "urllib", "webbrowser",
}

# module (relative path) -> (allowed stackrun modules, allowed external top-level packages, may branch on the OS)
RULES: dict[str, tuple[set[str], set[str], bool]] = {
    "__init__.py": (set(), set(), False),
    "domain.py": (set(), PURE, False),
    "ports.py": ({"stackrun.domain"}, PURE, False),
    "launcher.py": ({"stackrun.domain", "stackrun.ports"}, PURE, False),
    "declarative.py": ({"stackrun.domain"}, PURE, False),
    "testing.py": ({"stackrun.domain", "stackrun.ports"}, PURE | {"time", "pathlib"}, False),
    "api.py": (
        {"stackrun.adapters", "stackrun.declarative", "stackrun.domain", "stackrun.launcher", "stackrun.ports"},
        {"__future__", "re", "time", "collections", "pathlib"},
        False,
    ),
    "cli.py": ({"stackrun.api"}, {"__future__", "argparse", "sys", "pathlib"}, False),
    "__main__.py": ({"stackrun.cli"}, {"sys"}, False),
    "adapters/__init__.py": (
        {f"stackrun.adapters.{m}" for m in (
            "browser", "console", "environment", "file_record", "http_probe", "psutil_processes", "resolver",
            "signals", "socket_ports", "subprocess_runner", "terminate")},
        {"__future__"},
        False,
    ),
    "adapters/browser.py": ({"stackrun.adapters.http_probe"}, STDLIB_ADAPTER, True),
    "adapters/console.py": (set(), STDLIB_ADAPTER, True),
    "adapters/environment.py": (set(), STDLIB_ADAPTER, True),
    "adapters/file_record.py": ({"stackrun.domain", "stackrun.ports"}, STDLIB_ADAPTER, True),
    "adapters/http_probe.py": (set(), STDLIB_ADAPTER, True),
    "adapters/psutil_processes.py": ({"stackrun.domain", "stackrun.adapters.terminate"}, STDLIB_ADAPTER | {"psutil"}, True),
    "adapters/resolver.py": (set(), STDLIB_ADAPTER, True),
    "adapters/signals.py": (set(), STDLIB_ADAPTER, True),
    "adapters/socket_ports.py": (set(), STDLIB_ADAPTER, True),
    "adapters/subprocess_runner.py": ({"stackrun.ports", "stackrun.adapters.terminate"}, STDLIB_ADAPTER, True),
    "adapters/terminate.py": (set(), STDLIB_ADAPTER | {"proclaunch"}, True),
}


def _modules(rel: str) -> list[str]:
    path = PKG / rel
    package = "stackrun" + ("." + ".".join(Path(rel).parent.parts) if Path(rel).parent.parts else "")
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # resolve a relative import against this module's package
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                module = ".".join([*base, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            found.append(module)
            found += [f"{module}.{a.name}" for a in node.names if a.name != "*"]
    return found


def _is_package_module(name: str) -> bool:
    parts = name.split(".")
    return (PKG.parent / Path(*parts)).with_suffix(".py").is_file() or (PKG.parent / Path(*parts) / "__init__.py").is_file()


def _os_branching(rel: str) -> list[str]:
    hits = []
    for node in ast.walk(ast.parse((PKG / rel).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if (node.value.id, node.attr) in {("os", "name"), ("sys", "platform"), ("platform", "system")}:
                hits.append(f"{node.value.id}.{node.attr}")
    return hits


def test_every_module_is_classified():
    on_disk = {p.relative_to(PKG).as_posix() for p in PKG.rglob("*.py")}
    assert on_disk == set(RULES), f"unclassified: {sorted(on_disk - set(RULES))}; stale rows: {sorted(set(RULES) - on_disk)}"


@pytest.mark.parametrize("rel", sorted(RULES))
def test_module_obeys_its_ring(rel):
    internal_ok, external_ok, _ = RULES[rel]
    problems = []
    for name in set(_modules(rel)):
        top = name.split(".")[0]
        if top == "stackrun":
            if not _is_package_module(name):
                continue  # a name imported from a module, not a module
            if not any(name == ok or name.startswith(ok + ".") for ok in internal_ok) and name not in {"stackrun"}:
                problems.append(f"imports stackrun module {name}")
        elif top not in external_ok:
            problems.append(f"imports {name}")
    assert not problems, f"{rel}: " + "; ".join(sorted(problems))


@pytest.mark.parametrize("rel", sorted(RULES))
def test_only_adapters_branch_on_the_os(rel):
    allowed = RULES[rel][2]
    assert allowed or not _os_branching(rel), f"{rel} branches on the OS: {_os_branching(rel)}"


def test_the_core_names_no_third_party_process_library_even_lazily():
    for rel in ("domain.py", "ports.py", "launcher.py", "declarative.py", "testing.py", "api.py", "cli.py"):
        tops = {n.split(".")[0] for n in _modules(rel)}
        assert not tops & {"psutil", "proclaunch", "keyring", "lifecycle_runner"}, rel


def test_only_the_composition_root_imports_adapters():
    for rel in RULES:
        if rel.startswith("adapters/") or rel in {"api.py", "__init__.py"}:
            continue
        assert not any(n.startswith("stackrun.adapters") for n in _modules(rel)), rel


def test_the_launcher_names_no_concrete_adapter_or_app():
    text = (PKG / "launcher.py").read_text(encoding="utf-8")
    for name in ("SubprocessRunner", "SocketPorts", "FileRunRecord", "PsutilProcesses", "BrowserOpener"):
        assert name not in text
    for word in ("deepinterview", "livekit", "pnpm", "dotenv", "keyring"):
        assert word not in "".join(p.read_text(encoding="utf-8").lower() for p in PKG.rglob("*.py")), word


def test_the_third_party_imports_are_exactly_the_declared_extras():
    import tomllib

    project = tomllib.loads((PKG.parent.parent / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    extras = {k.lower() for k in project["optional-dependencies"]} - {"all"}
    imported = {
        n.split(".")[0] for rel in RULES for n in _modules(rel)
    } - {"stackrun"}
    import sys

    third_party = {t for t in imported if t not in sys.stdlib_module_names}
    assert third_party == extras == {"psutil", "proclaunch"}
    assert project["dependencies"] == []
