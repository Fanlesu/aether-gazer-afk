"""Startup tasks — launch game, skip popups, reach hub.

LaunchAndReachHub: Complete startup task that:
1. Ensures game is running (launch if needed)
2. Connects device adapter
3. Skips login screens, loading animations, popups
4. Returns success when the main hub page is detected

SkipStartupPopups: Sub-task for popup dismissal only (assumes game
is already running and device is connected).

Startup flow for 深空之眼 (observed 2026-04-06):
  Epilepsy warning (auto-dismiss ~5s) → Login screen "点击任意区域进入游戏"
  → Loading (~5s) → Hub (possibly with event popups on top)
"""
from __future__ import annotations

from pathlib import Path

from anime_game_afk.games.aether_gazer.checks.ocr import OcrScanCheck
from anime_game_afk.games.aether_gazer.checks.page import AtHubCheck
from anime_game_afk.games.aether_gazer.knowledge.keys import VK_ESCAPE
from anime_game_afk.games.aether_gazer.ops.interact.rapid_click import RapidClickAction
from anime_game_afk.games.aether_gazer.ops.primitives import (
    PressKeyOp,
    SleepOp,
)
from anime_game_afk.games.aether_gazer.tasks.base import TaskContext, TaskResult


class SkipStartupPopups:
    """Dismiss all startup popups until the main hub is reached.

    Assumes the game is already running and the device is connected.
    Uses a multi-strategy approach with stuck detection:

    1. Fast hub check (template match only — 5ms) → success
    2. Full hub check (template + OCR) → success
    3. Detect login screen → click center
    4. Detect loading screen → wait
    5. Detect event/announcement popup → ESC or click close
    6. Detect exit dialog → ESC to cancel
    7. Stuck detection: if 3+ attempts with no screen change → aggressive dismiss

    Metadata:
        name: skip_startup_popups
        category: startup
        requires_ocr: True
        safe: True

    The task is fully idempotent / state-aware: it inspects the current
    screen on every attempt and only does what is needed. This means it is
    safe to run whether the game was just launched (login screen / popups
    showing) or the user already has it open at the hub. Specifically:

    1. Hub check (template match + OCR keyword fallback, robust to 16:10
       and idle hub) -> success.
    2. Exit dialog ("退出游戏"/"是否退出") -> ESC to cancel.
    3. Login screen ("进入游戏"/"点击任意区域") -> click center to enter.
    4. Idle hub (UI hidden, music player visible) -> click center to wake.
    5. Otherwise (loading / event popup / unknown) -> rapid-click a blank
       area to dismiss.
    """

    name = "skip_startup_popups"
    description = "Skip startup popups, events, login until hub is reached"
    category = "startup"
    requires_pages = ("main_hub",)
    requires_ocr = True
    safe = True

    def __init__(self, max_attempts: int = 40) -> None:
        self._max_attempts = max_attempts

    async def can_run(self, ctx: TaskContext) -> bool:
        return True

    async def execute(self, ctx: TaskContext) -> TaskResult:
        """Bring the game to the hub from whatever screen it is on.

        Idempotent and state-aware: it inspects the live screen each attempt
        and only does what is needed (dismiss popups, click to enter a login
        screen, wake an idle hub, or confirm the hub is already reached). Safe
        to call whether the game was just launched or already open.
        """
        ctx.logger.info("=== SkipStartupPopups: starting ===")
        ctx.logger.info("  [startup] Dismissing startup popups")

        try:
            for attempt in range(self._max_attempts):
                # ── Hub check (template + OCR fallback; robust to 16:10) ──
                hub = await AtHubCheck().evaluate(ctx)
                if hub.passed:
                    ctx.logger.debug(f"  [startup] attempt {attempt}: hub detected, confirming")
                    await SleepOp(seconds=0.5).run(ctx)
                    confirm = await AtHubCheck().evaluate(ctx)
                    if confirm.passed:
                        ctx.logger.info(
                            f"  [startup] Hub confirmed after {attempt} attempts"
                        )
                        ctx.logger.info("=== SkipStartupPopups: completed successfully ===")
                        await self._trigger_corrector_interaction(ctx)
                        return TaskResult(
                            status="success",
                            message=f"Hub reached after {attempt} attempts",
                            data={"attempts": attempt},
                        )

                # ── Exit dialog — ESC to cancel ──
                r = await OcrScanCheck().evaluate(ctx)
                ocr = r.data if r.passed else None
                if ocr and (ocr.has("退出游戏") or ocr.has("是否退出")):
                    ctx.logger.info(f"  [startup] attempt {attempt}: exit dialog -> ESC")
                    await PressKeyOp(key=VK_ESCAPE, wait=1.0).run(ctx)
                    continue

                # ── Login screen — click anywhere to enter ──
                # The game may already be showing the login prompt (e.g. the
                # user opened it manually). Click the center to enter instead
                # of relying on the generic blank-area dismiss.
                if ocr and (ocr.has("进入游戏") or ocr.has("点击任意区域")):
                    ctx.logger.info(f"  [startup] attempt {attempt}: login screen -> enter")
                    await RapidClickAction(
                        x=0.5, y=0.5, times=1, interval=0.15,
                    ).run(ctx)
                    continue

                # ── Idle hub (UI hidden) — click center to wake ──
                if hub.data.get("hub_state") == "idle":
                    ctx.logger.info(f"  [startup] attempt {attempt}: idle hub -> wake")
                    await RapidClickAction(
                        x=0.5, y=0.5, times=1, interval=0.15,
                    ).run(ctx)
                    continue

                # ── Rapid click blank area to dismiss popups / loading ──
                ctx.logger.debug(f"  [startup] attempt {attempt}: rapid-clicking to dismiss popups")
                await RapidClickAction(
                    x=0.157, y=0.590, times=10, interval=0.15,
                ).run(ctx)

            # Max attempts exceeded — final check
            ctx.logger.warning(
                f"  [startup] Max attempts ({self._max_attempts}) reached"
            )
            hub_result = await AtHubCheck().evaluate(ctx)
            if hub_result.passed:
                ctx.logger.info("=== SkipStartupPopups: completed (final check) ===")
                await self._trigger_corrector_interaction(ctx)
                return TaskResult(status="success", message="Hub found at final check")

            ctx.logger.error("=== SkipStartupPopups: failed — hub not reached ===")
            return TaskResult(
                status="failed",
                message=f"Could not reach hub after {self._max_attempts} attempts",
            )
        except Exception as exc:
            ctx.logger.error(f"=== SkipStartupPopups: failed — {exc} ===")
            raise

    async def _trigger_corrector_interaction(self, ctx: TaskContext) -> None:
        """Click the screen center three times to trigger 修正者 interaction.

        Per user request, appended to the end of the startup task (after the
        hub is confirmed reached) to open the 修正者 (Corrector) dialogue.
        Center is (0.5, 0.5) in fractional coords (resolution-independent).
        """
        ctx.logger.info(
            "  [startup] triggering 修正者 interaction (3x center click)"
        )
        await RapidClickAction(
            x=0.5, y=0.5, times=3, interval=0.15,
        ).run(ctx)


