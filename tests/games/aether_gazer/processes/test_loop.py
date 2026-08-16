"""Tests for LoopProcess (processes.base).

LoopProcess is the shared combat-loop driver. These tests pin its
stop-on-consecutive-failure behaviour and confirm it does not swallow
external stops (a crashing task propagates, matching the original
per-process loops).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import numpy as np

from anime_game_afk.games.aether_gazer.processes.base import (
    LoopProcess,
    ProcessContext,
)
from anime_game_afk.games.aether_gazer.tasks.base import TaskResult


class MockDevice:
    def screenshot(self) -> np.ndarray:
        return np.zeros((900, 1600, 3), dtype=np.uint8)
    def click(self, x: int, y: int) -> None: ...
    def press_key(self, vk_code: int) -> None: ...
    def hold_key(self, vk_code: int, duration_s: float) -> None: ...


def _ctx() -> ProcessContext:
    return ProcessContext(device=MockDevice())


def _loop(task_cls: type, **kw) -> LoopProcess:
    attrs: dict = {
        "name": "loop",
        "description": "loop test",
        "task_cls": task_cls,
        "task_id": "loop_task",
        **kw,
    }
    return type("P", (LoopProcess,), attrs)()


def test_loop_stops_on_consecutive_failures():
    class T:
        name = "t"
        can_run = AsyncMock(return_value=True)
        execute = AsyncMock(
            return_value=TaskResult(status="failed", message="boom")
        )

    proc = _loop(T, max_consecutive_failures=3)
    result = asyncio.run(proc.execute(_ctx()))

    assert result.status == "failed"
    assert result.data["failed"] == 3
    assert result.data["completed"] == 0
    assert T.execute.call_count == 3  # stopped exactly at the threshold


def test_loop_counts_completed_until_external_stop():
    calls = {"n": 0}

    class T:
        name = "t"

        async def can_run(self, ctx: ProcessContext) -> bool:
            return True

        async def execute(self, ctx: ProcessContext) -> TaskResult:
            calls["n"] += 1
            if calls["n"] >= 3:
                # Mimic an external kill (e.g. user pressed Stop).
                raise RuntimeError("external stop")
            return TaskResult(status="success")

    proc = _loop(T, max_consecutive_failures=99)
    try:
        asyncio.run(proc.execute(_ctx()))
    except RuntimeError:
        pass  # expected — LoopProcess must not swallow the stop

    assert calls["n"] == 3  # ran 3 cycles, then the external stop propagated
