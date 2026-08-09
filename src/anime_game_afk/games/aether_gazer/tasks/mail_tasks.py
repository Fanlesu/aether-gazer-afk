"""Mail tasks — collect all reward mail.

CollectAllMail opens the mailbox and collects every available reward.
"""
from __future__ import annotations

from anime_game_afk.core.types import Rect
from anime_game_afk.games.aether_gazer.knowledge.keys import VK_H, VK_ENTER
from anime_game_afk.games.aether_gazer.ops.navigate.smart_return import (
    ReturnToHubAction,
)
from anime_game_afk.games.aether_gazer.ops.primitives import (
    ClickOp,
    PressKeyOp,
    ScreenshotOp,
)
from anime_game_afk.games.aether_gazer.tasks.base import TaskContext, TaskResult

# Verified coordinates (2026-04-06, 291,749 @ 1600x900, OCR verified)
_COLLECT_ALL_X, _COLLECT_ALL_Y = 0.182, 0.832   # 全部领取 button

# Red dot: HSV low-red range
_RED_LOW = (0, 120, 120)
_RED_HIGH = (10, 255, 255)
_RED_DOT_RATIO = 0.02
_RED_REGION_SIZE = 20


class CollectAllMail:
    """Open mail panel and collect all available rewards."""
    name = "collect_all_mail"
    description = "Collect all reward mail from mailbox"
    category = "daily"
    requires_pages = ("main_hub", "mail")
    requires_ocr = False
    safe = True

    async def can_run(self, ctx: TaskContext) -> bool:
        return True

    async def execute(self, ctx: TaskContext) -> TaskResult:
        ctx.logger.info("=== CollectAllMail: starting ===")

        # Step 0: Check red dot on mail icon at (0.870, 0.099)
        ctx.logger.info("[Step 0] Check red dot on mail at (0.870, 0.099)")
        r = await ScreenshotOp().run(ctx)
        _h, _w = r.data.shape[:2]
        red_ratio = self._red_pixel_ratio(
            r.data,
            Rect(
                x=int(0.870 * _w) - _RED_REGION_SIZE // 2,
                y=int(0.099 * _h) - _RED_REGION_SIZE // 2,
                w=_RED_REGION_SIZE, h=_RED_REGION_SIZE,
            ),
        )
        has_dot = red_ratio > _RED_DOT_RATIO
        ctx.logger.info(f"[Step 0] Red dot: {has_dot} (ratio={red_ratio:.3f})")
        if not has_dot:
            ctx.logger.info("=== CollectAllMail: skipped — no red dot ===")
            return TaskResult(
                status="skipped",
                message="No red dot on mail icon",
            )

        # Step 1: H shortcut opens the mail panel from hub
        ctx.logger.info("[Step 1] Press H → mail")
        await PressKeyOp(VK_H, wait=1.0).run(ctx)

        # Step 2: Click "全部领取" (collect all) button
        ctx.logger.info(
            f"[Step 2] Click 全部领取 at ({_COLLECT_ALL_X},{_COLLECT_ALL_Y})"
        )
        await ClickOp(x=_COLLECT_ALL_X, y=_COLLECT_ALL_Y, wait=0.5).run(ctx)

        # Step 3: Dismiss reward popup (Enter or click)
        ctx.logger.info("[Step 3] Dismiss reward popup")
        await PressKeyOp(VK_ENTER, wait=1.0).run(ctx)
        # Click again in case multiple popups
        await ClickOp(x=_COLLECT_ALL_X, y=_COLLECT_ALL_Y, wait=1.0).run(ctx)
        await PressKeyOp(VK_ENTER, wait=1.0).run(ctx)

        # Step 4: Return to hub
        ctx.logger.info("[Step 4] Return to hub")
        await ReturnToHubAction().run(ctx)

        ctx.logger.info("=== CollectAllMail: complete ===")
        return TaskResult(status="success", data={"action": "mail_collected"})

    # ------------------------------------------------------------------
    # Red dot helper (inline HSV detection — avoids importing vision/)
    # ------------------------------------------------------------------

    @staticmethod
    def _red_pixel_ratio(img, region: Rect) -> float:
        """Return fraction of red pixels in *region* of a BGR image."""
        import cv2
        import numpy as np

        crop = img[region.y:region.y + region.h,
                    region.x:region.x + region.w]
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
            return 0.0
        return float(np.count_nonzero(mask)) / total
