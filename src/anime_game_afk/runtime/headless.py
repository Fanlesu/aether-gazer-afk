"""Headless runner for scheduled (unattended) task execution.

Invoked when the app is launched with ``--scheduled``.
Runs the configured pipeline without any GUI, writes results to
``config/schedule_log.json``, then exits.

Exit codes:
    0 — All tasks succeeded.
    1 — One or more tasks failed (after optional retry).
"""
from __future__ import annotations

import asyncio
import subprocess
import time
from datetime import datetime

from anime_game_afk.runtime.logger import get_logger
from anime_game_afk.runtime.scheduler import (
    ScheduleConfig,
    append_schedule_log,
    load_schedule_config,
)

logger = get_logger("headless")


def _kill_game() -> None:
    """Kill the AetherGazer game process."""
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/IM", "AetherGazer.exe"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            logger.info("Game process killed")
        else:
            logger.warning("taskkill result: {}", result.stderr.strip())
    except Exception as e:
        logger.warning("Failed to kill game: {}", e)


async def _execute_pipeline(config: ScheduleConfig) -> tuple[bool, str, float]:
    """Run the daily pipeline. Returns (success, message, elapsed_seconds)."""
    from anime_game_afk.config.user_config import UserConfig
    from anime_game_afk.games.aether_gazer.orchestrator.pipeline import Pipeline
    from anime_game_afk.games.aether_gazer.orchestrator.types import (
        PlanConfig,
        ProcessDef,
    )
    from anime_game_afk.games.aether_gazer.processes.base import ProcessContext
    from anime_game_afk.games.aether_gazer.registry import build_registry
    from anime_game_afk.runtime.bootstrap import (
        BootstrapError,
        bootstrap_device,
    )

    start_time = time.monotonic()
    user_cfg = UserConfig.load()
    game_id = "aether_gazer"

    # --- Bring up the game device (shared bootstrap) ---
    try:
        device, game_was_launched = bootstrap_device(user_cfg, logger=logger)
    except BootstrapError as exc:
        return False, str(exc), time.monotonic() - start_time

    res = device.actual_resolution
    logger.info("Connected. Resolution: {}x{}", res.width, res.height)

    # --- Navigate to hub if game was just launched ---
    if game_was_launched:
        try:
            from anime_game_afk.games.aether_gazer.tasks.base import TaskContext
            from anime_game_afk.games.aether_gazer.tasks.startup_tasks import (
                LaunchAndReachHub,
            )
            ctx = TaskContext(device=device, logger=logger)
            launch_task = LaunchAndReachHub(
                max_popup_attempts=user_cfg.popup_dismiss_max_attempts(game_id),
            )
            launch_result = await launch_task.execute(ctx)
            if launch_result.status != "success":
                device.disconnect()
                msg = f"无法到达主界面: {launch_result.message}"
                return False, msg, time.monotonic() - start_time
        except Exception as exc:
            device.disconnect()
            return False, f"启动导航失败: {exc}", time.monotonic() - start_time

    # --- Execute pipeline ---
    registry = build_registry()

    def context_factory(proc_def: ProcessDef) -> ProcessContext:
        return ProcessContext(
            device=device,
            config=proc_def.config,
            logger=get_logger(f"headless.{proc_def.name}"),
        )

    pipeline = Pipeline(
        registry=registry,
        device=device,
        context_factory=context_factory,
    )

    plan = PlanConfig(
        game="aether_gazer",
        processes=[ProcessDef(
            name=config.pipeline_id,
            config={"game_was_launched": game_was_launched},
        )],
    )

    try:
        result = await pipeline.run(plan)
    except Exception as exc:
        device.disconnect()
        return False, f"Pipeline 异常: {exc}", time.monotonic() - start_time

    device.disconnect()
    elapsed = time.monotonic() - start_time

    if result.failed == 0 and not result.aborted:
        msg = f"完成 {result.succeeded} 个任务 ({elapsed:.0f}s)"
        return True, msg, elapsed
    else:
        msg = f"完成 {result.succeeded}, 失败 {result.failed} ({elapsed:.0f}s)"
        return False, msg, elapsed


class HeadlessRunner:
    """Orchestrates scheduled execution with retry and post-action."""

    def __init__(self, config: ScheduleConfig | None = None) -> None:
        self.config = config or load_schedule_config()

    def run(self) -> int:
        """Execute the scheduled pipeline. Returns exit code (0=success)."""
        logger.info("=== Headless scheduled run starting ===")
        logger.info("Config: time={}, days={}, pipeline={}, retry={}, post_action={}",
                     self.config.time, self.config.days, self.config.pipeline_id,
                     self.config.retry_on_failure, self.config.post_action)

        success, message, elapsed = asyncio.run(
            _execute_pipeline(self.config)
        )

        # Retry once if enabled and first attempt failed
        retried = False
        if not success and self.config.retry_on_failure:
            logger.info("First attempt failed, retrying in 30s...")
            time.sleep(30)
            retried = True
            success, message, elapsed2 = asyncio.run(
                _execute_pipeline(self.config)
            )
            elapsed += elapsed2
            if success:
                message = f"[重试成功] {message}"

        # Log result
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "pipeline": self.config.pipeline_id,
            "result": "success" if success else "failed",
            "message": message,
            "duration_s": round(elapsed, 1),
            "retried": retried,
            "post_action": self.config.post_action,
        }
        try:
            append_schedule_log(log_entry)
        except Exception as e:
            logger.error("Failed to write schedule log: {}", e)

        logger.info("Result: {} | {}", "SUCCESS" if success else "FAILED", message)

        # Post-action
        if self.config.post_action == "kill_game":
            logger.info("Post-action: killing game process")
            _kill_game()

        # Notification
        try:
            from anime_game_afk.core.notifier import notify
            icon = "✅" if success else "❌"
            notify(f"{icon} 定时任务{'完成' if success else '失败'}", message)
        except Exception:
            pass

        logger.info("=== Headless run finished (exit_code={}) ===",
                     0 if success else 1)
        return 0 if success else 1
