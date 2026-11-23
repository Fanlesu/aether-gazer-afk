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
    resolution: tuple = (1600, 900)

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

# can_run wakes the hub UI before the red-dot check (2026-11-23 fix); patch
# the wake action out in gate tests — its real path does template matching
# plus clicks, which the mocked gate tests must not perform.
_WAKE_PATCH = (
    "anime_game_afk.games.aether_gazer.tasks.observation_tasks"
    ".WakeHubUiAction.run"
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
    with (
        patch(_WAKE_PATCH, AsyncMock(return_value=None)),
        patch(_RED_DOT_PATCH, _red_dot(0.35)),
    ):
        assert _run(DailyWeeklyMissionClaim().can_run(ctx)) is True


def test_dw_can_run_false_without_hub_dot():
    ctx = _ctx()
    with (
        patch(_WAKE_PATCH, AsyncMock(return_value=None)),
        patch(_RED_DOT_PATCH, _red_dot(0.0)),
    ):
        assert _run(DailyWeeklyMissionClaim().can_run(ctx)) is False


def test_dw_can_run_wakes_hub_before_dot_check():
    """The gate must wake the hub UI first — the dot is invisible while
    the hub is idle/overlay-covered even though rewards are pending."""
    wake = AsyncMock(return_value=None)
    ctx = _ctx()
    with (
        patch(_WAKE_PATCH, wake),
        patch(_RED_DOT_PATCH, _red_dot(0.35)),
    ):
        assert _run(DailyWeeklyMissionClaim().can_run(ctx)) is True
    wake.assert_awaited_once()


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


def test_dw_execute_switches_weekly_tab_when_dot_present():
    """Hub + daily + weekly dots all present → claim both, and the weekly tab
    must be clicked (stabilize wait + double-click to survive UI stutter).

    This guards the regression where, after the daily-claim reward animation,
    the single weekly-tab click was swallowed by the stuttering UI and the
    weekly reward was silently never claimed.
    """
    device = MockDevice()
    ctx = _ctx(device)
    # All three dots present: hub gate, daily tab, weekly tab.
    ratios = {
        "hub-mission": 0.3,
        "daily-tab": 0.3,
        "weekly-tab": 0.3,
    }

    async def fake_evaluate(self, ctx):
        return CheckResult(
            passed=ratios.get(self._label, 0.0) > 0,
            data=ratios.get(self._label, 0.0),
        )

    from anime_game_afk.games.aether_gazer.tasks import observation_tasks
    sleep = AsyncMock()
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
        patch.object(observation_tasks.SleepOp, "run", sleep),
    ):
        result = _run(DailyWeeklyMissionClaim().execute(ctx))

    assert result.status == "success"
    assert result.data["claimed"] == 2
    # Weekly tab must have been clicked — twice (stabilize + recover).
    weekly_clicks = [
        (x, y) for x, y in device.click_log
        if abs(x - 0.045) < 1e-6 and abs(y - 0.281) < 1e-6
    ]
    assert len(weekly_clicks) == 2, (
        f"expected 2 weekly-tab clicks, got {device.click_log}"
    )
    # Stabilize wait must be inserted before the weekly-tab click.
    assert sleep.await_count >= 1


# ── MimiStationCollect / TacticsTaskClaim metadata ─────────────


def test_mimi_metadata():
    assert MimiStationCollect.name == "mimi_station_collect"
    assert MimiStationCollect.category == "daily"
    assert MimiStationCollect.safe is True


def test_tactics_can_run_false_without_red_dot():
    """TacticsTaskClaim skips when the 对策协议 hub icon has no red dot."""
    ctx = _ctx()
    with (
        patch(_WAKE_PATCH, AsyncMock(return_value=None)),
        patch(_RED_DOT_PATCH, _red_dot(0.0)),
    ):
        assert _run(TacticsTaskClaim().can_run(ctx)) is False


def test_tactics_can_run_true_when_red_dot_present():
    """TacticsTaskClaim runs when the 对策协议 hub icon shows a red dot."""
    ctx = _ctx()
    with (
        patch(_WAKE_PATCH, AsyncMock(return_value=None)),
        patch(_RED_DOT_PATCH, _red_dot(0.30)),
    ):
        assert _run(TacticsTaskClaim().can_run(ctx)) is True


def test_tactics_can_run_wakes_hub_before_dot_check():
    """22:48 run regression: the red-dot gate read 0.000 because can_run
    ran before any wake step and the left icon column was idle-faded /
    overlay-covered (both main_hub templates live on the right half).
    The gate must wake the hub UI *before* sampling the dot."""
    calls: list[str] = []

    async def _ordered_wake(self, ctx):
        calls.append("wake")
        return None

    async def _ordered_dot(self, ctx):
        calls.append("dot")
        return CheckResult(passed=True, data=0.30)

    ctx = _ctx()
    with patch(_WAKE_PATCH, _ordered_wake), patch(_RED_DOT_PATCH, _ordered_dot):
        assert _run(TacticsTaskClaim().can_run(ctx)) is True
    assert calls == ["wake", "dot"]


# ── TacticsTaskClaim entry (Step 1) regression ──────────────────
#
# The T shortcut IS the confirmed in-game entry for 对策协议 (user-verified).
# The old code pressed T blind and then ran every later step on whatever
# page was actually shown, faking "success". The fixed flow: press T →
# verify via stable on-page text (with one patient re-check — the page can
# take >1.5 s to load) → hub-icon fallback only if T truly failed →
# fail fast if nothing works. These tests lock that behaviour.

