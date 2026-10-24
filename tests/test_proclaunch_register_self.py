"""``register_self`` must let exactly one live process hold a service name, even when several call it at once.

The race test uses separate processes (a thread test would share one pid, which is "the same holder"). Every
child blocks on a go-file, so the calls overlap as closely as the file system allows, and stays alive afterwards
so the losers see a live holder. Everything is bounded by timeouts; nothing sleeps for a fixed time.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from proclaunch import api
from proclaunch.adapters.json_record_store import JsonFileRecordStore

PROCESSES = 6
ROUNDS = 8
SRC = str(Path(__file__).resolve().parent.parent / "distributions" / "proclaunch" / "src")

CHILD = r"""
import sys, time
from pathlib import Path
from proclaunch import api

root, index, rounds = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
deadline = time.monotonic() + 90


def wait_for(path):
    while not path.exists():
        if time.monotonic() > deadline:
            raise SystemExit("timed out waiting for " + path.name)
        time.sleep(0.001)


for r in range(rounds):
    (root / f"ready-{r}-{index}").write_text("")
    wait_for(root / f"go-{r}")
    won = api.register_self(f"svc{r}", state_dir=root / "state")
    (root / f"result-{r}-{index}").write_text("1" if won else "0")
wait_for(root / "release")
"""


def _wait(predicate, what: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(0.005)


@pytest.mark.timeout(180)
def test_exactly_one_of_several_processes_registering_at_once_wins(tmp_path):
    env = {**os.environ, "PYTHONPATH": SRC + os.pathsep + os.environ.get("PYTHONPATH", "")}
    children = [
        subprocess.Popen([sys.executable, "-c", CHILD, str(tmp_path), str(i), str(ROUNDS)], env=env)
        for i in range(PROCESSES)
    ]
    try:
        winners_per_round = []
        for r in range(ROUNDS):
            _wait(lambda: len(list(tmp_path.glob(f"ready-{r}-*"))) == PROCESSES, f"children ready for round {r}")
            (tmp_path / f"go-{r}").write_text("")
            _wait(lambda: len(list(tmp_path.glob(f"result-{r}-*"))) == PROCESSES, f"results of round {r}")
            winners_per_round.append(sum(p.read_text() == "1" for p in tmp_path.glob(f"result-{r}-*")))
        assert winners_per_round == [1] * ROUNDS, winners_per_round
        # the record names the winner, who is one of the children
        pids = {child.pid for child in children}
        for r in range(ROUNDS):
            record = json.loads((tmp_path / "state" / f"svc{r}.json").read_text(encoding="utf-8"))
            assert record["pid"] in pids
    finally:
        (tmp_path / "release").write_text("")
        for child in children:
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                child.kill()
    assert all(child.returncode == 0 for child in children)


def _write_record(state_dir: Path, name: str, **fields) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    base = {"name": name, "pid": -1, "create_time": -1, "reserved_at": None, "argv": [], "cwd": None, "method": None}
    (state_dir / f"{name}.json").write_text(json.dumps({**base, **fields}), encoding="utf-8")


def test_a_stale_record_is_replaced(tmp_path):
    _write_record(tmp_path, "svc", pid=2**22 + 12345, create_time=1.0, method="self")  # no such process
    assert api.register_self("svc", state_dir=tmp_path) is True
    assert JsonFileRecordStore(tmp_path).load("svc").identity.pid == os.getpid()


def test_registering_twice_from_the_same_process_is_idempotent(tmp_path):
    assert api.register_self("svc", state_dir=tmp_path) is True
    first = JsonFileRecordStore(tmp_path).load("svc")
    assert api.register_self("svc", state_dir=tmp_path) is True
    assert JsonFileRecordStore(tmp_path).load("svc") == first


def test_a_different_live_holder_is_left_alone(tmp_path):
    child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(60)"])
    try:
        import psutil

        _write_record(tmp_path, "svc", pid=child.pid, create_time=psutil.Process(child.pid).create_time())
        before = (tmp_path / "svc.json").read_text(encoding="utf-8")
        assert api.register_self("svc", state_dir=tmp_path) is False
        assert (tmp_path / "svc.json").read_text(encoding="utf-8") == before
    finally:
        child.kill()
        child.wait()


def test_an_unreadable_record_returns_false_and_is_preserved(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "svc.json").write_text("{not json", encoding="utf-8")
    assert api.register_self("svc", state_dir=tmp_path) is False
    assert (tmp_path / "svc.json").read_text(encoding="utf-8") == "{not json"
