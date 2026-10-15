from __future__ import annotations

import pytest

from commandport.domain import LaunchMethod, LaunchResult
from ensure_running import ConditionState, Target
from ensure_running import cli, config
from ensure_running.conditions import ServiceRunning
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


def test_service_running_condition_states(tmp_path):
    t = Target("svc", ("x",))
    cond = ServiceRunning(tmp_path)
    assert cond.check(t) is ConditionState.UNSATISFIED  # no record
    (tmp_path / "svc.json").write_text("not json")
    assert cond.check(t) is ConditionState.UNKNOWN  # unreadable record is never "not running"


def test_cli_run_starts_missing_target_and_reports_exit_code(tmp_path, monkeypatch, capsys):
    cfgfile = tmp_path / "c.toml"
    cfgfile.write_text(toml(tmp_path, '[[target]]\nname="a"\nargv=["x"]'))
    started = []

    class Starter:
        def __init__(self, manager): ...
        def launch(self, spec):
            started.append(spec.name)
            return LaunchResult(LaunchMethod.SPAWNED, pid=42)

    monkeypatch.setattr(cli, "_ServiceStarter", Starter)
    monkeypatch.setattr(cli, "_manager", lambda cfg: None)
    assert cli.main(["run", "--config", str(cfgfile)]) == 0
    assert started == ["a"] and "a: started pid=42" in capsys.readouterr().out
    assert (tmp_path / "state" / "history.json").exists()


def test_cli_dry_run_starts_nothing_and_writes_no_history(tmp_path, monkeypatch):
    cfgfile = tmp_path / "c.toml"
    cfgfile.write_text(toml(tmp_path, '[[target]]\nname="a"\nargv=["x"]'))
    monkeypatch.setattr(cli, "_manager", lambda cfg: None)
    assert cli.main(["run", "--config", str(cfgfile), "--dry-run"]) == 0
    assert not (tmp_path / "state" / "history.json").exists()


def test_cli_bad_config_exits_2(tmp_path, capsys):
    f = tmp_path / "c.toml"
    f.write_text("x = =")
    assert cli.main(["status", "--config", str(f)]) == 2
    assert "config error" in capsys.readouterr().err
