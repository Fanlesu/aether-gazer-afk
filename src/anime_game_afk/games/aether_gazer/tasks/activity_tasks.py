"""Activity tasks — event-based daily activities.

JointDefenseSweep: Run sweep on 联防协议 (Joint Defense) activity.
InvitationRewardClaim: Claim 见闻 rewards for each 邀约 (invitation) event.

Shared navigation lives in :class:`_ActivityPageNav` (hub → activity page
via the H shortcut label → back out to hub); both task classes inherit it.

Uses mixed identification methods:
- Fixed coord: hub elements, panel buttons (> >>)
- Template match: page identification via OnPageCheck
- OCR (batch via OcrScanCheck): activity names, dynamic text, button states
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from anime_game_afk.core.types import Rect
from anime_game_afk.games.aether_gazer.checks.ocr import (
    FindTextCheck,
    OcrResult,
    OcrScan,
    ocr_scan_with_retry,
)
from anime_game_afk.games.aether_gazer.checks.page import OnPageCheck
from anime_game_afk.games.aether_gazer.knowledge.keys import VK_ENTER, VK_ESCAPE
from anime_game_afk.games.aether_gazer.ops.navigate.smart_return import ReturnToHubAction
from anime_game_afk.games.aether_gazer.ops.navigate.wake_hub_ui import WakeHubUiAction
from anime_game_afk.games.aether_gazer.ops.primitives import (
    ClickOp,
    ClickPxOp,
    PressKeyOp,
    ScreenshotOp,
    SleepOp,
    SwipeOp,
)
from anime_game_afk.games.aether_gazer.tasks.base import TaskContext, TaskResult

if TYPE_CHECKING:
    from anime_game_afk.runtime.run_log import RunLog


class _ActivityPageNav:
    """Shared navigation for activity-page tasks (联防协议 / 邀约奖励).

    Owns the hub → activity-page entry (OCR the "H" shortcut label, click
    just below it) and the back-out-to-hub walker. Subclasses supply their
    own flow in between.
    """

    # OCR retry knobs shared by all activity-page tasks
    _OCR_RETRIES = 2
    _OCR_RETRY_DELAY = 1.5

    # H shortcut label search region (right side of hub)
    # At screenshot resolution (1280×720): x=1040..1200, y=80..160
    _H_SEARCH_REGION = Rect(0.8125, 0.1111, 0.125, 0.1111)
    # Activity list left column
    _LEFT_COLUMN = Rect(0.0, 0.1111, 0.25, 0.7778)
    # Back button (top-left), used to walk back out of sub-pages
    _BACK_X, _BACK_Y = 0.022, 0.039

    async def _ocr(
        self,
        ctx: TaskContext,
        *,
        region: Rect | None = None,
        ready: Callable[[OcrResult], bool] | None = None,
        retries: int | None = None,
    ) -> OcrScan:
        return await ocr_scan_with_retry(
            ctx,
            region=region,
            retries=self._OCR_RETRIES if retries is None else retries,
            retry_delay=self._OCR_RETRY_DELAY,
            ready=ready,
        )

    async def _ensure_hub(
        self, ctx: TaskContext, run_log: RunLog | None,
        snap_label: str = "hub",
    ) -> str | None:
        """Wake + return to hub, then template-match-verify.

        Returns ``None`` on success or a failure reason string (caller
        turns it into a ``failed`` TaskResult message).
        """
        await WakeHubUiAction().run(ctx)
        await SleepOp(seconds=0.15).run(ctx)
        result = await ReturnToHubAction().run(ctx)
        if not result.success:
            ctx.logger.error("  hub: FAILED cannot return to hub")
            return "Cannot return to hub"
        await SleepOp(seconds=0.5).run(ctx)

        # Verify hub via fast template match (~5ms).  Skip the OCR
        # pre-check for "前往作战" — when the hub is in a transitional
        # state right after returning, the text may flicker and trigger
        # ~10s of OCR retries.  WakeHubUiAction already ran above and
        # the template check below is the authoritative signal.
        hub_check = await OnPageCheck(page="main_hub").evaluate(ctx)
        if not hub_check.passed:
            ctx.logger.warning(
                "  hub: template mismatch after return; waking once more"
            )
            await WakeHubUiAction().run(ctx)
            await SleepOp(seconds=0.3).run(ctx)
            hub_check = await OnPageCheck(page="main_hub").evaluate(ctx)
            if not hub_check.passed:
                ctx.logger.error("  hub: not on hub after second wake")
                return "Not on hub page"
        if run_log:
            run_log.snap(ctx.device, snap_label)
        return None

    async def _enter_activity_page(
        self, ctx: TaskContext, run_log: RunLog | None,
    ) -> bool:
        """Find H label in hub, click ~50px below to enter activity page."""
        # Find "H" label via OCR (small region for speed)
        scan = await self._ocr(
            ctx,
            region=self._H_SEARCH_REGION,
            ready=lambda ocr: any(item.text.strip() == "H" for item in ocr.items),
        )
        h_label = None
        for item in scan.result.items:
            if item.text.strip() == "H":
                h_label = item
                break

        if h_label:
            hx = h_label.region.x + h_label.region.w // 2
            hy = h_label.region.y + h_label.region.h // 2
            click_px = hx
            # Activity entrance is ~50px below H (720p reference); scale to
            # the screenshot the OCR ran on (scan.image).
            _img_h = scan.image.shape[0]
            click_py = hy + int(50 * _img_h / 720)
            ctx.logger.info(
                f"  nav: H found at ({hx},{hy}), "
                f"clicking activity at ({click_px},{click_py})"
            )
            await ClickPxOp(px=click_px, py=click_py, wait=0.5).run(ctx)
        else:
            # Fallback from verified data.  Log what the region OCR *did*
            # see — if it keeps reading a non-"H" label (icon glyph, other
            # text) we can retarget the ready-check on the next run.
            ctx.logger.debug(
                f"  nav: H region OCR texts: "
                f"{[i.text for i in scan.result.items]}"
            )
            click_x, click_y = 0.858, 0.211  # 1372,190 @ 1600x900
            ctx.logger.warning(
                f"  nav: H not found via OCR, "
                f"using fallback ({click_x},{click_y})"
            )
            await ClickOp(x=click_x, y=click_y, wait=0.5).run(ctx)
        if run_log:
            run_log.snap(ctx.device, "activity_page")

        # Verify: one OCR pass to check for activity page keywords
        scan = await self._ocr(
            ctx,
            ready=lambda ocr: (
                ocr.has("前往挑战")
                or ocr.has("福利")
                or ocr.has("支线")
                or ocr.has("协议")
            ),
        )
        ocr = scan.result
        if (
            ocr.has("前往挑战")
            or ocr.has("福利")
            or ocr.has("支线")
            or ocr.has("协议")
        ):
            ctx.logger.info("  nav: activity page verified")
            return True

        ctx.logger.warning("  nav: could not verify activity page")
        return True  # Proceed anyway — later steps have their own verification

    async def _safe_return_to_hub(self, ctx: TaskContext) -> None:
        """Return to hub from any depth in the activity flow.

        Alternates between back button and ESC, since some pages only
        respond to one or the other. Checks for hub after each attempt
        via template matching.
        """
        ctx.logger.info("  return: navigating back to hub")
        for i in range(8):
            hub_check = await OnPageCheck(page="main_hub").evaluate(ctx)
            if hub_check.passed:
                ctx.logger.info(f"  return: hub reached after {i} actions")
                return

            # Alternate: even = back button, odd = ESC
            if i % 2 == 0:
                ctx.logger.debug(
                    f"  return: clicking back ({self._BACK_X},{self._BACK_Y}) [{i}]"
                )
                await ClickOp(x=self._BACK_X, y=self._BACK_Y, wait=1.0).run(ctx)
            else:
                ctx.logger.debug(f"  return: pressing ESC [{i}]")
                await PressKeyOp(key=VK_ESCAPE, wait=1.0).run(ctx)

        # Final fallback
        ctx.logger.info("  return: using ReturnToHubAction as fallback")
        await ReturnToHubAction().run(ctx)
        await SleepOp(seconds=1.0).run(ctx)


class JointDefenseSweep(_ActivityPageNav):
    """Sweep the 联防协议 (Joint Defense) activity — 震动 stage.

    Navigation:
        hub → activity page (below H mail shortcut) → 联防协议 (scroll if needed)
        → 前往挑战 → 信息集纳 → 震动 → max multiplier (>>) → 扫荡
        → confirm → dismiss result → return to hub

    Identification methods:
        - Template match: verify hub page
        - OCR (batch): find "前往作战" (hub active), "联防协议" (activity list),
               "前往挑战", "信息集纳", "震动", "扫荡"
        - Fixed coord: H button offset for activity entrance,
                       << / >> button for multiplier (graphical, OCR can't read)

    Verified coordinates (2026-04-06, pixel-mapped):
        - H label: ~(1372, 140), activity entrance: ~(1372, 190)
        - 联防协议: found via OCR + scroll in left column
        - 前往挑战: OCR ~(1440, 839)
        - 信息集纳: OCR ~(1146, 839)
        - 震动: OCR ~(319, 497) on map
        - 掉落倍数 <<: fixed (1180, 712), >>: fixed (1552, 712)
        - 扫荡: OCR ~(1252, 841)
    """

    name = "joint_defense_sweep"
    description = "Sweep 联防协议 (Joint Defense) 震动 stage for drops"
    category = "daily_activity"
    requires_pages = ("main_hub",)
    requires_ocr = True
    safe = False  # Consumes 吨吨值 (30 per sweep)

    # Multiplier buttons: 5-button layout << < [xN] > >>
    # Pixel-mapped from 008_jd_after_max_multi.jpg darkness scan:
    #   << button: half(590,355) = full(1180,710)  ← reset to min
    #   >> button: half(776,355) = full(1552,710)  ← set to max
    _MIN_MULTI_X = 0.738    # 1180 / 1600
    _MIN_MULTI_Y = 0.791    # 712 / 900
    _MAX_MULTI_X = 0.97     # 1552 / 1600
    _MAX_MULTI_Y = 0.791    # 712 / 900
    _MAX_SCROLL_ATTEMPTS = 5

    async def can_run(self, ctx: TaskContext) -> bool:
        return True

    async def execute(self, ctx: TaskContext) -> TaskResult:
        run_log: RunLog | None = getattr(ctx, "run_log", None)

        ctx.logger.info("=== JointDefenseSweep: starting ===")

        # ── Step 1: Return to hub ──
        ctx.logger.info("[Step 1] Return to hub")
        reason = await self._ensure_hub(ctx, run_log, snap_label="jd_hub")
        if reason:
            return TaskResult(status="failed", message=reason)

        # ── Step 2: Enter activity page ──
        ctx.logger.info("[Step 2] Enter activity page (below H button)")
        nav_ok = await self._enter_activity_page(ctx, run_log)
        if not nav_ok:
            ctx.logger.error("[Step 2] FAILED: cannot enter activity page")
            return TaskResult(
                status="failed", message="Cannot enter activity page"
            )

        # ── Step 3: Find and click 联防协议 ──
        ctx.logger.info("[Step 3] Find '联防协议' in activity list")
        jd_ok = await self._find_and_click_joint_defense(ctx, run_log)
        if not jd_ok:
            ctx.logger.error("[Step 3] FAILED: '联防协议' not found")
            await self._safe_return_to_hub(ctx)
            return TaskResult(
                status="failed", message="联防协议 not found in activity list"
            )

        # ── Step 4: Click 前往挑战 ──
        ctx.logger.info("[Step 4] Click '前往挑战'")
        challenge_ok = await self._click_challenge(ctx, run_log)
        if not challenge_ok:
            ctx.logger.error("[Step 4] FAILED: challenge button not found")
            await self._safe_return_to_hub(ctx)
            return TaskResult(
                status="failed", message="Challenge button not found"
            )

        # ── Step 5: Click 信息集纳 ──
        ctx.logger.info("[Step 5] Click '信息集纳'")
        await self._click_info_collection(ctx, run_log)

        # ── Step 6: Click 震动 ──
        ctx.logger.info("[Step 6] Click '震动'")
        quake_ok = await self._click_quake(ctx, run_log)
        if not quake_ok:
            ctx.logger.error("[Step 6] FAILED: '震动' not found")
            await self._safe_return_to_hub(ctx)
            return TaskResult(status="failed", message="震动 not found on map")

        # ── Step 7: Max multiplier + sweep ──
        ctx.logger.info("[Step 7] Max multiplier and sweep")
        sweep_ok = await self._max_multi_and_sweep(ctx, run_log)
        if not sweep_ok:
            ctx.logger.error("[Step 7] FAILED: sweep failed")
            await self._safe_return_to_hub(ctx)
            return TaskResult(status="failed", message="Sweep failed")

        # ── Step 8: Confirm and dismiss ──
        ctx.logger.info("[Step 8] Confirm sweep and dismiss result")
        swept = await self._confirm_and_dismiss(ctx, run_log)
        if not swept:
            # Stamina insufficient - sweep cancelled, don't report success.
            ctx.logger.warning("[Step 8] Sweep cancelled (stamina insufficient)")
            await self._safe_return_to_hub(ctx)
            return TaskResult(
                status="skipped",
                message="联防协议: 体力不足，扫荡取消",
            )

        # ── Step 9: Collect 联防协议 rewards ──
        ctx.logger.info("[Step 9] Navigate back to collect 联防协议 rewards")
        await self._collect_joint_defense_rewards(ctx, run_log)

        # ── Step 10: Return to hub ──
        ctx.logger.info("[Step 10] Return to hub")
        await self._safe_return_to_hub(ctx)
        if run_log:
            run_log.snap(ctx.device, "jd_final_hub")

        ctx.logger.info("=== JointDefenseSweep: complete ===")
        return TaskResult(
            status="success",
            message="Joint Defense sweep completed",
            data={"stage": "震动"},
        )

    # ------------------------------------------------------------------
    # Step 3: Find and click 联防协议
    # ------------------------------------------------------------------

    async def _find_and_click_joint_defense(
        self, ctx: TaskContext, run_log: RunLog | None,
    ) -> bool:
        """Find '联防协议' in activity list, scrolling if needed.

        Single OCR per scroll attempt — no internal retry/delay, since
        a missing text just means we need to scroll further.
        """

        async def _scan_once() -> tuple[OcrScan, object | None]:
            scan = await ocr_scan_with_retry(ctx, retries=0)
            return scan, scan.result.find("联防协议")

        scan, found = await _scan_once()

        # Scroll down to find
        scroll_down = 0
        while found is None and scroll_down < self._MAX_SCROLL_ATTEMPTS:
            ctx.logger.info(
                f"  search: scrolling down ({scroll_down + 1}/"
                f"{self._MAX_SCROLL_ATTEMPTS})"
            )
            await SwipeOp(
                x1=0.125, y1=0.667, x2=0.125, y2=0.333, duration=300, wait=0.6,
            ).run(ctx)
            if run_log:
                snap_r = await ScreenshotOp().run(ctx)
                run_log.save_image(snap_r.data, f"jd_scroll_down_{scroll_down}")
            scan, found = await _scan_once()
            scroll_down += 1

        # Scroll back up if not found
        if found is None:
            ctx.logger.info("  search: not found scrolling down, scrolling up")
            for i in range(self._MAX_SCROLL_ATTEMPTS + scroll_down):
                await SwipeOp(
                    x1=0.125, y1=0.333, x2=0.125, y2=0.667, duration=300, wait=0.6,
                ).run(ctx)
                if run_log:
                    snap_r = await ScreenshotOp().run(ctx)
                    run_log.save_image(snap_r.data, f"jd_scroll_up_{i}")
                scan, found = await _scan_once()
                if found:
                    break

        if found is None:
            ctx.logger.error("  search: '联防协议' not found after scrolling")
            return False

        jdx = found.region.x + found.region.w // 2
        jdy = found.region.y + found.region.h // 2
        ctx.logger.info(
            f"  search: '联防协议' found at ({jdx},{jdy}) "
            f"conf={found.confidence:.2f}"
        )
        await ClickPxOp(px=jdx, py=jdy, wait=0.5).run(ctx)

        if run_log:
            run_log.snap(ctx.device, "jd_panel")

        # Verify: right panel should show "联防协议"
        scan = await self._ocr(ctx, ready=lambda ocr: ocr.has("联防协议"))
        if scan.result.has("联防协议"):
            ctx.logger.info("  search: right panel verified '联防协议'")
        else:
            ctx.logger.warning("  search: could not verify right panel")
        return True

    # ------------------------------------------------------------------
    # Step 4: Click 前往挑战
    # ------------------------------------------------------------------

    async def _click_challenge(
        self, ctx: TaskContext, run_log: RunLog | None,
    ) -> bool:
        """Click 前往挑战 button."""
        scan = await self._ocr(
            ctx,
            ready=lambda ocr: (
                ocr.find("前往挑战") is not None or ocr.find("挑战") is not None
            ),
        )
        ocr = scan.result
        btn = ocr.find("前往挑战")
        if btn is None:
            btn = ocr.find("挑战")
        if btn is None:
            ctx.logger.error("  challenge: button not found")
            return False

        cx = btn.region.x + btn.region.w // 2
        cy = btn.region.y + btn.region.h // 2
        ctx.logger.info(f"  challenge: clicking '{btn.text}' at ({cx},{cy})")
        await ClickPxOp(px=cx, py=cy, wait=1.0).run(ctx)

        # Handle "前置章节" story prompt — dismiss with ESC (取消)
        scan = await self._ocr(ctx)
        check_ocr = scan.result
        if check_ocr.has("前置章节") or check_ocr.has("剧情观感"):
            ctx.logger.info("  challenge: story prompt detected, pressing ESC")
            await PressKeyOp(key=VK_ESCAPE, wait=0.5).run(ctx)

        if run_log:
            run_log.snap(ctx.device, "jd_after_challenge")
        return True

    # ------------------------------------------------------------------
    # Step 5: Click 信息集纳
    # ------------------------------------------------------------------

    async def _click_info_collection(
        self, ctx: TaskContext, run_log: RunLog | None,
    ) -> None:
        """Click 信息集纳 button (may already be selected)."""
        scan = await self._ocr(
            ctx,
            ready=lambda ocr: (
                ocr.find("信息集纳") is not None
                or ocr.find("集纳") is not None
                or ocr.find("震动") is not None
            ),
        )
        ocr = scan.result
        btn = ocr.find("信息集纳")
        if btn is None:
            btn = ocr.find("集纳")
        if btn:
            cx = btn.region.x + btn.region.w // 2
            cy = btn.region.y + btn.region.h // 2
            ctx.logger.info(
                f"  info: clicking '{btn.text}' at ({cx},{cy})"
            )
            await ClickPxOp(px=cx, py=cy, wait=1.5).run(ctx)
        else:
            ctx.logger.info("  info: '信息集纳' not found, may already be selected")
        if run_log:
            run_log.snap(ctx.device, "jd_info_collection")

    # ------------------------------------------------------------------
    # Step 6: Click 震动
    # ------------------------------------------------------------------

    async def _click_quake(
        self, ctx: TaskContext, run_log: RunLog | None,
    ) -> bool:
        """Click '震动' node on the map."""
        scan = await self._ocr(ctx, ready=lambda ocr: ocr.find("震动") is not None)
        ocr = scan.result
        quake = ocr.find("震动")
        if quake is None:
            ctx.logger.error("  quake: '震动' not found on map")
            return False

        cx = quake.region.x + quake.region.w // 2
        cy = quake.region.y + quake.region.h // 2
        ctx.logger.info(f"  quake: clicking '震动' at ({cx},{cy})")
        await ClickPxOp(px=cx, py=cy, wait=1.5).run(ctx)
        if run_log:
            run_log.snap(ctx.device, "jd_battle_panel")
        return True

    # ------------------------------------------------------------------
    # Step 7: Max multiplier and sweep
    # ------------------------------------------------------------------

    async def _max_multi_and_sweep(
        self, ctx: TaskContext, run_log: RunLog | None,
    ) -> bool:
        """Set multiplier to max available, then click 扫荡.

        Strategy: click << (min) to reset, then >> (max) to set highest
        affordable multiplier. This ensures a clean reset before maximizing.
        Note: at x1, << is not visible, but clicking its position is harmless.
        If the panel closes unexpectedly, re-click 震动 to reopen it.
        """
        # First verify the battle panel is still open
        scan = await self._ocr(
            ctx,
            ready=lambda ocr: ocr.has("扫荡") or ocr.find("震动") is not None,
        )
        ocr = scan.result
        if not ocr.has("扫荡"):
            ctx.logger.warning(
                "  multi: battle panel not open, re-clicking 震动"
            )
            quake = ocr.find("震动")
            if quake:
                cx = quake.region.x + quake.region.w // 2
                cy = quake.region.y + quake.region.h // 2
                await ClickPxOp(px=cx, py=cy, wait=2.0).run(ctx)

        # Step 1: Click << (min) to reset multiplier
        ctx.logger.info(
            f"  multi: clicking << (min) at "
            f"({self._MIN_MULTI_X},{self._MIN_MULTI_Y})"
        )
        await ClickOp(x=self._MIN_MULTI_X, y=self._MIN_MULTI_Y, wait=0.3).run(ctx)

        # Step 2: Click >> (max) to raise to highest affordable multiplier
        ctx.logger.info(
            f"  multi: clicking >> (max) at "
            f"({self._MAX_MULTI_X},{self._MAX_MULTI_Y})"
        )
        await ClickOp(x=self._MAX_MULTI_X, y=self._MAX_MULTI_Y, wait=0.5).run(ctx)

        snap_r = await ScreenshotOp().run(ctx)
        if run_log:
            run_log.save_image(snap_r.data, "jd_after_max_multi")

        # One OCR pass for multiplier + sweep button
        scan = await self._ocr(ctx, ready=lambda ocr: ocr.has("扫荡"))
        ocr = scan.result
        multi_text = ocr.find("x")
        if multi_text:
            ctx.logger.info(
                f"  multi: multiplier now '{multi_text.text}'"
            )

        # Find and click 扫荡
        sweep = ocr.find("扫荡")
        if sweep is None:
            # Panel may have closed — try reopening
            ctx.logger.warning("  sweep: '扫荡' not found, trying to reopen panel")
            quake = ocr.find("震动")
            if quake:
                cx = quake.region.x + quake.region.w // 2
                cy = quake.region.y + quake.region.h // 2
                await ClickPxOp(px=cx, py=cy, wait=2.0).run(ctx)
                await ClickOp(
                    x=self._MIN_MULTI_X, y=self._MIN_MULTI_Y, wait=0.3,
                ).run(ctx)
                await ClickOp(
                    x=self._MAX_MULTI_X, y=self._MAX_MULTI_Y, wait=0.5,
                ).run(ctx)
                scan = await self._ocr(ctx, ready=lambda ocr: ocr.has("扫荡"))
                ocr = scan.result
                sweep = ocr.find("扫荡")

        if sweep is None:
            ctx.logger.error("  sweep: '扫荡' button still not found")
            return False

        sx = sweep.region.x + sweep.region.w // 2
        sy = sweep.region.y + sweep.region.h // 2
        ctx.logger.info(f"  sweep: clicking '扫荡' at ({sx},{sy})")
        await ClickPxOp(px=sx, py=sy, wait=1.5).run(ctx)
        if run_log:
            run_log.snap(ctx.device, "jd_sweep_confirm")
        return True

    # ------------------------------------------------------------------
    # Step 8: Confirm and dismiss result
    # ------------------------------------------------------------------

    async def _confirm_and_dismiss(
        self, ctx: TaskContext, run_log: RunLog | None,
    ) -> bool:
        """Confirm sweep popup and dismiss result screen.

        Returns:
            True if the sweep actually went through; False if it was
            cancelled (stamina insufficient) and must NOT be reported
            as a successful sweep.

        Flow:
        1. Sweep confirm popup → Enter (确定)
        2. Wait for sweep animation
        3. Check for stamina-insufficient popup (补充吨吨值) → ESC to cancel
        4. Sweep result screen — press Enter multiple times to dismiss
        """
        # 1. Confirm sweep popup
        ctx.logger.info("  confirm: pressing Enter to confirm sweep")
        await PressKeyOp(key=VK_ENTER, wait=2.0).run(ctx)

        if run_log:
            run_log.snap(ctx.device, "jd_sweep_result")

        # 2. Check for stamina-insufficient popup (one OCR pass)
        scan = await self._ocr(ctx)
        ocr = scan.result
        if ocr.has("补充") or ocr.has("冷却剂") or ocr.has("吨吨值"):
            ctx.logger.info(
                "  confirm: stamina-insufficient popup detected, "
                "pressing ESC to cancel"
            )
            await PressKeyOp(key=VK_ESCAPE, wait=0.5).run(ctx)
            if run_log:
                run_log.snap(ctx.device, "jd_stamina_popup_canceled")
            return False  # Sweep didn't happen — caller must not report success

        # 3. Dismiss result screen — wait for animation, then rapid Enter
        await SleepOp(seconds=2.0).run(ctx)
        for _ in range(5):
            await PressKeyOp(key=VK_ENTER, wait=0.2).run(ctx)

        if run_log:
            run_log.snap(ctx.device, "jd_after_dismiss")
        return True

    # ------------------------------------------------------------------
    # Step 9: Collect 联防协议 rewards
    # ------------------------------------------------------------------

    async def _collect_joint_defense_rewards(
        self, ctx: TaskContext, run_log: RunLog | None,
    ) -> None:
        """Navigate back to 联防协议 detail page and click 一键领取 rewards.

        After sweep dismissal, press back to return to the 联防协议 detail
        page (where 前往挑战 was visible), then claim all completion rewards.

        The claim is gated on OCR-detecting the "一键领取" button itself
        rather than a red-dot badge. The button only exists when there is
        something to claim, so detecting it is both the presence signal and
        the click target — far more reliable than the previous single-pixel
        red-dot gate, which produced false negatives (rewards present but the
        step reported "no red dot" and never claimed).
        """
        # Navigate back from challenge map to 联防协议 detail page
        for i in range(4):
            ctx.logger.info(f"  rewards: pressing back [{i}]")
            await ClickOp(x=0.022, y=0.039, wait=1.0).run(ctx)

            # Check if we see 前往挑战 — means we're on 联防协议 detail page
            scan = await self._ocr(ctx, ready=lambda ocr: ocr.has("前往挑战"))
            if scan.result.has("前往挑战"):
                ctx.logger.info("  rewards: reached 联防协议 detail page")
                break
        else:
            ctx.logger.warning(
                "  rewards: could not reach 联防协议 detail page"
            )
            return

        # ── Gate the claim on the actual "一键领取" button ──
        # The button only appears when there are pending rewards, so detecting
        # it via OCR is both the "is there anything to claim?" signal and the
        # click target. No red dot lookup → no false-negative skip.
        claim_check = await FindTextCheck(target="一键领取").evaluate(ctx)
        if not claim_check.passed:
            ctx.logger.info(
                "  rewards: no '一键领取' button — nothing to claim, skipping"
            )
            return

        btn = claim_check.data
        cx = btn.region.x + btn.region.w // 2
        cy = btn.region.y + btn.region.h // 2
        ctx.logger.info(
            f"  rewards: found '一键领取' at ({cx},{cy}) — claiming"
        )
        await ClickPxOp(px=cx, py=cy, wait=1.5).run(ctx)

        # Dismiss any reward popup
        await PressKeyOp(key=VK_ENTER, wait=1.0).run(ctx)

        if run_log:
            run_log.snap(ctx.device, "jd_rewards_collected")


class InvitationRewardClaim(_ActivityPageNav):
    """邀约奖励 — claim 见闻 rewards for each invitation event.

    Flow (user-verified 2026-11-23, screenshot-confirmed):
        hub → activity page (H shortcut) → for each title in the left
        column — 夜宴之邀, 观星手记, 月色予梦, 咫尺身畔, 奇响派对:
            1. click the title
            2. OCR '前往邀约' → click
            3. OCR '见闻' → click
            4. OCR '一键领取' (preferred) or '领取' → click → Enter popup
            5. back ×2 to the activity page
        → return to hub

    Per-title failures (title / button not found — e.g. event locked or
    not running) are logged and skipped; the loop continues with the
    next title. Only a completely wrong page (no title found at all)
    or a navigation failure fails the task.
    """

    name = "invitation_reward_claim"
    description = "邀约奖励: 依次领取各邀约的见闻奖励"
    category = "daily_activity"
    requires_pages = ("main_hub",)
    requires_ocr = True
    safe = True  # claim-only, spends nothing

    # Invitation titles in the activity page's left column, top to bottom.
    # NOTE: the 5th event is 奇响派对 ("party") — an earlier 奇响排队 typo
    # made OCR miss it every run (field log 2026-11-23).
    _TITLES = ("夜宴之邀", "观星手记", "月色予梦", "咫尺身畔", "奇响派对")
    # Field log 2026-11-23: a 一键领取 reward popup can consume an extra
    # back press — returning once needed 3 presses. Keep headroom.
    _MAX_BACKS = 5

    async def can_run(self, ctx: TaskContext) -> bool:
        return True

    async def execute(self, ctx: TaskContext) -> TaskResult:
        run_log: RunLog | None = getattr(ctx, "run_log", None)

        ctx.logger.info("=== InvitationRewardClaim: starting ===")

        # ── Step 1: Return to hub ──
        ctx.logger.info("[Step 1] Return to hub")
        reason = await self._ensure_hub(ctx, run_log, snap_label="inv_hub")
        if reason:
            return TaskResult(status="failed", message=reason)

        # ── Step 2: Enter activity page ──
        ctx.logger.info("[Step 2] Enter activity page (below H button)")
        nav_ok = await self._enter_activity_page(ctx, run_log)
        if not nav_ok:
            return TaskResult(
                status="failed", message="Cannot enter activity page"
            )

        # ── Step 3: Claim each invitation in order ──
        claimed = 0
        skipped = 0
        titles_found = 0
        for title in self._TITLES:
            ctx.logger.info(f"[Step 3] Invitation '{title}'")
            ok, found = await self._claim_one(ctx, title, run_log)
            titles_found += found
            if ok:
                claimed += 1
            else:
                skipped += 1
            # Back out to the activity page regardless of the outcome,
            # so the next title attempt starts from a known state.
            back_ok = await self._back_to_activity_page(ctx, run_log)
            if not back_ok:
                ctx.logger.error(
                    f"[Step 3] could not return to activity page after "
                    f"'{title}' — aborting"
                )
                return TaskResult(
                    status="failed",
                    message=f"Lost after '{title}' — could not return to "
                            f"activity page",
                )

        if titles_found == 0:
            # Not a single title was found — we are almost certainly on
            # the wrong page; report it instead of faking success.
            # (All titles found but already claimed is a normal success.)
            ctx.logger.error("[Step 3] no invitation title found at all")
            return TaskResult(
                status="failed",
                message="No invitation title found on activity page",
            )

        # ── Step 4: Return to hub ──
        ctx.logger.info("[Step 4] Return to hub")
        await self._safe_return_to_hub(ctx)
        if run_log:
            run_log.snap(ctx.device, "inv_final_hub")

        ctx.logger.info(
            f"=== InvitationRewardClaim: complete "
            f"(claimed={claimed}, skipped={skipped}) ==="
        )
        return TaskResult(
            status="success",
            message=f"邀约奖励领取完成 (claimed={claimed}, skipped={skipped})",
            data={"claimed": claimed, "skipped": skipped},
        )

    # ------------------------------------------------------------------
    # Per-title claim
    # ------------------------------------------------------------------

    @staticmethod
    def _find_title(ocr: OcrResult, title: str) -> Any:
        """Find a title item, tolerating OCR segmentation variance.

        Exact substring first. RapidOCR occasionally splits a title into
        separate items ("咫尺" + "身畔") or misreads one character, which
        defeats exact matching forever (field log 2026-11-23: 咫尺身畔
        never matched while its neighbours did, despite sitting in a
        visibly empty slot between them). Fall back to any item sharing
        a 2-char bigram with the title — titles are unique within the
        left column, so a bigram hit is unambiguous.
        """
        hit = ocr.find(title)
        if hit is not None:
            return hit
        bigrams = [title[i:i + 2] for i in range(len(title) - 1)]
        for item in ocr.items:
            if any(b in item.text for b in bigrams):
                return item
        return None

    async def _claim_one(
        self, ctx: TaskContext, title: str, run_log: RunLog | None,
    ) -> tuple[bool, bool]:
        """Claim one invitation: title → 前往邀约 → 见闻 → 领取.

        Returns ``(claimed, title_found)``:

        - ``(True, True)`` — a claim button was clicked.
        - ``(False, True)`` — the title was processed but there was
          nothing to claim (already claimed / rewards unavailable).
        - ``(False, False)`` — the title or a navigation target was
          missing (event locked / not running); caller skips to the
        next title and walks back to the activity page.
        """
        # 1. Click the title in the left column
        def _title_ready(ocr: OcrResult) -> bool:
            return self._find_title(ocr, title) is not None

        scan = await self._ocr(
            ctx,
            region=self._LEFT_COLUMN,
            ready=_title_ready,
        )
        hit = self._find_title(scan.result, title)
        if hit is None:
            # List may have been scrolled (selection auto-scroll) or OCR
            # flaked — nudge the list both ways and rescan before giving
            # up. Coordinates always come from live OCR, so a shifted
            # list is harmless.
            for swipe_up in (True, False):
                await SwipeOp(
                    x1=0.125, y1=0.55, x2=0.125,
                    y2=0.3 if swipe_up else 0.8,
                    duration=300, wait=0.6,
                ).run(ctx)
                scan = await self._ocr(
                    ctx, region=self._LEFT_COLUMN, ready=_title_ready,
                )
                hit = self._find_title(scan.result, title)
                if hit is not None:
                    break
        if hit is None:
            # Diagnostic: log what the region OCR *did* read so a stubborn
            # title can be retargeted from the next run's log.
            ctx.logger.debug(
                f"  '{title}' left column OCR texts: "
                f"{[i.text for i in scan.result.items]}"
            )
            ctx.logger.info(f"  '{title}' not in left column — skipping")
            return False, False
        hx = hit.region.x + hit.region.w // 2
        hy = hit.region.y + hit.region.h // 2
        ctx.logger.info(f"  title: clicking '{title}' at ({hx},{hy})")
        await ClickPxOp(px=hx, py=hy, wait=1.0).run(ctx)

        # 2. Click 前往邀约 (兼容 '邀约')
        scan = await self._ocr(
            ctx,
            ready=lambda ocr: (
                ocr.find("前往邀约") is not None or ocr.find("邀约") is not None
            ),
        )
        ocr = scan.result
        btn = ocr.find("前往邀约")
        if btn is None:
            btn = ocr.find("邀约")
        if btn is None:
            ctx.logger.info(
                f"  '{title}': 前往邀约 button not found — skipping"
            )
            return False, False
        bx = btn.region.x + btn.region.w // 2
        by = btn.region.y + btn.region.h // 2
        ctx.logger.info(f"  invite: clicking '{btn.text}' at ({bx},{by})")
        await ClickPxOp(px=bx, py=by, wait=1.5).run(ctx)
        if run_log:
            run_log.snap(ctx.device, f"inv_{title}_entered")

        # 3. Click 见闻
        scan = await self._ocr(
            ctx, ready=lambda ocr: ocr.find("见闻") is not None,
        )
        tab = scan.result.find("见闻")
        if tab is None:
            ctx.logger.info(f"  '{title}': 见闻 tab not found — skipping")
            return False, False
        tx = tab.region.x + tab.region.w // 2
        ty = tab.region.y + tab.region.h // 2
        ctx.logger.info(f"  tab: clicking '见闻' at ({tx},{ty})")
        await ClickPxOp(px=tx, py=ty, wait=1.0).run(ctx)
        if run_log:
            run_log.snap(ctx.device, f"inv_{title}_jiwen")

        # 4. Claim — prefer 一键领取, fall back to a plain 领取 that is
        # NOT "已领取" (already claimed — a substring false-match that
        # was clicked blindly in the field, 2026-11-23 log).
        scan = await self._ocr(
            ctx,
            ready=lambda ocr: (
                self._claimable(ocr) is not None or ocr.has("已领取")
            ),
        )
        ocr = scan.result
        claim = self._claimable(ocr)
        if claim is None:
            if ocr.has("已领取"):
                ctx.logger.info(
                    f"  '{title}': rewards already claimed — skipping"
                )
            else:
                ctx.logger.info(f"  '{title}': nothing to claim — skipping")
            return False, True
        cx = claim.region.x + claim.region.w // 2
        cy = claim.region.y + claim.region.h // 2
        ctx.logger.info(
            f"  claim: clicking '{claim.text}' at ({cx},{cy})"
        )
        await ClickPxOp(px=cx, py=cy, wait=1.5).run(ctx)

        # Dismiss any reward popup
        await PressKeyOp(key=VK_ENTER, wait=1.0).run(ctx)
        if run_log:
            run_log.snap(ctx.device, f"inv_{title}_claimed")
        return True, True

    @staticmethod
    def _claimable(ocr: OcrResult) -> Any:
        """Pick the claim button: 一键领取 preferred, else plain 领取.

        "已领取" (already claimed) contains "领取" as a substring and
        must never be clicked.
        """
        claim = ocr.find("一键领取")
        if claim is not None:
            return claim
        for item in ocr.find_all("领取"):
            if "已领取" not in item.text:
                return item
        return None

    # ------------------------------------------------------------------
    # Back out to the activity page
    # ------------------------------------------------------------------

    async def _on_activity_page(self, ctx: TaskContext) -> bool:
        """OCR the left column: is the invitation list visible there?

        Must require >=2 titles INSIDE the left-column region. Matching
        "any title anywhere on screen" false-positived on the invite
        sub-page, whose header shows the event title itself — the walker
        then stopped one back-press short of the activity page and every
        remaining title read as "not in left column" (field log
        2026-11-23, 观星手记). Only the real activity page shows the
        multi-entry list, so a 2-title threshold discriminates cleanly.
        """
        scan = await self._ocr(ctx, region=self._LEFT_COLUMN, retries=0)
        ocr = scan.result
        visible = sum(
            1 for t in self._TITLES
            if self._find_title(ocr, t) is not None
        )
        return visible >= 2

    async def _back_to_activity_page(
        self, ctx: TaskContext, run_log: RunLog | None,
    ) -> bool:
        """Walk back to the activity page after one invitation.

        Check-then-press loop: verify the markers first, and only press
        the back button when the activity page is genuinely absent.
        Two guards against overshoot (pressing *past* the activity page
        into the hub, observed in the field 2026-11-23):

        1. Settle re-check — a page transition animation can make the
           verification OCR miss the markers right after a press; wait
           briefly and re-check before pressing again.
        2. Hub recovery — if the hub template matches we have already
           gone too far; re-enter the activity page via the H shortcut
           instead of pressing back again (which does nothing on hub).
        """
        for i in range(self._MAX_BACKS):
            if await self._on_activity_page(ctx):
                ctx.logger.info(f"  back: activity page after {i} presses")
                return True

            # Guard 2: overshot all the way to the hub → re-enter.
            hub = await OnPageCheck(page="main_hub").evaluate(ctx)
            if hub.passed:
                ctx.logger.warning(
                    "  back: overshot to hub — re-entering activity page"
                )
                if not await self._enter_activity_page(ctx, run_log):
                    return False
                if await self._on_activity_page(ctx):
                    return True
                # Still not verified (OCR flake) — keep walking back.

            # Guard 1: settle re-check before pressing again.
            await SleepOp(seconds=1.0).run(ctx)
            if await self._on_activity_page(ctx):
                ctx.logger.info(
                    f"  back: activity page after settle ({i} presses)"
                )
                return True

            ctx.logger.debug(f"  back: pressing back [{i}]")
            await ClickOp(
                x=self._BACK_X, y=self._BACK_Y, wait=1.5,
            ).run(ctx)
            if run_log:
                run_log.snap(ctx.device, f"inv_back_{i}")

        # Final verification — one more OCR pass after the last press
        ok = await self._on_activity_page(ctx)
        if not ok:
            ctx.logger.warning("  back: activity page not re-verified")
        return ok
