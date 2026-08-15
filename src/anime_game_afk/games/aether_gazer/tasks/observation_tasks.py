"""Observation, mission, and protocol tasks.

MimiStationCollect: Collect rewards from 弥弥观测站 and shorten return.
DailyWeeklyMissionClaim: Claim daily + weekly mission rewards.
TacticsTaskClaim: Claim 对策协议 task rewards.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from anime_game_afk.games.aether_gazer.checks.ocr import FindTextCheck
from anime_game_afk.games.aether_gazer.checks.red_dot import RedDotCheck
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
    ScreenshotOp,
)
from anime_game_afk.games.aether_gazer.tasks.base import TaskContext, TaskResult

if TYPE_CHECKING:
    from anime_game_afk.runtime.run_log import RunLog

# Verified coordinates (2026-04-06, 1600x900 design resolution)
# 弥弥观测站 button in daily tasks page (110,820 @ 1600x900)
_MIMI_STATION_X, _MIMI_STATION_Y = 0.069, 0.911
# 一键领取 button in 弥弥观测站 (1205,809 @ 1600x900, OCR verified center)
_MIMI_CLAIM_X, _MIMI_CLAIM_Y = 0.753, 0.899

# Red dot positions (verified via coord-picker)
# Hub gate: mission entry red dot — if absent there is nothing to claim.
_HUB_MISSION_RED_DOT = (0.828, 0.094)
# Inside the daily/weekly panel, left sidebar tabs:
_DAILY_TAB_RED_DOT = (0.058, 0.142)    # 日常任务 tab red dot
_WEEKLY_TAB_RED_DOT = (0.058, 0.248)   # 周常任务 tab red dot (detection only)
_WEEKLY_TAB_CLICK = (0.045, 0.281)     # 周常任务 tab 点击目标 (coord-picker @2560x1440)


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
        hub -> red dot check at (0.828, 0.094)
        -> skip entire task if absent
        -> G(daily/weekly panel)
        -> daily tab red dot (0.058, 0.142)?  -> OCR "一键领取" -> click
        -> weekly tab red dot (0.058, 0.248)? -> click weekly tab (0.045, 0.281)
                                              -> OCR "一键领取" -> click
        -> return to hub

    The hub dot is the gate: it lights up when either section has
    something to claim. Inside the panel each sidebar tab carries its own
    dot, so we only visit the sections that actually have rewards.
    """

    name = "daily_weekly_mission_claim"
    description = "Claim daily and weekly mission rewards"
    category = "daily"
    requires_pages = ("main_hub", "daily_tasks")
    requires_ocr = True
    safe = True

    async def can_run(self, ctx: TaskContext) -> bool:
        """Gate the task on the hub's mission red dot."""
        ctx.logger.info("DailyWeeklyMissionClaim.can_run: hub red-dot check")
        check = await RedDotCheck(
            *_HUB_MISSION_RED_DOT, label="hub-mission",
        ).evaluate(ctx)
        ctx.logger.info(
            f"DailyWeeklyMissionClaim.can_run: hub dot={check.data:.3f} "
            f"-> {'run' if check.passed else 'skip'}"
        )
        return check.passed

    async def execute(self, ctx: TaskContext) -> TaskResult:
        run_log: RunLog | None = getattr(ctx, "run_log", None)
        ctx.logger.info("=== DailyWeeklyMissionClaim: starting ===")

        # Step 1: Hub red dot gate
        ctx.logger.info(
            f"[Step 1] Hub red dot check at {_HUB_MISSION_RED_DOT}"
        )
        shot = await ScreenshotOp().run(ctx)
        if run_log:
            run_log.snap(ctx.device, "mission_hub_redot")

        hub_check = await RedDotCheck(
            *_HUB_MISSION_RED_DOT, label="hub-mission", image=shot.data,
        ).evaluate(ctx)
        hub_ratio = hub_check.data
        ctx.logger.info(f"[Step 1] Hub dot ratio={hub_ratio:.3f}")
        if hub_ratio <= 0:
            ctx.logger.info("[Step 1] No hub red dot - skipping")
            return TaskResult(
                status="skipped",
                message="No red dot on hub mission entry",
            )

        # Step 2: G -> daily/weekly panel
        ctx.logger.info("[Step 2] Press G -> daily/weekly panel")
        await PressKeyOp(VK_G, wait=1.5).run(ctx)

        # Step 3: Screenshot the panel, read both sidebar tab dots
        panel = await ScreenshotOp().run(ctx)
        if run_log:
            run_log.snap(ctx.device, "mission_panel_redot")

        daily_check = await RedDotCheck(
            *_DAILY_TAB_RED_DOT, label="daily-tab", image=panel.data,
        ).evaluate(ctx)
        weekly_check = await RedDotCheck(
            *_WEEKLY_TAB_RED_DOT, label="weekly-tab", image=panel.data,
        ).evaluate(ctx)
        daily_ratio = daily_check.data
        weekly_ratio = weekly_check.data
        ctx.logger.info(
            f"[Step 3] Tab dots - daily={daily_ratio:.3f}, "
            f"weekly={weekly_ratio:.3f}"
        )

        claimed = 0

        # Step 4: Claim daily (already the active tab after G)
        if daily_ratio > 0:
            ctx.logger.info("[Step 4] Daily tab has red dot - claiming")
            claimed += await self._claim_section(ctx, "daily", 5)
            if run_log:
                run_log.snap(ctx.device, "mission_after_daily")
        else:
            ctx.logger.info("[Step 4] No daily red dot - skipped")

        # Step 5: Switch to the weekly tab by clicking the tab itself (the
        # red dot is only a detector — clicking the dot misses the tab).
        if weekly_ratio > 0:
            cx, cy = _WEEKLY_TAB_CLICK
            ctx.logger.info(
                f"[Step 5] Weekly tab red dot - clicking tab at ({cx}, {cy})"
            )
            await ClickOp(x=cx, y=cy, wait=1.0).run(ctx)
            if run_log:
                run_log.snap(ctx.device, "mission_weekly_tab")

            claimed += await self._claim_section(ctx, "weekly", 5)
            if run_log:
                run_log.snap(ctx.device, "mission_after_weekly")
        else:
            ctx.logger.info("[Step 5] No weekly red dot - skipped")

        # Step 6: Return to hub
        ctx.logger.info("[Step 6] Return to hub")
        await ReturnToHubAction().run(ctx)
        if run_log:
            run_log.snap(ctx.device, "mission_done")

        ctx.logger.info(
            f"=== DailyWeeklyMissionClaim: complete (claimed={claimed}) ==="
        )
        return TaskResult(
            status="success",
            data={"task": "daily_weekly_claim", "claimed": claimed},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _claim_section(
        self, ctx: TaskContext, label: str, times: int,
    ) -> int:
        """OCR '一键领取' and click ×N. Returns 1 if claimed, 0 otherwise."""
        ctx.logger.info(f"  [{label}] Checking '一键领取'...")
        result = await FindTextCheck(target="一键领取").evaluate(ctx)
        if result.passed:
            btn = result.data
            cx = btn.region.x + btn.region.w // 2
            cy = btn.region.y + btn.region.h // 2
            ctx.logger.info(
                f"  [{label}] Found '一键领取' at ({cx},{cy}) — clicking ×{times}"
            )
            for _ in range(times):
                await ClickPxOp(px=cx, py=cy, wait=0.5).run(ctx)
            return 1
        ctx.logger.info(f"  [{label}] '一键领取' not found — skipped")
        return 0



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
