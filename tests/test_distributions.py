"""The three libraries are published as separate distributions plus a meta-package (``distributions/``).

This is the release gate: versions move together, the dependencies a distribution declares are exactly the ones
its code imports, the meta-package pins the set, and the wheels build and work from a clean install target.
"""
from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DISTRIBUTIONS = REPO / "distributions"

# distribution name -> (import name, package directory)
LIBRARIES = {
    "commandport": ("commandport", DISTRIBUTIONS / "commandport" / "src" / "commandport"),
    "proclaunch": ("proclaunch", DISTRIBUTIONS / "proclaunch" / "src" / "proclaunch"),
    "lifecycle-runner": ("lifecycle_runner", DISTRIBUTIONS / "lifecycle-runner" / "src" / "lifecycle_runner"),
}
# the import name of a third-party dependency -> its distribution name
THIRD_PARTY = {"psutil": "psutil"}
OWN_IMPORTS = {import_name: dist for dist, (import_name, _) in LIBRARIES.items()}


def _project(dist: str) -> dict:
    return tomllib.loads((DISTRIBUTIONS / dist / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def _normalise(requirement: str) -> str:
    return re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0].lower().replace("_", "-")


def _imported_top_level_names(package_dir: Path) -> set[str]:
    names: set[str] = set()
    for path in package_dir.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names.add(node.module.split(".")[0])
    return names


def _package_version(import_name: str) -> str:
    package_dir = next(d for name, d in LIBRARIES.values() if name == import_name)
    tree = ast.parse((package_dir / "__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "__version__" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{import_name}/__init__.py has no __version__")


def test_every_distribution_has_the_same_version_as_its_package():
    versions = {dist: _project(dist)["version"] for dist in (*LIBRARIES, "launch-runner")}
    assert len(set(versions.values())) == 1, f"versions must move together: {versions}"
    for dist, (import_name, _) in LIBRARIES.items():
        assert _package_version(import_name) == versions[dist], f"{import_name}.__version__ != {dist} version"


@pytest.mark.parametrize("dist", sorted(LIBRARIES))
def test_declared_dependencies_are_exactly_what_the_code_imports(dist):
    import_name, package_dir = LIBRARIES[dist]
    needed: set[str] = set()
    for name in _imported_top_level_names(package_dir):
        if name == import_name or name in sys.stdlib_module_names:
            continue
        if name in OWN_IMPORTS:
            needed.add(OWN_IMPORTS[name])
        elif name in THIRD_PARTY:
            needed.add(THIRD_PARTY[name])
        else:
            pytest.fail(f"{dist}: imports {name!r}, which is neither stdlib nor a known dependency")
    declared = {_normalise(r) for r in _project(dist).get("dependencies", [])}
    assert declared == needed, f"{dist}: declares {sorted(declared)} but imports {sorted(needed)}"


def test_internal_dependencies_are_pinned_to_the_matching_version():
    version = _project("commandport")["version"]
    for dist in ("proclaunch", "lifecycle-runner", "launch-runner"):
        for requirement in _project(dist).get("dependencies", []):
            if _normalise(requirement) in LIBRARIES:
                assert requirement.replace(" ", "").endswith(f"=={version}"), f"{dist}: {requirement}"


def test_the_meta_package_pulls_exactly_the_three_libraries_and_ships_no_code():
    project = _project("launch-runner")
    assert {_normalise(r) for r in project["dependencies"]} == set(LIBRARIES)
    config = tomllib.loads((DISTRIBUTIONS / "launch-runner" / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["setuptools"]["packages"] == []


def test_the_contract_depends_on_nothing():
    assert _project("commandport").get("dependencies", []) == []


def test_every_distribution_declares_a_python_floor_the_code_needs():
    # tomllib (3.11) is used by the scan; `X | Y` annotations are used throughout.
    for dist in (*LIBRARIES, "launch-runner"):
        assert _project(dist)["requires-python"] == ">=3.11"


def test_every_distribution_carries_complete_publishing_metadata():
    for dist in (*LIBRARIES, "launch-runner"):
        project = _project(dist)
        assert project["license"] == "MIT", dist
        assert project["license-files"] == ["LICENSE"], dist
        assert (DISTRIBUTIONS / dist / "LICENSE").is_file(), f"{dist} has no LICENSE file"
        assert project["authors"] and all(a.get("name") for a in project["authors"]), dist
        assert {"Homepage", "Repository", "Issues"} <= set(project["urls"]), dist
        assert project["urls"]["Repository"].startswith("https://github.com/"), dist
        assert project["keywords"] and project["classifiers"], dist
        assert (DISTRIBUTIONS / dist / "README.md").is_file(), dist
        assert project["description"].strip(), dist


def test_the_license_text_names_the_copyright_holder():
    text = (REPO / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License") and "Copyright (c) 2026 Brian Powers" in text
    for dist in (*LIBRARIES, "launch-runner"):
        assert (DISTRIBUTIONS / dist / "LICENSE").read_text(encoding="utf-8") == text


def test_every_library_ships_a_py_typed_marker_and_declares_it_as_package_data():
    for dist, (import_name, package_dir) in LIBRARIES.items():
        assert (package_dir / "py.typed").is_file(), f"{import_name}/py.typed missing"
        config = tomllib.loads((DISTRIBUTIONS / dist / "pyproject.toml").read_text(encoding="utf-8"))
        assert config["tool"]["setuptools"]["package-data"][import_name] == ["py.typed"]


# ----------------------------------------------------------------------------- build + install smoke test
def _pip_available() -> bool:
    from commandport.domain import CaptureSpec
    from lifecycle_runner.api import capture

    result = capture(CaptureSpec((sys.executable, "-c", "import pip, setuptools"), timeout_seconds=60))
    return result.ok


def test_the_wheels_build_offline_install_to_a_clean_target_and_work(tmp_path):
    from commandport.domain import CaptureSpec
    from lifecycle_runner.api import capture

    if not _pip_available():
        pytest.skip("pip and setuptools are needed to build the wheels")
    # Build from a copy: the build writes build/ and *.egg-info next to the project, not into the working tree.
    import shutil

    tree = tmp_path / "tree"
    shutil.copytree(DISTRIBUTIONS, tree / "distributions", ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", "build", "*.egg-info",
    ))

    wheels = tmp_path / "wheels"
    for dist in ("commandport", "proclaunch", "lifecycle-runner", "launch-runner"):
        built = capture(CaptureSpec(
            (sys.executable, "-m", "pip", "wheel", str(tree / "distributions" / dist), "--no-deps",
             "--no-build-isolation", "-q", "--disable-pip-version-check", "-w", str(wheels)),
            cwd=str(tmp_path), timeout_seconds=300,
        ))
        assert built.ok, f"building {dist}: {built.stderr or built.stdout or built.error}"
    wheel_files = sorted(p.name for p in wheels.glob("*.whl"))
    assert len(wheel_files) == 4, wheel_files

    import zipfile

    for wheel in wheels.glob("*.whl"):
        names = zipfile.ZipFile(wheel).namelist()
        assert any(n.endswith("/licenses/LICENSE") or n.endswith("LICENSE") for n in names), f"{wheel.name}: no LICENSE"
        if not wheel.name.startswith("launch_runner"):
            assert any(n.endswith("/py.typed") for n in names), f"{wheel.name}: no py.typed"
        metadata = next(n for n in names if n.endswith(".dist-info/METADATA"))
        text = zipfile.ZipFile(wheel).read(metadata).decode("utf-8")
        assert "License-Expression: MIT" in text and "Author: Brian Powers" in text, wheel.name

    target = tmp_path / "site"
    installed = capture(CaptureSpec(
        (sys.executable, "-m", "pip", "install", "--no-deps", "--no-index", "-q", "--disable-pip-version-check",
         "--target", str(target), *[str(w) for w in sorted(wheels.glob("*.whl"))]),
        cwd=str(tmp_path), timeout_seconds=300,
    ))
    assert installed.ok, installed.stderr or installed.stdout or installed.error

    # A tiny project that violates the contract, checked by the INSTALLED scan, with the installed runner.
    project = tmp_path / "proj"
    (project / "app").mkdir(parents=True)
    (project / "app" / "mod.py").write_text("import subprocess\nsubprocess.run(['x'])\n", encoding="utf-8")
    (project / "pyproject.toml").write_text('[tool.commandport]\nroots = ["app"]\n', encoding="utf-8")
    smoke = (
        "import sys; sys.path.insert(0, sys.argv[1])\n"
        "import commandport, lifecycle_runner, proclaunch\n"
        "for m in (commandport, lifecycle_runner, proclaunch):\n"
        "    assert m.__file__.startswith(sys.argv[1]), m.__file__\n"
        "from commandport.domain import CaptureSpec\n"
        "from commandport.scan import load_config, scan\n"
        "from lifecycle_runner.api import capture\n"
        "done = capture(CaptureSpec((sys.executable, '-c', 'print(42)'), timeout_seconds=30))\n"
        "assert done.ok and done.stdout.strip() == '42', done\n"
        "report = scan(load_config(sys.argv[2]))\n"
        "assert [f.kind for f in report.new] == ['subprocess.run'], report\n"
        "print('smoke ok')\n"
    )
    ran = capture(CaptureSpec(
        (sys.executable, "-c", smoke, str(target), str(project)), cwd=str(tmp_path), timeout_seconds=120,
    ))
    assert ran.ok and "smoke ok" in ran.stdout, ran.stderr or ran.stdout or ran.error
