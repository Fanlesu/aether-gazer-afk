"""Tests for tasks.activity_tasks -- JointDefenseSweep.

Mock strategy: patch Op classes (ClickOp, PressKeyOp.run) at the
activity_tasks namespace, stub RedDotCheck so the reward-claim gate yields a
deterministic result without running real HSV detection on the mock (black)
screenshot, and stub JointDefenseSweep._ocr so the reward-collection helper
reports that it reached the 联防协议 detail page (the page just before hub).
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

from anime_game_afk.games.aether_gazer.checks.base import CheckResult
from anime_game_afk.games.aether_gazer.ops.base import OpResult
from anime_game_afk.games.aether_gazer.tasks.activity_tasks import (
    JointDefenseSweep,
)
from anime_game_afk.games.aether_gazer.tasks.base import TaskContext


@dataclass
class MockDevice:
    click_log: list = field(default_factory=list)
    key_log: list = field(default_factory=list)
    swipe_log: list = field(default_factory=list)

    def screenshot(self) -> np.ndarray:
        return np.zeros((900, 1600, 3), dtype=np.uint8)

    def click(self, x: int, y: int) -> None:
        self.click_log.append((x, y))

    def press_key(self, vk_code: int) -> None:
        self.key_log.append(vk_code)

    def hold_key(self, vk_code: int, duration_s: float) -> None:
        pass

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> None:
        self.swipe_log.append((x1, y1, x2, y2))


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


_ACT = "anime_game_afk.games.aether_gazer.tasks.activity_tasks"
_CLICK = f"{_ACT}.ClickOp"
_PRESS_RUN = f"{_ACT}.PressKeyOp.run"
_RED_DOT = f"{_ACT}.RedDotCheck"


def _patch_red_dot(passed: bool):
    """Patch RedDotCheck at the activity namespace to force pass/fail."""

    class _FakeRedDot:
        def __init__(self, *args, label: str = "", image=None, **kwargs):
            self.label = label

        async def evaluate(self, ctx: TaskContext) -> CheckResult:
            return CheckResult(
                passed=passed,
                data=0.1 if passed else 0.0,
                message="red dot (mocked)",
            )

    return patch(_RED_DOT, _FakeRedDot)


def _stub_at_detail_page(task: JointDefenseSweep) -> None:
    """Make _ocr report the 联防协议 detail page reached (前往挑战 visible)."""
    fake_scan = MagicMock()
    fake_scan.result.has = lambda target: target == "前往挑战"
    task._ocr = AsyncMock(return_value=fake_scan)


def _spy_clicks():
    """Return (clicks, SpyClick) where SpyClick records (x, y) at construction."""
    clicks: list = []

    class _SpyClick:
        def __init__(self, *args, **kwargs):
            clicks.append((kwargs.get("x"), kwargs.get("y")))

        async def run(self, ctx: TaskContext) -> OpResult:
            return OpResult(success=True)

    return clicks, _SpyClick


# -- JointDefenseSweep -- metadata --

def test_joint_defense_name():
    assert JointDefenseSweep.name == "joint_defense_sweep"


def test_joint_defense_can_run():
    device = MockDevice()
    ctx = TaskContext(device=device)
    assert _run(JointDefenseSweep().can_run(ctx)) is True


# -- JointDefenseSweep -- reward-claim red-dot gate (Step 9, 一键领取) --

def test_joint_defense_claims_rewards_when_red_dot_present():
    """Red dot present -> 一键领取 (0.934, 0.829) is clicked."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = JointDefenseSweep()
    _stub_at_detail_page(task)
    clicks, spy = _spy_clicks()
    with (
        patch(_CLICK, spy),
        patch(_PRESS_RUN, AsyncMock(return_value=OpResult(success=True))),
        _patch_red_dot(True),
    ):
        _run(task._collect_joint_defense_rewards(ctx, None))

    assert (0.934, 0.829) in clicks


def test_joint_defense_skips_rewards_when_no_red_dot():
    """Red dot absent -> 一键领取 (0.934,0.829) skipped, but nav still ran."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = JointDefenseSweep()
    _stub_at_detail_page(task)
    clicks, spy = _spy_clicks()
    with (
        patch(_CLICK, spy),
        patch(_PRESS_RUN, AsyncMock(return_value=OpResult(success=True))),
        _patch_red_dot(False),
    ):
        _run(task._collect_joint_defense_rewards(ctx, None))

    assert (0.934, 0.829) not in clicks
    # Back-navigation click (0.022,0.039) still ran to reach the detail page.
    assert (0.022, 0.039) in clicks
