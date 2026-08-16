"""Generic task-level execution engine.

A small, reusable engine that runs an ordered list of tasks (a "plan")
for a single process. It is deliberately kept separate from any concrete
process so that every process that *composes* tasks shares one execution
model: ordered steps, per-task timeout/retry/wait knobs, an optional
inter-step callback (e.g. return-to-hub), and status notification.

This mirrors the MaaFramework / MAG ``interface.json`` convention — a
declarative task registry (id -> metadata) plus an ordered step list,
kept independent of the task implementations themselves (data-driven,
open/closed: adding a task never touches the engine).

The engine depends only on the ``Task`` protocol and ``ProcessContext``,
so it is reused unchanged by any process in this game (and, conceptually,
by any content pack that supplies a registry).
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from anime_game_afk.games.aether_gazer.processes.base import (
    ProcessContext,
    ProcessResult,
)
from anime_game_afk.games.aether_gazer.tasks.base import TaskResult


@dataclass
class TaskParams:
    """Per-task tuning knobs exposed to the user (L1 orchestration)."""

    timeout: float | None = None      # max seconds for a single execute()
    retry: int = 0                    # extra execute() attempts on failure
    wait_before: float = 0.0          # seconds to sleep before can_run/execute
    wait_after: float = 0.0           # seconds to sleep after execute

    @classmethod
    def from_dict(cls, data: dict | None) -> TaskParams:
        data = data or {}
        timeout = data.get("timeout")
        return cls(
            timeout=float(timeout) if timeout is not None else None,
            retry=int(data.get("retry", 0) or 0),
            wait_before=float(data.get("wait_before", 0) or 0),
            wait_after=float(data.get("wait_after", 0) or 0),
        )


@dataclass
class PlanStep:
    """One step in a user plan."""

    task_id: str
    enabled: bool = True
    params: TaskParams = field(default_factory=TaskParams)

    @classmethod
    def from_dict(cls, data) -> PlanStep:
        if isinstance(data, str):
            return cls(task_id=data, enabled=True)
        return cls(
            task_id=data["id"],
            enabled=bool(data.get("enabled", True)),
            params=TaskParams.from_dict(data.get("params")),
        )


@dataclass
class TaskMeta:
    """Metadata for a registrable task."""

    cls: type
    name: str
    safe: bool


# Hook signatures (annotations only — not evaluated at runtime).
InterStep = Callable[[ProcessContext], Awaitable[None]]
ShouldSkip = Callable[["PlanStep", ProcessContext], "str | None"]


class TaskEngine:
    """Generic engine that runs an ordered plan of tasks for one process.

    Args:
        registry: Mapping ``task_id -> TaskMeta``. Only ids present here are
            eligible to run; unknown plan ids are dropped.
        inter_step: Optional coroutine called *between* tasks (and after a
            skip caused by ``should_skip``). Used, for example, to return to
            the hub after each task. Receives the ``ProcessContext``.
        should_skip: Optional predicate ``(step, ctx) -> reason | None``.
            When it returns a truthy reason the step is skipped (with that
            reason in the status message) instead of being executed.
    """

    def __init__(
        self,
        registry: dict[str, TaskMeta],
        *,
        inter_step: InterStep | None = None,
        should_skip: ShouldSkip | None = None,
    ) -> None:
        self._registry = registry
        self._inter_step = inter_step
        self._should_skip = should_skip

    # ------------------------------------------------------------------
    # Plan resolution
    # ------------------------------------------------------------------

    def build_plan(self, config: dict[str, Any]) -> list[PlanStep]:
        """Resolve the ordered, enabled plan for this run.

        Priority: explicit ``config["plan"]`` (ordered step list) >
        legacy ``config["enabled_tasks"]`` set (default order) >
        all registered tasks enabled (default order).

        Unknown task ids are always dropped. On the explicit-plan path,
        ``safe`` tasks are forced enabled so a user/bug can never silently
        disable a task that spends in-game currency or resources. The
        legacy ``enabled_tasks`` whitelist path is left strict (no forcing)
        to preserve its exact backward-compatible meaning.
        """
        raw = config.get("plan")
        if raw:
            steps = [PlanStep.from_dict(e) for e in raw]
            # safe tasks may not be disabled via an explicit user plan
            for step in steps:
                meta = self._registry.get(step.task_id)
                if meta is not None and meta.safe and not step.enabled:
                    step.enabled = True
        elif "enabled_tasks" in config:
            enabled = set(config["enabled_tasks"])
            steps = [
                PlanStep(tid, enabled=(tid in enabled))
                for tid in self._registry
            ]
        else:
            steps = [PlanStep(tid) for tid in self._registry]

        # Drop unknown task ids (defensive — a stale config should not crash)
        return [s for s in steps if s.task_id in self._registry]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def run(self, ctx: ProcessContext) -> ProcessResult:
        completed: list[str] = []
        failed: list[str] = []
        routine_t0 = time.monotonic()
        plan = self.build_plan(ctx.config)
        total = len(plan)

        for i, step in enumerate(plan):
            task_id = step.task_id
            cls = self._registry[task_id].cls

            if not step.enabled:
                ctx.notify_task(task_id, "skipped", "disabled by user")
                ctx.logger.info(f"  {task_id}: skipped (disabled)")
                continue

            reason = self._should_skip(step, ctx) if self._should_skip else None
            if reason:
                ctx.notify_task(task_id, "skipped", reason)
                ctx.logger.info(f"  {task_id}: skipped ({reason})")
                if self._inter_step:
                    await self._inter_step(ctx)
                continue

            ctx.logger.info(f"--- task {i+1}/{total} — {task_id} ---")
            ctx.notify_task(task_id, "running")
            task_t0 = time.monotonic()
            try:
                if step.params.wait_before:
                    await asyncio.sleep(step.params.wait_before)

                task = cls()
                if await task.can_run(ctx):
                    result = await self._run_task(task, ctx, step.params)
                    elapsed = time.monotonic() - task_t0
                    if result.status == "success":
                        summary = self._summarize(task_id, result)
                        completed.append(summary)
                        ctx.notify_task(task_id, "success", result.message)
                        ctx.logger.info(
                            f"  {task_id}: success ({elapsed:.1f}s)"
                        )
                    elif result.status == "skipped":
                        completed.append(f"{task_id}(skipped)")
                        ctx.notify_task(task_id, "skipped", result.message)
                        ctx.logger.info(
                            f"  {task_id}: skipped — {result.message} "
                            f"({elapsed:.1f}s)"
                        )
                    else:
                        failed.append(task_id)
                        ctx.notify_task(task_id, "failed", result.message)
                        ctx.logger.warning(
                            f"  {task_id}: {result.status} — {result.message} "
                            f"({elapsed:.1f}s)"
                        )
                else:
                    elapsed = time.monotonic() - task_t0
                    ctx.notify_task(task_id, "skipped", "can_run=False")
                    ctx.logger.info(
                        f"  {task_id}: can_run=False, skipping "
                        f"({elapsed:.1f}s)"
                    )
            except Exception as exc:
                elapsed = time.monotonic() - task_t0
                failed.append(task_id)
                ctx.notify_task(task_id, "failed", str(exc))
                ctx.logger.error(
                    f"  {task_id}: crashed — {exc} ({elapsed:.1f}s)"
                )

            if step.params.wait_after:
                await asyncio.sleep(step.params.wait_after)

            # Return to hub (or any inter-step hook) between tasks.
            if self._inter_step:
                await self._inter_step(ctx)

        total_elapsed = time.monotonic() - routine_t0
        ctx.logger.info(
            f"=== engine complete "
            f"({len(completed)} done, {len(failed)} failed) "
            f"in {total_elapsed:.1f}s ===\n"
            f"  completed={completed}\n"
            f"  failed={failed}"
        )
        # Surface partial failure: hardcoding "success" here hid real
        # breakage during debugging (the pipeline would log "1/1 succeeded"
        # while tasks silently failed).
        return ProcessResult(
            status="success" if not failed else "failed",
            message=(
                f"{len(completed)} done, {len(failed)} failed: "
                f"{', '.join(failed)}"
                if failed
                else f"{len(completed)} tasks completed"
            ),
            data={"completed": completed, "failed": failed},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _summarize(task_id: str, result: TaskResult) -> str:
        """Build the completed-summary label, appending a count when present."""
        if result.data:
            for key in ("purchased", "claimed", "count"):
                if key in result.data:
                    return f"{task_id}({result.data[key]})"
        return task_id

    async def _run_task(
        self, task, ctx: ProcessContext, params: TaskParams
    ) -> TaskResult:
        """Execute one task, applying the retry/timeout knobs from params.

        ``retry`` re-runs execute() on a non-success result; ``timeout``
        bounds a single execute() with asyncio.wait_for. These are pure
        orchestration concerns and never touch the task implementation.
        """
        attempts = 1 + max(0, params.retry)
        last: TaskResult | None = None
        for attempt in range(attempts):
            coro = task.execute(ctx)
            if params.timeout:
                coro = asyncio.wait_for(coro, params.timeout)
            try:
                result = await coro
            except TimeoutError:
                result = TaskResult(
                    status="failed",
                    message=f"任务超时 ({params.timeout}s)",
                )
            if result.status == "success":
                return result
            last = result
            if attempt < attempts - 1:
                ctx.logger.warning(
                    f"  {getattr(task, 'name', 'task')}: attempt {attempt+1} "
                    f"failed ({result.status}), retrying..."
                )
                await asyncio.sleep(1.0)
        return last if last is not None else TaskResult(
            status="failed", message="no attempts executed"
        )
