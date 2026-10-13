"""lifecycle_runner is hexagonal, like proclaunch: domain and the runner depend
on ports, never on adapters or process/file modules; adapters never depend on
the runner; only ``api`` wires them. It may import proclaunch's public
composition root (``proclaunch.api``) and nothing from the application."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parent.parent / "distributions" / "lifecycle-runner" / "src" / "lifecycle_runner"

IO_MODULES = {
    "subprocess", "psutil", "socket", "urllib", "http", "tempfile", "shutil", "signal",
    "os", "time", "platform", "json", "ctypes", "multiprocessing", "asyncio", "requests",
}
CORE = ["ports.py", "runner.py", "capture.py"]
APP_MODULES = {"lifecycle_runner.api", "lifecycle_runner.runner"}
FOREIGN = {"jobsearch", "tracker", "state", "llm", "cover_letter", "resume", "libraries", "scripts", "jobsearch_cli"}


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


@pytest.mark.parametrize("module", CORE)
def test_core_imports_no_io_module_adapter_or_proclaunch(module):
    for imp in _imports(PKG / module):
        assert imp.split(".")[0] not in IO_MODULES, f"{module} imports I/O module {imp}"
        assert not imp.startswith("lifecycle_runner.adapters"), f"{module} imports adapter {imp}"
        assert imp.split(".")[0] != "proclaunch", f"{module} imports proclaunch; only adapters may"


def test_ports_import_no_application_logic():
    for module in ("ports.py",):
        for imp in _imports(PKG / module):
            assert imp not in APP_MODULES, f"{module} imports {imp}"


def test_adapters_do_not_import_the_runner_or_api():
    for path in (PKG / "adapters").glob("*.py"):
        for imp in _imports(path):
            assert imp not in APP_MODULES, f"{path.name} imports {imp}"


def test_only_api_imports_adapters():
    for path in PKG.glob("*.py"):
        if any(i.startswith("lifecycle_runner.adapters") for i in _imports(path)):
            assert path.name == "api.py", f"{path.name} imports adapters"


def test_package_imports_nothing_from_the_application():
    for path in PKG.rglob("*.py"):
        for imp in _imports(path):
            assert imp.split(".")[0] not in FOREIGN, f"{path} imports {imp}"


def test_proclaunch_is_reached_only_through_its_composition_root():
    for path in PKG.rglob("*.py"):
        for imp in _imports(path):
            if imp.split(".")[0] != "proclaunch":
                continue
            assert imp == "proclaunch.api" or imp.startswith("proclaunch.api."), f"{path.name} imports {imp}"


def test_the_runner_names_no_concrete_adapter():
    text = (PKG / "runner.py").read_text(encoding="utf-8")
    for name in ("PopenSpawner", "SystemClock", "PopenChild"):
        assert name not in text
