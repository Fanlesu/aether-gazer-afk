"""Tests for tasks.observation_tasks — mission claim tasks.

Covers the red-dot gating logic (the shared entry point for all three
daily tasks) — if that gate is wrong, every mission task silently skips
and the user loses daily rewards without any visible error.
"""
import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import numpy as np

from anime_game_afk.games.aether_gazer.checks.base import CheckResult
from anime_game_afk.games.aether_gazer.knowledge.keys import VK_G
from anime_game_afk.games.aether_gazer.tasks.base import TaskContext
from anime_game_afk.games.aether_gazer.tasks.observation_tasks import (
    DailyWeeklyMissionClaim,
    MimiStationCollect,
    TacticsTaskClaim,
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


def _ctx(device=None):
    return TaskContext(device=device or MockDevice())


# RedDotCheck is imported into observation_tasks as a name; patch its
# evaluate to control the gate without real image analysis.
_RED_DOT_PATCH = (
    "anime_game_afk.games.aether_gazer.tasks.observation_tasks"
    ".RedDotCheck.evaluate"
)


def _red_dot(ratio: float):
    return AsyncMock(return_value=CheckResult(passed=ratio > 0, data=ratio))


def _claim_patch(found: bool):
    """Mock _claim_section to return 1/0 without real OCR."""
    if found:
        return AsyncMock(return_value=1)
    return AsyncMock(return_value=0)


# ── DailyWeeklyMissionClaim: can_run gate ──────────────────────


def test_dw_can_run_true_when_hub_dot_present():
    ctx = _ctx()
    with patch(_RED_DOT_PATCH, _red_dot(0.35)):
        assert _run(DailyWeeklyMissionClaim().can_run(ctx)) is True


def test_dw_can_run_false_without_hub_dot():
    ctx = _ctx()
    with patch(_RED_DOT_PATCH, _red_dot(0.0)):
        assert _run(DailyWeeklyMissionClaim().can_run(ctx)) is False


# ── DailyWeeklyMissionClaim: execute skip path ─────────────────


def test_dw_execute_skips_when_no_hub_dot():
    """execute() returns skipped when the hub gate finds no red dot."""
    ctx = _ctx()
    with patch(_RED_DOT_PATCH, _red_dot(0.0)):
        result = _run(DailyWeeklyMissionClaim().execute(ctx))
    assert result.status == "skipped"


def test_dw_execute_skips_pressed_no_g_when_no_dot():
    """No hub dot → must NOT press G (no navigation at all)."""
    device = MockDevice()
    ctx = _ctx(device)
    with patch(_RED_DOT_PATCH, _red_dot(0.0)):
        _run(DailyWeeklyMissionClaim().execute(ctx))
    assert VK_G not in device.key_log, "should not open daily panel with no dot"


def test_dw_execute_claims_daily_when_dot_present():
    """With hub dot + daily tab dot → daily claim runs, no weekly visit."""
    device = MockDevice()
    ctx = _ctx(device)
    # Hub dot present, daily tab dot present, weekly tab dot absent.
    ratios = {
        "hub-mission": 0.3,
        "daily-tab": 0.3,
        "weekly-tab": 0.0,
    }

    async def fake_evaluate(self, ctx):
        return CheckResult(
            passed=ratios.get(self._label, 0.0) > 0,
            data=ratios.get(self._label, 0.0),
        )

    from anime_game_afk.games.aether_gazer.tasks import observation_tasks
    with (
        patch.object(
            observation_tasks.RedDotCheck, "evaluate",
            new=fake_evaluate,
        ),
        patch.object(
            DailyWeeklyMissionClaim, "_claim_section", _claim_patch(True),
        ),
        patch(
            "anime_game_afk.games.aether_gazer.ops.navigate.smart_return"
            ".ReturnToHubAction.run",
            AsyncMock(),
        ),
    ):
        result = _run(DailyWeeklyMissionClaim().execute(ctx))

    assert result.status == "success"
    assert result.data["claimed"] == 1


# ── MimiStationCollect / TacticsTaskClaim metadata ─────────────


def test_mimi_metadata():
    assert MimiStationCollect.name == "mimi_station_collect"
    assert MimiStationCollect.category == "daily"
    assert MimiStationCollect.safe is True


def test_tactics_can_run_false_when_not_found():
    """TacticsTaskClaim skips when '对策协议' is not on the hub."""
    ctx = _ctx()
    # Patch FindTextCheck to return not-passed.
    with patch(
        "anime_game_afk.games.aether_gazer.tasks.observation_tasks"
        ".FindTextCheck.evaluate",
        AsyncMock(return_value=CheckResult(passed=False, message="not found")),
    ):
        assert _run(TacticsTaskClaim().can_run(ctx)) is False


def test_tactics_can_run_true_when_found():
    ctx = _ctx()
    from anime_game_afk.vision.types import TextResult
    from anime_game_afk.core.types import Rect
    fake = TextResult(text="对策协议", confidence=0.9, region=Rect(10, 10, 60, 20))
    with patch(
        "anime_game_afk.games.aether_gazer.tasks.observation_tasks"
        ".FindTextCheck.evaluate",
        AsyncMock(return_value=CheckResult(passed=True, data=fake)),
    ):
        assert _run(TacticsTaskClaim().can_run(ctx)) is True
