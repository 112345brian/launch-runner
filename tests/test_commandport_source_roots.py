"""commandport.scan with a src layout (or one ``src`` per distribution in a monorepo)."""
from __future__ import annotations

from pathlib import Path

import pytest

from commandport import scan


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_module_names_are_relative_to_a_source_root(tmp_path):
    _write(tmp_path, "dists/a/src/pkg/adapters/spawn.py", "import subprocess\nsubprocess.Popen(['x'])\n")
    _write(tmp_path, "dists/a/src/pkg/core.py", "import subprocess\nsubprocess.run(['x'])\n")
    config = scan.config_from_table(
        tmp_path, {"roots": [], "allow": ["pkg.adapters"], "source_roots": ["dists/a/src"]},
    )
    findings = scan.collect(config)
    assert [f.path for f in findings] == ["dists/a/src/pkg/core.py"]
    assert findings[0].module == "pkg.core"


def test_the_longest_source_root_wins_and_roots_outside_any_are_root_relative(tmp_path):
    _write(tmp_path, "src/outer/x.py", "import os\nos.system('x')\n")
    _write(tmp_path, "src/nested/src/inner/y.py", "import os\nos.system('x')\n")
    _write(tmp_path, "tool/z.py", "import os\nos.system('x')\n")
    config = scan.config_from_table(
        tmp_path, {"roots": ["tool"], "allow": [], "source_roots": ["src", "src/nested/src"]},
    )
    assert {f.path: f.module for f in scan.collect(config)} == {
        "src/outer/x.py": "outer.x",
        "src/nested/src/inner/y.py": "inner.y",
        "tool/z.py": "tool.z",
    }


def test_a_source_root_is_also_scanned_without_being_listed_in_roots(tmp_path):
    _write(tmp_path, "src/pkg/mod.py", "import os\nos.system('x')\n")
    config = scan.config_from_table(tmp_path, {"roots": ["elsewhere"], "allow": [], "source_roots": ["src"]})
    assert [f.path for f in scan.collect(config)] == ["src/pkg/mod.py"]


def test_source_roots_must_be_strings(tmp_path):
    with pytest.raises(scan.ConfigError, match="source_roots"):
        scan.config_from_table(tmp_path, {"roots": ["a"], "source_roots": [1]})
