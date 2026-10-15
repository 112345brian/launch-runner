from __future__ import annotations

import pytest

from ensure_running.domain import StartOutcome, StartResult
import sys

from ensure_running import Target
from ensure_running import api, cli, config
from ensure_running.conditions import CheckFailed, CommandCheck, service_not_running
from ensure_running.lifecycle_check import LifecycleCheckRunner
from ensure_running.config import ConfigError


def toml(tmp_path, body=""):
    return f'state_dir = "{tmp_path}/state"\n{body}'


def test_parse_command_string_argv_defaults_and_log_path(tmp_path):
    cfg = config.parse(toml(tmp_path, f"""
[defaults]
max_starts = 3
[[target]]
name = "notes"
cwd = "{tmp_path}"
command = "claude remote-control --name 'my notes'"
[[target]]
name = "b"
argv = ["echo", "hi"]
max_starts = 1
"""))
    a, b = cfg.targets
    assert a.argv == ("claude", "remote-control", "--name", "my notes") and a.max_starts == 3
    assert a.log_path == tmp_path / "state" / "logs" / "notes.log" and b.max_starts == 1 and cfg.pty


@pytest.mark.parametrize("body, fragment", [
    ("", "at least one"),
    ('[[target]]\nname="a"', "exactly one of argv or command"),
    ('[[target]]\nname="a"\nargv=["x"]\ncommand="y"', "exactly one of argv or command"),
    ('[[target]]\nname="a/b"\nargv=["x"]', "name must match"),
    ('[[target]]\nname="a"\nargv=["x"]\n[[target]]\nname="a"\nargv=["y"]', "duplicate"),
    ('[[target]]\nname="a"\nargv=[]', "non-empty list"),
    ('[[target]]\nname="a"\nargv=["x"]\ncwd="/definitely/not/here"', "not a directory"),
    ('[[target]]\nname="a"\nargv=["x"]\nmax_starts=0', "max_starts"),
    ('[[target]]\nname="a"\nargv=["x"]\nbogus=1', "unknown key"),
    ('bogus=1\n[[target]]\nname="a"\nargv=["x"]', "unknown key"),
    ("this is = = not toml", "not valid TOML"),
])
def test_invalid_config_names_the_problem(tmp_path, body, fragment):
    with pytest.raises(ConfigError, match=fragment):
        config.parse(toml(tmp_path, body))


def test_load_missing_file_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        config.load(tmp_path / "nope.toml")


def test_default_check_starts_only_a_target_without_a_live_record(tmp_path):
    t = Target("svc", ("x",))
    should_run = service_not_running(tmp_path)
    assert should_run(t) is True  # no record
    (tmp_path / "svc.json").write_text("not json")
    with pytest.raises(CheckFailed):  # an unreadable record is never "not running"
        should_run(t)


@pytest.mark.parametrize("code, expected", [(0, True), (1, False)])
def test_command_check_exit_code_is_the_answer(code, expected):
    t = Target("a", ("x",), check=(sys.executable, "-c", f"raise SystemExit({code})"))
    assert CommandCheck(LifecycleCheckRunner())(t) is expected


@pytest.mark.parametrize("check", [
    (sys.executable, "-c", "raise SystemExit(2)"),
    ("/definitely/not/a/command",),
    (sys.executable, "-c", "import time; time.sleep(5)"),
])
def test_command_check_that_cannot_tell_raises(check):
    with pytest.raises(CheckFailed):
        CommandCheck(LifecycleCheckRunner(), timeout_seconds=0.5)(Target("a", ("x",), check=check))


def test_parse_check_as_string_or_list(tmp_path):
    cfg = config.parse(toml(tmp_path, """
[[target]]
name = "a"
argv = ["x"]
check = "./wanted.sh --quiet"
[[target]]
name = "b"
argv = ["x"]
check = ["python", "-c", "pass"]
"""))
    assert cfg.targets[0].check == ("./wanted.sh", "--quiet") and cfg.targets[1].check[0] == "python"
    with pytest.raises(ConfigError, match="check must be a string or a list"):
        config.parse(toml(tmp_path, '[[target]]\nname="a"\nargv=["x"]\ncheck=3'))


