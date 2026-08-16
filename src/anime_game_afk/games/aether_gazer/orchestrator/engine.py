"""Generic task-level execution engine.

A small, reusable engine that runs an ordered list of tasks (a "plan")
for a single process. It is deliberately kept separate from any concrete
process so that every process that *composes* tasks shares one execution
model: ordered steps, per-task timeout/retry/wait knobs, optional
conditions and control flow (L2), an optional inter-step callback
(e.g. return-to-hub), and status notification.

This mirrors the MaaFramework / MAG ``interface.json`` convention — a
declarative task registry (id -> metadata) plus an ordered step list,
kept independent of the task implementations themselves (data-driven,
open/closed: adding a task never touches the engine).

The engine depends only on the ``Task`` protocol and ``ProcessContext``,
so it is reused unchanged by any process in this game (and, conceptually,
by any content pack that supplies a registry).

L2 extensions (conditions + control flow)
-----------------------------------------
A plan item is either a :class:`PlanStep` (one task) or a
:class:`PlanGroup` (a named sequence that may repeat). Both may carry:

* ``condition`` — a user condition (``{"type": "reddot", ...}``) evaluated
  by the ``resolve_condition`` callback. When it resolves falsy the item is
  skipped. The callback is game-specific (red dot / OCR / value), supplied
  by the owning process, so the engine itself stays game-agnostic.
* ``on_fail`` — ``"skip"`` (continue, default) or ``"abort"`` (stop the
  whole run on failure).

A :class:`PlanGroup` may additionally repeat its steps ``repeat`` times.
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
    """One task step in a user plan (L1), with optional L2 gates."""

    task_id: str
    enabled: bool = True
    params: TaskParams = field(default_factory=TaskParams)
    condition: dict | None = None     # L2: when-gate; resolved via callback
    on_fail: str = "skip"             # L2: "skip" | "abort"
    actions: list[dict] | None = None  # L3: custom atomic-action sequence

    @classmethod
    def from_dict(cls, data) -> PlanStep:
        if isinstance(data, str):
            return cls(task_id=data, enabled=True)
        return cls(
            task_id=data["id"],
            enabled=bool(data.get("enabled", True)),
            params=TaskParams.from_dict(data.get("params")),
            condition=data.get("condition"),
            on_fail=data.get("on_fail", "skip"),
            actions=data.get("actions"),
        )


@dataclass
class PlanGroup:
    """A named sequence of steps that may repeat (L2 control flow)."""

    steps: list[PlanItem]
    name: str = ""
    repeat: int = 1                   # loop count; 1 = run once
    condition: dict | None = None     # L2: when-gate for the whole group
    on_fail: str = "skip"             # L2: "skip" | "abort"
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> PlanGroup:
        items = [TaskEngine._parse_item(e) for e in data.get("steps", [])]
        return cls(
            steps=items,
            name=data.get("name", ""),
            repeat=int(data.get("repeat", 1) or 1),
            condition=data.get("condition"),
            on_fail=data.get("on_fail", "skip"),
            enabled=bool(data.get("enabled", True)),
        )


# A plan item is either a single task step or a (possibly repeating) group.
PlanItem = PlanStep | PlanGroup


@dataclass
class TaskMeta:
    """Metadata for a registrable task."""

    cls: type
    name: str
    safe: bool


# Hook signatures (annotations only — not evaluated at runtime).
InterStep = Callable[[ProcessContext], Awaitable[None]]
ShouldSkip = Callable[["PlanStep", ProcessContext], "str | None"]
# Condition resolver: given a condition dict + context, return truthiness.
ResolveCondition = Callable[[dict, ProcessContext], Awaitable[bool]]
# Action executor: given an action dict + context, run it; return success.
ActionExecutor = Callable[[dict, ProcessContext], Awaitable[bool]]


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
        resolve_condition: Optional async ``(condition, ctx) -> bool`` invoked
            for each item's ``condition`` gate. Game-specific (red dot / OCR /
            value); when omitted, conditions are ignored (backward compatible).
    """

    def __init__(
        self,
        registry: dict[str, TaskMeta],
        *,
        inter_step: InterStep | None = None,
        should_skip: ShouldSkip | None = None,
        resolve_condition: ResolveCondition | None = None,
        action_executor: ActionExecutor | None = None,
    ) -> None:
        self._registry = registry
        self._inter_step = inter_step
        self._should_skip = should_skip
        self._resolve_condition = resolve_condition
        self._action_executor = action_executor

    # ------------------------------------------------------------------
    # Plan resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_item(data) -> PlanItem:
        """Coerce a raw plan entry into a PlanStep or PlanGroup."""
        if isinstance(data, str):
            return PlanStep(task_id=data, enabled=True)
        if isinstance(data, dict):
            if data.get("type") == "group":
                return PlanGroup.from_dict(data)
            return PlanStep.from_dict(data)
        raise TypeError(f"unsupported plan item: {data!r}")

    def build_plan(self, config: dict[str, Any]) -> list[PlanItem]:
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
            steps = [self._parse_item(e) for e in raw]
            # safe tasks may not be disabled via an explicit user plan
            for step in steps:
                if isinstance(step, PlanStep) and not step.enabled:
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
        return [s for s in steps if self._eligible(s)]

    def _eligible(self, item: PlanItem) -> bool:
        if isinstance(item, PlanGroup):
            return all(self._eligible(s) for s in item.steps)
        # L3 custom atomic steps carry their own actions, not a registry id.
        if getattr(item, "actions", None):
            return True
        return item.task_id in self._registry

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def run(self, ctx: ProcessContext) -> ProcessResult:
        completed: list[str] = []
        failed: list[str] = []
        routine_t0 = time.monotonic()
        plan = self.build_plan(ctx.config)
        total = len(plan)

        aborted = False
        for i, item in enumerate(plan):
            ctx.logger.info(f"--- step {i+1}/{total} ---")
            if await self._run_item(item, ctx, completed, failed) == "abort":
                aborted = True
                ctx.logger.warning("engine aborted by on_fail=abort")
                break

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
            status="success" if not failed and not aborted else "failed",
            message=(
                f"{len(completed)} done, {len(failed)} failed: "
                f"{', '.join(failed)}"
                if failed
                else f"{len(completed)} tasks completed"
            ),
            data={"completed": completed, "failed": failed, "aborted": aborted},
        )

    async def _run_item(
        self,
        item: PlanItem,
        ctx: ProcessContext,
        completed: list[str],
        failed: list[str],
    ) -> str | None:
        """Execute one plan item (step or group). Return "abort" to halt run.

        Handles the shared L2 gates (enabled / condition) before delegating
        to the concrete task runner or recursing into a group.
        """
        # ---- shared gates ----
        if not item.enabled:
            return None
        if getattr(item, "condition", None):
            if not await self._resolve(item.condition, ctx, item):
                label = getattr(item, "task_id", None) or getattr(
                    item, "name", "group"
                )
                ctx.notify_task(label, "skipped", "condition not met")
                ctx.logger.info(f"  {label}: skipped (condition not met)")
                return None

        # ---- group: recurse, optionally repeating ----
        if isinstance(item, PlanGroup):
            for _ in range(max(1, item.repeat)):
                for sub in item.steps:
                    if (
                        await self._run_item(sub, ctx, completed, failed)
                        == "abort"
                    ):
                        return "abort"
            return None

        # ---- single task step ----
        return await self._run_step(item, ctx, completed, failed)

    async def _resolve(
        self, condition: dict, ctx: ProcessContext, item: PlanItem
    ) -> bool:
        """Evaluate a condition via the (optional) resolver callback."""
        if self._resolve_condition is None:
            return True  # no resolver wired -> conditions are no-ops (compat)
        try:
            return bool(await self._resolve_condition(condition, ctx))
        except Exception as exc:  # resolver bug must not crash the run
            label = getattr(item, "task_id", None) or getattr(item, "name", "?")
            ctx.logger.warning(
                f"  condition for {label} errored ({exc}); treating as unmet"
            )
            return False

    async def _run_step(
        self,
        step: PlanStep,
        ctx: ProcessContext,
        completed: list[str],
        failed: list[str],
    ) -> str | None:
        # L3: a custom atomic-action sequence runs instead of a built-in task.
        if step.actions:
            return await self._run_actions(step, ctx, completed, failed)
        task_id = step.task_id
        cls = self._registry[task_id].cls

        reason = self._should_skip(step, ctx) if self._should_skip else None
        if reason:
            ctx.notify_task(task_id, "skipped", reason)
            ctx.logger.info(f"  {task_id}: skipped ({reason})")
            if self._inter_step:
                await self._inter_step(ctx)
            return None

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
                    if step.on_fail == "abort":
                        return "abort"
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
            if step.on_fail == "abort":
                return "abort"

        if step.params.wait_after:
            await asyncio.sleep(step.params.wait_after)

        # Return to hub (or any inter-step hook) between tasks.
        if self._inter_step:
            await self._inter_step(ctx)
        return None

    async def _run_actions(
        self,
        step: PlanStep,
        ctx: ProcessContext,
        completed: list[str],
        failed: list[str],
    ) -> str | None:
        """Run a custom L3 atomic-action sequence (no built-in task lookup).

        Each action is delegated to the wired ``action_executor`` callback and
        is expected to return a truthy value when satisfied. A ``*_wait``
        action returns falsy on timeout. The first falsy result stops the
        sequence early; whether that aborts the whole run depends on the
        step's ``on_fail`` policy.
        """
        label = step.task_id
        ctx.notify_task(label, "running")
        ctx.logger.info(
            f"  {label}: running {len(step.actions)} custom action(s)"
        )
        ok = True
        for act in step.actions:
            if self._action_executor is None:
                ctx.logger.warning(
                    f"  {label}: no action_executor wired; skipping {act}"
                )
                continue
            try:
                act_ok = bool(await self._action_executor(act, ctx))
            except Exception as exc:  # a bad action must not crash the run
                ctx.logger.warning(f"  {label}: action {act} errored: {exc}")
                act_ok = False
            if not act_ok:
                ok = False
                break
        if ok:
            completed.append(label)
            ctx.notify_task(label, "success")
            ctx.logger.info(f"  {label}: custom actions done")
        else:
            failed.append(label)
            ctx.notify_task(label, "failed", "action not satisfied")
            ctx.logger.warning(f"  {label}: custom action failed")
            if step.on_fail == "abort":
                return "abort"
        if self._inter_step:
            await self._inter_step(ctx)
        return None

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
