"""The DeepInterview-shaped example builds the old plan(), without importing DeepInterview, and runs on fakes."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from stackrun.domain import StackrunError
from stackrun.launcher import Launcher
from stackrun.testing import FakeConfig, FakeConsole, FakeHook, FakePorts, FakeResolver, FakeRunner

EXAMPLE = Path(__file__).resolve().parent.parent / "distributions" / "stackrun" / "examples" / "deepinterview_shape.py"


@pytest.fixture(scope="module")
def example():
    spec = importlib.util.spec_from_file_location("deepinterview_shape", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["deepinterview_shape"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("deepinterview_shape", None)


def test_the_example_does_not_import_deepinterview():
    import ast

    tops = {
        (n.module or "").split(".")[0] if isinstance(n, ast.ImportFrom) else a.name.split(".")[0]
        for n in ast.walk(ast.parse(EXAMPLE.read_text(encoding="utf-8")))
        if isinstance(n, (ast.Import, ast.ImportFrom)) for a in (getattr(n, "names", None) or [None])
    }
    assert not tops & {"launcher", "bootstrap", "deepinterview", "deepinterview_agent", "proclaunch"}


def names(stack):
    return [s.name for s in stack.services]


def test_plan_shapes_match_the_old_launcher(example):
    assert names(example.build_stack({}, with_voice=False)) == ["api", "web"]
    assert names(example.build_stack({}, with_voice=True)) == ["api", "web", "worker"]
    config = {"TTS_SERVER_CMD": "tts-cmd --port 1", "LIVEKIT_SERVER_CMD": "lk --dev", "STT_SERVER_CMD": "   "}
    stack = example.build_stack(config)
    assert names(stack) == ["api", "web", "worker", "livekit", "tts"]
    assert {s.name: s.port for s in stack.services} == {"api": 8000, "web": 3000, "worker": None, "livekit": 7880, "tts": 1}
    assert example.build_stack({"WORKER_LOG_LEVEL": "debug"}).services[2].argv[-2:] == ("--log-level", "debug")
    assert "--log-level" not in example.build_stack({"WORKER_LOG_LEVEL": " "}).services[2].argv
    assert stack.services[0].argv[:4] == ("uv", "run", "--project", "apps/agent")


@pytest.mark.parametrize("cmd", ["x --port", "x --port abc", "x"])
def test_a_missing_or_malformed_port_flag_leaves_the_port_unknown(example, cmd):
    stack = example.build_stack({"STT_SERVER_CMD": cmd})
    assert next(s for s in stack.services if s.name == "stt").port is None


def test_dotenv_config_needs_the_file_and_the_environment_wins(example, tmp_path):
    with pytest.raises(StackrunError, match=".env missing"):
        example.DotenvConfig(tmp_path, {}).environment()
    (tmp_path / ".env").write_text("A=file\nB=file\nexport C='q'\n", encoding="utf-8")
    env = example.DotenvConfig(tmp_path, {"B": "process", "VIRTUAL_ENV": "/x"}).environment()
    assert env == {"A": "file", "B": "process", "C": "q"}


def test_the_hook_publishes_the_web_env(example, tmp_path):
    (tmp_path / "apps" / "web").mkdir(parents=True)
    (tmp_path / ".env").write_text("A=1\n", encoding="utf-8")
    example.PublishWebEnv(tmp_path).before_start(example.build_stack({}))
    assert (tmp_path / "apps" / "web" / ".env.local").read_text(encoding="utf-8") == "A=1\n"


def test_the_example_stack_runs_through_the_core_with_fakes(example):
    stack = example.build_stack({}, with_voice=False)
    runner, hook, console = FakeRunner(exits={"uv": 0}), FakeHook(), FakeConsole()
    launcher = Launcher(stack, runner, FakeResolver(), FakeConfig({"K": "v"}), console, lambda s: None,
                        open_url=example.START_URL, hook=hook)
    assert launcher.run() == 0
    assert [a[0] for a, _ in runner.started] == ["/resolved/uv", "/resolved/npx"] and hook.seen == [stack]
    busy = Launcher(stack, FakeRunner(), FakeResolver(), FakeConfig({}), console, lambda s: None,
                    ports=FakePorts({3000: "node (pid 4242)"}))
    with pytest.raises(StackrunError, match="web: port 3000 is used by node"):
        busy.run()
