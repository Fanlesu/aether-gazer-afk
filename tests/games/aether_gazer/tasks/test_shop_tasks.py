"""Tests for tasks.shop_tasks -- BuyIntelShards, ClaimFreeStamina.

Updated to match the Op/Check refactoring: shop tasks now use Check
classes (HasTextCheck, FindTextCheck, etc.) instead of bare ocr_find
imports, and ReturnToHubAction instead of smart_return_to_hub function.

Mock strategy: patch the underlying vision functions at the Check module
level (checks.ocr.ocr_find, checks.ocr.ocr_once, etc.) and patch Op
classes (ReturnToHubAction.run, WakeHubUiAction.run, etc.) at their class level.
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

from anime_game_afk.core.types import Rect
from anime_game_afk.games.aether_gazer.checks.base import CheckResult
from anime_game_afk.games.aether_gazer.ops.base import OpResult
from anime_game_afk.games.aether_gazer.tasks.base import TaskContext
from anime_game_afk.games.aether_gazer.tasks.shop_tasks import (
    BuyIntelShards,
    ClaimFreeStamina,
)
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


# Patch targets for Op classes used by shop tasks
_SHOP = "anime_game_afk.games.aether_gazer.tasks.shop_tasks"
_RETURN_TO_HUB_RUN = f"{_SHOP}.ReturnToHubAction.run"
_WAKE_HUB_RUN = f"{_SHOP}.WakeHubUiAction.run"
_IS_ON_PAGE = f"{_SHOP}.is_on_page"
_SMART_RETURN_RUN = f"{_SHOP}.ReturnToHubAction.run"


def _patch_red_dot(passed: bool):
    """Patch RedDotCheck at the shop_tasks namespace to force pass/fail.

    ClaimDailyStaminaPacks Step 0 gates on a hub red dot via RedDotCheck;
    we stub the class so the gate yields a deterministic CheckResult without
    running real HSV detection on the mock (black) screenshot.
    """
    fake_cls = MagicMock()
    fake_cls.return_value.evaluate = AsyncMock(
        return_value=CheckResult(
            passed=passed,
            data=0.1 if passed else 0.0,
            message="red dot (mocked)",
        ),
    )
    return patch(f"{_SHOP}.RedDotCheck", fake_cls)

# Patch targets for underlying vision functions used by Check classes
_OCR_FIND = "anime_game_afk.games.aether_gazer.checks.ocr.ocr_find"
_OCR_FIND_ALL = "anime_game_afk.games.aether_gazer.checks.ocr.ocr_find_all"
_OCR_ONCE = "anime_game_afk.games.aether_gazer.checks.ocr.ocr_once"
_OCR_FULL = "anime_game_afk.games.aether_gazer.checks.ocr.ocr_full"
_PAGE_IS_ON_PAGE = "anime_game_afk.games.aether_gazer.checks.page.is_on_page"


# -- BuyIntelShards -- metadata --

def test_buy_intel_name():
    assert BuyIntelShards.name == "buy_intel_shards"


def test_buy_intel_description():
    assert "\u60c5\u62a5" in BuyIntelShards.description


def test_buy_intel_metadata():
    assert BuyIntelShards.category == "daily_shop"
    assert BuyIntelShards.requires_ocr is True
    assert BuyIntelShards.safe is False
    assert "shop_daily" in BuyIntelShards.requires_pages


def test_buy_intel_can_run():
    device = MockDevice()
    ctx = TaskContext(device=device)
    assert _run(BuyIntelShards().can_run(ctx)) is True


# -- BuyIntelShards -- execution --

def test_buy_intel_fails_when_nav_fails():
    """BuyIntelShards returns failed when cannot reach daily purchase page."""
    device = MockDevice()
    ctx = TaskContext(device=device)

    with patch(
        _RETURN_TO_HUB_RUN,
        AsyncMock(return_value=OpResult(success=False, error="no hub")),
    ), patch(
        _WAKE_HUB_RUN,
        AsyncMock(return_value=OpResult(success=True)),
    ):
        result = _run(BuyIntelShards().execute(ctx))

    assert result.status == "failed"
    assert "navigate" in result.message.lower() or "daily" in result.message.lower()


def test_buy_intel_skips_badge_exchange_without_red_dot():
    """No red dot on the intel-badge sidebar entry → Step 3 exchange skipped.

    The buy loop (Step 2) still runs, so the task succeeds; only the
    intel badge exchange sub-step is skipped.
    """
    device = MockDevice()
    ctx = TaskContext(device=device)

    exchange = AsyncMock(return_value="exchanged")
    with (
        patch.object(
            BuyIntelShards, "_navigate_to_daily_purchase",
            new=AsyncMock(return_value=True),
        ),
        patch.object(BuyIntelShards, "_buy_loop", new=AsyncMock(return_value=3)),
        patch.object(BuyIntelShards, "_exchange_intel_badge", new=exchange),
        patch(_RETURN_TO_HUB_RUN, AsyncMock(return_value=OpResult(success=True))),
        _patch_red_dot(False),
    ):
        result = _run(BuyIntelShards().execute(ctx))

    exchange.assert_not_called()
    assert result.status == "success"
    assert result.data["purchased"] == 3


def test_buy_intel_exchanges_badge_with_red_dot():
    """Red dot present → Step 3 intel badge exchange is attempted."""
    device = MockDevice()
    ctx = TaskContext(device=device)

    exchange = AsyncMock(return_value="exchanged")
    with (
        patch.object(
            BuyIntelShards, "_navigate_to_daily_purchase",
            new=AsyncMock(return_value=True),
        ),
        patch.object(BuyIntelShards, "_buy_loop", new=AsyncMock(return_value=2)),
        patch.object(BuyIntelShards, "_exchange_intel_badge", new=exchange),
        patch(_RETURN_TO_HUB_RUN, AsyncMock(return_value=OpResult(success=True))),
        _patch_red_dot(True),
    ):
        result = _run(BuyIntelShards().execute(ctx))

    exchange.assert_called_once()
    assert result.status == "success"
    assert result.data["purchased"] == 2


# -- ClaimFreeStamina -- metadata --

def test_claim_free_stamina_name():
    assert ClaimFreeStamina.name == "claim_free_stamina"


def test_claim_free_stamina_description():
    assert "stamina" in ClaimFreeStamina.description.lower()


def test_claim_free_stamina_metadata():
    assert ClaimFreeStamina.category == "daily_shop"
    assert ClaimFreeStamina.requires_ocr is True
    assert ClaimFreeStamina.safe is True  # Free item
    assert "shop_supply" in ClaimFreeStamina.requires_pages


def test_claim_free_stamina_can_run():
    device = MockDevice()
    ctx = TaskContext(device=device)
    assert _run(ClaimFreeStamina().can_run(ctx)) is True


# -- ClaimFreeStamina -- execution --

def test_claim_free_stamina_fails_when_nav_fails():
    """ClaimFreeStamina fails when cannot reach daily supply page."""
    device = MockDevice()
    ctx = TaskContext(device=device)

    with patch(
        _RETURN_TO_HUB_RUN,
        AsyncMock(return_value=OpResult(success=False, error="no hub")),
    ), patch(
        _WAKE_HUB_RUN,
        AsyncMock(return_value=OpResult(success=True)),
    ):
        result = _run(ClaimFreeStamina().execute(ctx))

    assert result.status == "failed"
    assert "navigate" in result.message.lower() or "supply" in result.message.lower()


def test_claim_free_stamina_skips_when_cooldown():
    """ClaimFreeStamina returns skipped when cooldown is active.

    The red-dot gate (Step 2) is stubbed present so navigation proceeds:
    - FindTextCheck("免费") -> not found (ocr_find returns None)
    - HasTextCheck("冷却") -> found (ocr_find returns TextResult)
    -> returns "skipped" with cooldown message
    """
    device = MockDevice()
    ctx = TaskContext(device=device)

    def mock_ocr_find(img, target, **kwargs):
        """Mock ocr_find for Check classes.

        HasTextCheck("免费") and FindTextCheck("免费") both call ocr_find.
        HasTextCheck("冷却") also calls ocr_find.
        Navigation verification (HasTextCheck("冷却"/"免费"/"日常补给"))
        also goes through ocr_find.
        """
        if target == "\u51b7\u5374":  # 冷却
            return TextResult(
                text="\u51b7\u5374",
                confidence=0.95,
                region=Rect(350, 290, 50, 20),
            )
        if target == "\u514d\u8d39":  # 免费
            return None
        # Navigation verification: return match for 日常补给 or other nav checks
        if target == "\u65e5\u5e38\u8865\u7ed9":  # 日常补给
            return TextResult(
                text="\u65e5\u5e38\u8865\u7ed9",
                confidence=0.90,
                region=Rect(500, 120, 100, 30),
            )
        return None

    with patch(
        _RETURN_TO_HUB_RUN,
        AsyncMock(return_value=OpResult(success=True)),
    ), patch(
        _WAKE_HUB_RUN,
        AsyncMock(return_value=OpResult(success=True)),
    ), patch(
        _IS_ON_PAGE,
        return_value=True,
    ), patch(
        _SMART_RETURN_RUN,
        AsyncMock(return_value=OpResult(success=True)),
    ), patch(
        _OCR_FIND,
        side_effect=mock_ocr_find,
    ), _patch_red_dot(True):
        result = _run(ClaimFreeStamina().execute(ctx))

    assert result.status == "skipped"
    assert "cooldown" in result.message.lower()


def test_claim_free_stamina_skips_without_supply_red_dot():
    """No red dot on the supply-area entry → skip before 补给区 navigation.

    RedDotCheck stubbed absent: the task reaches the shop page, fails the
    gate, returns to hub, and reports skipped without touching the claim or
    cooldown logic.
    """
    device = MockDevice()
    ctx = TaskContext(device=device)

    return_hub = AsyncMock(return_value=OpResult(success=True))
    with (
        patch(_RETURN_TO_HUB_RUN, return_hub),
        patch(_WAKE_HUB_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_IS_ON_PAGE, return_value=True),
        _patch_red_dot(False),
    ):
        result = _run(ClaimFreeStamina().execute(ctx))

    return_hub.assert_called()  # returned to hub before exiting
    assert result.status == "skipped"
    assert "red dot" in result.message.lower()


# -- ClaimDailyStaminaPacks --

from anime_game_afk.games.aether_gazer.tasks.shop_tasks import (  # noqa: E402
    ClaimDailyStaminaPacks,
)


def test_daily_stamina_name():
    assert ClaimDailyStaminaPacks.name == "claim_daily_stamina_packs"


def test_daily_stamina_metadata():
    assert ClaimDailyStaminaPacks.category == "daily_resource"
    assert ClaimDailyStaminaPacks.safe is True


def test_daily_stamina_can_run_always():
    """can_run is unconditional (task always opens the panel and claims)."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    assert _run(ClaimDailyStaminaPacks().can_run(ctx)) is True


