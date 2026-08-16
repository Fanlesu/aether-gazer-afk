"""Subprocess worker entry point for pipeline execution.

Runs as a child process so the parent GUI can ``process.kill()`` it for
reliable stop.  Communicates with the parent via a JSON-line protocol on
stdout; all log output goes to stderr only.

Usage::

    python -m anime_game_afk.ui.worker --pipeline daily_routine \\
        --tasks mail,intel_shards,stamina_packs
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import traceback
from typing import Any

# Force UTF-8 on stdout/stderr so JSON lines containing Chinese characters
# don't crash on systems whose default codec is cp936/cp950/etc.
for _stream_name in ("stdout", "stderr"):
    _s = getattr(sys, _stream_name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# JSON-line helpers
# ---------------------------------------------------------------------------

def _emit(obj: dict[str, Any]) -> None:
    """Write a single JSON object as one line to stdout and flush."""
    line = json.dumps(obj, ensure_ascii=False)
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        # Fallback if stdout reconfigure failed (e.g. exotic locale).
        sys.stdout.buffer.write((line + "\n").encode("utf-8", errors="replace"))
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# JsonLineListener — translates PipelineListener events to JSON lines
# ---------------------------------------------------------------------------

class JsonLineListener:
    """Implements PipelineListener by emitting JSON lines to stdout."""

    def on_task_status(
        self, task_id: str, status: str, message: str = "",
    ) -> None:
        _emit({"type": "task_status", "id": task_id, "status": status,
               "message": message})

    def on_process_status(
        self, name: str, status: str, message: str = "",
    ) -> None:
        _emit({"type": "process_status", "name": name, "status": status,
               "message": message})

    def on_connected(self, resolution: str) -> None:
        _emit({"type": "connected", "resolution": resolution})

    def on_done(
        self, completed: int, failed: int, elapsed_s: float,
    ) -> None:
        _emit({"type": "done", "completed": completed, "failed": failed,
               "elapsed_s": elapsed_s})


# ---------------------------------------------------------------------------
# Notification helper
# ---------------------------------------------------------------------------

def _try_notify(title: str, message: str) -> None:
    """Send a toast notification, swallowing any errors."""
    try:
        from anime_game_afk.core.notifier import notify
        notify(title, message)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Async main loop
# ---------------------------------------------------------------------------

async def _run(
    pipeline_id: str,
    enabled_ids: set[str],
    plan: list | None = None,
) -> int:
    """Execute the requested pipeline and stream status to stdout.

    Returns:
        Exit code — 0 for success, 1 for fatal error.
    """
    # Late imports so the module can be parsed even if deps aren't installed.
    from anime_game_afk.config.user_config import UserConfig
    from anime_game_afk.games.aether_gazer.orchestrator.pipeline import Pipeline
    from anime_game_afk.games.aether_gazer.orchestrator.types import (
        PlanConfig,
        ProcessDef,
    )
    from anime_game_afk.games.aether_gazer.processes.base import ProcessContext
    from anime_game_afk.games.content_pack import get_content_pack
    from anime_game_afk.runtime.bootstrap import (
        BootstrapError,
        bootstrap_device,
    )
    from anime_game_afk.runtime.logger import get_logger

    listener = JsonLineListener()
    logger = get_logger("worker")
    logger.info("Worker started: pipeline={}, tasks={}", pipeline_id, enabled_ids)

    # Preload RapidOCR engine in the background so the first task's first
    # OCR call doesn't pay the ~10s DirectML init cost on the critical path.
    import threading as _threading
    def _preload_ocr():
        try:
            from anime_game_afk.vision.ocr import _get_ocr_engine
            _get_ocr_engine()
        except Exception as exc:  # noqa: BLE001
            logger.debug("OCR preload failed: {}", exc)
    _threading.Thread(target=_preload_ocr, name="OcrPreload", daemon=True).start()

    import platform
    import time as _time
    _worker_start = _time.monotonic()
    logger.info(
        "Environment: Python {} | {} | frozen={}",
        sys.version_info[:3], platform.platform(),
        getattr(sys, "frozen", False),
    )

    user_cfg = UserConfig.load()
    notify_on_complete = user_cfg.notify_on_complete()

    # ---- Bring up the game device (shared bootstrap) ----------------------
    try:
        device, game_was_launched = bootstrap_device(
            user_cfg,
            logger=logger,
            status_cb=lambda m: _emit({"type": "status", "msg": m}),
        )
    except BootstrapError as exc:
        _emit({"type": "error", "msg": str(exc)})
        return 1

    # Best-effort cleanup hooks: any "soft" interpreter shutdown (atexit,
    # SIGTERM, SIGINT) tries to release stuck keys before exit.  This does
    # NOT cover ``proc.kill()`` (TerminateProcess) — the parent runs its
    # own recovery in that case via ``_auto_recover_input``.
    import atexit
    import signal

    def _cleanup_input() -> None:
        """Release stuck keys + unblock input via MaaFw post_inactive."""
        try:
            if device.connected:
                # Full disconnect — also calls post_inactive() which is
                # the only way to release MaaFw's BlockInput from its
                # internal worker thread.
                device.disconnect()
        except Exception:
            pass

    atexit.register(_cleanup_input)
    try:
        signal.signal(signal.SIGTERM, lambda *_: (_cleanup_input(), sys.exit(1)))
        signal.signal(signal.SIGINT, lambda *_: (_cleanup_input(), sys.exit(1)))
    except (ValueError, OSError):
        # signal handlers can't be installed on non-main threads or
        # certain platforms; atexit alone still gives best-effort coverage.
        pass

    res = device.actual_resolution
    listener.on_connected(f"{res.width}x{res.height}")

    # ---- Build pipeline ---------------------------------------------------
    pack = get_content_pack()
    registry = pack.build_registry()

    def context_factory(proc_def: ProcessDef) -> ProcessContext:
        return ProcessContext(
            device=device,
            config=proc_def.config,
            listener=listener,
            logger=get_logger(f"worker.{proc_def.name}"),
        )

    pipeline = Pipeline(
        registry=registry,
        device=device,
        context_factory=context_factory,
    )

    # ---- Build plan from CLI args -----------------------------------------
    config: dict[str, Any] = {
        "enabled_tasks": sorted(enabled_ids),
        "game_was_launched": game_was_launched,
    }
    if plan is not None:  # explicit L1 plan (ordered steps + params)
        config["plan"] = plan
    plan_config = PlanConfig(
        game=pack.game_id,
        processes=[ProcessDef(name=pipeline_id, config=config)],
    )

    # ---- Execute ----------------------------------------------------------
    try:
        result = await pipeline.run(plan_config)
    except Exception as exc:
        _emit({"type": "error", "msg": f"Pipeline error: {exc}"})
        if notify_on_complete:
            _try_notify("❌ 任务失败", f"Pipeline error: {exc}")
        device.disconnect()
        return 1

    listener.on_done(result.succeeded, result.failed, result.elapsed_s)
    device.disconnect()

    if notify_on_complete:
        if result.failed == 0 and not result.aborted:
            _try_notify(
                "✅ 任务完成",
                f"已完成 {result.succeeded} 个任务 ({result.elapsed_s:.0f}s)",
            )
        else:
            _try_notify(
                "⚠️ 任务结束",
                f"完成 {result.succeeded}，失败 {result.failed}",
            )

    _elapsed = _time.monotonic() - _worker_start
    logger.info("Worker finished: succeeded={}, failed={}, elapsed={:.1f}s",
                result.succeeded, result.failed, _elapsed)

    return 0 if not result.aborted and result.failed == 0 else 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse CLI arguments, configure logging, and run the async loop."""
    # Ensure MaaFw DLLs are findable in frozen mode (supplement the rthook)
    if getattr(sys, "frozen", False):
        import os
        from pathlib import Path
        maa_bin = Path(sys._MEIPASS) / "maa" / "bin"  # type: ignore[attr-defined]
        if maa_bin.exists():
            maa_bin_str = str(maa_bin)
            os.environ["MAAFW_BINARY_PATH"] = maa_bin_str
            os.environ["PATH"] = (
                maa_bin_str + os.pathsep + os.environ.get("PATH", "")
            )
            try:
                os.add_dll_directory(maa_bin_str)
            except (OSError, AttributeError):
                pass
            # Preload MaaFw DLLs in dependency order so ctypes finds them
            import ctypes
            for dll_name in ("MaaUtils.dll", "MaaFramework.dll",
                             "MaaToolkit.dll", "MaaWin32ControlUnit.dll"):
                dll_path = maa_bin / dll_name
                if dll_path.exists():
                    try:
                        ctypes.WinDLL(str(dll_path))
                    except OSError:
                        pass

    # Line-buffered stdout for real-time JSON streaming
    if sys.stdout is not None:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

    # Redirect loguru to stderr only (stdout is the JSON protocol channel)
    from loguru import logger

    logger.remove()
    logger.add(
        sys.stderr,
        format="{time:HH:mm:ss} | {level:<7} | {message}",
        level="DEBUG",
    )

    parser = argparse.ArgumentParser(
        description="Subprocess worker for pipeline execution",
    )
    parser.add_argument(
        "--pipeline",
        required=True,
        help="Pipeline ID to execute (e.g. daily_routine)",
    )
    parser.add_argument(
        "--tasks",
        required=True,
        help="Comma-separated list of enabled task IDs",
    )
    parser.add_argument(
        "--plan",
        required=False,
        default=None,
        help="JSON plan: ordered steps with per-task enabled/params",
    )
    args = parser.parse_args()

    enabled_ids = {t.strip() for t in args.tasks.split(",") if t.strip()}
    plan_arg = json.loads(args.plan) if args.plan else None

    try:
        exit_code = asyncio.run(_run(args.pipeline, enabled_ids, plan_arg))
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        _emit({"type": "error", "msg": f"Fatal: {exc}"})
        sys.exit(1)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
