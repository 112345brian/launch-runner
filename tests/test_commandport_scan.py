"""commandport.scan: the self-enforcing half of the command contract.

The engine is exercised on small synthetic trees (so each rule is pinned on its own), and the repo itself is
checked against its own ``[tool.commandport]`` config in ``test_commandport_self_enforcement.py``.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from commandport import scan


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")


def _config(root: Path, **table) -> scan.ScanConfig:
    table.setdefault("roots", ["app"])
    return scan.config_from_table(root, table)


def _kinds(config: scan.ScanConfig) -> list[str]:
    return [f.kind for f in scan.collect(config)]


# --------------------------------------------------------------------------- what counts as a raw process call
@pytest.mark.parametrize("source,expected", [
    ("import subprocess\nsubprocess.run(['x'])\n", ["subprocess.run"]),
    ("import subprocess\nsubprocess.Popen(['x'])\n", ["subprocess.Popen"]),
    ("import subprocess as sp\nsp.check_output(['x'])\n", ["subprocess.check_output"]),
    ("from subprocess import run\nrun(['x'])\n", ["from subprocess import run"]),
    ("from subprocess import Popen as P\nP(['x'])\n", ["from subprocess import Popen"]),
    ("import os\nos.system('x')\n", ["os.system"]),
    ("import os as o\no.popen('x')\n", ["os.popen"]),
    ("import os\nos.execv('/bin/x', ['x'])\n", ["os.execv"]),
    ("import asyncio\nasyncio.create_subprocess_exec('x')\n", ["asyncio.create_subprocess_exec"]),
    # a reference that is not a call is still a way to start a process later
    ("import subprocess\nrunner = subprocess.run\n", ["subprocess.run"]),
    ("import subprocess\ndef f(popen=subprocess.Popen): ...\n", ["subprocess.Popen"]),
])
def test_raw_process_apis_are_found_through_aliases_and_references(tmp_path, source, expected):
    _write(tmp_path, "app/mod.py", source)
    assert _kinds(_config(tmp_path)) == expected


@pytest.mark.parametrize("source", [
    "import subprocess\nsubprocess.CREATE_NO_WINDOW\n",                     # a constant is not a process
    "import subprocess\ntry:\n    pass\nexcept subprocess.TimeoutExpired:\n    pass\n",   # an exception type
    "import os\nos.startfile('x')\nos.getcwd()\nos.path.join('a')\n",       # not process creation
    "def run(x):\n    return x\nrun(1)\n",                                  # an unrelated run()
    "subprocess = object()\nsubprocess.run()\n",                            # not the stdlib module
    "import shlex\nshlex.split('a b')\n",
])
def test_things_that_are_not_process_creation_are_not_findings(tmp_path, source):
    _write(tmp_path, "app/mod.py", source)
    assert _kinds(_config(tmp_path)) == []


def test_findings_carry_a_path_line_and_a_message_that_names_the_fix(tmp_path):
    _write(tmp_path, "app/deep/mod.py", "import subprocess\n\nsubprocess.run(['x'])\n")
    report = scan.scan(_config(tmp_path))
    (finding,) = report.new
    assert (finding.path, finding.line, finding.kind) == ("app/deep/mod.py", 3, "subprocess.run")
    text = scan.format_report(report)
    assert "app/deep/mod.py:3" in text and "CommandCapturer" in text and "BackgroundLauncher" in text


# --------------------------------------------------------------------------- allow / exempt / excluded
def test_the_named_adapter_modules_may_use_raw_apis(tmp_path):
    _write(tmp_path, "app/adapters/spawn.py", "import subprocess\nsubprocess.Popen(['x'])\n")
    _write(tmp_path, "app/adapters_extra/other.py", "import subprocess\nsubprocess.Popen(['x'])\n")
    config = _config(tmp_path, allow=["app.adapters"])
    # "app.adapters" is a package prefix: it must not also swallow the look-alike sibling package
    assert [f.path for f in scan.collect(config)] == ["app/adapters_extra/other.py"]


def test_exempt_roots_are_skipped_and_must_say_why(tmp_path):
    _write(tmp_path, "app/tool/bootstrap.py", "import subprocess\nsubprocess.run(['x'])\n")
    config = _config(tmp_path, exempt=[{"path": "app/tool", "reason": "runs before dependencies exist"}])
    assert scan.collect(config) == ()
    with pytest.raises(scan.ConfigError, match="needs a `reason`"):
        _config(tmp_path, exempt=[{"path": "app/tool"}])
    with pytest.raises(scan.ConfigError, match="needs a `reason`"):
        _config(tmp_path, exempt=[{"path": "app/tool", "reason": "   "}])


def test_excluded_directories_and_unparseable_files_are_not_scanned(tmp_path):
    _write(tmp_path, "app/tests/test_x.py", "import subprocess\nsubprocess.run(['x'])\n")
    _write(tmp_path, "app/broken.py", "def (:\n")
    config = _config(tmp_path, exclude_dirs=["tests"])
    assert scan.collect(config) == ()


def test_a_single_file_can_be_a_root(tmp_path):
    _write(tmp_path, "tool.py", "import subprocess\nsubprocess.run(['x'])\n")
    assert _kinds(_config(tmp_path, roots=["tool.py"])) == ["subprocess.run"]


# --------------------------------------------------------------------------- the shrink-only baseline
def test_a_baselined_finding_passes_a_new_one_fails_and_a_vanished_one_is_stale(tmp_path):
    _write(tmp_path, "app/legacy.py", "import subprocess\nsubprocess.run(['a'])\n")
    config = _config(tmp_path, baseline="baseline.json")
    (tmp_path / "baseline.json").write_text(scan.baseline_text(config), encoding="utf-8")

    assert scan.scan(config).ok

    _write(tmp_path, "app/legacy.py", "import subprocess\nsubprocess.run(['a'])\nsubprocess.run(['b'])\n")
    grown = scan.scan(config)
    assert not grown.ok and [f.line for f in grown.new] == [3]

    _write(tmp_path, "app/legacy.py", "x = 1\n")
    shrunk = scan.scan(config)
    assert not shrunk.ok and shrunk.new == () and any("app/legacy.py::subprocess.run" in s for s in shrunk.stale)


def test_the_baseline_text_is_stable_sorted_json_and_the_scan_writes_nothing(tmp_path):
    _write(tmp_path, "app/b.py", "import subprocess\nsubprocess.run(['a'])\n")
    _write(tmp_path, "app/a.py", "import subprocess\nsubprocess.run(['a'])\n")
    config = _config(tmp_path, baseline="baseline.json")
    data = json.loads(scan.baseline_text(config))
    assert list(data["findings"]) == ["app/a.py::subprocess.run", "app/b.py::subprocess.run"]
    assert not (tmp_path / "baseline.json").exists()


# --------------------------------------------------------------------------- configuration and the CLI
def test_load_config_reads_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(textwrap.dedent('''
        [tool.commandport]
        roots = ["app"]
        allow = ["app.adapters"]
    '''), encoding="utf-8")
    config = scan.load_config(tmp_path)
    assert config.roots == ("app",) and config.allow == ("app.adapters",)


@pytest.mark.parametrize("body", [
    "[tool.other]\nx = 1\n",
    '[tool.commandport]\nroots = []\n',
    '[tool.commandport]\nroots = "app"\n',
    '[tool.commandport]\nroots = ["app"]\nallow = [1]\n',
])
def test_a_missing_or_malformed_config_is_a_clear_error(tmp_path, body):
    (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")
    with pytest.raises(scan.ConfigError):
        scan.load_config(tmp_path)


def test_the_cli_exits_nonzero_on_a_finding_and_zero_when_clean(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text('[tool.commandport]\nroots = ["app"]\n', encoding="utf-8")
    _write(tmp_path, "app/mod.py", "import subprocess\nsubprocess.run(['x'])\n")
    assert scan.main(["--root", str(tmp_path)]) == 1
    assert "raw process call subprocess.run" in capsys.readouterr().err

    _write(tmp_path, "app/mod.py", "x = 1\n")
    assert scan.main(["--root", str(tmp_path)]) == 0
    assert scan.main(["--root", str(tmp_path / "missing")]) == 2


def test_assert_clean_raises_with_the_report(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[tool.commandport]\nroots = ["app"]\n', encoding="utf-8")
    _write(tmp_path, "app/mod.py", "import os\nos.system('x')\n")
    with pytest.raises(AssertionError, match="os.system"):
        scan.assert_clean(tmp_path)


# --------------------------------------------------------------------------- defaults and the fix hint
def test_allow_defaults_to_the_reference_adapters_when_omitted(tmp_path):
    _write(tmp_path, "lifecycle_runner/adapters/spawn.py", "import subprocess\nsubprocess.Popen(['x'])\n")
    _write(tmp_path, "app/mod.py", "import subprocess\nsubprocess.run(['x'])\n")
    config = scan.config_from_table(tmp_path, {"roots": ["app", "lifecycle_runner"]})
    assert config.allow == scan.DEFAULT_ALLOW
    assert [f.path for f in scan.collect(config)] == ["app/mod.py"]


def test_an_explicit_empty_allow_means_nothing_may_use_a_raw_api(tmp_path):
    _write(tmp_path, "lifecycle_runner/adapters/spawn.py", "import subprocess\nsubprocess.Popen(['x'])\n")
    config = scan.config_from_table(tmp_path, {"roots": ["lifecycle_runner"], "allow": []})
    assert [f.path for f in scan.collect(config)] == ["lifecycle_runner/adapters/spawn.py"]


def test_a_projects_own_fix_hint_replaces_the_default_in_the_report(tmp_path):
    _write(tmp_path, "app/mod.py", "import subprocess\nsubprocess.run(['x'])\n")
    config = scan.config_from_table(tmp_path, {"roots": ["app"], "fix_hint": "use myapp.procs.run()"})
    text = scan.format_report(scan.scan(config))
    assert "Fix: use myapp.procs.run()." in text and "lifecycle_runner" not in text
    default = scan.format_report(scan.scan(scan.config_from_table(tmp_path, {"roots": ["app"]})))
    assert "BackgroundLauncher" in default


def test_a_blank_fix_hint_is_a_config_error(tmp_path):
    with pytest.raises(scan.ConfigError, match="fix_hint"):
        scan.config_from_table(tmp_path, {"roots": ["app"], "fix_hint": "  "})