_ON_PAGE_PATCH = (
    "anime_game_afk.games.aether_gazer.tasks.observation_tasks"
    ".TacticsTaskClaim._on_tactics_page"
)
_RETURN_RUN = (
    "anime_game_afk.games.aether_gazer.ops.navigate.smart_return"
    ".ReturnToHubAction.run"
)
_FIND_TEXT = (
    "anime_game_afk.games.aether_gazer.tasks.observation_tasks"
    ".FindTextCheck.evaluate"
)


def test_tactics_enters_via_hub_icon_when_shortcut_fails():
    """T shortcut no-op (both checks) → verified fallback clicks the hub icon."""
    device = MockDevice()
    ctx = _ctx(device)
    task = TacticsTaskClaim()
    # Page check: False ×2 after T (initial + patient re-check), True after
    # the icon click.
    on_page = AsyncMock(side_effect=[False, False, True])
    with (
        patch(_ON_PAGE_PATCH, on_page),
        patch(_FIND_TEXT, AsyncMock(return_value=CheckResult(passed=False))),
        patch(_RETURN_RUN, AsyncMock()),
    ):
        result = _run(task.execute(ctx))

    assert result.status == "success"
    assert (0.062, 0.189) in device.click_log  # verified hub icon fallback


def test_tactics_shortcut_ok_on_recheck_skips_icon_click():
    """T works but the page loads slowly → the patient re-check catches it,
    and the hub-icon fallback must NOT fire (it would leave the page)."""
    device = MockDevice()
    ctx = _ctx(device)
    task = TacticsTaskClaim()
    # Page check: False right after T (still loading), True on the re-check.
    on_page = AsyncMock(side_effect=[False, True])
    with (
        patch(_ON_PAGE_PATCH, on_page),
        patch(_FIND_TEXT, AsyncMock(return_value=CheckResult(passed=False))),
        patch(_RETURN_RUN, AsyncMock()),
    ):
        result = _run(task.execute(ctx))

    assert result.status == "success"
    assert (0.062, 0.189) not in device.click_log
    # The 任务-tab click must have run — we are on the page.
    assert (0.101, 0.932) in device.click_log


def test_tactics_fails_fast_when_entry_never_succeeds():
    """Every entry attempt fails → task returns failed, no blind steps run."""
    device = MockDevice()
    ctx = _ctx(device)
    task = TacticsTaskClaim()
    with (
        patch(_ON_PAGE_PATCH, AsyncMock(return_value=False)),
        patch(_FIND_TEXT, AsyncMock(return_value=CheckResult(passed=False))),
        patch(_RETURN_RUN, AsyncMock()),
    ):
        result = _run(task.execute(ctx))

    assert result.status == "failed"
    # The 任务-tab click (0.101, 0.932) must NOT run — we never entered.
    assert (0.101, 0.932) not in device.click_log


def test_tactics_claims_weekly_tab_button():
    """2026-11-23 regression: the 一键领取 button only appears after
    selecting the 本周任务 sidebar tab — landing view has none, and the
    old back-click step exited to the hub instead. The flow must click
    本周任务 (OCR-located) and claim there."""
    device = MockDevice()
    ctx = _ctx(device)
    task = TacticsTaskClaim()

    def _find():
        async def _eval(self, ctx):
            target = self._target
            if target == "本周任务":
                # OCR-located sidebar tab (screenshot space 1600x900)
                return CheckResult(
                    passed=True,
                    data=type("R", (), {"region": type(
                        "Reg", (), {"x": 120, "y": 190, "w": 80, "h": 30},
                    )()})(),
                )
            if target == "一键领取":
                return CheckResult(
                    passed=True,
                    data=type("R", (), {"region": type(
                        "Reg", (), {"x": 1100, "y": 660, "w": 120, "h": 40},
                    )()})(),
                )
            return CheckResult(passed=False)
        return _eval

    with (
        patch(_ON_PAGE_PATCH, AsyncMock(side_effect=[True])),
        patch(_FIND_TEXT, _find()),
        patch(_RETURN_RUN, AsyncMock()),
    ):
        result = _run(task.execute(ctx))

    assert result.status == "success"
    assert result.data["claimed_weekly"] is True
    # 本周任务 clicked at its OCR-derived center (160,205)@1600x900 → frac
    assert (0.1, 205 / 900) in device.click_log
    # 一键领取 clicked at its OCR center (1160,680)@1600x900 → frac, ×3
    assert (1160 / 1600, 680 / 900) in device.click_log


def test_tactics_weekly_tab_ocr_miss_falls_back_to_fixed_coords():
    """OCR miss on 本周任务 → fixed measured coords (0.102, 0.282) are used
    instead of the old back-click (which left the tasks page entirely)."""
    device = MockDevice()
    ctx = _ctx(device)
    task = TacticsTaskClaim()
    with (
        patch(_ON_PAGE_PATCH, AsyncMock(side_effect=[True])),
        patch(_FIND_TEXT, AsyncMock(return_value=CheckResult(passed=False))),
        patch(_RETURN_RUN, AsyncMock()),
    ):
        result = _run(task.execute(ctx))

    assert result.status == "success"
    assert result.data["claimed_weekly"] is False
    assert (0.102, 0.282) in device.click_log
    # The old buggy behaviour clicked back (0.022, 0.039) here — must not.
    assert (0.022, 0.039) not in device.click_log
