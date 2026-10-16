"""The use case: for each target, ask whether it should run and start it when so."""
from __future__ import annotations

from collections.abc import Callable, Iterable

from ensure_running.domain import (
    Outcome, ServiceSpec, ServiceStarter, ShouldRun, StartOutcome, Target, TargetResult,
)


class Reconciler:
    """Never raises: every target yields a ``TargetResult``. Callers must read the results (a START_FAILED
    or THROTTLED target is not running). ``history`` maps target name -> start times (unix), the store of
    the restart cap; pass a persistent mapping so the cap survives each scheduled run."""

    def __init__(
        self, starter: ServiceStarter, should_run: ShouldRun, *,
        now: Callable[[], float], history: dict[str, list[float]] | None = None, dry_run: bool = False,
    ) -> None:
        self._starter, self._should_run, self._now = starter, should_run, now
        self.history = history if history is not None else {}
        self._dry_run = dry_run

    def reconcile(self, targets: Iterable[Target]) -> list[TargetResult]:
        return [self._one(t) for t in targets]

    def _one(self, t: Target) -> TargetResult:
        try:
            wanted = self._should_run(t)
        except Exception as exc:  # noqa: BLE001 -- a check that cannot tell must not start anything
            return TargetResult(t.name, Outcome.UNKNOWN, detail=f"{type(exc).__name__}: {exc}")
        if wanted is not True:
            return TargetResult(t.name, Outcome.OK)
        now = self._now()
        recent = [s for s in self.history.get(t.name, []) if now - s < t.window_seconds]
        self.history[t.name] = recent
        if len(recent) >= t.max_starts:
            return TargetResult(t.name, Outcome.THROTTLED, detail=f"{len(recent)} starts in {t.window_seconds:g}s")
        if self._dry_run:
            return TargetResult(t.name, Outcome.DRY_RUN)
        result = self._starter.start(ServiceSpec(t.name, t.argv, cwd=t.cwd, log_path=t.log_path))
        if result.outcome is StartOutcome.STARTED:
            recent.append(now)
            return TargetResult(t.name, Outcome.STARTED, result)
        if result.outcome is StartOutcome.ALREADY_RUNNING:  # the condition lagged the record; nothing to do
            return TargetResult(t.name, Outcome.OK, result)
        # IN_PROGRESS and FAILED: nothing is known to be running because of this call
        return TargetResult(t.name, Outcome.START_FAILED, result, result.error)
