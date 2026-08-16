"""Base types for processes (complete user-visible features).

Processes are the top-level units users see and enable.
They compose Layer 6 tasks and are NOT composable by each other.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from anime_game_afk.games.aether_gazer.orchestrator.listener import (
    PipelineListener,
)
from anime_game_afk.games.aether_gazer.tasks.base import TaskContext


@dataclass
class ProcessResult:
    """Result of a complete process."""
    status: Literal["success", "failed", "skipped"]
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProcessContext(TaskContext):
    """Extended context for processes. Adds process-level config and listener."""
    config: dict[str, Any] = field(default_factory=dict)
    listener: PipelineListener | None = None

    def notify_task(self, task_id: str, status: str, message: str = "") -> None:
        """Fire a task status event if a listener is attached."""
        if self.listener is not None:
            self.listener.on_task_status(task_id, status, message)


@runtime_checkable
class Process(Protocol):
    """Protocol for user-visible processes."""
    name: str
    description: str

    async def execute(self, ctx: ProcessContext) -> ProcessResult: ...


class LoopProcess:
    """Base class for processes that repeat a single task indefinitely.

    Concrete subclasses set ``task_cls`` (the :class:`Task` to loop),
    ``task_id`` (the status-notification id), and optionally
    ``max_consecutive_failures``. The loop runs until the process is
    stopped from outside, or ``max_consecutive_failures`` consecutive
    failures occur.

    This removes the copy-pasted ``while True`` loop that used to live in
    each combat-loop process (duowei / lizhan) — the cycle driver,
    consecutive-failure stop, status notification and result aggregation
    now live in exactly one place.
    """

    name: str = ""
    description: str = ""
    task_cls: type = object
    task_id: str = ""
    max_consecutive_failures: int = 3

    async def execute(self, ctx: ProcessContext) -> ProcessResult:
        tag = f"[{self.name or self.__class__.__name__}]"
        task = self.task_cls()
        completed = 0
        failed = 0
        consecutive_failures = 0
        process_t0 = time.monotonic()
        cycle = 0
        stop_reason = "user_stop"

        ctx.logger.info(f"{tag}: starting")

        while True:
            cycle += 1
            ctx.logger.info(
                f"{tag}: cycle {cycle} "
                f"(done={completed}, fail={failed}, consec_fail={consecutive_failures})"
            )
            ctx.notify_task(self.task_id, "running", f"Cycle {cycle}")

            cycle_t0 = time.monotonic()
            result = await task.execute(ctx)
            cycle_elapsed = time.monotonic() - cycle_t0

            if result.status == "success":
                completed += 1
                consecutive_failures = 0
                ctx.notify_task(
                    self.task_id, "success", f"Cycle {cycle}: {result.message}"
                )
                ctx.logger.info(
                    f"{tag}: cycle {cycle} success: "
                    f"{result.message} ({cycle_elapsed:.1f}s)"
                )
            else:
                failed += 1
                consecutive_failures += 1
                ctx.notify_task(
                    self.task_id, "failed", f"Cycle {cycle}: {result.message}"
                )
                ctx.logger.warning(
                    f"{tag}: cycle {cycle} failed: {result.message} "
                    f"({cycle_elapsed:.1f}s) "
                    f"[consec={consecutive_failures}/{self.max_consecutive_failures}]"
                )
                if consecutive_failures >= self.max_consecutive_failures:
                    stop_reason = (
                        f"{self.max_consecutive_failures} consecutive failures"
                    )
                    ctx.logger.error(f"{tag}: Stopping: {stop_reason}")
                    break

        total_elapsed = time.monotonic() - process_t0
        ctx.logger.info(
            f"{tag}: stopped — reason={stop_reason} "
            f"(completed={completed}, failed={failed}) "
            f"total_time={total_elapsed:.1f}s"
        )
        return ProcessResult(
            status="success" if completed > 0 else "failed",
            message=f"Completed {completed} cycles, {failed} failures",
            data={"completed": completed, "failed": failed},
        )
