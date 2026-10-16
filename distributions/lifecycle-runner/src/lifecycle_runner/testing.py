"""In-memory implementation of the command ports, for the tests of anything that depends on them.

    from lifecycle_runner.testing import FakeCommandRunner

    fake = FakeCommandRunner().when("agents", stdout='[{"id": "a"}]')
    with lifecycle_runner.api.use_commands(fake):
        ...
    assert fake.argvs() == [("claude", "agents", "--json")]

``FakeCommandRunner`` implements ``CommandRunner`` / ``CommandCapturer`` / ``CommandStreamer``. A command nothing
scripted fails the test loudly instead of returning a made-up success. Pure: nothing here imports a process,
file or network module.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from lifecycle_runner.domain import (
    CaptureResult,
    CaptureSpec,
    RunOutcome,
    RunResult,
    RunSpec,
    StreamSpec,
)

Match = str | Callable[[tuple[str, ...]], bool]


@dataclass
class _Rule:
    match: Match
    outcome: RunOutcome
    returncode: int | None
    stdout: str
    stderr: str
    error: str | None
    lines: list[str] | None
    raises: BaseException | None

    def matches(self, argv: tuple[str, ...]) -> bool:
        if callable(self.match):
            return bool(self.match(argv))
        return self.match in " ".join(argv)


class FakeLineStream:
    """A ``LineStream`` over scripted lines."""

    def __init__(self, rule: _Rule | None, error: str | None = None) -> None:
        self.pid: int | None = None if rule is None else 4242
        self.start_error = error
        self._rule = rule
        self.killed = False
        self.closed = False

    def __iter__(self) -> Iterator[str]:
        if self._rule is None:
            return iter(())
        lines = self._rule.lines if self._rule.lines is not None else self._rule.stdout.splitlines(keepends=True)
        return iter(lines)

    @property
    def returncode(self) -> int | None:
        if self._rule is None or self._rule.outcome is RunOutcome.TIMED_OUT:
            return None
        return self._rule.returncode

    @property
    def timed_out(self) -> bool:
        return self._rule is not None and self._rule.outcome is RunOutcome.TIMED_OUT

    def kill(self) -> None:
        self.killed = True

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeCommandRunner:
    rules: list[_Rule] = field(default_factory=list)
    calls: list[RunSpec | CaptureSpec | StreamSpec] = field(default_factory=list)

    def when(
        self, match: Match, *, returncode: int | None = 0, stdout: str = "", stderr: str = "",
        outcome: RunOutcome = RunOutcome.COMPLETED, error: str | None = None,
        lines: list[str] | None = None, raises: BaseException | None = None,
    ) -> "FakeCommandRunner":
        """Script a command: *match* is a substring of the space-joined argv or a predicate on the argv.
        The first rule that matches wins."""
        self.rules.append(_Rule(match, outcome, returncode, stdout, stderr, error, lines, raises))
        return self

    def timeout(self, match: Match, *, stdout: str = "") -> "FakeCommandRunner":
        return self.when(match, returncode=None, stdout=stdout, outcome=RunOutcome.TIMED_OUT)

    def not_found(self, match: Match, error: str = "FileNotFoundError: executable not found") -> "FakeCommandRunner":
        return self.when(match, returncode=None, outcome=RunOutcome.FAILED_TO_START, error=error)

    def argvs(self) -> list[tuple[str, ...]]:
        return [c.argv for c in self.calls]

    def _rule_for(self, spec) -> _Rule:
        self.calls.append(spec)
        for rule in self.rules:
            if rule.matches(spec.argv):
                if rule.raises is not None:
                    raise rule.raises
                return rule
        raise AssertionError(f"FakeCommandRunner: no rule matches {spec.argv!r}; add fake.when(...)")

    def run(self, spec: RunSpec) -> RunResult:
        rule = self._rule_for(spec)
        return RunResult(rule.outcome, returncode=rule.returncode, error=rule.error, log_path=spec.log_path)

    def capture(self, spec: CaptureSpec) -> CaptureResult:
        rule = self._rule_for(spec)
        return CaptureResult(
            rule.outcome, returncode=rule.returncode, stdout=rule.stdout, stderr=rule.stderr, error=rule.error,
        )

    def stream(self, spec: StreamSpec) -> FakeLineStream:
        rule = self._rule_for(spec)
        if rule.outcome is RunOutcome.FAILED_TO_START:
            return FakeLineStream(None, error=rule.error or "failed to start")
        return FakeLineStream(rule)
