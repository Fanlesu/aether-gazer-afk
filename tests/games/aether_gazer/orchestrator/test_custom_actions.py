"""Tests for the L3 custom atomic-action executor (custom_actions.py).

Pure-logic: the device, OCR and RedDotCheck are mocked so we can assert the
exact calls and the True/False (satisfied/timeout) contract of each action.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import numpy as np

from anime_game_afk.games.aether_gazer.orchestrator import custom_actions
from anime_game_afk.games.aether_gazer.processes.base import ProcessContext


class MockDevice:
    def __init__(self) -> None:
        self.clicks: list[tuple[float, float]] = []
        self.swipes: list[tuple] = []

    def screenshot(self):
        return np.zeros((900, 1600, 3), dtype=np.uint8)

    def click(self, x: float, y: float) -> None:
        self.clicks.append((x, y))

    def swipe(self, x1: float, y1: float, x2: float, y2: float,
              duration: int) -> None:
        self.swipes.append((x1, y1, x2, y2, duration))


def _ctx() -> ProcessContext:
    return ProcessContext(device=MockDevice(), config={})


def _fake_result(passed: bool):
    class _R:
        pass
    r = _R()
    r.passed = passed
    return r


def test_click_calls_device():
    ctx = _ctx()
    assert asyncio.run(custom_actions.run_custom_action(
        {"type": "click", "x": 0.3, "y": 0.7}, ctx)) is True
    assert ctx.device.clicks == [(0.3, 0.7)]


def test_wait_sleeps():
    ctx = _ctx()
    with patch.object(asyncio, "sleep", new=AsyncMock()):
        assert asyncio.run(custom_actions.run_custom_action(
            {"type": "wait", "seconds": 2}, ctx)) is True


def test_swipe_calls_device():
    ctx = _ctx()
    assert asyncio.run(custom_actions.run_custom_action(
        {"type": "swipe", "x1": 0.1, "y1": 0.8, "x2": 0.1, "y2": 0.2,
         "duration": 400}, ctx)) is True
    assert ctx.device.swipes == [(0.1, 0.8, 0.1, 0.2, 400)]


def test_ocr_wait_finds_text():
    ctx = _ctx()
    with patch.object(custom_actions, "ocr_find", return_value=object()) as f:
        with patch.object(asyncio, "sleep", new=AsyncMock()):
            ok = asyncio.run(custom_actions.run_custom_action(
                {"type": "ocr_wait", "text": "确认", "timeout": 5}, ctx))
    assert ok is True
    f.assert_called_once()


def test_ocr_wait_timeout_returns_false():
    ctx = _ctx()
    with patch.object(custom_actions, "ocr_find", return_value=None):
        with patch.object(asyncio, "sleep", new=AsyncMock()):
            ok = asyncio.run(custom_actions.run_custom_action(
                {"type": "ocr_wait", "text": "确认", "timeout": 0.0}, ctx))
    assert ok is False


def test_reddot_wait_finds():
    ctx = _ctx()
    chk = AsyncMock()
    chk.evaluate = AsyncMock(return_value=_fake_result(True))
    with patch.object(custom_actions, "RedDotCheck", return_value=chk):
        with patch.object(asyncio, "sleep", new=AsyncMock()):
            ok = asyncio.run(custom_actions.run_custom_action(
                {"type": "reddot_wait", "fx": 0.5, "fy": 0.5, "timeout": 5},
                ctx))
    assert ok is True


def test_reddot_wait_timeout_returns_false():
    ctx = _ctx()
    chk = AsyncMock()
    chk.evaluate = AsyncMock(return_value=_fake_result(False))
    with patch.object(custom_actions, "RedDotCheck", return_value=chk):
        with patch.object(asyncio, "sleep", new=AsyncMock()):
            ok = asyncio.run(custom_actions.run_custom_action(
                {"type": "reddot_wait", "fx": 0.5, "fy": 0.5, "timeout": 0.0},
                ctx))
    assert ok is False


def test_unknown_action_type_is_skipped():
    ctx = _ctx()
    assert asyncio.run(custom_actions.run_custom_action(
        {"type": "teleport"}, ctx)) is True
