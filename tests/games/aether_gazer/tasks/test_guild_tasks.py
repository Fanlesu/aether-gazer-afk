"""Tests for tasks.guild_tasks -- GuildSupplyClaim.

Mock strategy: patch Op classes (ReturnToHubAction.run, ClickOp.run,
PressKeyOp.run) at the guild_tasks namespace, stub RedDotCheck per gate
label so the two red-dot gates yield deterministic results without running
real HSV detection on the mock (black) screenshot, and patch the underlying
OCR function (checks.ocr.ocr_find) for the 矩阵补给 membership check.
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, patch

import numpy as np

from anime_game_afk.core.types import Rect
from anime_game_afk.games.aether_gazer.checks.base import CheckResult
from anime_game_afk.games.aether_gazer.ops.base import OpResult
from anime_game_afk.games.aether_gazer.tasks.base import TaskContext
from anime_game_afk.games.aether_gazer.tasks.guild_tasks import GuildSupplyClaim
from anime_game_afk.vision.types import TextResult


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


# Patch targets for Op classes used by guild tasks
_GUILD = "anime_game_afk.games.aether_gazer.tasks.guild_tasks"
_RETURN_TO_HUB_RUN = f"{_GUILD}.ReturnToHubAction.run"
_CLICK_RUN = f"{_GUILD}.ClickOp.run"
_PRESS_RUN = f"{_GUILD}.PressKeyOp.run"
_RED_DOT = f"{_GUILD}.RedDotCheck"

# Patch target for the OCR membership check
_OCR_FIND = "anime_game_afk.games.aether_gazer.checks.ocr.ocr_find"


def _patch_red_dots(supply: bool, task: bool):
    """Patch RedDotCheck so each gate yields a deterministic CheckResult.

    The gate label distinguishes the two calls:
    - "guild_matrix_supply" -> supply flag
    - "guild_task"          -> task flag
    """
    class _FakeRedDot:
        def __init__(self, *args, label: str = "", image=None, **kwargs):
            self.label = label

        async def evaluate(self, ctx: TaskContext) -> CheckResult:
            if self.label == "guild_matrix_supply":
                passed = supply
            elif self.label == "guild_task":
                passed = task
            else:
                passed = False
            return CheckResult(
                passed=passed,
                data=0.1 if passed else 0.0,
                message="red dot (mocked)",
            )

    return patch(_RED_DOT, _FakeRedDot)


def _patch_ocr_matrix_found(found: bool):
    """Patch ocr_find: return a match for 矩阵补给 (or None) as requested."""
    def side_effect(img, target, **kwargs):
        if target == "矩阵补给" and found:
            return TextResult(
                text="矩阵补给",
                confidence=0.95,
                region=Rect(500, 400, 100, 30),
            )
        return None

    return patch(_OCR_FIND, side_effect=side_effect)


# -- GuildSupplyClaim -- metadata --

def test_guild_supply_name():
    assert GuildSupplyClaim.name == "guild_supply_claim"


def test_guild_supply_metadata():
    assert GuildSupplyClaim.category == "daily"
    assert GuildSupplyClaim.requires_ocr is True
    assert GuildSupplyClaim.safe is True


def test_guild_supply_can_run():
    device = MockDevice()
    ctx = TaskContext(device=device)
    assert _run(GuildSupplyClaim().can_run(ctx)) is True


# -- GuildSupplyClaim -- red-dot gates --

def test_guild_supply_skips_matrix_when_no_supply_red_dot():
    """Gate 1 absent -> matrix supply block skipped (supply_clicked=False)."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    # supply=False, task=True: matrix skipped, guild task still claimed.
    with (
        patch(_RETURN_TO_HUB_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_CLICK_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_PRESS_RUN, AsyncMock(return_value=OpResult(success=True))),
        _patch_red_dots(False, True),
    ):
        result = _run(GuildSupplyClaim().execute(ctx))

    assert result.status == "success"
    assert result.data["supply_clicked"] is False
    assert result.data["task_clicked"] is True


def test_guild_supply_skips_task_when_no_task_red_dot():
    """Gate 2 absent -> guild task block skipped (task_clicked=False)."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    # supply=True, task=False: matrix claimed, guild task skipped.
    # Matrix block runs OCR membership check, so stub 矩阵补给 as found.
    with (
        patch(_RETURN_TO_HUB_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_CLICK_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_PRESS_RUN, AsyncMock(return_value=OpResult(success=True))),
        _patch_red_dots(True, False),
        _patch_ocr_matrix_found(True),
    ):
        result = _run(GuildSupplyClaim().execute(ctx))

    assert result.status == "success"
    assert result.data["supply_clicked"] is True
    assert result.data["task_clicked"] is False


def test_guild_supply_claims_both_when_red_dots_present():
    """Both gates present -> both blocks run."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    with (
        patch(_RETURN_TO_HUB_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_CLICK_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_PRESS_RUN, AsyncMock(return_value=OpResult(success=True))),
        _patch_red_dots(True, True),
        _patch_ocr_matrix_found(True),
    ):
        result = _run(GuildSupplyClaim().execute(ctx))

    assert result.status == "success"
    assert result.data["supply_clicked"] is True
    assert result.data["task_clicked"] is True


def test_guild_supply_skipped_when_no_guild_membership():
    """Gate 1 present but OCR 矩阵补给 missing -> return skipped (no guild)."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    with (
        patch(_RETURN_TO_HUB_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_CLICK_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_PRESS_RUN, AsyncMock(return_value=OpResult(success=True))),
        _patch_red_dots(True, True),
        _patch_ocr_matrix_found(False),
    ):
        result = _run(GuildSupplyClaim().execute(ctx))

    assert result.status == "skipped"
    assert "矩阵补给" in result.message