def test_daily_stamina_returns_failed_when_cannot_reach_hub():
    """If returning to hub fails, task reports failed (not false success)."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    with (
        patch(_RETURN_TO_HUB_RUN, AsyncMock(return_value=OpResult(success=False))),
        patch(_WAKE_HUB_RUN, AsyncMock(return_value=OpResult(success=True))),
    ):
        result = _run(ClaimDailyStaminaPacks().execute(ctx))
    assert result.status == "failed"


def test_daily_stamina_claims_packs_on_success():
    """Happy path: hub reached, stamina read, packs claimed, gain verified."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    with (
        patch(_WAKE_HUB_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_RETURN_TO_HUB_RUN, AsyncMock(return_value=OpResult(success=True))),
        # Mock the private helpers so no real OCR/panel interaction.
        # _read_stamina is called twice (before / after); side_effect yields
        # 100 then 160 so the gain computation is exercised.
        patch.object(
            ClaimDailyStaminaPacks, "_read_stamina",
            new=AsyncMock(side_effect=[100, 160]),
        ),
        patch.object(
            ClaimDailyStaminaPacks, "_open_stamina_panel",
            new=AsyncMock(return_value=True),
        ),
        patch.object(
            ClaimDailyStaminaPacks, "_claim_packs",
            new=AsyncMock(return_value=2),
        ),
        # Step 5.5 reads the panel stamina (160 < default target 450), but
        # the potion flow itself is stubbed out here.
        patch.object(
            ClaimDailyStaminaPacks, "_read_stamina_from_panel",
            new=AsyncMock(return_value=160),
        ),
        patch.object(
            ClaimDailyStaminaPacks, "_use_stamina_potions",
            new=AsyncMock(return_value={}),
        ),
    ):
        result = _run(ClaimDailyStaminaPacks().execute(ctx))
    assert result.status == "success"
    assert result.data["claimed"] == 2
    assert result.data["stamina_gained"] == 60
    assert result.data["potions_used"] == {}
    assert result.data["target_stamina"] == 450


