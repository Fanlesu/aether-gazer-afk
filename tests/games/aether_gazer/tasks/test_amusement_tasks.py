"""Tests for tasks.amusement_tasks -- AmusementStreetDaily.

Mock strategy: patch Op classes (ReturnToHubAction.run, ClickOp.run,
ClickPxOp.run, PressKeyOp.run, SleepOp.run) at the amusement_tasks
namespace, stub RedDotCheck so the park-task gate yields a deterministic
result without running real HSV detection on the mock (black) screenshot,
and patch the underlying OCR function (checks.ocr.ocr_find) to None so every
FindTextCheck fails — letting the full execute() reach Step 8's gate while
skipping the optional OCR-driven sub-steps (income, dispatch, training/PvP).
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, patch

import numpy as np

from anime_game_afk.games.aether_gazer.checks.base import CheckResult
from anime_game_afk.games.aether_gazer.ops.base import OpResult
from anime_game_afk.games.aether_gazer.tasks.amusement_tasks import (
    AmusementStreetDaily,
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


# Patch targets for Op classes used by amusement tasks
_AMUSE = "anime_game_afk.games.aether_gazer.tasks.amusement_tasks"
_RETURN_TO_HUB_RUN = f"{_AMUSE}.ReturnToHubAction.run"
_CLICK_RUN = f"{_AMUSE}.ClickOp.run"
_CLICKPX_RUN = f"{_AMUSE}.ClickPxOp.run"
_PRESS_RUN = f"{_AMUSE}.PressKeyOp.run"
_SLEEP_RUN = f"{_AMUSE}.SleepOp.run"
_RED_DOT = f"{_AMUSE}.RedDotCheck"

# Patch target for the OCR checks (FindTextCheck uses ocr_find)
_OCR_FIND = "anime_game_afk.games.aether_gazer.checks.ocr.ocr_find"


def _patch_red_dot(passed: bool):
    """Patch RedDotCheck at the amusement namespace to force pass/fail."""

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


# -- AmusementStreetDaily -- metadata --

def test_amusement_name():
    assert AmusementStreetDaily.name == "amusement_street_daily"


def test_amusement_metadata():
    assert AmusementStreetDaily.category == "daily"
    assert AmusementStreetDaily.requires_ocr is True
    assert AmusementStreetDaily.safe is True


def test_amusement_can_run():
    device = MockDevice()
    ctx = TaskContext(device=device)
    assert _run(AmusementStreetDaily().can_run(ctx)) is True


# -- AmusementStreetDaily -- red-dot gate (Step 8, 游园任务) --

def test_amusement_claims_park_task_when_red_dot_present():
    """Red dot present -> park-task claim block runs (park_task_claimed=True)."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    with (
        patch(_RETURN_TO_HUB_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_CLICK_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_CLICKPX_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_PRESS_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_SLEEP_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_OCR_FIND, return_value=None),
        _patch_red_dot(True),
    ):
        result = _run(AmusementStreetDaily().execute(ctx))

    assert result.status == "success"
    assert result.data["park_task_claimed"] is True


def test_amusement_skips_park_task_when_no_red_dot():
    """Red dot absent -> park-task claim block skipped (park_task_claimed=False)."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    with (
        patch(_RETURN_TO_HUB_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_CLICK_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_CLICKPX_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_PRESS_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_SLEEP_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_OCR_FIND, return_value=None),
        _patch_red_dot(False),
    ):
        result = _run(AmusementStreetDaily().execute(ctx))

    assert result.status == "success"
    assert result.data["park_task_claimed"] is False
