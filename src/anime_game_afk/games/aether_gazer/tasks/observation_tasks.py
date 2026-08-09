"""Observation, mission, and protocol tasks.

MimiStationCollect: Collect rewards from 弥弥观测站 and shorten return.
DailyWeeklyMissionClaim: Claim daily + weekly mission rewards.
TacticsTaskClaim: Claim 对策协议 task rewards.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from anime_game_afk.core.types import Rect
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
    ScreenshotOp,
    SleepOp,
)
from anime_game_afk.games.aether_gazer.tasks.base import TaskContext, TaskResult

if TYPE_CHECKING:
    from anime_game_afk.runtime.run_log import RunLog


# HSV low-red range for red dot detection
_RED_LOW = (0, 120, 120)
_RED_HIGH = (10, 255, 255)
_RED_DOT_RATIO = 0.02
_RED_REGION_SIZE = 20

# Verified coordinates (2026-04-06, 1600x900 design resolution)
# 弥弥观测站 button in daily tasks page (110,820 @ 1600x900)
_MIMI_STATION_X, _MIMI_STATION_Y = 0.069, 0.911
# 一键领取 button in 弥弥观测站 (1205,809 @ 1600x900, OCR verified center)
_MIMI_CLAIM_X, _MIMI_CLAIM_Y = 0.753, 0.899
# 周常任务 tab (estimated, left sidebar below 每日任务)
_WEEKLY_TAB_X, _WEEKLY_TAB_Y = 0.05, 0.30

# Red dot positions on daily tasks page (verified via coord-picker)
_DAILY_TAB_RED_DOT = (0.828, 0.095)    # 日常任务 tab red dot
_WEEKLY_TAB_RED_DOT = (0.052, 0.153)   # 周常任务 tab red dot


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
        hub → G(daily tasks) → screenshot
        → red dot check: daily (0.828,0.095), weekly (0.052,0.153)
        → skip if neither has red dot
        → OCR "一键领取" on daily page → click ×5 (if daily dot)
        → click 周常任务 tab (red dot coord) → click 返回
        → OCR "一键领取" on weekly page → click ×5 ×2 (if weekly dot)
        → return to hub

    All claim clicks are OCR-driven — if "一键领取" is not found
    the step is skipped. Red dot detection gates the whole task.
    """

    name = "daily_weekly_mission_claim"
    description = "Claim daily and weekly mission rewards"
    category = "daily"
    requires_pages = ("main_hub", "daily_tasks")
    requires_ocr = True
    safe = True

    _DAILY_DOT = _DAILY_TAB_RED_DOT   # (0.828, 0.095)
    _WEEKLY_DOT = _WEEKLY_TAB_RED_DOT  # (0.052, 0.153)

    async def can_run(self, ctx: TaskContext) -> bool:
        return True

    async def execute(self, ctx: TaskContext) -> TaskResult:
        run_log: RunLog | None = getattr(ctx, "run_log", None)
        ctx.logger.info("=== DailyWeeklyMissionClaim: starting ===")

        # Step 1: G → daily tasks
        ctx.logger.info("[Step 1] Press G → daily tasks")
        await PressKeyOp(VK_G, wait=1.5).run(ctx)

        # Step 2: Screenshot + red dot check on both tabs
        ctx.logger.info("[Step 2] Red dot check on daily/weekly tabs")
        screenshot = await ScreenshotOp().run(ctx)
        _h, _w = screenshot.data.shape[:2]
        if run_log:
            run_log.snap(ctx.device, "mission_daily_tasks")

        daily_dot = self._check_red_dot(screenshot.data, *_DAILY_TAB_RED_DOT, _w, _h)
        weekly_dot = self._check_red_dot(screenshot.data, *_WEEKLY_TAB_RED_DOT, _w, _h)
        ctx.logger.info(
            f"[Step 2] Red dots — daily={daily_dot}, weekly={weekly_dot}"
        )

        if not daily_dot and not weekly_dot:
            ctx.logger.info("[Step 2] Neither tab has red dot — skipping")
            await ReturnToHubAction().run(ctx)
            return TaskResult(
                status="skipped",
                message="No red dot on daily or weekly mission tabs",
            )

        claimed = 0

        # Step 3: Claim daily (if red dot)
        if daily_dot:
            claimed += await self._claim_section(
                ctx, "daily", 5,
            )

        # Step 4: Switch to 周常任务 tab (if weekly red dot, but also try
        # even if daily was the only dot — user has no weekly dot but
        # might have a pending secondary weekly claim)
        if weekly_dot:
            ctx.logger.info("[Step 4] Switch to 周常任务 tab")
            await self._switch_to_weekly(ctx)
            if run_log:
                run_log.snap(ctx.device, "mission_weekly")

            claimed += await self._claim_section(
                ctx, "weekly-primary", 5,
            )
            claimed += await self._claim_section(
                ctx, "weekly-secondary", 5,
            )

        # Step 5: Return to hub
        ctx.logger.info("[Step 5] Return to hub")
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

    async def _switch_to_weekly(self, ctx: TaskContext) -> None:
        """Switch to 周常任务 tab via OCR, fallback to fixed coord."""
        await SleepOp(seconds=0.5).run(ctx)
        result = await FindTextCheck(target="周常任务").evaluate(ctx)
        if result.passed:
            tab = result.data
            wx = tab.region.x + tab.region.w // 2
            wy = tab.region.y + tab.region.h // 2
            ctx.logger.info(f"  Found '周常任务' at ({wx},{wy})")
            await ClickPxOp(px=wx, py=wy, wait=0.2).run(ctx)
            await ClickPxOp(px=wx, py=wy, wait=1.0).run(ctx)
        else:
            ctx.logger.warning("  '周常任务' OCR failed, using fallback coord")
            await ClickOp(x=_WEEKLY_TAB_X, y=_WEEKLY_TAB_Y, wait=0.2).run(ctx)
            await ClickOp(x=_WEEKLY_TAB_X, y=_WEEKLY_TAB_Y, wait=1.0).run(ctx)

        # Click 返回 button
        back_result = await FindTextCheck(target="返回").evaluate(ctx)
        if back_result.passed:
            btn = back_result.data
            bx = btn.region.x + btn.region.w // 2
            by = btn.region.y + btn.region.h // 2
            await ClickPxOp(px=bx, py=by, wait=1.0).run(ctx)
        else:
            await ClickOp(x=0.022, y=0.039, wait=1.0).run(ctx)

    @staticmethod
    def _check_red_dot(img, fx: float, fy: float, w: int, h: int) -> bool:
        """Check for red dot at normalized coords (fx, fy) in a BGR image."""
        import cv2
        import numpy as np

        cx = int(fx * w)
        cy = int(fy * h)
        hs = _RED_REGION_SIZE // 2
        crop = img[cy - hs:cy + hs, cx - hs:cx + hs]

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask_low = cv2.inRange(
            hsv,
            np.array(_RED_LOW, dtype=np.uint8),
            np.array(_RED_HIGH, dtype=np.uint8),
        )
        mask_high = cv2.inRange(
            hsv,
            np.array((170, 120, 120), dtype=np.uint8),
            np.array((180, 255, 255), dtype=np.uint8),
        )
        mask = mask_low | mask_high
        total = mask.size
        if total == 0:
            return False
        ratio = float(np.count_nonzero(mask)) / total
        return ratio > _RED_DOT_RATIO


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
