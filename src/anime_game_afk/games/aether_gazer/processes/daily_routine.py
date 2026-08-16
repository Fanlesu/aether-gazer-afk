"""Daily routine process.

Runs all daily tasks in sequence. The actual execution model — ordered
steps, per-task timeout/retry/wait knobs, return-to-hub between tasks —
lives in the shared :class:`TaskEngine` (``orchestrator/engine``). This
module only declares the process-specific pieces:

* the task registry (id -> class/name/safe) and its default order, and
* two process-specific behaviours that the generic engine does not know
  about: return to hub between tasks, and the startup task only running
  when the game was freshly launched.

The public process id ``daily_routine`` is unchanged, so the registry,
the frontend orchestrator, and the persisted plan JSON stay compatible.
"""
from __future__ import annotations

from typing import Any

from anime_game_afk.games.aether_gazer.orchestrator.engine import (
    PlanStep,
    TaskEngine,
    TaskMeta,
)
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

# Fast lookup consumed by the engine.
_REGISTRY: dict[str, TaskMeta] = {
    tid: TaskMeta(cls, name, safe)
    for (tid, cls, name, safe) in _DAILY_TASKS
}


class DailyRoutine:
    """Complete all daily tasks and claim rewards.

    A thin process: it owns the task registry and two process-specific
    rules, and delegates the actual execution to :class:`TaskEngine`.
    """

    name = "每日一条龙"
    description = "自动完成每日任务：邮件、商店、体力、公会、游园街等"

    def __init__(self) -> None:
        self._hub = ReturnToHub()
        self._engine = TaskEngine(
            _REGISTRY,
            inter_step=self._hub.execute,
            should_skip=self._should_skip,
        )

    @classmethod
    def task_defs(cls) -> list[dict[str, Any]]:
        """Return task metadata for UI discovery."""
        return [
            {
                "id": task_id,
                "name": display_name,
                "description": (
                    task_cls().description
                    if hasattr(task_cls, "description")
                    else ""
                ),
                "safe": safe,
            }
            for task_id, task_cls, display_name, safe in _DAILY_TASKS
        ]

    def _should_skip(self, step: PlanStep, ctx: ProcessContext) -> str | None:
        """Skip the startup task when the game was already running."""
        if step.task_id == "startup" and not ctx.config.get(
            "game_was_launched", False
        ):
            return "game already running"
        return None

    async def execute(self, ctx: ProcessContext) -> ProcessResult:
        ctx.logger.info("=== DailyRoutine: starting ===")
        return await self._engine.run(ctx)

    def build_plan(self, ctx: ProcessContext) -> list[PlanStep]:
        """Resolve the plan (delegates to the engine; kept for API use)."""
        return self._engine.build_plan(ctx.config)
