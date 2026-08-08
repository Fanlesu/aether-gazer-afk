"""Tests for tasks.mail_tasks -- CollectAllMail.

Updated to match the Op/Check refactoring: mail task now uses
ReturnToHubAction (from ops.navigate.smart_return) instead of a bare
smart_return_to_hub function import.

Updated for fractional coordinate API: _COLLECT_ALL_X/Y are now
fractional [0.0, 1.0] values. device.click_log receives the
converted pixel values via int(frac * design_resolution).

Mock strategy: patch ReturnToHubAction.run at the class level so the
return-to-hub step completes instantly. The primitives (PressKeyOp,
ClickOp) still call through to MockDevice methods, so key_log and
click_log work as before.
"""
import asyncio
from dataclasses import dataclass, field
from unittest.mock import patch, AsyncMock

import numpy as np

from anime_game_afk.games.aether_gazer.knowledge.keys import VK_H, VK_ENTER
from anime_game_afk.games.aether_gazer.ops.base import OpResult
from anime_game_afk.games.aether_gazer.tasks.base import TaskContext
from anime_game_afk.games.aether_gazer.tasks.mail_tasks import (
    CollectAllMail,
    _COLLECT_ALL_X,
    _COLLECT_ALL_Y,
)


@dataclass
class MockDevice:
    click_log: list = field(default_factory=list)
    key_log: list = field(default_factory=list)

    def screenshot(self) -> np.ndarray:
        return np.zeros((900, 1600, 3), dtype=np.uint8)
    def click(self, x: int, y: int) -> None:
        self.click_log.append((x, y))
    def press_key(self, vk_code: int) -> None:
        self.key_log.append(vk_code)
    def hold_key(self, vk_code: int, duration_s: float) -> None:
        pass


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


_SMART_RETURN = (
    "anime_game_afk.games.aether_gazer.ops.navigate.smart_return"
    ".ReturnToHubAction.run"
)


_RED_DOT_PATCH = "anime_game_afk.games.aether_gazer.tasks.mail_tasks.CollectAllMail._red_pixel_ratio"

def _run_with_mocks(device=None, red_dot_ratio=None):
    """Run CollectAllMail.execute() with mocked ReturnToHub + optional red dot.

    If red_dot_ratio is None, the test was written before red-dot detection —
    the check happens before the ReturnToHub mock would kick in, so
    patches are ordered to deliver the intended result.
    """
    device = device or MockDevice()
    ctx = TaskContext(device=device)
    with (
        patch(
            _SMART_RETURN,
            AsyncMock(return_value=OpResult(success=True, data={"attempts": 0})),
        ),
        patch(_RED_DOT_PATCH, return_value=red_dot_ratio if red_dot_ratio is not None else 0.15),
    ):
        result = _run(CollectAllMail().execute(ctx))
    return device, result


def test_collect_all_mail_returns_success():
    _, result = _run_with_mocks(red_dot_ratio=0.15)
    assert result.status == "success"
    assert result.data.get("action") == "mail_collected"


def test_collect_all_mail_skips_without_red_dot():
    """No red dot → task skips immediately."""
    _, result = _run_with_mocks(red_dot_ratio=0.0)
    assert result.status == "skipped"


def test_collect_all_mail_presses_h_shortcut():
    """CollectAllMail uses H shortcut to open mail panel."""
    device, _ = _run_with_mocks(red_dot_ratio=0.15)
    assert VK_H in device.key_log


def test_collect_all_mail_clicks_collect_all():
    """CollectAllMail clicks the collect-all button at verified coordinates."""
    device, _ = _run_with_mocks(red_dot_ratio=0.15)
    assert (_COLLECT_ALL_X, _COLLECT_ALL_Y) in device.click_log


def test_collect_all_mail_dismisses_with_enter():
    """CollectAllMail presses Enter to dismiss reward popup."""
    device, _ = _run_with_mocks(red_dot_ratio=0.15)
    assert VK_ENTER in device.key_log


def test_collect_all_mail_can_run():
    device = MockDevice()
    ctx = TaskContext(device=device)
    assert _run(CollectAllMail().can_run(ctx)) is True


def test_collect_all_mail_name():
    assert CollectAllMail.name == "collect_all_mail"
