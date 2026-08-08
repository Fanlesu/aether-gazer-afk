"""Observation, mission, and protocol tasks.

MimiStationCollect: Collect rewards from 弥弥观测站 and shorten return.
DailyWeeklyMissionClaim: Claim daily + weekly mission rewards.
TacticsTaskClaim: Claim 对策协议 task rewards.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from anime_game_afk.games.aether_gazer.checks.ocr import FindTextCheck
from anime_game_afk.games.aether_gazer.knowledge.keys import VK_G, VK_T
from anime_game_afk.games.aether_gazer.ops.interact.rapid_click import (
    RapidClickAction,
)
from anime_game_afk.games.aether_gazer.ops.navigate.smart_return import (
    ReturnToHubAction,
)
from anime_game_afk.games.aether_gazer.ops.primitives import (
    ClickOp,
    ClickPxOp,
    PressKeyOp,
    SleepOp,
)
from anime_game_afk.games.aether_gazer.tasks.base import TaskContext, TaskResult

if TYPE_CHECKING:
    from anime_game_afk.runtime.run_log import RunLog


# Verified coordinates (2026-04-06, 1600x900 design resolution)
# 弥弥观测站 button in daily tasks page (110,820 @ 1600x900)
_MIMI_STATION_X, _MIMI_STATION_Y = 0.069, 0.911
# 一键领取 button in 弥弥观测站 (1205,809 @ 1600x900, OCR verified center)
_MIMI_CLAIM_X, _MIMI_CLAIM_Y = 0.753, 0.899
# 周常任务 tab (estimated, left sidebar below 每日任务)
_WEEKLY_TAB_X, _WEEKLY_TAB_Y = 0.05, 0.30


class MimiStationCollect:
    """Collect rewards from 弥弥观测站 and shorten return time.

    Flow: hub → G(daily tasks) → 弥弥观测站(110,820) → 一键领取(1205,809) ×20
          → x10(OCR, weekly reward) ×20 → return to hub

    x10 is a weekly one-time reward (higher multiplier = better value).
    Only clicks when x10 is available; skips if not found.

    Identification methods:
    - Keyboard: G shortcut opens daily tasks
    - Fixed coord: 弥弥观测站 button, 一键领取 button
    - OCR: x10 缩短遣回 button (weekly reward, dynamic position)
    """

    name = "mimi_station_collect"
    description = "Collect 弥弥观测站 rewards and shorten return time"
    category = "daily"
    requires_pages = ("main_hub", "daily_tasks")
    requires_ocr = True
    safe = True

    async def can_run(self, ctx: TaskContext) -> bool:
        return True

    async def execute(self, ctx: TaskContext) -> TaskResult:
        run_log: RunLog | None = getattr(ctx, "run_log", None)
        ctx.logger.info("=== MimiStationCollect: starting ===")

        # Step 1: G → daily tasks
        ctx.logger.info("[Step 1] Press G → daily tasks")
        await PressKeyOp(VK_G, wait=1.5).run(ctx)
        if run_log:
            run_log.snap(ctx.device, "mimi_daily_tasks")

        # Step 2: Click 弥弥观测站
        ctx.logger.info(
            f"[Step 2] Click 弥弥观测站 at ({_MIMI_STATION_X},{_MIMI_STATION_Y})"
        )
        await ClickOp(x=_MIMI_STATION_X, y=_MIMI_STATION_Y, wait=0.5).run(ctx)
        if run_log:
            run_log.snap(ctx.device, "mimi_station")

        # Step 3: 一键领取 ×20
        ctx.logger.info(
            f"[Step 3] Rapid click 一键领取 at ({_MIMI_CLAIM_X},{_MIMI_CLAIM_Y}) ×20"
        )
        await RapidClickAction(
            x=_MIMI_CLAIM_X, y=_MIMI_CLAIM_Y, times=20, interval=0.15,
        ).run(ctx)
        if run_log:
            run_log.snap(ctx.device, "mimi_after_claim")

        # Step 4: Return to hub
        ctx.logger.info("[Step 4] Return to hub")
        await ReturnToHubAction().run(ctx)
        if run_log:
            run_log.snap(ctx.device, "mimi_done")

        ctx.logger.info("=== MimiStationCollect: complete ===")
        return TaskResult(status="success", data={"task": "mimi_station"})


class DailyWeeklyMissionClaim:
    """Claim daily and weekly mission rewards.

    Flow:
        hub → G(daily tasks)
        → OCR "一键领取" → if found, click ×5 (daily)
        → OCR "周常任务" tab → click
        → click 返回 button
        → OCR "一键领取" → if found, click ×5 (weekly primary)
        → OCR "一键领取" → if found, click ×5 (weekly secondary)
        → return to hub

    All claim clicks are OCR-driven — if "一键领取" is not found
    the step is skipped.
    """

    name = "daily_weekly_mission_claim"
    description = "Claim daily and weekly mission rewards"
    category = "daily"
    requires_pages = ("main_hub", "daily_tasks")
    requires_ocr = True
    safe = True

    async def can_run(self, ctx: TaskContext) -> bool:
        return True

    async def execute(self, ctx: TaskContext) -> TaskResult:
        run_log: RunLog | None = getattr(ctx, "run_log", None)
        ctx.logger.info("=== DailyWeeklyMissionClaim: starting ===")

        # Step 1: G → daily tasks
        ctx.logger.info("[Step 1] Press G → daily tasks")
        await PressKeyOp(VK_G, wait=1.5).run(ctx)
        if run_log:
            run_log.snap(ctx.device, "mission_daily_tasks")

        # Step 2: OCR "一键领取" → if found, click ×5 (daily)
        ctx.logger.info("[Step 2] Check for '一键领取' on daily page")
        daily_claim = await FindTextCheck(target="一键领取").evaluate(ctx)
        if daily_claim.passed:
            btn = daily_claim.data
            cx = btn.region.x + btn.region.w // 2
            cy = btn.region.y + btn.region.h // 2
            ctx.logger.info(
                f"  [Step 2] Found '一键领取' at ({cx},{cy}) — clicking ×5"
            )
            for _ in range(5):
                await ClickPxOp(px=cx, py=cy, wait=0.5).run(ctx)
        else:
            ctx.logger.info("  [Step 2] '一键领取' not found — skipped")
        if run_log:
            run_log.snap(ctx.device, "mission_after_daily")

        # Step 3: Switch to 周常任务 tab, then click 返回
        await SleepOp(seconds=0.5).run(ctx)
        ctx.logger.info("[Step 3] Find and click '周常任务' tab via OCR")
        weekly_result = await FindTextCheck(target="周常任务").evaluate(ctx)
        if weekly_result.passed:
            weekly = weekly_result.data
            wx = weekly.region.x + weekly.region.w // 2
            wy = weekly.region.y + weekly.region.h // 2
            ctx.logger.info(f"  Found '周常任务' at ({wx},{wy})")
            await ClickPxOp(px=wx, py=wy, wait=0.2).run(ctx)
            await ClickPxOp(px=wx, py=wy, wait=1.0).run(ctx)
        else:
            ctx.logger.warning(
                "  '周常任务' not found via OCR, using fallback coord"
            )
            await ClickOp(x=_WEEKLY_TAB_X, y=_WEEKLY_TAB_Y, wait=0.2).run(ctx)
            await ClickOp(x=_WEEKLY_TAB_X, y=_WEEKLY_TAB_Y, wait=1.0).run(ctx)

        # Click 返回 button after entering weekly tab
        ctx.logger.info("  clicking 返回 button")
        back_result = await FindTextCheck(target="返回").evaluate(ctx)
        if back_result.passed:
            btn = back_result.data
            bx = btn.region.x + btn.region.w // 2
            by = btn.region.y + btn.region.h // 2
            await ClickPxOp(px=bx, py=by, wait=1.0).run(ctx)
        else:
            await ClickOp(x=0.022, y=0.039, wait=1.0).run(ctx)
        if run_log:
            run_log.snap(ctx.device, "mission_weekly")

        # Step 4: OCR "一键领取" → if found, click ×5 (weekly — primary)
        ctx.logger.info("[Step 4] Check for '一键领取' on weekly page (primary)")
        weekly_claim = await FindTextCheck(target="一键领取").evaluate(ctx)
        if weekly_claim.passed:
            btn = weekly_claim.data
            cx = btn.region.x + btn.region.w // 2
            cy = btn.region.y + btn.region.h // 2
            ctx.logger.info(
                f"  [Step 4] Found '一键领取' at ({cx},{cy}) — clicking ×5"
            )
            for _ in range(5):
                await ClickPxOp(px=cx, py=cy, wait=0.5).run(ctx)
        else:
            ctx.logger.info("  [Step 4] '一键领取' not found — skipped")
        if run_log:
            run_log.snap(ctx.device, "mission_after_weekly_primary")

        # Step 5: OCR "一键领取" → if found, click ×5 (weekly — secondary)
        ctx.logger.info("[Step 5] Check for '一键领取' again (weekly secondary)")
        secondary_claim = await FindTextCheck(target="一键领取").evaluate(ctx)
        if secondary_claim.passed:
            btn = secondary_claim.data
            cx = btn.region.x + btn.region.w // 2
            cy = btn.region.y + btn.region.h // 2
            ctx.logger.info(
                f"  [Step 5] Found '一键领取' at ({cx},{cy}) — clicking ×5"
            )
            for _ in range(5):
                await ClickPxOp(px=cx, py=cy, wait=0.5).run(ctx)
        else:
            ctx.logger.info("  [Step 5] '一键领取' not found — skipped")
        if run_log:
            run_log.snap(ctx.device, "mission_after_weekly_secondary")

        # Step 6: Return to hub
        ctx.logger.info("[Step 6] Return to hub")
        await ReturnToHubAction().run(ctx)
        if run_log:
            run_log.snap(ctx.device, "mission_done")

        ctx.logger.info("=== DailyWeeklyMissionClaim: complete ===")
        return TaskResult(status="success", data={"task": "daily_weekly_claim"})


class TacticsTaskClaim:
    """Claim 对策协议 (Tactics Protocol) task rewards.

    Flow: hub → T(对策协议) → 任务(162,839) → 一键领取(1480,860) ×3 → return to hub

    Identification methods:
    - Keyboard: T shortcut opens tactics protocol
    - Fixed coord: 任务 button, 一键领取 button
    """

    name = "tactics_task_claim"
    description = "Claim 对策协议 task rewards"
    category = "daily"
    requires_pages = ("main_hub", "tactics")
    requires_ocr = True
    safe = True

    _TACTICS_TASK_X, _TACTICS_TASK_Y = 0.101, 0.932
    _TACTICS_CLAIM_X, _TACTICS_CLAIM_Y = 0.925, 0.956

    async def can_run(self, ctx: TaskContext) -> bool:
        ctx.logger.info("TacticsTaskClaim.can_run: OCR hub for '对策协议'…")
        result = await FindTextCheck(target="对策协议").evaluate(ctx)
        ctx.logger.info(
            f"TacticsTaskClaim.can_run: result.passed={result.passed} "
            f"msg={result.message}"
        )
        if not result.passed:
            ctx.logger.info(
                "TacticsTaskClaim: '对策协议' not found on hub — skipping"
            )
            return False
        return True

    async def execute(self, ctx: TaskContext) -> TaskResult:
        run_log: RunLog | None = getattr(ctx, "run_log", None)
        ctx.logger.info("=== TacticsTaskClaim: starting ===")

        # Step 1: T → 对策协议
        ctx.logger.info("[Step 1] Press T → 对策协议")
        await PressKeyOp(VK_T, wait=1.5).run(ctx)
        if run_log:
            run_log.snap(ctx.device, "tactics_page")

        # Step 2: Click 任务 button (left-bottom)
        ctx.logger.info(
            f"[Step 2] Click 任务 at ({self._TACTICS_TASK_X},{self._TACTICS_TASK_Y})"
        )
        await ClickOp(x=self._TACTICS_TASK_X, y=self._TACTICS_TASK_Y, wait=1.5).run(ctx)
        if run_log:
            run_log.snap(ctx.device, "tactics_tasks")

        # Step 3: OCR "一键领取" → if found, click ×3
        ctx.logger.info("[Step 3] Check for '一键领取' on 对策协议 page")
        claim_result = await FindTextCheck(target="一键领取").evaluate(ctx)
        if claim_result.passed:
            btn = claim_result.data
            cx = btn.region.x + btn.region.w // 2
            cy = btn.region.y + btn.region.h // 2
            ctx.logger.info(
                f"  [Step 3] Found '一键领取' at ({cx},{cy}) — clicking ×3"
            )
            for _ in range(3):
                await ClickPxOp(px=cx, py=cy, wait=0.5).run(ctx)
        else:
            ctx.logger.info("  [Step 3] '一键领取' not found — skipped")
        if run_log:
            run_log.snap(ctx.device, "tactics_after_claim")

        # Step 4: Click 返回, then OCR "一键领取" again
        ctx.logger.info("[Step 4] Click 返回 → check for '一键领取' again")
        back_result = await FindTextCheck(target="返回").evaluate(ctx)
        if back_result.passed:
            btn = back_result.data
            bx = btn.region.x + btn.region.w // 2
            by = btn.region.y + btn.region.h // 2
            await ClickPxOp(px=bx, py=by, wait=1.0).run(ctx)
        else:
            await ClickOp(x=0.022, y=0.039, wait=1.0).run(ctx)

        ctx.logger.info("  checking for secondary '一键领取'")
        claim2 = await FindTextCheck(target="一键领取").evaluate(ctx)
        if claim2.passed:
            btn = claim2.data
            cx = btn.region.x + btn.region.w // 2
            cy = btn.region.y + btn.region.h // 2
            ctx.logger.info(
                f"  [Step 4] Found secondary '一键领取' at ({cx},{cy}) — clicking ×3"
            )
            for _ in range(3):
                await ClickPxOp(px=cx, py=cy, wait=0.5).run(ctx)
        else:
            ctx.logger.info("  [Step 4] Secondary '一键领取' not found — skipped")
        if run_log:
            run_log.snap(ctx.device, "tactics_after_secondary_claim")

        # Step 5: Return to hub
        ctx.logger.info("[Step 5] Return to hub")
        await ReturnToHubAction().run(ctx)
        if run_log:
            run_log.snap(ctx.device, "tactics_done")

        ctx.logger.info("=== TacticsTaskClaim: complete ===")
        return TaskResult(status="success", data={"task": "tactics_claim"})