class LaunchAndReachHub:
    """Complete game launch task: start game → skip popups → reach hub.

    For pipeline integration:
    - Call ensure_game_running() BEFORE device.connect() (Phase 1)
    - Then run this task's execute() after connection (Phase 2)

    Metadata:
        name: launch_and_reach_hub
        category: startup
        requires_ocr: True
        safe: True
    """

    name = "launch_and_reach_hub"
    description = "Launch game, skip startup popups, and reach main hub"
    category = "startup"
    requires_pages = ("main_hub",)
    requires_ocr = True
    safe = True

    def __init__(self, max_popup_attempts: int = 40) -> None:
        self._skip_popups = SkipStartupPopups(max_attempts=max_popup_attempts)

    async def can_run(self, ctx: TaskContext) -> bool:
        return True

    async def execute(self, ctx: TaskContext) -> TaskResult:
        ctx.logger.info("=== LaunchAndReachHub: starting ===")
        ctx.logger.info("=== LaunchAndReachHub: Phase 2 — skip popups ===")
        try:
            result = await self._skip_popups.execute(ctx)
            ctx.logger.info(f"=== LaunchAndReachHub: finished (status={result.status}) ===")
            return result
        except Exception as exc:
            ctx.logger.error(f"=== LaunchAndReachHub: failed — {exc} ===")
            raise


def ensure_game_running(
    exe_path: str,
    window_title: str = "AetherGazer",
    timeout: float = 120,
) -> bool:
    """Phase 1: Ensure the game is running before device connection.

    Call this BEFORE DeviceAdapter.connect() in the pipeline.

    Args:
        exe_path: Full path to the game executable.
        window_title: Window title to wait for.
        timeout: Maximum wait time in seconds.

    Returns:
        True if game is running and window is available.
    """
    from anime_game_afk.engine.game_launcher import GameLauncher

    launcher = GameLauncher(
        exe_path=exe_path,
        window_title=window_title,
        process_name=Path(exe_path).name,
    )

    return launcher.ensure_running(timeout=timeout)