def test_cli_run_uses_a_targets_own_check(tmp_path, monkeypatch, capsys):
    f = tmp_path / "c.toml"
    f.write_text(toml(tmp_path, f'''
[[target]]
name = "no"
argv = ["x"]
check = ["{sys.executable}", "-c", "raise SystemExit(1)"]
[[target]]
name = "unknown"
argv = ["x"]
check = ["{sys.executable}", "-c", "raise SystemExit(7)"]
'''))
    monkeypatch.setattr(api, "_manager", lambda cfg: None)
    assert cli.main(["run", "--config", str(f)]) == 1  # unknown is not healthy
    out = capsys.readouterr().out
    assert "no: ok" in out and "unknown: unknown" in out


def test_cli_run_starts_missing_target_and_reports_exit_code(tmp_path, monkeypatch, capsys):
    cfgfile = tmp_path / "c.toml"
    cfgfile.write_text(toml(tmp_path, '[[target]]\nname="a"\nargv=["x"]'))
    started = []

    class Starter:
        def __init__(self, manager): ...
        def start(self, spec):
            started.append(spec.name)
            return StartResult(StartOutcome.STARTED, pid=42)

    monkeypatch.setattr(api, "_ServiceStarter", Starter)
    monkeypatch.setattr(api, "_manager", lambda cfg: None)
    assert cli.main(["run", "--config", str(cfgfile)]) == 0
    assert started == ["a"] and "a: started pid=42" in capsys.readouterr().out
    assert (tmp_path / "state" / "history.json").exists()


def test_cli_dry_run_starts_nothing_and_writes_no_history(tmp_path, monkeypatch):
    cfgfile = tmp_path / "c.toml"
    cfgfile.write_text(toml(tmp_path, '[[target]]\nname="a"\nargv=["x"]'))
    monkeypatch.setattr(api, "_manager", lambda cfg: None)
    assert cli.main(["run", "--config", str(cfgfile), "--dry-run"]) == 0
    assert not (tmp_path / "state" / "history.json").exists()


def test_cli_bad_config_exits_2(tmp_path, capsys):
    f = tmp_path / "c.toml"
    f.write_text("x = =")
    assert cli.main(["status", "--config", str(f)]) == 2
    assert "config error" in capsys.readouterr().err


def test_run_once_is_callable_without_the_command_line(tmp_path):
    cfg = config.parse(toml(tmp_path, '[[target]]\nname="a"\nargv=["x"]\n[[target]]\nname="b"\nargv=["y"]'))
    started = []

    class Starter:
        def start(self, spec):
            started.append(spec.name)
            return StartResult(StartOutcome.STARTED, pid=len(started))

    ticks = iter([1000.0, 1000.0, 1000.0, 1000.0])
    results = api.run_once(cfg, starter=Starter(), should_run=lambda t: t.name == "a", now=lambda: next(ticks))
    assert [(r.target, r.outcome.value) for r in results] == [("a", "started"), ("b", "ok")]
    assert started == ["a"]
    history = (cfg.state_dir / "history.json").read_text()
    assert '"a": [1000.0]' in history


def test_run_once_dry_run_starts_and_records_nothing(tmp_path):
    cfg = config.parse(toml(tmp_path, '[[target]]\nname="a"\nargv=["x"]'))

    class Starter:
        def start(self, spec):
            raise AssertionError("a dry run must not start anything")

    results = api.run_once(cfg, starter=Starter(), should_run=lambda t: True, dry_run=True)
    assert [r.outcome.value for r in results] == ["dry_run"]
    assert not (cfg.state_dir / "history.json").exists()
