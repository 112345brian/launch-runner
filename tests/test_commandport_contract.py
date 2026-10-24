"""commandport imports none of the libraries it checks, and this repository holds itself to its own scan."""
from __future__ import annotations

import ast
from pathlib import Path

from commandport import scan

REPO = Path(__file__).resolve().parent.parent


def test_the_contract_package_is_pure():
    """commandport checks the libraries from outside: it imports none of them, nor a process-starting module."""
    forbidden = {"subprocess", "psutil", "socket", "urllib", "http", "requests", "ctypes",
                 "lifecycle_runner", "proclaunch", "ensure_running"}
    package = REPO / "distributions" / "commandport" / "src" / "commandport"
    for path in sorted(package.glob("*.py")):
        name = path.name
        tree = ast.parse(path.read_text(encoding="utf-8"))
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
    assert scan.load_config(REPO).allow == ("lifecycle_runner.adapters", "proclaunch.adapters", "stackrun.adapters")
