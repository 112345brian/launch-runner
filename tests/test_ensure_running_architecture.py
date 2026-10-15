"""ensure_running is an onion: dependencies point only inward.

    domain  <-  application (reconciler)  <-  adapters (conditions, config, history)  <-  root (cli)

The domain knows nothing of the application; the application knows nothing of an adapter or of any I/O
module; adapters never reach the application or the root; only the root names both."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parent.parent / "distributions" / "ensure-running" / "src" / "ensure_running"
DOMAIN = ["domain.py"]
APPLICATION = ["reconciler.py"]
ADAPTERS = ["conditions.py", "config.py", "history.py", "lifecycle_check.py"]
ROOT = ["cli.py", "__main__.py"]
IO_MODULES = {"subprocess", "psutil", "socket", "urllib", "http", "tempfile", "shutil", "signal", "os",
              "time", "platform", "json", "ctypes", "multiprocessing", "asyncio", "requests", "tomllib",
              "sys", "proclaunch", "lifecycle_runner", "commandport"}
INNER_OF = {  # module -> ring names it may NOT import
    "domain": {"reconciler", "conditions", "config", "history", "lifecycle_check", "cli"},
    "reconciler": {"conditions", "config", "history", "lifecycle_check", "cli"},
    "adapter": {"reconciler", "cli"},
}


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


def _ensure_running_modules(imps: set[str]) -> set[str]:
    return {i.split(".")[1] for i in imps if i.startswith("ensure_running.") and i.count(".") >= 1}


@pytest.mark.parametrize("module", DOMAIN + APPLICATION)
def test_core_rings_import_no_io_module(module):
    for imp in _imports(PKG / module):
        assert imp.split(".")[0] not in IO_MODULES, f"{module} imports I/O module {imp}"


def test_domain_imports_nothing_outward():
    assert not _ensure_running_modules(_imports(PKG / "domain.py")) & INNER_OF["domain"]


def test_application_imports_no_adapter_and_no_root():
    assert not _ensure_running_modules(_imports(PKG / "reconciler.py")) & INNER_OF["reconciler"]


@pytest.mark.parametrize("module", ADAPTERS)
def test_adapters_import_neither_application_nor_root(module):
    assert not _ensure_running_modules(_imports(PKG / module)) & INNER_OF["adapter"]


def test_only_the_root_names_both_application_and_adapters():
    for path in PKG.glob("*.py"):
        mods = _ensure_running_modules(_imports(path))
        if mods & {"reconciler"} and mods & set(ADAPTERS):
            assert path.name in ROOT, f"{path.name} wires application to adapters"
