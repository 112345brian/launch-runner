"""The old ``commandport`` import paths keep working for names that moved to the providers.

What is pinned: the forwarded name is the provider's own class (identity, ``isinstance``, pickles under the old
path), ``commandport`` stays importable and dependency-free without the providers, and a missing provider is an
``ImportError`` that says what to install. ``commandport`` itself never imports a provider at import time.
"""
from __future__ import annotations

import os
import pickle
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DISTS = ROOT / "distributions"

# (old module, providing module) -> names that moved
MOVED = {
    ("commandport.domain", "lifecycle_runner.domain"):
        ["RunSpec", "RunOutcome", "RunResult", "CaptureSpec", "CaptureResult", "StreamSpec"],
    ("commandport.ports", "lifecycle_runner.ports"):
        ["LineStream", "CommandCapturer", "CommandStreamer", "CommandRunner"],
    ("commandport.testing", "lifecycle_runner.testing"): ["FakeCommandRunner", "FakeLineStream"],
    ("commandport.domain", "proclaunch.domain"): ["ProcessSpec", "LaunchMethod", "LaunchResult", "EndResult"],
    ("commandport.ports", "proclaunch.ports"): ["BackgroundLauncher", "Supervisor"],
    ("commandport.testing", "proclaunch.testing"): ["FakeLauncher", "FakeSupervisor", "FakeSupervisors"],
}


@pytest.mark.parametrize(("old_module", "new_module"), sorted(MOVED))
def test_a_forwarded_name_is_the_providers_own_object(old_module, new_module):
    import importlib

    old, new = importlib.import_module(old_module), importlib.import_module(new_module)
    for name in MOVED[(old_module, new_module)]:
        assert getattr(old, name) is getattr(new, name), name
        assert name in dir(old)


def test_isinstance_and_pickles_agree_across_the_old_and_new_path():
    from commandport.domain import RunSpec as Old
    from lifecycle_runner.domain import RunSpec as New

    assert Old is New and isinstance(New(("a",)), Old)
    assert Old.__module__ == "lifecycle_runner.domain"
    spec = New(("a", "b"), timeout_seconds=3)
    assert pickle.loads(pickle.dumps(spec)) == spec
    Old.__module__ = "commandport.domain"  # a pickle written when the class lived there
    try:
        legacy = pickle.dumps(spec)
    finally:
        Old.__module__ = "lifecycle_runner.domain"
    assert pickle.loads(legacy) == spec and type(pickle.loads(legacy)) is New


def test_launch_types_forward_too_and_a_result_made_through_either_path_is_the_same_type():
    from commandport.domain import LaunchMethod as OldMethod
    from commandport.domain import LaunchResult as OldResult
    from proclaunch.domain import LaunchMethod, LaunchResult

    assert OldResult is LaunchResult and OldMethod is LaunchMethod
    assert OldResult(OldMethod.SPAWNED, pid=1).started


def test_an_unknown_name_is_an_attribute_error():
    import commandport.domain as old

    with pytest.raises(AttributeError):
        old.NoSuchThing  # noqa: B018


def _run(code: str, *dists: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(str(DISTS / d / "src") for d in dists)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, env=env,
                          cwd=str(ROOT))


def test_commandport_imports_without_any_provider_and_names_the_missing_one():
    code = (
        "import importlib.abc, sys\n"
        "class Absent(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, name, path, target=None):\n"
        "        if name.split('.')[0] in ('lifecycle_runner', 'proclaunch'):\n"
        "            raise ModuleNotFoundError('No module named ' + repr(name), name=name.split('.')[0])\n"
        "sys.meta_path.insert(0, Absent())\n"
        "import commandport, commandport.domain as d, commandport.ports, commandport.testing\n"
        "assert not any(m.split('.')[0] in ('lifecycle_runner', 'proclaunch') for m in sys.modules)\n"
        "try:\n"
        "    d.RunSpec\n"
        "except ImportError as exc:\n"
        "    assert 'lifecycle-runner' in str(exc), exc\n"
        "try:\n"
        "    d.ProcessSpec\n"
        "except ImportError as exc:\n"
        "    assert \"'proclaunch'\" in str(exc), exc\n"
        "    print('named')\n"
    )
    ran = _run(code, "commandport")
    assert ran.returncode == 0 and "named" in ran.stdout, ran.stderr or ran.stdout