# -- ClaimDailyStaminaPacks: potion top-up (Step 5.5) --


def test_plan_potions_greedy_exact_and_overshoot():
    """Greedy: largest potion that fits; smallest when nothing fits."""
    plan = ClaimDailyStaminaPacks._plan_potions
    assert plan(0) == []
    # deficit exactly coverable → exact fill
    assert plan(450) == [120, 120, 120, 60, 30]
    assert plan(90) == [60, 30]
    # deficit < 30 → smallest potion, overshoot ≤ 29 (prefer exceeding)
    assert plan(10) == [30]
    assert plan(29) == [30]
    # 100 → 60+30+30 (exact 100), never a needless 120
    assert plan(100) == [60, 30, 30]
    # mixed deficit
    assert plan(341) == [120, 120, 60, 30, 30]  # 360 ≥ 341, overshoot 19


def test_plan_potions_respects_max_cap():
    plan = ClaimDailyStaminaPacks._plan_potions
    huge = plan(999999)
    assert len(huge) <= ClaimDailyStaminaPacks._MAX_POTIONS_PER_RUN


def test_target_stamina_default_and_extra():
    task = ClaimDailyStaminaPacks()
    assert task._target_stamina() == 450  # default
    task.extra = {"target_stamina": 500}
    assert task._target_stamina() == 500
    task.extra = {"target_stamina": "not-a-number"}
    assert task._target_stamina() == 450  # bad value → fallback to default


