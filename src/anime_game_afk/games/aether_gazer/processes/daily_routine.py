"""Daily routine process.

Runs all daily tasks in sequence. The actual execution model — ordered
steps, per-task timeout/retry/wait knobs, return-to-hub between tasks —
lives in the shared :class:`WorkflowEngine` (``engine/workflow_engine``). This
module only declares the process-specific pieces:

* the task registry (id -> class/name/safe) and its default order, and
* one process-specific behaviour that the generic engine does not know
  about: returning to the hub between tasks.

The startup task (``SkipStartupPopups``) runs unconditionally and is
idempotent / state-aware: it inspects the live screen and only does what is
needed (dismiss popups, click to enter a login screen, wake an idle hub, or
confirm the hub is already reached). This means the routine works whether the
tool launched the game or the user already had it open.

The public process id ``daily_routine`` is unchanged, so the registry,
the frontend orchestrator, and the persisted plan JSON stay compatible.
"""
from __future__ import annotations

from typing import Any

from anime_game_afk.engine.workflow_engine import (
    PlanStep,
    TaskMeta,
    WorkflowEngine,
)
from anime_game_afk.games.aether_gazer.orchestrator.actions import (
    run_custom_action,
)
from anime_game_afk.games.aether_gazer.orchestrator.conditions import (
    resolve_condition,
)
from anime_game_afk.games.aether_gazer.processes.base import (
    ProcessContext,
    ProcessResult,
)
from anime_game_afk.games.aether_gazer.tasks.activity_tasks import (
    InvitationRewardClaim,
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

# All daily tasks: (id, class, display_name, safe, default_enabled)
# ``default_enabled`` is the initial checkbox state for FRESH configs only —
# a saved ui_state.json always overrides it (user choice wins).
_DAILY_TASKS: list[tuple[str, type, str, bool, bool]] = [
    ("startup", SkipStartupPopups, "启动游戏", True, True),
    ("mail", CollectAllMail, "领取邮件", True, True),
    ("intel_shards", BuyIntelShards, "购买情报", False, True),
    ("stamina_packs", ClaimDailyStaminaPacks, "领取体力包", True, True),
    ("free_stamina", ClaimFreeStamina, "商店免费体力", True, True),
    ("mimi_station", MimiStationCollect, "弥弥观测站", True, True),
    ("guild_supply", GuildSupplyClaim, "公会补给", True, True),
    ("amusement", AmusementStreetDaily, "游园街日常", True, True),
    ("joint_special_ops", JointSpecialOpsSweep, "联合特勤", False, True),
    # 默认不勾选：消耗吨吨值且"找震动"OCR 偶发失败，由用户按需启用
    ("joint_defense", JointDefenseSweep, "联防协议", False, False),
    ("medium_seizure", MediumSeizureCombat, "介质攫取", False, True),
    ("missions", DailyWeeklyMissionClaim, "每日周常任务", True, True),
    ("tactics", TacticsTaskClaim, "对策协议", True, True),
    ("invitation_reward", InvitationRewardClaim, "邀约奖励", True, True),
]

# Fast lookup consumed by the engine.
_REGISTRY: dict[str, TaskMeta] = {
    tid: TaskMeta(cls, name, safe, default_enabled=default_enabled)
    for (tid, cls, name, safe, default_enabled) in _DAILY_TASKS
}


# Task-specific custom params rendered by the orchestrator UI (L1 extra
# knobs). Saved into ``params.extra`` and attached to the task instance by
# the engine. Tasks not listed here have no custom params.
_TASK_PARAM_SCHEMAS: dict[str, list[dict[str, Any]]] = {
    "stamina_packs": [
        {
            "key": "target_stamina",
            "label": "目标体力",
            "type": "number",
            "default": 450,
            "min": 240,
            "max": 2000,
        },
    ],
}


class DailyRoutine:
    """Complete all daily tasks and claim rewards.

    A thin process: it owns the task registry and two process-specific
    rules, and delegates the actual execution to :class:`WorkflowEngine`.
    """

    name = "每日一条龙"
    description = "自动完成每日任务：邮件、商店、体力、公会、游园街等"

    def __init__(self) -> None:
        self._hub = ReturnToHub()
        self._engine = WorkflowEngine(
            _REGISTRY,
            inter_step=self._hub.execute,
            resolve_condition=resolve_condition,
            action_executor=run_custom_action,
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
                "default_enabled": default_enabled,
                "params_schema": _TASK_PARAM_SCHEMAS.get(task_id, []),
            }
            for task_id, task_cls, display_name, safe, default_enabled in (
                _DAILY_TASKS
            )
        ]

    async def execute(self, ctx: ProcessContext) -> ProcessResult:
        ctx.logger.info("=== DailyRoutine: starting ===")
        return await self._engine.run(ctx)

    def build_plan(self, ctx: ProcessContext) -> list[PlanStep]:
        """Resolve the plan (delegates to the engine; kept for API use)."""
        return self._engine.build_plan(ctx.config)
