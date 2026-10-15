"""commandport stays free of providers and I/O modules, and this repository holds itself to its own scan."""
from __future__ import annotations

import ast
from pathlib import Path

from commandport import scan

REPO = Path(__file__).resolve().parent.parent


def test_the_contract_package_is_pure():
    """commandport forwards to the providers lazily; it must not import them, nor any process, file or network module."""
    forbidden = {"subprocess", "os", "psutil", "socket", "urllib", "http", "tempfile", "shutil", "signal",
                 "ctypes", "requests", "lifecycle_runner", "proclaunch"}
    for name in ("domain.py", "ports.py", "testing.py", "__init__.py"):
        tree = ast.parse((REPO / "distributions" / "commandport" / "src" / "commandport" / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                modules = [node.module]
            for module in modules:
                assert module.split(".")[0] not in forbidden, f"commandport/{name} imports {module}"


def test_no_process_is_started_outside_the_adapters():
    """The scan, configured by [tool.commandport] in this repository's own pyproject.toml."""
    scan.assert_clean(REPO)


def test_the_only_modules_allowed_raw_process_apis_are_the_two_adapter_packages():
    assert scan.load_config(REPO).allow == ("lifecycle_runner.adapters", "proclaunch.adapters")