def test_daily_stamina_uses_potions_with_extra_target():
    """params.extra.target_stamina drives the deficit passed to the potion flow."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    potion_mock = AsyncMock(return_value={"120": 2, "60": 1, "30": 1})
    with (
        patch(_WAKE_HUB_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_RETURN_TO_HUB_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch.object(
            ClaimDailyStaminaPacks, "_read_stamina",
            new=AsyncMock(side_effect=[160, 490]),
        ),
        patch.object(
            ClaimDailyStaminaPacks, "_open_stamina_panel",
            new=AsyncMock(return_value=True),
        ),
        patch.object(
            ClaimDailyStaminaPacks, "_claim_packs",
            new=AsyncMock(return_value=2),
        ),
        patch.object(
            ClaimDailyStaminaPacks, "_read_stamina_from_panel",
            new=AsyncMock(return_value=160),
        ),
        patch.object(ClaimDailyStaminaPacks, "_use_stamina_potions", new=potion_mock),
    ):
        task = ClaimDailyStaminaPacks()
        task.extra = {"target_stamina": 500}
        result = _run(task.execute(ctx))
    assert result.status == "success"
    # deficit = 500 - 160 = 340
    assert potion_mock.call_args.args[1] == 340
    assert result.data["potions_used"] == {"120": 2, "60": 1, "30": 1}
    assert result.data["target_stamina"] == 500


def test_daily_stamina_skips_potions_at_target():
    """Stamina already >= target → potion flow never invoked."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    potion_mock = AsyncMock(return_value={})
    with (
        patch(_WAKE_HUB_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_RETURN_TO_HUB_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch.object(
            ClaimDailyStaminaPacks, "_read_stamina",
            new=AsyncMock(side_effect=[500, 500]),
        ),
        patch.object(
            ClaimDailyStaminaPacks, "_open_stamina_panel",
            new=AsyncMock(return_value=True),
        ),
        patch.object(
            ClaimDailyStaminaPacks, "_claim_packs",
            new=AsyncMock(return_value=2),
        ),
        patch.object(
            ClaimDailyStaminaPacks, "_read_stamina_from_panel",
            new=AsyncMock(return_value=500),
        ),
        patch.object(ClaimDailyStaminaPacks, "_use_stamina_potions", new=potion_mock),
    ):
        result = _run(ClaimDailyStaminaPacks().execute(ctx))
    assert result.status == "success"
    potion_mock.assert_not_called()
    assert result.data["potions_used"] == {}


def test_daily_stamina_skips_potions_when_stamina_unreadable():
    """Cannot read panel stamina → conservative skip (never guess potions)."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    potion_mock = AsyncMock(return_value={})
    with (
        patch(_WAKE_HUB_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(_RETURN_TO_HUB_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch.object(
            ClaimDailyStaminaPacks, "_read_stamina",
            new=AsyncMock(side_effect=[160, 160]),
        ),
        patch.object(
            ClaimDailyStaminaPacks, "_open_stamina_panel",
            new=AsyncMock(return_value=True),
        ),
        patch.object(
            ClaimDailyStaminaPacks, "_claim_packs",
            new=AsyncMock(return_value=2),
        ),
        patch.object(
            ClaimDailyStaminaPacks, "_read_stamina_from_panel",
            new=AsyncMock(return_value=None),
        ),
        patch.object(ClaimDailyStaminaPacks, "_use_stamina_potions", new=potion_mock),
    ):
        result = _run(ClaimDailyStaminaPacks().execute(ctx))
    assert result.status == "success"
    potion_mock.assert_not_called()


def test_use_stamina_potions_mismatch_cancels():
    """OCR total mismatch vs planned selection → cancel, no potion used."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = ClaimDailyStaminaPacks()
    with (
        patch.object(
            ClaimDailyStaminaPacks, "_read_selection_total",
            new=AsyncMock(return_value=999),  # != planned 360
        ),
        patch.object(ClaimDailyStaminaPacks, "_cancel_selection", new=AsyncMock()) as cancel,
    ):
        result = _run(task._use_stamina_potions(ctx, 341, None))
    assert result == {}
    cancel.assert_awaited_once()


def test_use_stamina_potions_zero_total_cancels():
    """Selection total reads 0 → nothing got selected → cancel."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = ClaimDailyStaminaPacks()
    with (
        patch.object(
            ClaimDailyStaminaPacks, "_read_selection_total",
            new=AsyncMock(return_value=0),
        ),
        patch.object(ClaimDailyStaminaPacks, "_cancel_selection", new=AsyncMock()) as cancel,
    ):
        result = _run(task._use_stamina_potions(ctx, 341, None))
    assert result == {}
    cancel.assert_awaited_once()
