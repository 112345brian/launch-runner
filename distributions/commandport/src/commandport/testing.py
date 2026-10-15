"""In-memory fakes for the launch ports (still defined here until they move).

``FakeCommandRunner`` / ``FakeLineStream`` live in ``lifecycle_runner.testing`` now; their old names are
forwarded.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from commandport._moved import forward
from commandport.domain import EndResult, LaunchMethod, LaunchResult, ProcessSpec


@dataclass
class FakeLauncher:
    """Records every ``ProcessSpec`` it is asked to launch; ``result`` is what every launch reports."""

    result: LaunchResult = field(default_factory=lambda: LaunchResult(LaunchMethod.SPAWNED, pid=4242))
    specs: list[ProcessSpec] = field(default_factory=list)

    def launch(self, spec: ProcessSpec) -> LaunchResult:
        self.specs.append(spec)
        return self.result

    def argvs(self) -> list[tuple[str, ...]]:
        return [s.argv for s in self.specs]

    @classmethod
    def failing(cls, error: str = "FileNotFoundError: executable not found") -> "FakeLauncher":
        return cls(result=LaunchResult(LaunchMethod.FAILED, error=error))


@dataclass
class FakeSupervisor:
    task_name: str
    owner: "FakeSupervisors"

    def available(self) -> bool:
        return self.owner.available

    def start(self, spec: ProcessSpec) -> int | None:
        self.owner.started.append(self.task_name)
        return None

    def end(self) -> EndResult:
        if not self.owner.available:
            return EndResult(ended=False, skipped=True)
        self.owner.ended.append(self.task_name)
        return self.owner.end_result


@dataclass
class FakeSupervisors:
    """A ``task_name -> Supervisor`` factory. ``available=False`` models a platform with no supervisor."""

    available: bool = True
    end_result: EndResult = field(default_factory=lambda: EndResult(ended=True))
    started: list[str] = field(default_factory=list)
    ended: list[str] = field(default_factory=list)

    def __call__(self, task_name: str) -> FakeSupervisor:
        return FakeSupervisor(task_name, self)


forward(
    globals(),
    {name: "lifecycle_runner.testing" for name in ("FakeCommandRunner", "FakeLineStream")},
    {"lifecycle_runner": "lifecycle-runner"},
)
