"""Daily routine process.

Runs all daily tasks in sequence. Each task is wrapped in try/except
so one failure doesn't block the rest. Returns to hub between tasks.

Task order:
1. 领取所有邮件 — Collect all mail
2. 购买情报碎片 — Buy intel shards from daily shop
3. 领取吨吨值福利包 — Claim daily stamina packs
4. 领取商店免费体力 — Claim free stamina from shop supply
5. 弥弥观测站 — Collect rewards + shorten return
6. 公会矩阵补给 — Guild supply claim
7. 游园街日常管理 — Amusement street daily
8. 联防协议扫荡 — Joint Defense sweep (震动)
9. 联合特勤 — Joint Special Ops sweep (S级)
10. 介质攫取 — Medium Seizure combat + reward claim
11. 每日/周常任务领取 — Daily + weekly mission rewards
12. 对策协议任务领取 — Tactics Protocol task rewards
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from anime_game_afk.games.aether_gazer.processes.base import (
    ProcessContext,
    ProcessResult,
)
from anime_game_afk.games.aether_gazer.tasks.activity_tasks import (
    JointDefenseSweep,
)
from anime_game_afk.games.aether_gazer.tasks.amusement_tasks import (
    AmusementStreetDaily,
)
from anime_game_afk.games.aether_gazer.tasks.base import TaskResult
from anime_game_afk.games.aether_gazer.tasks.guild_tasks import GuildSupplyClaim
from anime_game_afk.games.aether_gazer.tasks.keyin_tasks import (
    JointSpecialOpsSweep,
    MediumSeizureCombat,
)
from anime_game_afk.games.aether_gazer.tasks.mail_tasks import CollectAllMail
from anime_game_afk.games.aether_gazer.tasks.navigation_tasks import ReturnToHub
from anime_game_afk.games.aether_gazer.tasks.observation_tasks import (
    DailyWeeklyMissionClaim,
    MimiStationCollect,
    TacticsTaskClaim,
)
from anime_game_afk.games.aether_gazer.tasks.shop_tasks import (
    BuyIntelShards,
    ClaimDailyStaminaPacks,
    ClaimFreeStamina,
)
from anime_game_afk.games.aether_gazer.tasks.startup_tasks import (
    SkipStartupPopups,
)

# All daily tasks: (id, class, display_name, safe)
_DAILY_TASKS: list[tuple[str, type, str, bool]] = [
    ("startup", SkipStartupPopups, "启动游戏", True),
    ("mail", CollectAllMail, "领取邮件", True),
    ("intel_shards", BuyIntelShards, "购买情报", False),
    ("stamina_packs", ClaimDailyStaminaPacks, "领取体力包", True),
    ("free_stamina", ClaimFreeStamina, "商店免费体力", True),
    ("mimi_station", MimiStationCollect, "弥弥观测站", True),
    ("guild_supply", GuildSupplyClaim, "公会补给", True),
    ("amusement", AmusementStreetDaily, "游园街日常", True),
    ("joint_special_ops", JointSpecialOpsSweep, "联合特勤", False),
    ("joint_defense", JointDefenseSweep, "联防协议", False),
    ("medium_seizure", MediumSeizureCombat, "介质攫取", False),
    ("missions", DailyWeeklyMissionClaim, "每日周常任务", True),
    ("tactics", TacticsTaskClaim, "对策协议", True),
]


# ---------------------------------------------------------------------------
# User-configurable plan (L1 task orchestration)
# ---------------------------------------------------------------------------
# A "plan" is an ordered list of steps. Each step names a registered task,
# whether it is enabled, and per-task tuning knobs (params). The plan is
# supplied via ``ctx.config["plan"]`` (preferred) or derived from the legacy
# ``ctx.config["enabled_tasks"]`` set; if neither is present, every
# registered task runs in its default order (backward compatible).
#
# This deliberately mirrors the MaaFramework / MAG ``interface.json``
# convention: a declarative task registry plus an ordered step list, kept
# separate from the task implementations themselves (data-driven, open/closed
# — adding a task never touches the orchestration logic).
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


# Fast lookup: task_id -> (class, display_name, safe)
_TASK_LOOKUP: dict[str, tuple[type, str, bool]] = {
    tid: (cls, name, safe) for (tid, cls, name, safe) in _DAILY_TASKS
}


class DailyRoutine:
    """Complete all daily tasks and claim rewards.

    Runs tasks in sequence, returning to hub between each.
    Each task failure is caught independently.

    Supports ``ctx.config["enabled_tasks"]`` to filter which tasks run.
    If not set, all tasks run (backward compatible).
    """
    name = "每日一条龙"
    description = "自动完成每日任务：邮件、商店、体力、公会、游园街等"

    @classmethod
    def task_defs(cls) -> list[dict[str, Any]]:
        """Return task metadata for UI discovery."""
        return [
            {
                "id": task_id,
                "name": display_name,
                "description": task_cls().description
                if hasattr(task_cls, "description") else "",
                "safe": safe,
            }
            for task_id, task_cls, display_name, safe in _DAILY_TASKS
        ]

    async def execute(self, ctx: ProcessContext) -> ProcessResult:
        hub = ReturnToHub()
        completed: list[str] = []
        failed: list[str] = []
        game_was_launched = ctx.config.get("game_was_launched", False)

        ctx.logger.info("=== DailyRoutine: starting ===")

        plan = self.build_plan(ctx)
        # Log the resolved plan
        for step in plan:
            state = "enabled" if step.enabled else "DISABLED"
            extra = f" (params={step.params})" if step.enabled else ""
            ctx.logger.info(f"  plan: {step.task_id} — {state}{extra}")

        routine_t0 = time.monotonic()
        total = len(plan)
        for i, step in enumerate(plan):
            task_id = step.task_id
            cls, _display, _safe = _TASK_LOOKUP[task_id]

            if not step.enabled:
                ctx.notify_task(task_id, "skipped", "disabled by user")
                ctx.logger.info(f"  {task_id}: skipped (disabled)")
                continue

            ctx.logger.info(
                f"--- DailyRoutine: task {i+1}/{total} — {task_id} ---"
            )
            ctx.notify_task(task_id, "running")

            task_t0 = time.monotonic()
            try:
                if step.params.wait_before:
                    await asyncio.sleep(step.params.wait_before)

                # Startup task only runs when game was freshly launched
                if task_id == "startup" and not game_was_launched:
                    ctx.notify_task(task_id, "skipped", "game already running")
                    ctx.logger.info(
                        f"  {task_id}: skipped (game already running)"
                    )
                    # Go to hub via normal ReturnToHub instead
                    await hub.execute(ctx)
                    continue

                task = cls()
                if await task.can_run(ctx):
                    result = await self._run_task(task, ctx, step.params)
                    elapsed = time.monotonic() - task_t0
                    if result.status == "success":
                        summary = task_id
                        if result.data:
                            for key in ("purchased", "claimed", "count"):
                                if key in result.data:
                                    summary = f"{task_id}({result.data[key]})"
                                    break
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

            # Return to hub between tasks
            await hub.execute(ctx)

        total_elapsed = time.monotonic() - routine_t0
        ctx.logger.info(
            f"=== DailyRoutine: complete "
            f"({len(completed)} done, {len(failed)} failed) "
            f"in {total_elapsed:.1f}s ===\n"
            f"  completed={completed}\n"
            f"  failed={failed}"
        )
        # Report partial failure upward. Hardcoding "success" here made the
        # pipeline log "1/1 succeeded" even when individual tasks failed or
        # silently did nothing, which hid real breakage during debugging.
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
    # Plan resolution & execution helpers
    # ------------------------------------------------------------------

    def build_plan(self, ctx: ProcessContext) -> list[PlanStep]:
        """Resolve the ordered, enabled plan for this run.

        Priority: explicit ``ctx.config["plan"]`` (ordered step list) >
        legacy ``ctx.config["enabled_tasks"]`` set (default order) >
        all registered tasks enabled (default order).

        Unknown task ids are always dropped. On the explicit-plan path,
        ``safe`` tasks are forced enabled so a user/bug can never silently
        disable a task that spends in-game currency or resources. The
        legacy ``enabled_tasks`` whitelist path is left strict (no forcing)
        to preserve its exact backward-compatible meaning.
        """
        raw = ctx.config.get("plan")
        if raw:
            steps = [PlanStep.from_dict(e) for e in raw]
            # safe tasks may not be disabled via an explicit user plan
            for step in steps:
                meta = _TASK_LOOKUP.get(step.task_id)
                if meta is not None and meta[2] and not step.enabled:
                    ctx.logger.info(
                        f"  plan: safe task '{step.task_id}' forced enabled"
                    )
                    step.enabled = True
        elif "enabled_tasks" in ctx.config:
            enabled = set(ctx.config["enabled_tasks"])
            steps = [
                PlanStep(tid, enabled=(tid in enabled))
                for tid in (e[0] for e in _DAILY_TASKS)
            ]
        else:
            steps = [PlanStep(tid) for tid in (e[0] for e in _DAILY_TASKS)]

        # Drop unknown task ids (defensive — a stale config should not crash)
        return [s for s in steps if s.task_id in _TASK_LOOKUP]

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
                    f"  {task.name}: attempt {attempt+1} failed "
                    f"({result.status}), retrying..."
                )
                await asyncio.sleep(1.0)
        return last if last is not None else TaskResult(
            status="failed", message="no attempts executed"
        )
