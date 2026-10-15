"""The use case: for each target, check its condition and start it when it does not hold."""
from __future__ import annotations

from collections.abc import Callable, Iterable

from commandport.domain import ProcessSpec
from commandport.ports import BackgroundLauncher
from ensure_running.domain import Condition, ConditionState, Outcome, Target, TargetResult


class Reconciler:
    """Never raises: every target yields a ``TargetResult``. Callers must read the results (a START_FAILED
    or THROTTLED target is not running). ``history`` maps target name -> start times (unix), the store of
    the restart cap; pass a persistent mapping so the cap survives each scheduled run."""

    def __init__(
        self, launcher: BackgroundLauncher, condition: Condition, *,
        now: Callable[[], float], history: dict[str, list[float]] | None = None, dry_run: bool = False,
    ) -> None:
        self._launcher, self._condition, self._now = launcher, condition, now
        self.history = history if history is not None else {}
        self._dry_run = dry_run

    def reconcile(self, targets: Iterable[Target]) -> list[TargetResult]:
        return [self._one(t) for t in targets]

    def _one(self, t: Target) -> TargetResult:
        try:
            state = self._condition.check(t)
        except Exception as exc:  # noqa: BLE001 -- a broken condition must not start anything
            return TargetResult(t.name, Outcome.UNKNOWN, detail=f"{type(exc).__name__}: {exc}")
        if state is ConditionState.SATISFIED:
            return TargetResult(t.name, Outcome.OK)
        if state is ConditionState.UNKNOWN:
            return TargetResult(t.name, Outcome.UNKNOWN)
        now = self._now()
        recent = [s for s in self.history.get(t.name, []) if now - s < t.window_seconds]
        self.history[t.name] = recent
        if len(recent) >= t.max_starts:
            return TargetResult(t.name, Outcome.THROTTLED, detail=f"{len(recent)} starts in {t.window_seconds:g}s")
        if self._dry_run:
            return TargetResult(t.name, Outcome.DRY_RUN)
        spec = ProcessSpec(t.argv, cwd=t.cwd, log_path=t.log_path, name=t.name)
        launch = self._launcher.launch(spec)
        if launch.started:
            recent.append(now)
            return TargetResult(t.name, Outcome.STARTED, launch)
        if launch.ok:  # ALREADY_RUNNING: the condition lagged the record; nothing to do
            return TargetResult(t.name, Outcome.OK, launch)
        return TargetResult(t.name, Outcome.START_FAILED, launch, launch.error)
