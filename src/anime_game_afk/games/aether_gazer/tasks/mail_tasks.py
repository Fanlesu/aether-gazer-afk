"""Mail tasks - collect all reward mail.

CollectAllMail opens the mailbox and collects every available reward.
"""
from __future__ import annotations

from anime_game_afk.games.aether_gazer.checks.red_dot import RedDotCheck
from anime_game_afk.games.aether_gazer.knowledge.keys import VK_ENTER, VK_H
from anime_game_afk.games.aether_gazer.knowledge.red_dots import RED_DOTS
from anime_game_afk.games.aether_gazer.ops.navigate.smart_return import (
    ReturnToHubAction,
)
from anime_game_afk.games.aether_gazer.ops.primitives import (
    ClickOp,
    PressKeyOp,
)
from anime_game_afk.games.aether_gazer.tasks.base import TaskContext, TaskResult

# Verified coordinates (2026-04-06, 291,749 @ 1600x900, OCR verified)
_COLLECT_ALL_X, _COLLECT_ALL_Y = 0.182, 0.832   # 全部领取 button

# Red dot position on the mail icon at the hub (verified via coord-picker)
_MAIL_RED_DOT = RED_DOTS["mail"]


class CollectAllMail:
    """Open mail panel and collect all available rewards.

    Flow:
        hub -> can_run: red dot check on mail icon (0.870, 0.099)
        -> skip if no red dot
        -> H(mail) -> 全部领取 -> Enter -> 全部领取 -> Enter
        -> return to hub
    """

    name = "collect_all_mail"
    description = "Collect all reward mail from mailbox"
    category = "daily"
    requires_pages = ("main_hub", "mail")
    requires_ocr = False
    safe = True

    async def can_run(self, ctx: TaskContext) -> bool:
        """Gate on the red dot visible on the mail icon at the hub."""
        ctx.logger.info("CollectAllMail.can_run: red-dot check at hub")
        check = await RedDotCheck(
            *_MAIL_RED_DOT, label="mail",
        ).evaluate(ctx)
        ctx.logger.info(
            f"CollectAllMail.can_run: ratio={check.data:.3f} "
            f"-> {'run' if check.passed else 'skip'}"
        )
        return check.passed

    async def execute(self, ctx: TaskContext) -> TaskResult:
        ctx.logger.info("=== CollectAllMail: starting ===")

        # Step 1: H shortcut opens the mail panel from hub
        ctx.logger.info("[Step 1] Press H -> mail")
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
