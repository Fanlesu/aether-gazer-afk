"""Tests for tasks.keyin_tasks — JointSpecialOpsSweep grade selection.

Locks the S级 → A级 fallback contract: if 3 refresh attempts find no S级
(red >15%), the task checks for A级 (purple >15%) on the current cards
and continues the sweep flow; only when neither grade is present does it
ESC back to the hub and skip.
"""
import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import numpy as np

from anime_game_afk.games.aether_gazer.knowledge.keys import VK_ESCAPE
from anime_game_afk.games.aether_gazer.tasks.base import TaskContext
from anime_game_afk.games.aether_gazer.tasks.keyin_tasks import (
    JointSpecialOpsSweep,
)


@dataclass
class MockDevice:
    images: list = field(default_factory=list)
    click_log: list = field(default_factory=list)
    key_log: list = field(default_factory=list)

    def screenshot(self) -> np.ndarray:
        if self.images:
            return self.images.pop(0)
        return np.zeros((720, 1280, 3), dtype=np.uint8)
    def click(self, x: float, y: float) -> None:
        self.click_log.append((x, y))
    def press_key(self, vk_code: int) -> None:
        self.key_log.append(vk_code)
    def hold_key(self, vk_code: int, duration_s: float) -> None:
        pass


def _run(coro):
    return asyncio.run(coro)


def _ctx(device=None):
    return TaskContext(device=device or MockDevice())


# BGR colors whose HSV sit inside the class ranges.
_RED = (0, 0, 255)      # H=0   → S级 range
_PURPLE = (255, 0, 255)  # H=150 → A级 range


def _img_with(color: tuple[int, int, int], card_index: int) -> np.ndarray:
    """720p canvas with a filled patch at one card's grade-icon position."""
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    fx, fy = JointSpecialOpsSweep._CARD_GRADE_POSITIONS[card_index]
    px, py = int(fx * 1280), int(fy * 720)
    img[max(0, py - 8):py + 8, max(0, px - 12):px + 12] = color
    return img


# Patch targets for execute()-level tests.
_NAV_PATCH = (
    "anime_game_afk.games.aether_gazer.tasks.keyin_tasks"
    ".JointSpecialOpsSweep._navigate_to_special_ops"
)
_RETURN_RUN = (
    "anime_game_afk.games.aether_gazer.ops.navigate.smart_return"
    ".ReturnToHubAction.run"
)
_WAKE_RUN = (
    "anime_game_afk.games.aether_gazer.ops.navigate.wake_hub_ui"
    ".WakeHubUiAction.run"
)
_S_RANK = (
    "anime_game_afk.games.aether_gazer.tasks.keyin_tasks"
    ".JointSpecialOpsSweep._find_and_select_s_rank"
)
_A_RANK = (
    "anime_game_afk.games.aether_gazer.tasks.keyin_tasks"
    ".JointSpecialOpsSweep._find_and_select_a_rank"
)


# ── Color-scan helpers (direct) ────────────────────────────────


def test_a_rank_fallback_selects_purple_card():
    """Purple >15% at a grade icon → A级 selected, card clicked."""
    device = MockDevice(images=[_img_with(_PURPLE, card_index=1)])
    ctx = _ctx(device)
    task = JointSpecialOpsSweep()

    assert _run(task._find_and_select_a_rank(ctx)) is True
    assert (0.393, 0.329) in device.click_log  # card 2's grade icon


def test_a_rank_fallback_false_when_no_purple():
    """No purple anywhere → A级 not found, no card clicks."""
    device = MockDevice()
    ctx = _ctx(device)
    task = JointSpecialOpsSweep()

    assert _run(task._find_and_select_a_rank(ctx)) is False
    assert device.click_log == []


def test_s_rank_red_still_detected():
    """Red >15% → S级 selected on the first attempt, no refresh click."""
    device = MockDevice(images=[_img_with(_RED, card_index=0)])
    ctx = _ctx(device)
    task = JointSpecialOpsSweep()

    assert _run(task._find_and_select_s_rank(ctx)) is True
    assert (0.084, 0.415) in device.click_log
    assert (0.810, 0.924) not in device.click_log  # 刷新 never clicked


# ── execute() wiring: A级 fallback continues the sweep ─────────


def test_execute_continues_sweep_via_a_rank_fallback():
    """S级 misses ×3 → A级 found → sweep proceeds to success."""
    device = MockDevice()
    ctx = _ctx(device)
    task = JointSpecialOpsSweep()
    with (
        patch(_WAKE_RUN, AsyncMock()),
        patch(_RETURN_RUN, AsyncMock()),
        patch(_NAV_PATCH, AsyncMock(return_value=True)),
        patch(_S_RANK, AsyncMock(return_value=False)),
        patch(_A_RANK, AsyncMock(return_value=True)),
        patch(
            "anime_game_afk.games.aether_gazer.tasks.keyin_tasks"
            ".JointSpecialOpsSweep._min_max_sweep",
            AsyncMock(return_value=True),
        ),
        patch(
            "anime_game_afk.games.aether_gazer.tasks.keyin_tasks"
            ".JointSpecialOpsSweep._confirm_and_dismiss",
            AsyncMock(return_value=True),
        ),
    ):
        result = _run(task.execute(ctx))

    assert result.status == "success"


def test_execute_skips_when_no_s_or_a_rank():
    """Neither S级 nor A级 → ESC + return to hub, status skipped."""
    device = MockDevice()
    ctx = _ctx(device)
    task = JointSpecialOpsSweep()
    with (
        patch(_WAKE_RUN, AsyncMock()),
        patch(_RETURN_RUN, AsyncMock()),
        patch(_NAV_PATCH, AsyncMock(return_value=True)),
        patch(_S_RANK, AsyncMock(return_value=False)),
        patch(_A_RANK, AsyncMock(return_value=False)),
    ):
        result = _run(task.execute(ctx))

    assert result.status == "skipped"
    assert "S/A级" in (result.message or "")
    assert VK_ESCAPE in device.key_log
