"""``python -m stackrun``: the declarative composition root, on a free port and a short-lived service."""
from __future__ import annotations

import socket
import sys

from stackrun.cli import main


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _toml(tmp_path, command: str, port: int) -> None:
    (tmp_path / "stackrun.toml").write_text(
        f'name = "clitest"\n[[service]]\nname = "s"\nargv = [{sys.executable!r}, "-c", {command!r}]\nport = {port}\n'
        .replace("'", '"').replace("\\", "/"),
        encoding="utf-8",
    )


def test_a_missing_or_invalid_file_is_an_error_not_a_traceback(tmp_path, capsys):
    assert main(["-f", str(tmp_path / "nope.toml")]) == 1
    assert "cannot read" in capsys.readouterr().err
    (tmp_path / "bad.toml").write_text("name = [", encoding="utf-8")
    assert main(["-f", str(tmp_path / "bad.toml")]) == 1
    assert "not valid TOML" in capsys.readouterr().err


def test_status_and_stop_when_nothing_runs(tmp_path, capsys):
    _toml(tmp_path, "pass", _free_port())
    assert main(["-f", str(tmp_path / "stackrun.toml"), "status"]) == 1
    assert "not running" in capsys.readouterr().out
    assert main(["-f", str(tmp_path / "stackrun.toml"), "stop"]) == 1


def test_run_returns_the_exit_code_of_the_service_that_ended(tmp_path):
    _toml(tmp_path, "raise SystemExit(4)", _free_port())
    assert main(["-f", str(tmp_path / "stackrun.toml"), "--no-browser", "run"]) == 4
    assert not (tmp_path / ".stackrun" / "clitest.pid").exists()


def test_run_with_every_port_taken_reports_already_running(tmp_path, capsys):
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        port = holder.getsockname()[1]
        _toml(tmp_path, "pass", port)
        # every declared port is taken, so the CLI treats it as "already running" and reopens (no browser configured)
        assert main(["-f", str(tmp_path / "stackrun.toml"), "--no-browser"]) == 0
    assert "already running" in capsys.readouterr().out
