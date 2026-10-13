"""proclaunch is hexagonal: domain and application depend on ports, never on
adapters or on process/file/network modules; adapters never depend on the
application's services; only ``api`` wires them together."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parent.parent / "distributions" / "proclaunch" / "src" / "proclaunch"

# Modules that perform I/O. The pure core may not import them.
IO_MODULES = {
    "subprocess", "psutil", "socket", "urllib", "http", "tempfile", "shutil", "signal",
    "os", "time", "platform", "json", "ctypes", "multiprocessing", "asyncio", "requests",
}
CORE = ["domain.py", "ports.py", "launching.py", "services.py", "readiness.py"]
APPLICATION = ["launching.py", "services.py", "readiness.py"]
APP_MODULES = {"proclaunch.api", "proclaunch.launching", "proclaunch.services", "proclaunch.readiness"}
FOREIGN = {"jobsearch", "tracker", "state", "llm", "cover_letter", "resume", "libraries", "scripts"}


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
def test_core_imports_no_io_module_and_no_adapter(module):
    for imp in _imports(PKG / module):
        assert imp.split(".")[0] not in IO_MODULES, f"{module} imports I/O module {imp}"
        assert not imp.startswith("proclaunch.adapters"), f"{module} imports adapter {imp}"


@pytest.mark.parametrize("module", ["domain.py", "ports.py"])
def test_domain_and_ports_import_no_application_logic(module):
    for imp in _imports(PKG / module):
        assert imp not in APP_MODULES, f"{module} imports application module {imp}"


def test_adapters_do_not_import_application_logic_or_api():
    for path in (PKG / "adapters").glob("*.py"):
        for imp in _imports(path):
            assert imp not in APP_MODULES, f"{path.name} imports {imp}"


def test_only_api_imports_both_application_and_adapters():
    for path in PKG.glob("*.py"):
        imps = _imports(path)
        has_adapters = any(i.startswith("proclaunch.adapters") for i in imps)
        has_app = bool(imps & (APP_MODULES - {"proclaunch.api"}))
        if has_adapters:
            assert path.name == "api.py", f"{path.name} imports adapters"
        if has_adapters and has_app:
            assert path.name == "api.py"


def test_nothing_outside_proclaunch_imports_adapters():
    # Callers reach adapters through the composition root (proclaunch.api),
    # never by naming a concrete adapter. Tests may import adapters directly.
    repo = PKG.parent
    allowed_roots = {"tests", "proclaunch"}
    ignored_parts = {".git", ".venv", "venv", "node_modules", ".claude", "client", "runtime", "__pycache__"}
    offenders = []
    for path in repo.rglob("*.py"):
        rel = path.relative_to(repo)
        if rel.parts[0] in allowed_roots or ignored_parts & set(rel.parts):
            continue
        try:
            imps = _imports(path)
        except (SyntaxError, UnicodeDecodeError):
            continue
        bad = sorted(i for i in imps if i == "proclaunch.adapters" or i.startswith("proclaunch.adapters."))
        if bad:
            offenders.append(f"{rel}: {bad}")
    assert not offenders, "import proclaunch.api instead of adapters: " + "; ".join(offenders)


def test_task_scheduler_supervisor_factory_returns_the_supervisor_port():
    from proclaunch.api import task_scheduler_supervisor

    sup = task_scheduler_supervisor("some-task")
    assert sup.task_name == "some-task"
    for method in ("available", "start", "end"):
        assert callable(getattr(sup, method))


def test_package_imports_nothing_from_the_application():
    for path in PKG.rglob("*.py"):
        for imp in _imports(path):
            assert imp.split(".")[0] not in FOREIGN, f"{path} imports {imp}"


def test_application_modules_take_dependencies_as_ports():
    # Application classes must receive collaborators; none may build an adapter.
    for module in APPLICATION:
        text = (PKG / module).read_text(encoding="utf-8")
        for adapter_name in ("SubprocessSpawner", "PsutilInspector", "JsonFileRecordStore", "SystemClock"):
            assert adapter_name not in text, f"{module} names adapter {adapter_name}"
