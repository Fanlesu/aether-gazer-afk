"""Tests for tasks.mail_tasks -- CollectAllMail.

Updated to match the Op/Check refactoring: mail task now uses
ReturnToHubAction (from ops.navigate.smart_return) instead of a bare
smart_return_to_hub function import.

Updated for fractional coordinate API: _COLLECT_ALL_X/Y are now
fractional [0.0, 1.0] values. device.click_log receives the
converted pixel values via int(frac * design_resolution).

Red-dot detection now lives in vision.color.red_dot_ratio and is
called from can_run (gates the whole task at the hub). can_run is
patched so execute() can be tested in isolation.

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
    return asyncio.run(coro)


_SMART_RETURN = (
    "anime_game_afk.games.aether_gazer.ops.navigate.smart_return"
    ".ReturnToHubAction.run"
)

# Patch target for the red-dot gate: RedDotCheck.evaluate, looked up from
# where mail_tasks imports it.
_RED_DOT_PATCH = (
    "anime_game_afk.games.aether_gazer.tasks.mail_tasks.RedDotCheck.evaluate"
)


def _red_dot_result(ratio: float):
    from anime_game_afk.games.aether_gazer.checks.base import CheckResult
    return AsyncMock(return_value=CheckResult(passed=ratio > 0, data=ratio))


def _run_with_mocks(device=None, red_dot=0.15):
    """Run CollectAllMail.execute() with mocked ReturnToHub + red dot.

    can_run is bypassed (we test it separately); execute() calls
    ScreenshotOp then proceeds straight to pressing H.
    """
    device = device or MockDevice()
    ctx = TaskContext(device=device)
    with (
        patch(
            _SMART_RETURN,
            AsyncMock(return_value=OpResult(success=True, data={"attempts": 0})),
        ),
    ):
        result = _run(CollectAllMail().execute(ctx))
    return device, result


def test_collect_all_mail_returns_success():
    _, result = _run_with_mocks()
    assert result.status == "success"
    assert result.data.get("action") == "mail_collected"


def test_collect_all_mail_presses_h_shortcut():
    """CollectAllMail uses H shortcut to open mail panel."""
    device, _ = _run_with_mocks()
    assert VK_H in device.key_log


def test_collect_all_mail_clicks_collect_all():
    """CollectAllMail clicks the collect-all button at verified coordinates."""
    device, _ = _run_with_mocks()
    assert (_COLLECT_ALL_X, _COLLECT_ALL_Y) in device.click_log


def test_collect_all_mail_dismisses_with_enter():
    """CollectAllMail presses Enter to dismiss reward popup."""
    device, _ = _run_with_mocks()
    assert VK_ENTER in device.key_log


def test_collect_all_mail_can_run_true_with_red_dot():
    """can_run returns True when red_dot_ratio > 0."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    with patch(_RED_DOT_PATCH, _red_dot_result(0.2)):
        assert _run(CollectAllMail().can_run(ctx)) is True


def test_collect_all_mail_can_run_false_without_red_dot():
    """can_run returns False when there is no red dot."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    with patch(_RED_DOT_PATCH, _red_dot_result(0.0)):
        assert _run(CollectAllMail().can_run(ctx)) is False


def test_collect_all_mail_name():
    assert CollectAllMail.name == "collect_all_mail"
